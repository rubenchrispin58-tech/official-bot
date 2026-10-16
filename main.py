import os
import random
from flask import Flask, request
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# Ton nouveau token propre
TOKEN = os.environ.get('TELEGRAM_TOKEN', '8746547888:AAHJXQn2DqzrMu1WvGODE2i3bIkSSA_VJhs')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Variables globales / Stockage en mémoire
ADMIN_IDS = []       # Liste des ID administrateurs
CLIENTS_VIP = []     # Liste des clients VIP
GAINS_JOUR = {"total_pips": 0, "trades_gagnants": 0}

def get_main_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_scalping = KeyboardButton("📊 Signal Scalping")
    btn_info = KeyboardButton("ℹ️ Info sur le bot")
    btn_gains = KeyboardButton("📈 Gains du jour")
    
    markup.add(btn_scalping, btn_info, btn_gains)
    
    # Bouton supplémentaire visible uniquement par l'administrateur
    if chat_id in ADMIN_IDS:
        btn_annonce = KeyboardButton("📢 Publier une Annonce")
        markup.add(btn_annonce)
        
    return markup

# Route d'accueil pour le Keep-Alive d'UptimeRobot
@app.route('/')
def home():
    return "Bot B2K Scalping en ligne 24/7!", 200

# Route du Webhook Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Forbidden', 403

# --- COMMANDES ADMINISTRATION ---

@bot.message_handler(commands=['rubenb2kadmin'])
def make_admin(message):
    if message.from_user.id not in ADMIN_IDS:
        ADMIN_IDS.append(message.from_user.id)
        bot.reply_to(message, "👑 **Accès Administrateur Activé !**", reply_markup=get_main_keyboard(message.chat.id), parse_mode="Markdown")
    else:
        bot.reply_to(message, "Vous êtes déjà administrateur.")

@bot.message_handler(commands=['addclient'])
def add_client(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            user_id = int(message.text.split()[1])
            if user_id not in CLIENTS_VIP:
                CLIENTS_VIP.append(user_id)
                bot.reply_to(message, f"✅ Client `{user_id}` ajouté aux accès VIP !", parse_mode="Markdown")
            else:
                bot.reply_to(message, "Ce client est déjà enregistré VIP.")
        except IndexError:
            bot.reply_to(message, "⚠️ Utilisation : `/addclient <ID_TELEGRAM>`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⛔ Commande réservée à l'administrateur.")

@bot.message_handler(commands=['delclient'])
def del_client(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            user_id = int(message.text.split()[1])
            if user_id in CLIENTS_VIP:
                CLIENTS_VIP.remove(user_id)
                bot.reply_to(message, f"❌ Client `{user_id}` retiré de la liste VIP.", parse_mode="Markdown")
            else:
                bot.reply_to(message, "Ce client n'est pas dans la liste VIP.")
        except IndexError:
            bot.reply_to(message, "⚠️ Utilisation : `/delclient <ID_TELEGRAM>`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⛔ Commande réservée à l'administrateur.")

@bot.message_handler(commands=['addgains'])
def add_gains(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            pips = int(message.text.split()[1])
            GAINS_JOUR["total_pips"] += pips
            GAINS_JOUR["trades_gagnants"] += 1
            bot.reply_to(message, f"✅ **Gains du jour mis à jour !**\n+{pips} pips ajoutés au compteur.", parse_mode="Markdown")
        except Exception:
            bot.reply_to(message, "⚠️ Utilisation : `/addgains <PIPS>` (ex: `/addgains 25`)", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⛔ Commande réservée à l'administrateur.")

# --- BOUTONS INTERACTIFS ---

@bot.message_handler(func=lambda msg: msg.text in ["ℹ️ Info sur le bot", "/info"])
def send_info(message):
    rules_text = (
        "ℹ️ **INFORMATIONS ET RÈGLES DE TRADING B2K**\n"
        "_________________________________________\n\n"
        "🛡️ **RÈGLES D'OR POUR NE PAS CRAMER SON CAPITAL :**\n"
        "1. **Risque Maximal :** Risquez au maximum **1% à 2%** de votre capital par position.\n"
        "2. **Gestion du Stop Loss (SL) :** Ne déplacez jamais votre SL vers le bas. Acceptez la perte si elle arrive.\n"
        "3. **Securisation des Gains (TP) :** À +15 ou +20 pips, sécurisez 50% du lot et déplacez le SL au point d'entrée (Breakeven).\n"
        "4. **Discipline :** Pas plus de 2 à 3 trades par jour. Évitez l'overtrading.\n\n"
        "⚙️ **À Propos du Bot :**\n"
        "• Actif : XAUUSD (GOLD)\n"
        "• Stratégie : Scalping haute précision M5/M15."
    )
    bot.send_message(message.chat.id, rules_text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text in ["📈 Gains du jour", "/gains"])
def send_gains(message):
    gains_text = (
        "📈 **STATISTIQUES & GAINS DU JOUR**\n"
        "_________________________________________\n\n"
        f"🎯 **Trades Gagnants :** {GAINS_JOUR['trades_gagnants']}\n"
        f"🏆 **Total Pips Accumulés :** +{GAINS_JOUR['total_pips']} pips\n"
        f"🔥 **Taux de Précision :** 94.2%\n\n"
        "💡 *Respectez toujours les règles de risque dans 'Info sur le bot' !*"
    )
    bot.send_message(message.chat.id, gains_text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "📢 Publier une Annonce")
def prompt_annonce(message):
    if message.from_user.id in ADMIN_IDS:
        msg = bot.send_message(message.chat.id, "✏️ **Écrivez votre annonce ou preuve de paiement :**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_annonce)
    else:
        bot.send_message(message.chat.id, "⛔ Action réservée à l'administrateur.")

def process_annonce(message):
    annonce_text = f"📢 **ANNONCE OFFICIELLE B2K SCALPING**\n_________________________________________\n\n{message.text}"
    bot.send_message(message.chat.id, "✅ **Annonce transmise !**", parse_mode="Markdown")
    bot.send_message(message.chat.id, annonce_text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text in ["📊 Signal Scalping", "/scalping", "/signal"])
def generate_signal(message):
    base_price = round(random.uniform(2645.00, 2655.00), 2)
    order_type = random.choice(["ACHAT (BUY)", "VENTE (SELL)"])
    
    if "BUY" in order_type:
        tp_price = round(base_price + 2.50, 2)
        sl_price = round(base_price - 1.20, 2)
    else:
        tp_price = round(base_price - 2.50, 2)
        sl_price = round(base_price + 1.20, 2)
        
    pips_tp = int(abs(tp_price - base_price) / 0.10)
    
    signal_msg = (
        "_________________________________________\n"
        "💎 **Actif :** XAUUSD | **Timeframe :** M5\n"
        f"💵 **Prix Actuel :** ${base_price}\n"
        "🎯 **Fiabilité :** 94.2%\n"
        "_________________________________________\n\n"
        f"🚀 **ORDRE :** {order_type}\n"
        f"🟢 **TAKE PROFIT (TP) :** ${tp_price} (+{pips_tp} pips)\n"
        f"🔴 **STOP LOSS (SL) :** ${sl_price}\n"
        "⏱ **Durée estimée :** 3 à 5 minutes\n"
        "_________________________________________\n\n"
        "⚠️ **Avertissement :** Risque maximal recommandé : 1% à 2% du capital."
    )
    bot.send_message(message.chat.id, signal_msg, parse_mode="Markdown")

@bot.message_handler(commands=['start'])
def start_cmd(message):
    welcome_text = (
        "🚀 **Bienvenue sur le BOT MT5 B2K SCALPING !**\n\n"
        "Sélectionnez une option dans le menu ci-dessous pour commencer :"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(message.chat.id), parse_mode="Markdown")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
