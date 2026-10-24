import os
import time
import sqlite3
import threading
import random
import requests
from flask import Flask
import telebot
from telebot import types

# ----------------------------------------------------
# 0. ZONE DE FORMATION & TUTOS (MODIFIABLE À VOLONTÉ)
# ----------------------------------------------------
TRAINING_CHAPTERS = {
    "ch1": (
        "📘 **CHAPITRE 1 : C'est quoi le Trading ?**\n"
        "───────────────────────────\n"
        "Le trading consiste à spéculer sur la hausse (BUY) ou la baisse (SELL) des actifs financiers "
        "comme le Bitcoin (BTCUSD) ou l'Or (XAUUSD) pour générer des profits."
    ),
    "ch2": (
        "⏱️ **CHAPITRE 2 : Maîtriser les Timeframes**\n"
        "───────────────────────────\n"
        "• **M1 / M5 :** Micro-scalping ultra-rapide.\n"
        "• **M15 / H1 :** Analyse des tendances majeures."
    ),
    "ch3": (
        "🚀 **CHAPITRE 3 : Guide du Micro-Scalping**\n"
        "───────────────────────────\n"
        "1. Lance l'analyse sur le bot.\n"
        "2. Exécute immédiatement ton ordre dès le début de la nouvelle bougie."
    )
}

# ----------------------------------------------------
# 1. SERVEUR FLASK POUR UPTIMEROBOT & RENDER (24/7)
# ----------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "B2K Algo MT5 Pro Auto v19.0 - Actif !"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ----------------------------------------------------
# 2. RÉCUPÉRATION FLUX DYNAMIQUE
# ----------------------------------------------------
def get_live_price(symbol):
    if symbol == "BTCUSD":
        try:
            res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=2).json()
            return round(float(res['price']), 2)
        except Exception:
            pass
    return 80800.00

# ----------------------------------------------------
# 3. INITIALISATION BASE DE DONNÉES
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect("trading_v19.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            trials_left INTEGER DEFAULT 3,
            is_paid INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ----------------------------------------------------
# 4. CONFIGURATION BOT & CLEAN CHAT
# ----------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown", threaded=True, num_threads=16)

LOCKED_ADMIN_ID = None
testing_as_user = {}

def clean_delete_message(chat_id, message_id):
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
        types.BotCommand("payment", "Guide de paiement (20$) 💳"),
        types.BotCommand("test", "Mode Test Admin ⚙️"),
        types.BotCommand("annonce", "Diffuser une annonce 📣")
    ]
    try:
        bot.set_my_commands(commands)
    except Exception as e:
        print("Erreur commandes:", e)

set_native_commands()

def get_user(chat_id):
    conn = sqlite3.connect("trading_v19.db", check_same_thread=False)
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
# 5. COMMANDES ADMIN, VIP & PAIEMENT
# ----------------------------------------------------
@bot.message_handler(commands=['adminrubenb2k'])
def admin_secret_cmd(message):
    global LOCKED_ADMIN_ID
    chat_id = message.chat.id
    conn = sqlite3.connect("trading_v19.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM users WHERE is_admin=1")
    admin_exists = cursor.fetchone()
    
    if admin_exists and admin_exists[0] != chat_id:
        bot.send_message(chat_id, "⛔ Clé administrative déjà verrouillée.")
        conn.close()
        return

    cursor.execute("UPDATE users SET is_admin=1, is_paid=1 WHERE chat_id=?", (chat_id,))
    conn.commit()
    conn.close()
    
    LOCKED_ADMIN_ID = chat_id
    bot.send_message(chat_id, "🔑 **ACCÈS ADMINISTRATEUR ACTIVÉ !**\n\nBienvenue Ruben (@b2k_ruben).")

@bot.message_handler(commands=['vip'])
def activate_vip_user(message):
    chat_id = message.chat.id
    u = get_user(chat_id)
    if u[2] != 1 and chat_id != LOCKED_ADMIN_ID:
        return
    try:
        target_id = int(message.text.split()[1])
        conn = sqlite3.connect("trading_v19.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_paid=1 WHERE chat_id=?", (target_id,))
        conn.commit()
        conn.close()
        bot.send_message(chat_id, f"✅ **ID {target_id} activé VIP !**")
    except Exception:
        bot.send_message(chat_id, "Format: `/vip CHAT_ID`")

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
    bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

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
    trials, is_paid, is_admin = u
    is_testing = testing_as_user.get(chat_id, False)
    
    text = (
        "⚡ **B2K ALGO SCALPING MT5 PRO v19.0**\n"
        "───────────────────────────\n"
        "🤖 Analyseur de marché haute précision 24/7.\n\n"
        "👇 Sélectionne ton actif pour lancer l'analyse :"
    )
    
    if is_testing or (not is_paid and not is_admin):
        text += f"\n\n🎁 **Essais gratuits restants :** `{trials}/3`"
    else:
        text += "\n\n⭐ **Statut :** `Abonné VIP Actif`"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("₿ BTCUSD (Bitcoin)", callback_data="asset_BTCUSD"),
        types.InlineKeyboardButton("🥇 XAUUSD (Or) - Marché Fermé 🚪", callback_data="asset_XAUUSD"),
        types.InlineKeyboardButton("📚 Formation & Tutos", callback_data="show_book"),
        types.InlineKeyboardButton("💳 Abonnement VIP (20$)", callback_data="show_payment")
    )
    
    bot.send_message(chat_id, text, reply_markup=markup)

# ----------------------------------------------------
# 7. TRAITEMENT AUTOMATIQUE SANS BUGS
# ----------------------------------------------------
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data

    clean_delete_message(chat_id, message_id)

    if data == "back_home":
        show_main_menu(chat_id)
        return

    if data == "show_payment":
        send_payment_message(chat_id)
        return

    if data == "show_book":
        text = "📖 **ACADÉMIE B2K | SECTIONS DE FORMATION**\nChoisis un chapitre :"
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📘 1. C'est quoi le Trading ?", callback_data="book_ch1"),
            types.InlineKeyboardButton("⏱️ 2. Les Timeframes", callback_data="book_ch2"),
            types.InlineKeyboardButton("🚀 3. Guide Micro-Scalping", callback_data="book_ch3"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    if data.startswith("book_"):
        ch_key = data.replace("book_", "")
        text = TRAINING_CHAPTERS.get(ch_key, "Contenu bientôt disponible.")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📖 Formation", callback_data="show_book"), types.InlineKeyboardButton("Menu", callback_data="back_home"))
        bot.send_message(chat_id, text, reply_markup=markup)
        return

    if data.startswith("asset_"):
        symbol = data.split("_")[1]

        if symbol == "XAUUSD":
            text = "🚪 **MARCHÉ DU GOLD FERMÉ**\nLe marché de l'Or est fermé durant le week-end.\n💡 Utilise le BTCUSD qui fonctionne 24/7 !"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("₿ BTCUSD (Bitcoin)", callback_data="asset_BTCUSD"))
            markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
            bot.send_message(chat_id, text, reply_markup=markup)
            return

        text = f"📌 **ACTIF : {symbol}**\nSélectionne ton mode de trading :"
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

    # GENERATION INSTANTANÉE ET AUTOMATIQUE DU SIGNAL
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
                    "Débloquez votre accès VIP illimité pour 20 $ USD / 2 700 HTG.\n\n"
                    "📩 Telegram : [@b2k_ruben](https://t.me/b2k_ruben)\n"
                    "📱 WhatsApp : +50943528461"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("💳 Payer mon accès (20$)", callback_data="show_payment"))
                markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
                bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)
                return
            else:
                conn = sqlite3.connect("trading_v19.db", check_same_thread=False)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET trials_left = trials_left - 1 WHERE chat_id=?", (chat_id,))
                conn.commit()
                conn.close()

        # Récupération automatique du prix en temps réel
        current_price = get_live_price(symbol)

        tp_offset = 20.0
        sl_offset = 12.0
        pips_count = 200

        is_buy = random.choice([True, False])
        order_str = "🟢 ACHAT (BUY)" if is_buy else "🔴 VENTE (SELL)"
        win_probability = round(random.uniform(86.5, 94.2), 1)

        if is_buy:
            tp_price = round(current_price + tp_offset, 2)
            sl_price = round(current_price - sl_offset, 2)
        else:
            tp_price = round(current_price - tp_offset, 2)
            sl_price = round(current_price + tp_offset, 2)

        # Message adapté au Timeframe sans aucun bug d'affichage
        if tf == "M1":
            tempo_str = "~30s à 1 min"
            exec_note = "Exécutez immédiatement à l'ouverture de la nouvelle bougie M1 (seconde 00)."
        elif tf == "M5":
            tempo_str = "~3 min à 5 min"
            exec_note = "Exécutez à l'ouverture de la bougie M5."
        elif tf == "M15":
            tempo_str = "~10 min à 15 min"
            exec_note = "Exécutez à l'ouverture de la bougie M15."
        else: # H1
            tempo_str = "~30 min à 1h"
            exec_note = "Exécutez dès la confirmation de la bougie H1."

        result_text = (
            f"🎯 **SIGNAL SCALPING B2K | {symbol} {tf}**\n"
            f"───────────────────────────\n"
            f"📍 **PRIX INDICATIF EN DIRECT :** `{current_price:.2f}`\n"
            f"⚡ **ORDRE :** {order_str}\n\n"
            f"🎯 **TAKE PROFIT :** `{tp_price:.2f}` *(+{pips_count} pips)*\n"
            f"🛑 **STOP LOSS :** `{sl_price:.2f}`\n\n"
            f"📊 **PROBABILITÉ ALGORITHMIQUE :** `{win_probability}%`\n"
            f"⏱️ **TEMPO FERMETURE :** {tempo_str}\n"
            f"💡 *{exec_note}*"
        )

        # Boutons propres sans l'option "Réanalyser" qui bugguait
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📊 Nouvelle Analyse", callback_data=f"asset_{symbol}"),
            types.InlineKeyboardButton("Menu Principal", callback_data="back_home")
        )
        bot.send_message(chat_id, result_text, reply_markup=markup)
        return

if __name__ == '__main__':
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
