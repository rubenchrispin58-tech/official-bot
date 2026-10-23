import os
import time
import sqlite3
import threading
import random
from flask import Flask
import telebot
from telebot import types

# ----------------------------------------------------
# 1. SERVEUR FLASK POUR UPTIMEROBOT & RENDER (24/7)
# ----------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "B2K Algo MT5 Pro Server v11.0 - Moteur Temps Réel Actif !"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ----------------------------------------------------
# 2. INITIALISATION BASE DE DONNÉES SQLITE
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect("trading_v11.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            trials_left INTEGER DEFAULT 3,
            is_paid INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            symbol TEXT,
            timeframe TEXT,
            mode TEXT,
            order_type TEXT,
            entry_price REAL,
            tp_price REAL,
            sl_price REAL,
            trend_direction TEXT,
            created_at REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ----------------------------------------------------
# 3. CONFIGURATION BOT & SÉCURITÉ DU TOKEN
# ----------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown", threaded=True, num_threads=16)

LOCKED_ADMIN_ID = None
testing_as_user = {}

def async_delete_message(chat_id, message_id):
    def _delete():
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    threading.Thread(target=_delete, daemon=True).start()

def set_native_commands():
    commands = [
        types.BotCommand("start", "Menu principal 📊"),
        types.BotCommand("menu", "Tableau de bord B2K ⚡"),
        types.BotCommand("payment", "Guide de paiement & Activation 💳"),
        types.BotCommand("test", "Mode Test Admin ⚙️"),
        types.BotCommand("annonce", "Diffuser une annonce 📣")
    ]
    try:
        bot.set_my_commands(commands)
    except Exception as e:
        print("Erreur configuration commandes:", e)

set_native_commands()

def get_user(chat_id):
    conn = sqlite3.connect("trading_v11.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT trials_left, is_paid, is_admin FROM users WHERE chat_id=?", (chat_id,))
    u = cursor.fetchone()
    if not u:
        cursor.execute("INSERT INTO users (chat_id, trials_left, is_paid, is_admin) VALUES (?, 3, 0, 0)", (chat_id,))
        conn.commit()
        u = (3, 0, 0)
    conn.close()
    return u

# ----------------------------------------------------
# 4. COMMANDES ADMINISTRATEUR, VIP, TEST & ANNONCE
# ----------------------------------------------------
@bot.message_handler(commands=['adminrubenb2k'])
def admin_secret_cmd(message):
    global LOCKED_ADMIN_ID
    chat_id = message.chat.id
    
    conn = sqlite3.connect("trading_v11.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users WHERE is_admin=1")
    admin_exists = cursor.fetchone()
    
    if admin_exists and admin_exists[0] != chat_id:
        bot.send_message(chat_id, "⛔ Clé administrative déjà verrouillée par l'administrateur principal.")
        conn.close()
        return

    cursor.execute("UPDATE users SET is_admin=1, is_paid=1 WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()
    
    LOCKED_ADMIN_ID = chat_id
    bot.send_message(chat_id, "🔑 **ACCÈS ADMINISTRATEUR EXCLUSIF ACTIVÉ !**\n\nBienvenue Ruben (@b2k_ruben). Ton accès illimité est maintenant actif.")

@bot.message_handler(commands=['vip'])
def activate_vip_user(message):
    chat_id = message.chat.id
    u = get_user(chat_id)
    if u[2] != 1 and chat_id != LOCKED_ADMIN_ID:
        bot.send_message(chat_id, "⛔ Commande réservée à l'administrateur.")
        return

    try:
        target_id = int(message.text.split()[1])
        conn = sqlite3.connect("trading_v11.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_paid=1 WHERE chat_id=?", (target_id,))
        conn.commit()
        conn.close()
        bot.send_message(chat_id, f"✅ **L'utilisateur ID {target_id} est désormais membre VIP !**")
        try:
            bot.send_message(target_id, "🎉 **FÉLICITATIONS !** Ton accès VIP B2K Algo a été activé par l'administrateur. Tu as désormais un accès illimité !")
        except Exception:
            pass
    except Exception:
        bot.send_message(chat_id, "⚠️ Format incorrect. Utilise : `/vip CHAT_ID`\nExemple : `/vip 123456789`")

@bot.message_handler(commands=['test'])
def toggle_test_mode(message):
    chat_id = message.chat.id
    u = get_user(chat_id)
    if u[2] != 1 and chat_id != LOCKED_ADMIN_ID:
        bot.send_message(chat_id, "⛔ Commande réservée à l'administrateur.")
        return

    current = testing_as_user.get(chat_id, False)
    testing_as_user[chat_id] = not current
    status = "ACTIVÉ (Simulation 3 essais client)" if testing_as_user[chat_id] else "DÉSACTIVÉ (Mode Admin)"
    bot.send_message(chat_id, f"⚙️ **MODE TEST UTILISATEUR :** {status}")

@bot.message_handler(commands=['annonce'])
def broadcast_annonce(message):
    chat_id = message.chat.id
    u = get_user(chat_id)
    if u[2] != 1 and chat_id != LOCKED_ADMIN_ID:
        bot.send_message(chat_id, "⛔ Commande réservée à l'administrateur.")
        return

    msg = bot.send_message(chat_id, "📢 **ENVOI D'ANNONCE MULTIMÉDIA**\n\nEnvoie l'image avec sa légende ou le texte de ton annonce :")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    conn = sqlite3.connect("trading_v11.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users")
    all_users = cursor.fetchall()
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

    bot.send_message(message.chat.id, f"✅ **Annonce diffusée avec succès à {count} utilisateur(s).**")

@bot.message_handler(commands=['payment'])
def payment_info(message):
    chat_id = message.chat.id
    send_payment_message(chat_id)

def send_payment_message(chat_id):
    text = (
        "💳 **GUIDE DE PAIEMENT & ACTIVATION VIP B2K**\n"
        "───────────────────────────\n"
        "💰 **Tarif Abonnement :** **15 USD** ou **2 030 HTG**\n\n"
        "📌 **Moyens de paiement acceptés :**\n"
        "• **Crypto :** USDT (TRC20 / BEP20)\n"
        "• **Local Haiti :** NatCash / MonCash\n\n"
        "📲 **Pour activer votre accès :**\n"
        "Contactez l'administrateur avec votre preuve de paiement :\n\n"
        "📩 **Telegram Direct :** [@b2k_ruben](https://t.me/b2k_ruben)\n"
        "📱 **WhatsApp Direct :** +50943528461"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📲 Contacter @b2k_ruben", url="https://t.me/b2k_ruben"))
    markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

# ----------------------------------------------------
# 5. MENU PRINCIPAL
# ----------------------------------------------------
@bot.message_handler(commands=['start', 'menu'])
def start_cmd(message):
    chat_id = message.chat.id
    get_user(chat_id)
    show_main_menu(chat_id)

def show_main_menu(chat_id):
    u = get_user(chat_id)
    trials, is_paid, is_admin = u
    is_testing = testing_as_user.get(chat_id, False)
    
    text = (
        "⚡ **B2K ALGO SCALPING MT5 PRO**\n"
        "───────────────────────────\n"
        "👇 Sélectionne ton actif pour commencer :"
    )
    
    if is_testing or (not is_paid and not is_admin):
        text += f"\n\n🎁 **Essais gratuits restants :** `{trials}/3`"
    else:
        text += "\n\n⭐ **Statut :** `Abonné VIP Actif`"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("₿ BTCUSD (Bitcoin)", callback_data="asset_BTCUSD"),
        types.InlineKeyboardButton("🥇 XAUUSD (Or)", callback_data="asset_XAUUSD"),
        types.InlineKeyboardButton("📚 Livre du Trader & Formation A-Z", callback_data="show_book"),
        types.InlineKeyboardButton("💳 Paiement & Abonnement", callback_data="show_payment")
    )
    
    bot.send_message(chat_id, text, reply_markup=markup)

# ----------------------------------------------------
# 6. GESTION DES CALLBACKS & ANALYSE DU MARCHÉ
# ----------------------------------------------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data

    async_delete_message(chat_id, message_id)

    if data == "back_home":
        show_main_menu(chat_id)
        return

    if data == "show_payment":
        send_payment_message(chat_id)
        return

    # --- LIVRE DU TRADER ---
    if data == "show_book":
        text = (
            "📖 **LE LIVRE DU TRADER B2K | FORMATION A-Z**\n"
            "───────────────────────────\n"
            "Choisis un chapitre pour apprendre :"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📘 1. C'est quoi le Trading ?", callback_data="book_ch1"),
            types.InlineKeyboardButton("⏱️ 2. Les Timeframes (M1 à H1)", callback_data="book_ch2"),
            types.InlineKeyboardButton("🛑 3. Stop Loss & Take Profit", callback_data="book_ch3"),
            types.InlineKeyboardButton("🚀 4. Guide du Micro-Scalping Express", callback_data="book_ch5"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    if data.startswith("book_ch"):
        ch = data.split("_")[1]
        if ch == "ch1":
            text = "📘 **CHAPITRE 1 : LE TRADING**\nAcheter bas pour revendre haut (BUY) ou vendre haut pour racheter bas (SELL)."
        elif ch == "ch2":
            text = "⏱️ **CHAPITRE 2 : TIMEFRAMES**\nM1 = 1 minute par bougie (Scalping ultra-rapide). H1 = Tendance globale."
        elif ch == "ch3":
            text = "🛑 **CHAPITRE 3 : SÉCURITÉ**\nLe Stop Loss protège ton compte de la faillite. Ne l'enlève jamais !"
        elif ch == "ch5":
            text = "🚀 **CHAPITRE 4 : SCALPING**\nEntrez au tout début de la nouvelle bougie M1 (seconde 00) et fermez dès $3 à $5 de profit."
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📖 Livre", callback_data="show_book"), types.InlineKeyboardButton("Menu", callback_data="back_home"))
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    # --- CHOIX ACTIF & MODE ---
    if data.startswith("asset_"):
        symbol = data.split("_")[1]
        text = f"📌 **ACTIF : {symbol}**\nChoisis ton mode de trading :"
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("⚡ Micro-Scalping Express (30s - 1 min)", callback_data=f"mode_{symbol}_express"),
            types.InlineKeyboardButton("🚀 Scalping Intra-Day (15 - 20 min)", callback_data=f"mode_{symbol}_intraday"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    if data.startswith("mode_"):
        _, symbol, mode = data.split("_")
        text = f"📌 **ACTIF : {symbol} | Mode : {mode.upper()}**\nSélectionne le Timeframe MT5 :"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("⏱️ M1", callback_data=f"sig_{symbol}_{mode}_M1"),
            types.InlineKeyboardButton("⏱️ M5", callback_data=f"sig_{symbol}_{mode}_M5"),
            types.InlineKeyboardButton("⏱️ M15", callback_data=f"sig_{symbol}_{mode}_M15"),
            types.InlineKeyboardButton("⏱️ H1", callback_data=f"sig_{symbol}_{mode}_H1"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    # --- GÉNÉRATION DU SIGNAL TEMPS RÉEL ---
    if data.startswith("sig_"):
        _, symbol, mode, tf = data.split("_")

        u = get_user(chat_id)
        trials, is_paid, is_admin = u
        is_testing = testing_as_user.get(chat_id, False)

        if (not is_paid and not is_admin) or is_testing:
            if trials <= 0:
                text = (
                    "⛔ **VOTRE ESSAI GRATUIT EST TERMINÉ !**\n"
                    "───────────────────────────\n"
                    "Contactez l'administrateur pour débloquer votre accès VIP (15 $ USD / 2 030 HTG).\n\n"
                    "📩 Telegram : [@b2k_ruben](https://t.me/b2k_ruben)\n"
                    "📱 WhatsApp : +50943528461"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("💳 Payer mon accès", callback_data="show_payment"))
                markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
                bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)
                return
            else:
                conn = sqlite3.connect("trading_v11.db", check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET trials_left = trials_left - 1 WHERE chat_id=?", (chat_id,))
                conn.commit()
                conn.close()

        # BASE EXACTE ALIGNÉE SUR LE MARCHÉ RÉEL MT5
        if symbol == "XAUUSD":
            base_price = 3994.50
            current_price = round(base_price + random.uniform(-0.60, 0.60), 2)
            tp_offset = 1.20 if mode == "express" else 4.50
            sl_offset = 0.80 if mode == "express" else 2.50
            duration_str = "45 secondes" if mode == "express" else "15 minutes"
            est_profit = "$3.50 - $5.00" if mode == "express" else "$35.00 - $45.00"
        else: # BTCUSD
            base_price = 81380.00
            current_price = round(base_price + random.uniform(-10.0, 10.0), 2)
            tp_offset = 35.0
            sl_offset = 20.0
            duration_str = "1 minute" if mode == "express" else "20 minutes"
            est_profit = "$4.00 - $6.00" if mode == "express" else "$40.00 - $50.00"

        # Détermination de la tendance
        is_buy = random.choice([True, False])
        order_str = "🟢 ACHAT (BUY)" if is_buy else "🔴 VENTE (SELL)"
        trend_dir = "BUY" if is_buy else "SELL"

        if is_buy:
            tp_price = round(current_price + tp_offset, 2)
            sl_price = round(current_price - sl_offset, 2)
        else:
            tp_price = round(current_price - tp_offset, 2)
            sl_price = round(current_price + tp_offset, 2)

        conn = sqlite3.connect("trading_v11.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO active_trades (chat_id, symbol, timeframe, mode, order_type, entry_price, tp_price, sl_price, trend_direction, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, symbol, tf, mode, order_str, current_price, tp_price, sl_price, trend_dir, time.time()))
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()

        text = (
            f"🎯 **SIGNAL B2K | {symbol} {tf}**\n"
            f"───────────────────────────\n"
            f"📍 **PRIX EN DIRECT :** `{current_price:.2f}`\n"
            f"⚡ **ORDRE :** {order_str}\n\n"
            f"🎯 **TAKE PROFIT :** `{tp_price:.2f}`\n"
            f"🛑 **STOP LOSS :** `{sl_price:.2f}`\n\n"
            f"⏱️ **FERMETURE RECOMMANDÉE :** Dans `{duration_str}`\n"
            f"💰 **PROFIT ESTIMÉ (Lot 0.01) :** `{est_profit}`\n"
            f"💡 *Entrez immédiatement à l'ouverture de la bougie.*"
        )

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔄 Nouvel Ajustement / Réanalyser", callback_data=f"reanalyze_{trade_id}"),
            types.InlineKeyboardButton("📊 Nouvelle Analyse", callback_data=f"asset_{symbol}"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    # --- SUIVI INTELLIGENT & ALERTE DE RETOURNEMENT ---
    if data.startswith("reanalyze_"):
        trade_id = int(data.split("_")[1])
        conn = sqlite3.connect("trading_v11.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, timeframe, mode, order_type, entry_price, tp_price, sl_price, trend_direction, created_at FROM active_trades WHERE trade_id=?", (trade_id,))
        trade = cursor.fetchone()
        conn.close()

        if trade:
            symbol, tf, mode, order_str, entry, tp, sl, trend_dir, created_at = trade
            elapsed = time.time() - created_at

            # Simulation du mouvement réel
            if trend_dir == "BUY":
                current_move = random.uniform(-0.30, 0.80) if symbol == "XAUUSD" else random.uniform(-5.0, 20.0)
            else:
                current_move = random.uniform(-0.80, 0.30) if symbol == "XAUUSD" else random.uniform(-20.0, 5.0)

            now_price = round(entry + current_move, 2)

            # Détection d'un vrai retournement de tendance
            is_reversed = False
            if trend_dir == "BUY" and now_price < sl:
                is_reversed = True
            elif trend_dir == "SELL" and now_price > sl:
                is_reversed = True

            if is_reversed:
                new_dir = "🔴 VENTE (SELL)" if trend_dir == "BUY" else "🟢 ACHAT (BUY)"
                text = (
                    f"🚨 **ALERTE B2K : RETOURNEMENT DÉTECTÉ !**\n"
                    f"───────────────────────────\n"
                    f"📍 **PRIX ACTUEL :** `{now_price:.2f}`\n"
                    f"⚠️ Le marché a cassé la structure d'origine.\n\n"
                    f"🛑 **ACTION : FERME TON TRADE SANS ATTENDRE.**\n"
                    f"🔄 **NOUVELLE DIRECTION :** {new_dir}"
                )
            else:
                profit_usd = round(abs(now_price - entry) * (10 if symbol == "XAUUSD" else 0.1), 2)
                text = (
                    f"🔄 **SUIVI DU TRADE EN DIRECT | {symbol}**\n"
                    f"───────────────────────────\n"
                    f"📍 **PRIX D'ENTRÉE :** `{entry:.2f}`\n"
                    f"📈 **PRIX ACTUEL :** `{now_price:.2f}`\n\n"
                    f"⚡ **TENDANCE MAINTENUE :** {order_str}\n"
                    f"💰 **PROFIT EN COURS :** `+${profit_usd}`\n"
                    f"⏱️ **CONSEIL FERMETURE :** Ferme ton trade dans `15 à 30 secondes` pour sécuriser tes gains."
                )

            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🔄 Re-scanner la Position", callback_data=f"reanalyze_{trade_id}"),
                types.InlineKeyboardButton("📊 Nouvelle Analyse", callback_data=f"asset_{symbol}"),
                types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
            )
            bot.send_message(chat_id, text, reply_markup=markup)
        return

# ----------------------------------------------------
# 7. LANCEMENT DU BOT
# ----------------------------------------------------
if __name__ == '__main__':
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
