import os
import time
import sqlite3
import threading
import requests
from flask import Flask
import telebot
from telebot import types

# ----------------------------------------------------
# CONFIGURATION (variables d'environnement Render)
# ----------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "trading_v21.db")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
PIP_SIZE = float(os.getenv("PIP_SIZE", "0.1"))  # 1 pip = 0.1 $ sur ton XM (20 $ = 200 pips)
SYMBOLS = {"BTCUSD": "BTCUSDT"}

TF_MAP = {
    "M1": {"binance": "1m", "bybit": "1"},
    "M5": {"binance": "5m", "bybit": "5"},
    "M15": {"binance": "15m", "bybit": "15"},
    "H1": {"binance": "1h", "bybit": "60"},
}

MODES = {
    "express": {"sl_atr": 1.0, "tp_atr": 1.6, "expiry_s": 3600},
    "intraday": {"sl_atr": 1.5, "tp_atr": 2.5, "expiry_s": 14400},
}

MIN_SCORE = 3
DISCLAIMER = "⚠️ Aucun indicateur n'est fiable à 100 %. Risque max 1-2 % du capital par trade."

# ----------------------------------------------------
# 0. FORMATION & TUTOS
# ----------------------------------------------------
TRAINING_CHAPTERS = {
    "ch1": (
        "📘 **CHAPITRE 1 : C'est quoi le Trading ?**\n"
        "───────────────────────────\n"
        "Le trading consiste à spéculer sur la hausse (BUY) ou la baisse (SELL) "
        "d'un actif (comme BTCUSD) pour encaisser la différence en pips."
    ),
    "ch2": (
        "⏱️ **CHAPITRE 2 : Les Timeframes MT5**\n"
        "───────────────────────────\n"
        "• **M1 / M5 :** Micro-scalping dynamique.\n"
        "• **M15 / H1 :** Analyse des niveaux clés et tendances de fond."
    ),
    "ch3": (
        "🚀 **CHAPITRE 3 : Discipline de Scalpeur**\n"
        "───────────────────────────\n"
        "1. Entre ton prix exact XM.\n"
        "2. Place ton Take Profit et ton Stop Loss directement.\n"
        "3. Si le marché se retourne, utilise 🔄 Réanalyser et suis le verdict."
    ),
}

# ----------------------------------------------------
# 1. SERVEUR FLASK (uptime Render)
# ----------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "B2K Algo MT5 Pro v22.0 - Opérationnel !"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ----------------------------------------------------
# 2. BASE DE DONNÉES
# ----------------------------------------------------
db_lock = threading.Lock()

def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with db_lock:
        conn = db()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                trials_left INTEGER DEFAULT 3,
                is_paid INTEGER DEFAULT 0,
                is_admin INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                symbol TEXT,
                mode TEXT,
                tf TEXT,
                side TEXT,
                entry REAL,
                sl REAL,
                tp REAL,
                offset REAL,
                rr REAL,
                created_ms INTEGER,
                expiry_ms INTEGER,
                status TEXT DEFAULT 'OPEN',
                closed_ms INTEGER
            )
        ''')
        conn.commit()
        conn.close()

init_db()

# ----------------------------------------------------
# 3. BOT TELEGRAM & FONCTIONS UTILES
# ----------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown", threaded=True, num_threads=16)

testing_as_user = {}   # chat_id -> True si l'admin simule un client
awaiting_price = {}    # chat_id -> (symbol, mode, tf)

def clean_delete_message(chat_id, message_id):
    def _delete():
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    threading.Thread(target=_delete, daemon=True).start()

def safe_send(chat_id, text, **kwargs):
    """Envoie en Markdown ; si Telegram refuse le format, renvoie en texte simple."""
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception:
        try:
            plain = text.replace("*", "").replace("_", "").replace("`", "")
            return bot.send_message(chat_id, plain, parse_mode=None, **{k: v for k, v in kwargs.items() if k != "parse_mode"})
        except Exception as e:
            print("Erreur envoi:", e)

def set_native_commands():
    commands = [
        types.BotCommand("start", "Menu principal 📊"),
        types.BotCommand("menu", "Tableau de bord B2K ⚡"),
        types.BotCommand("payment", "Abonnement VIP (20$) 💳"),
        types.BotCommand("test", "Mode Test Admin ⚙️"),
        types.BotCommand("stats", "Statistiques réelles 📈"),
        types.BotCommand("annonce", "Diffuser une annonce 📣"),
    ]
    try:
        bot.set_my_commands(commands)
    except Exception as e:
        print("Erreur commandes:", e)

set_native_commands()

def get_user(chat_id):
    with db_lock:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT trials_left, is_paid, is_admin FROM users WHERE chat_id=?", (chat_id,))
        u = cur.fetchone()
        if not u:
            cur.execute("INSERT INTO users (chat_id, trials_left, is_paid, is_admin) VALUES (?, 3, 0, 0)", (chat_id,))
            conn.commit()
            u = (3, 0, 0)
        if ADMIN_ID and chat_id == ADMIN_ID and (u[1] != 1 or u[2] != 1):
            cur.execute("UPDATE users SET is_admin=1, is_paid=1 WHERE chat_id=?", (chat_id,))
            conn.commit()
            u = (u[0], 1, 1)
        conn.close()
        return u

def is_admin(chat_id):
    return get_user(chat_id)[2] == 1

def has_access(chat_id):
    trials, is_paid, admin = get_user(chat_id)
    if testing_as_user.get(chat_id, False):
        return trials > 0
    if is_paid or admin:
        return True
    return trials > 0

def consume_trial(chat_id):
    trials, is_paid, admin = get_user(chat_id)
    if testing_as_user.get(chat_id, False) or (not is_paid and not admin):
        with db_lock:
            conn = db()
            conn.execute("UPDATE users SET trials_left = MAX(trials_left - 1, 0) WHERE chat_id=?", (chat_id,))
            conn.commit()
            conn.close()

def deny_admin(chat_id):
    safe_send(chat_id, "⛔ Commande réservée à l'administrateur.")

# ----------------------------------------------------
# 4. DONNÉES DE MARCHÉ & CALCULS TECHNIQUES (INDICATEURS)
# ----------------------------------------------------
BINANCE_BASES = ("https://api.binance.com", "https://data-api.binance.vision")

def fetch_candles(symbol, tf, limit=300):
    """Retourne (highs, lows, closes) du plus ancien au plus récent, ou None."""
    market_symbol = SYMBOLS[symbol]
    cfg = TF_MAP[tf]

    for base in BINANCE_BASES:
        try:
            r = requests.get(
                f"{base}/api/v3/klines",
                params={"symbol": market_symbol, "interval": cfg["binance"], "limit": limit},
                timeout=8,
            )
            if r.status_code == 200:
                rows = r.json()
                if len(rows) >= 60:
                    return ([float(x[2]) for x in rows], [float(x[3]) for x in rows], [float(x[4]) for x in rows])
        except Exception:
            pass

    try:  # Secours : Bybit
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={"category": "linear", "symbol": market_symbol, "interval": cfg["bybit"], "limit": limit},
            timeout=8,
        )
        if r.status_code == 200:
            rows = list(reversed(r.json()["result"]["list"]))
            if len(rows) >= 60:
                return ([float(x[2]) for x in rows], [float(x[3]) for x in rows], [float(x[4]) for x in rows])
    except Exception:
        pass
    return None

def compute_indicators(highs, lows, closes):
    """Calcule les indicateurs techniques et retourne un dictionnaire de scores et valeurs."""
    n = len(closes)
    if n < 50:
        return None

    # EMA 20 & 50
    def ema(data, period):
        k = 2 / (period + 1)
        res = [data[0]]
        for val in data[1:]:
            res.append(val * k + res[-1] * (1 - k))
        return res

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    # RSI (14)
    gains, losses = [], []
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    
    avg_gain = sum(gains[:14]) / 14
    avg_loss = sum(losses[:14]) / 14
    rsi_list = []
    for i in range(14, len(gains)):
        avg_gain = (avg_gain * 13 + gains[i]) / 14
        avg_loss = (avg_loss * 13 + losses[i]) / 14
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsi_list.append(100 - (100 / (1 + rs)))
    rsi = rsi_list[-1] if rsi_list else 50

    # ATR (14)
    atrs = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        atrs.append(tr)
    atr = sum(atrs[-14:]) / 14 if len(atrs) >= 14 else (highs[-1] - lows[-1])

    # Votes d'indicateurs (10 indicateurs simplifiés)
    bull_votes = 0
    bear_votes = 0

    # 1. EMA Cross
    if ema20[-1] > ema50[-1]: bull_votes += 1
    else: bear_votes += 1

    # 2. Prix vs EMA20
    if closes[-1] > ema20[-1]: bull_votes += 1
    else: bear_votes += 1

    # 3. RSI Zone
    if rsi < 40: bull_votes += 1  # Rebond potentiel
    elif rsi > 60: bear_votes += 1

    # 4-10. Momentum & Variations récentes
    for step in [2, 3, 5, 8, 13, 21]:
        if n > step:
            if closes[-1] > closes[-step]: bull_votes += 1
            else: bear_votes += 1

    side = "BUY" if bull_votes >= bear_votes else "SELL"
    score = abs(bull_votes - bear_votes)

    return {"side": side, "score": score, "atr": atr, "rsi": rsi}

# ----------------------------------------------------
# 5. COMMANDES ADMIN & PAIEMENT
# ----------------------------------------------------
@bot.message_handler(commands=['adminrubenb2k'])
def admin_secret_cmd(message):
    chat_id = message.chat.id
    with db_lock:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM users WHERE is_admin=1")
        row = cur.fetchone()
        if row and row[0] != chat_id:
            conn.close()
            return safe_send(chat_id, "⛔ Clé administrative déjà verrouillée.")
        cur.execute("UPDATE users SET is_admin=1, is_paid=1 WHERE chat_id=?", (chat_id,))
        conn.commit()
        conn.close()
    safe_send(chat_id, "🔑 **ACCÈS ADMINISTRATEUR ACTIVÉ !**\n\nBienvenue Ruben (@b2k_ruben).")

@bot.message_handler(commands=['vip'])
def activate_vip_user(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        return deny_admin(chat_id)
    try:
        target_id = int(message.text.split()[1])
        with db_lock:
            conn = db()
            conn.execute("UPDATE users SET is_paid=1 WHERE chat_id=?", (target_id,))
            conn.commit()
            conn.close()
        safe_send(chat_id, f"✅ **Utilisateur ID {target_id} activé VIP !**")
        safe_send(target_id, "🎉 **FÉLICITATIONS !** Ton accès VIP B2K Algo a été activé !")
    except Exception:
        safe_send(chat_id, "Format : `/vip CHAT_ID`")

@bot.message_handler(commands=['test'])
def toggle_test_mode(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        return deny_admin(chat_id)
    current = testing_as_user.get(chat_id, False)
    testing_as_user[chat_id] = not current
    status = "ACTIVÉ (Simulation 3 essais client)" if testing_as_user[chat_id] else "DÉSACTIVÉ (Mode Admin)"
    safe_send(chat_id, f"⚙️ **MODE TEST UTILISATEUR :** {status}")

@bot.message_handler(commands=['annonce'])
def broadcast_annonce(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        return deny_admin(chat_id)
    msg = safe_send(chat_id, "📢 **ENVOI D'ANNONCE**\n\nEnvoie le message ou la photo à diffuser à tous les utilisateurs :")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    with db_lock:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM users")
        all_users = cur.fetchall()
        conn.close()

    count = 0
    for u in all_users:
        uid = u[0]
        try:
            if message.photo:
                bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption)
            else:
                bot.send_message(uid, message.text)
            count += 1
        except Exception:
            pass
    safe_send(message.chat.id, f"✅ **Annonce diffusée avec succès à {count} utilisateur(s).**")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    chat_id = message.chat.id
    with db_lock:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END), SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) FROM signals")
        total, wins, losses = cur.fetchone()
        conn.close()
    total = total or 0
    wins = wins or 0
    losses = losses or 0
    winrate = round((wins / total * 100), 1) if total > 0 else 0.0
    text = (
        f"📈 **STATISTIQUES DES SIGNAUX B2K**\n"
        f"───────────────────────────\n"
        f"• Total signaux émis : `{total}`\n"
        f"• Gagnés (TP touché) : `{wins}`\n"
        f"• Perdus (SL touché) : `{losses}`\n"
        f"• **Winrate Réel :** `{winrate}%`"
    )
    safe_send(chat_id, text)

@bot.message_handler(commands=['payment'])
def payment_info(message):
    send_payment_message(message.chat.id)

def send_payment_message(chat_id):
    text = (
        "💳 **ACTIVATION ACCÈS VIP B2K ALGO**\n"
        "───────────────────────────\n"
        "💰 **Tarif Abonnement :** **20 USD** ou **2 700 HTG**\n\n"
        "📌 **Moyens de paiement :**\n"
        "• **Crypto :** USDT (TRC20 / BEP20)\n"
        "• **Local Haïti :** MonCash / NatCash\n\n"
        "📲 **Pour activer votre compte :**\n"
        "📩 **Telegram Direct :** [@b2k_ruben](https://t.me/b2k_ruben)\n"
        "📱 **WhatsApp Direct :** +50943528461"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📲 Contacter @b2k_ruben", url="https://t.me/b2k_ruben"))
    markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    safe_send(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

# ----------------------------------------------------
# 6. MENU PRINCIPAL
# ----------------------------------------------------
@bot.message_handler(commands=['start', 'menu'])
def start_cmd(message):
    chat_id = message.chat.id
    get_user(chat_id)
    show_main_menu(chat_id)

def show_main_menu(chat_id):
    u = get_user(chat_id)
    trials, is_paid, admin = u
    is_testing = testing_as_user.get(chat_id, False)

    text = (
        "⚡ **B2K ALGO SCALPING PRO (XM EDITION)**\n"
        "───────────────────────────\n"
        "👇 Sélectionne ton actif pour démarrer :"
    )

    if is_testing or (not is_paid and not admin):
        text += f"\n\n🎁 **Essais gratuits restants :** `{trials}/3`"
    else:
        text += "\n\n⭐ **Statut :** `Abonné VIP Actif`"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("₿ BTCUSD (Bitcoin) - Analyse Auto", callback_data="asset_BTCUSD"),
        types.InlineKeyboardButton("🥇 XAUUSD (Or) - Marché Fermé 🚪", callback_data="asset_XAUUSD"),
        types.InlineKeyboardButton("📚 Formation B2K", callback_data="show_book"),
        types.InlineKeyboardButton("💳 Abonnement VIP (20$)", callback_data="show_payment")
    )
    safe_send(chat_id, text, reply_markup=markup)

# ----------------------------------------------------
# 7. GESTION DES CALLBACKS ET SIGNAUX INTERACTIFS
# ----------------------------------------------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    clean_delete_message(chat_id, message_id)

    if data == "back_home":
        show_main_menu(chat_id)
        return

    if data == "show_payment":
        send_payment_message(chat_id)
        return

    if data == "show_book":
        text = "📖 **ACADÉMIE B2K | FORMATION**\nChoisis un module :"
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📘 1. C'est quoi le Trading ?", callback_data="book_ch1"),
            types.InlineKeyboardButton("⏱️ 2. Les Timeframes", callback_data="book_ch2"),
            types.InlineKeyboardButton("🚀 3. Discipline de Scalpeur", callback_data="book_ch3"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        safe_send(chat_id, text, reply_markup=markup)
        return

    if data.startswith("book_"):
        ch_key = data.replace("book_", "")
        text = TRAINING_CHAPTERS.get(ch_key, "Contenu en cours d'édition.")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📖 Formation", callback_data="show_book"), types.InlineKeyboardButton("Menu", callback_data="back_home"))
        safe_send(chat_id, text, reply_markup=markup)
        return

    if data.startswith("asset_"):
        symbol = data.split("_")[1]
        if symbol == "XAUUSD":
            text = "🚪 **MARCHÉ DU GOLD FERMÉ**\nLe marché de l'Or est fermé en week-end.\n💡 Bascule sur le **BTCUSD** actif 24/7 !"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("₿ BTCUSD (Bitcoin)", callback_data="asset_BTCUSD"))
            markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
            safe_send(chat_id, text, reply_markup=markup)
            return

        text = f"📌 **ACTIF : {symbol}**\nSélectionne ton mode de trading :"
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("⚡ Micro-Scalping Express (30s - 1 min)", callback_data=f"mode_{symbol}_express"),
            types.InlineKeyboardButton("🚀 Scalping Intra-Day (15 - 20 min)", callback_data=f"mode_{symbol}_intraday"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        safe_send(chat_id, text, reply_markup=markup)
        return

    if data.startswith("mode_"):
        _, symbol, mode = data.split("_")
        text = f"📌 **ACTIF : {symbol} | Mode : {mode.upper()}**\nSélectionne le Timeframe :"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("⏱️ M1", callback_data=f"sig_{symbol}_{mode}_M1"),
            types.InlineKeyboardButton("⏱️ M5", callback_data=f"sig_{symbol}_{mode}_M5"),
            types.InlineKeyboardButton("⏱️ M15", callback_data=f"sig_{symbol}_{mode}_M15"),
            types.InlineKeyboardButton("⏱️ H1", callback_data=f"sig_{symbol}_{mode}_H1"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        safe_send(chat_id, text, reply_markup=markup)
        return

    # --- VERIFICATION DES ESSAIS & DEMANDE DU PRIX MANUEL XM (sig_) ---
    if data.startswith("sig_"):
        _, symbol, mode, tf = data.split("_")

        if not has_access(chat_id):
            text = (
                "⛔ **VOTRE ESSAI GRATUIT EST TERMINÉ !**\n"
                "───────────────────────────\n"
                "Débloquez votre accès VIP illimité pour 20 $ USD / 2 700 HTG.\n\n"
                "📩 Telegram : [@b2k_ruben](https://t.me/b2k_ruben)\n"
                "📱 WhatsApp : +50943528461"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💳 Payer mon accès (20$)", callback_data="show_payment"))
            markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
            safe_send(chat_id, text, reply_markup=markup, disable_web_page_preview=True)
            return

        consume_trial(chat_id)
        awaiting_price[chat_id] = (symbol, mode, tf)

        msg = safe_send(
            chat_id,
            f"🎯 **SAISIE DU PRIX XM | {symbol} {tf}**\n"
            f"───────────────────────────\n"
            f"📱 Regarde ton application MT5 XM.\n"
            f"✍️ **Entre le prix exact affiché sur ton écran** (Ex: `80819.85`) :"
        )
        bot.register_next_step_handler(msg, process_manual_signal)
        return

# ----------------------------------------------------
# 8. TRAITEMENT DU SIGNAL HYBRIDE (ANALYSE AUTO + PRIX XM)
# ----------------------------------------------------
def process_manual_signal(message):
    chat_id = message.chat.id
    if chat_id not in awaiting_price:
        return show_main_menu(chat_id)

    symbol, mode, tf = awaiting_price.pop(chat_id)
    text_input = message.text.strip().replace(",", ".")

    try:
        entry_price = float(text_input)
    except ValueError:
        msg = safe_send(
            chat_id,
            "⚠️ **Format invalide !** Entre uniquement un nombre correct (Ex: `80819.85`). Réessaie :"
        )
        awaiting_price[chat_id] = (symbol, mode, tf)
        bot.register_next_step_handler(msg, process_manual_signal)
        return

    # Téléchargement des bougies et calcul des indicateurs en arrière-plan
    candles = fetch_candles(symbol, tf)
    if not candles:
        safe_send(chat_id, "⚠️ Erreur de récupération des données du marché. Réessaie dans un instant.")
        return show_main_menu(chat_id)

    highs, lows, closes = candles
    indicators = compute_indicators(highs, lows, closes)
    if not indicators:
        safe_send(chat_id, "⚠️ Données insuffisantes pour l'analyse technique.")
        return show_main_menu(chat_id)

    side = indicators["side"]
    score = indicators["score"]
    atr = indicators["atr"]
    rsi = indicators["rsi"]

    if score < MIN_SCORE:
        safe_send(chat_id, "⚠️ Marché trop neutre ou incertain détecté par les indicateurs. Patiente un instant avant de relancer.")
        return show_main_menu(chat_id)

    cfg = MODES[mode]
    sl_dist = atr * cfg["sl_atr"]
    tp_dist = atr * cfg["tp_atr"]

    if side == "BUY":
        sl_price = round(entry_price - sl_dist, 2)
        tp_price = round(entry_price + tp_dist, 2)
        order_str = "🟢 ACHAT (BUY)"
    else:
        sl_price = round(entry_price + sl_dist, 2)
        tp_price = round(entry_price - tp_dist, 2)
        order_str = "🔴 VENTE (SELL)"

    pips_count = round(abs(tp_price - entry_price) / PIP_SIZE, 1)
    rr = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 1.0

    now = int(time.time() * 1000)
    expiry = now + (cfg["expiry_s"] * 1000)

    with db_lock:
        conn = db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO signals (chat_id, symbol, mode, tf, side, entry, sl, tp, offset, rr, created_ms, expiry_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, symbol, mode, tf, side, entry_price, sl_price, tp_price, sl_dist, rr, now, expiry))
        conn.commit()
        conn.close()

    result_text = (
        f"🎯 **SIGNAL SCALPING B2K (XM) | {symbol} {tf}**\n"
        f"───────────────────────────\n"
        f"📍 **PRIX D'ENTRÉE XM :** `{entry_price:.2f}`\n"
        f"⚡ **ORDRE :** {order_str}\n\n"
        f"🎯 **TAKE PROFIT :** `{tp_price:.2f}` *(+{pips_count} pips)*\n"
        f"🛑 **STOP LOSS :** `{sl_price:.2f}`\n\n"
        f"📊 **SCORE TECHNIQUE :** `{score}/10` (RSI: `{rsi:.1f}`)\n"
        f"⚖️ **Ratio R:R :** `1:{rr}`\n\n"
        f"{DISCLAIMER}"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📊 Nouvelle Analyse", callback_data=f"asset_{symbol}"),
        types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
    )
    safe_send(chat_id, result_text, reply_markup=markup)

if __name__ == '__main__':
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
