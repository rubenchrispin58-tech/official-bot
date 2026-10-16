import os
import random
from flask import Flask, request
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

TOKEN = os.environ.get('TELEGRAM_TOKEN', '8892964388:AAFPcBAPtal5QXsgOqEGN3tbKYV77Hsn1Ow')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

ADMIN_IDS = []       
CLIENTS_VIP = []     
GAINS_JOUR = {"total_pips": 0, "trades_gagnants": 0}

def get_main_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    btn_scalping = KeyboardButton("📊 Signal Scalping Gold")
    btn_gains = KeyboardButton("🏆 Performance & Gains")
    btn_info = KeyboardButton("🛡️ Gestion du Risque & Règles")
    btn_vip = KeyboardButton("💎 Mon Statut VIP")
    
    markup.add(btn_scalping, btn_gains)
    markup.add(btn_info, btn_vip)
    
    if chat_id in ADMIN_IDS:
        btn_annonce = KeyboardButton("📢 Diffusion Annonce / Preuve")
        markup.add(btn_annonce)
        
    return markup

@app.route('/')
def home():
    return "👑 Server B2K Scalping 24/7 Active!", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return 'Forbidden', 403

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Trader"
    welcome_text = (
        f"✨ **BIENVENUE SUR B2K SCALPING VIP** ✨\n"
        f"_________________________________________\n\n"
        f"👋 Salut **{first_name}** !\n\n"
        f"🏆 **Plateforme Officielle de Signaux XAUUSD (Gold)**\n"
        f"⚡ Signaux Haute Précision M5/M15 avec algorithme automatisé.\n\n"
        f"👉 *Utilisez le menu ci-dessous pour naviguer.*"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")

@bot.message_handler(commands=['rubenb2kadmin'])
def make_admin(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        ADMIN_IDS.append(user_id)
        if user_id not in CLIENTS_VIP:
            CLIENTS_VIP.append(user_id)
        bot.reply_to(message, "👑 **ACCÈS FONDATEUR & ADMIN ACTIVÉ !**\nVous avez un contrôle total sur le bot.", reply_markup=get_main_keyboard(user_id), parse_mode="Markdown")
    else:
        bot.reply_to(message, "👑 Vous êtes déjà administrateur du système.")

@bot.message_handler(commands=['addclient'])
def add_client(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            parts = message.text.split()
            if len(parts) < 2:
                bot.reply_to(message, "⚠️ **Format correct :** `/addclient <ID_TELEGRAM>`", parse_mode="Markdown")
                return
            user_id = int(parts[1])
            if user_id not in CLIENTS_VIP:
                CLIENTS_VIP.append(user_id)
                bot.reply_to(message, f"✅ **CLIENT VIP AJOUTÉ !**\n💳 L'utilisateur `{user_id}` a désormais accès aux signaux.", parse_mode="Markdown")
            else:
                bot.reply_to(message, "ℹ️ Ce membre est déjà VIP.")
        except ValueError:
            bot.reply_to(message, "❌ L'ID doit être un nombre valide.")
    else:
        bot.reply_to(message, "⛔ Commande réservée à l'admin.")

@bot.message_handler(func=lambda msg: msg.text in ["💎 Mon Statut VIP", "/vip"])
def check_vip_status(message):
    user_id = message.from_user.id
    if user_id in CLIENTS_VIP or user_id in ADMIN_IDS:
        status_msg = "💎 **VOTRE ABONNEMENT B2K VIP**\n✅ **Statut :** MEMBRE ACTIF (15$ Validé)"
    else:
        status_msg = "🔒 **ACCÈS VIP RESTREINT**\n💵 **Tarif Accès VIP :** 15$"
    bot.send_message(message.chat.id, status_msg, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text in ["📊 Signal Scalping Gold", "/scalping", "/signal"])
def generate_signal(message):
    user_id = message.from_user.id
    if user_id not in CLIENTS_VIP and user_id not in ADMIN_IDS:
        bot.reply_to(message, "🔒 **ACCÈS REFUSÉ !** Réservé aux membres VIP.", parse_mode="Markdown")
        return

    base_price = round(random.uniform(2645.00, 2660.00), 2)
    order_type = random.choice(["🟢 ACHAT (BUY)", "🔴 VENTE (SELL)"])
    tp_price = round(base_price + 2.50, 2) if "BUY" in order_type else round(base_price - 2.50, 2)
    sl_price = round(base_price - 1.20, 2) if "BUY" in order_type else round(base_price + 1.20, 2)
    pips_tp = int(abs(tp_price - base_price) / 0.10)
    
    signal_msg = (
        f"🔥 **NOUVEAU SIGNAL SCALPING GOLD** 🔥\n\n"
        f"📊 **ACTIF :** XAUUSD (Gold) | **TF :** M5\n"
        f"💵 **PRIX :** ${base_price}\n"
        f"🚀 **ORDRE :** {order_type}\n"
        f"🎯 **TP :** ${tp_price} (+{pips_tp} pips)\n"
        f"🛡️ **SL :** ${sl_price}"
    )
    bot.send_message(message.chat.id, signal_msg, parse_mode="Markdown")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
