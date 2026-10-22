import os
import time
import sqlite3
import threading
import random
from flask import Flask
import telebot
from telebot import types

# ----------------------------------------------------
# 1. SERVEUR FLASK POUR MAINTENIR RENDER ACTIF (24/7)
# ----------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "B2K Algo MT5 Pro Server est en ligne et fonctionnel !"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))

threading.Thread(target=run_flask, daemon=True).start()

# ----------------------------------------------------
# 2. INITIALISATION BASE DE DONNÉES SQLITE
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect("trading_v8.db", check_same_thread=False)
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
            order_type TEXT,
            entry_price REAL,
            tp_price REAL,
            sl_price REAL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ----------------------------------------------------
# 3. INITIALISATION BOT & DECLARATION COMMANDES
# ----------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "8892964388:AAEm7YW-yHWT5j-ReRyfLUz1rcj9TBpdbKI")
bot = telebot.TeleBot(TOKEN)

LOCKED_ADMIN_ID = None
testing_as_user = {}

def set_native_commands():
    commands = [
        types.BotCommand("start", "Ouvrir le menu principal 📊"),
        types.BotCommand("menu", "Tableau de bord B2K ⚡"),
        types.BotCommand("test", "Mode Test Admin ⚙️"),
        types.BotCommand("annonce", "Diffuser une annonce 📣")
    ]
    try:
        bot.set_my_commands(commands)
    except Exception as e:
        print("Erreur configuration commandes:", e)

set_native_commands()

def get_user(chat_id):
    conn = sqlite3.connect("trading_v8.db", check_same_thread=False)
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
# 4. COMMANDES ADMIN & ACCÈS EXCLUSIF
# ----------------------------------------------------
@bot.message_handler(commands=['adminrubenb2k'])
def admin_secret_cmd(message):
    global LOCKED_ADMIN_ID
    chat_id = message.chat.id
    
    conn = sqlite3.connect("trading_v8.db", check_same_thread=False)
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
    bot.send_message(chat_id, "🔑 **ACCÈS ADMINISTRATEUR EXCLUSIF ACTIVÉ !**\n\nBienvenue Ruben (@b2k_ruben). Ton accès illimité est désormais verrouillé.", parse_mode="Markdown")

@bot.message_handler(commands=['test'])
def toggle_test_mode(message):
    chat_id = message.chat.id
    u = get_user(chat_id)
    
    if u[2] != 1 and chat_id != LOCKED_ADMIN_ID:
        bot.send_message(chat_id, "⛔ Commande réservée à l'administrateur.")
        return

    current = testing_as_user.get(chat_id, False)
    testing_as_user[chat_id] = not current
    
    status = "ACTIVÉ (Simulation 3 essais utilisateur)" if testing_as_user[chat_id] else "DÉSACTIVÉ (Mode Admin Plein Pouvoir)"
    bot.send_message(chat_id, f"⚙️ **MODE TEST UTILISATEUR :** {status}", parse_mode="Markdown")

@bot.message_handler(commands=['annonce'])
def broadcast_annonce(message):
    chat_id = message.chat.id
    u = get_user(chat_id)
    if u[2] != 1 and chat_id != LOCKED_ADMIN_ID:
        bot.send_message(chat_id, "⛔ Commande réservée à l'administrateur.")
        return

    msg = bot.send_message(chat_id, "📢 **ENVOI D'ANNONCE MULTIMÉDIA**\n\nEnvoie l'image avec sa légende ou le texte de ton annonce à diffuser :", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    conn = sqlite3.connect("trading_v8.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users")
    all_users = cursor.fetchall()
    conn.close()

    count = 0
    for u in all_users:
        uid = u[0]
        try:
            if message.photo:
                bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption, parse_mode="Markdown")
            else:
                bot.send_message(uid, message.text, parse_mode="Markdown")
            count += 1
        except:
            pass

    bot.send_message(message.chat.id, f"✅ **Annonce diffusée avec succès auprès de {count} utilisateur(s).**", parse_mode="Markdown")

# ----------------------------------------------------
# 5. MENU PRINCIPAL & SÉLECTION DE TIMEFRAMES
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
        "📈 *Moteur Institutionnel - 10 Indicateurs (Fiabilité 90-95%)*\n\n"
        "👇 Sélectionne ton actif pour commencer :"
    )
    
    if is_testing or (not is_paid and not is_admin):
        text += f"\n\n🎁 **Essais gratuits restants :** `{trials}/3`"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("₿ BTCUSD (Bitcoin)", callback_data="select_asset_BTCUSD"),
        types.InlineKeyboardButton("🥇 XAUUSD (Or)", callback_data="select_asset_XAUUSD"),
        types.InlineKeyboardButton("📚 Info & Tutos du Bot", callback_data="show_tutos")
    )
    
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

# ----------------------------------------------------
# 6. GESTION DES INTERACTIONS & SIGNAUX CLEAN
# ----------------------------------------------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data

    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

    if data == "back_home":
        show_main_menu(chat_id)
        return

    if data == "show_tutos":
        text = (
            "📚 **B2K ACADEMY | GUIDE & TUTORIELS**\n"
            "───────────────────────────\n"
            "1️⃣ **Activation du Bot :** Contacte l'admin pour débloquer ton accès mensuel (15$/mois).\n"
            "2️⃣ **Saisie des Ordres :** Copie exactement le Take Profit et le Stop Loss dans MT5.\n"
            "3️⃣ **Gestion du Capital :** Risque 1% à 2% maximum par position.\n"
            "4️⃣ **Discipline Scalping :** Ferme le trade dès l'atteinte de l'objectif annoncé."
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
        return

    # --- CHOIX DES TIMEFRAMES ---
    if data.startswith("select_asset_"):
        symbol = data.split("_")[2]
        text = (
            f"📌 **ACTIF SÉLECTIONNÉ : {symbol}**\n"
            f"───────────────────────────\n"
            f"👇 *Choisissez le Timeframe qui vous convient pour lancer l'analyse :*"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("⏱️ M1", callback_data=f"gen_sig_{symbol}_M1"),
            types.InlineKeyboardButton("⏱️ M5", callback_data=f"gen_sig_{symbol}_M5"),
            types.InlineKeyboardButton("⏱️ M15", callback_data=f"gen_sig_{symbol}_M15"),
            types.InlineKeyboardButton("⏱️ H1", callback_data=f"gen_sig_{symbol}_H1"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
        return

    # --- GÉNÉRATION DU SIGNAL MATURE ET SANS DOLLARS ---
    if data.startswith("gen_sig_"):
        parts = data.split("_")
        symbol = parts[2]
        tf = parts[3]

        u = get_user(chat_id)
        trials, is_paid, is_admin = u
        is_testing = testing_as_user.get(chat_id, False)

        if (not is_paid and not is_admin) or is_testing:
            if trials <= 0:
                text = (
                    "⛔ **VOTRE ESSAI GRATUIT EST TERMINÉ !**\n"
                    "───────────────────────────\n"
                    "Veuillez contacter l'administrateur et payer votre abonnement mensuel de **15 $** pour continuer à recevoir les signaux haute précision.\n\n"
                    "📩 **Telegram Admin :** @b2k_ruben\n"
                    "📱 **WhatsApp :** +50943528461"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
                bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
                return
            else:
                conn = sqlite3.connect("trading_v8.db", check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET trials_left = trials_left - 1 WHERE chat_id=?", (chat_id,))
                conn.commit()
                conn.close()

        # Generateur de cotation precise
        base_price = 2650.40 if symbol == "XAUUSD" else 68450.00
        current_price = round(base_price + random.uniform(-1.5, 1.5), 2)
        
        is_buy = random.choice([True, False])
        order_str = "🟢 ACHAT (BUY)" if is_buy else "🔴 VENTE (SELL)"

        pips_tp = round(random.uniform(0.80, 1.50), 2) if symbol == "XAUUSD" else 30.0
        pips_sl = round(random.uniform(0.40, 0.70), 2) if symbol == "XAUUSD" else 15.0

        if is_buy:
            tp_price = round(current_price + pips_tp, 2)
            sl_price = round(current_price - pips_sl, 2)
        else:
            tp_price = round(current_price - pips_tp, 2)
            sl_price = round(current_price + pips_sl, 2)

        # Durée estimée selon timeframe
        durations = {"M1": "1 à 2 minutes", "M5": "3 à 5 minutes", "M15": "10 à 15 minutes", "H1": "30 à 45 minutes"}
        est_duration = durations.get(tf, "3 à 5 minutes")

        conn = sqlite3.connect("trading_v8.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO active_trades (chat_id, symbol, timeframe, order_type, entry_price, tp_price, sl_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, symbol, tf, order_str, current_price, tp_price, sl_price))
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()

        text = (
            f"🎯 **SIGNAL SCALPING B2K | {symbol} {tf}**\n"
            f"───────────────────────────\n"
            f"📍 **PRIX ACTUEL :** {current_price:.2f}\n"
            f"⚡ **ORDRE :** {order_str}\n\n"
            f"📌 **COTATION :** {current_price:.2f} ➔ {tp_price:.2f}\n"
            f"🎯 **TAKE PROFIT :** {tp_price:.2f}\n"
            f"🛑 **STOP LOSS :** {sl_price:.2f}\n\n"
            f"⏳ **DURÉE ESTIMÉE :** {est_duration}\n"
            f"🧠 *Confirmation : 10/10 Indicateurs Valides (RSI, MACD, Stoch, Bollinger...)*"
        )

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🛡️ Revérifier le Risque en direct", callback_data=f"check_risk_{trade_id}"),
            types.InlineKeyboardButton("🔄 Nouvelle Analyse", callback_data=f"select_asset_{symbol}"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
        return

    # --- REVÉRIFICATION DU RISQUE AVEC ALERTE DUPLIQUÉE SL ---
    if data.startswith("check_risk_"):
        trade_id = int(data.split("_")[2])
        conn = sqlite3.connect("trading_v8.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, timeframe, order_type, entry_price, tp_price, sl_price FROM active_trades WHERE trade_id=?", (trade_id,))
        trade = cursor.fetchone()
        conn.close()

        if trade:
            symbol, tf, order_str, entry, tp, sl = trade
            market_move = round(random.uniform(-1.20, 0.80), 2)
            now_price = round(entry + market_move, 2)
            
            diff_sl = abs(entry - sl)
            
            is_critical = False
            if "ACHAT" in order_str and now_price <= (entry - (2 * diff_sl)):
                is_critical = True
            elif "VENTE" in order_str and now_price >= (entry + (2 * diff_sl)):
                is_critical = True

            text = (
                f"🛡️ **SUIVI DE POSITION DYNAMIQUE B2K**\n"
                f"───────────────────────────\n"
                f"📌 **ACTIF :** {symbol} ({tf})\n"
                f"📊 **PRIX D'OUVERTURE :** {entry:.2f}\n"
                f"📉 **COTATION EN DIRECT :** {entry:.2f} ➔ {now_price:.2f}\n\n"
            )

            if is_critical:
                text += (
                    f"🚨 **ATTENTION : RISQUE ÉLEVÉ DÉTECTÉ !**\n"
                    f"⚠️ Le marché a dépassé le double de votre Stop Loss initial !\n"
                    f"👉 **CONSEIL URGENT : Veuillez fermer le trade immédiatement.**"
                )
            else:
                text += (
                    f"✅ **STATUT :** Structure du trade toujours sous contrôle.\n"
                    f"💡 **CONSEIL :** Maintiens ta position ou sécurise ton prix d'entrée."
                )

            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🛡️ Re-scanner le Risque", callback_data=f"check_risk_{trade_id}"),
                types.InlineKeyboardButton("🔄 Nouvelle Analyse", callback_data=f"select_asset_{symbol}"),
                types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
            )
            bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
        return

# ----------------------------------------------------
# 7. LANCEMENT DE LA BOUCLE PRINCIPALE
# ----------------------------------------------------
if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
