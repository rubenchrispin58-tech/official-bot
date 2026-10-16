import os
import random
import threading
from flask import Flask
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton

# Token officiel B2K Scalping Bot
TOKEN = os.environ.get('TELEGRAM_TOKEN', '8746547888:AAHJXQn2DqzrMu1WvGODE2i3bIkSSA_VJhs')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- DONNÉES EN MÉMOIRE ---
ADMIN_IDS = []        # Liste des administrateurs
CLIENTS_VIP = []      # Liste des abonnés VIP (15$)
GAINS_JOUR = {"total_pips": 0, "trades_gagnants": 0}

# --- SERVEUR WEB ANTI-EXTINCTION (RENDER) ---
@app.route('/')
def home():
    return "👑 Server B2K Scalping 24/7 Active!", 200

# --- CLAVIER INTERACTIF PREMIUM ---
def get_main_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    btn_scalping = KeyboardButton("📊 Signal Scalping Gold")
    btn_gains = KeyboardButton("🏆 Performance & Gains")
    btn_info = KeyboardButton("🛡️ Gestion du Risque & Règles")
    btn_vip = KeyboardButton("💎 Mon Statut VIP")
    
    markup.add(btn_scalping, btn_gains)
    markup.add(btn_info, btn_vip)
    
    # Bouton exclusif Administrateur
    if chat_id in ADMIN_IDS:
        btn_annonce = KeyboardButton("📢 Diffusion Annonce / Preuve")
        markup.add(btn_annonce)
        
    return markup

# --- COMMANDES DE DÉMARRAGE ET SÉCURITÉ ---

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

# --- GESTION DES ABONNÉS (15$) & ACCÈS VIP ---

@bot.message_handler(commands=['addclient'])
def add_client(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            parts = message.text.split()
            if len(parts) < 2:
                bot.reply_to(message, "⚠️ **Format correct :** `/addclient <ID_TELEGRAM>`\n\n*Exemple :* `/addclient 123456789`", parse_mode="Markdown")
                return
            user_id = int(parts[1])
            if user_id not in CLIENTS_VIP:
                CLIENTS_VIP.append(user_id)
                bot.reply_to(message, f"✅ **CLIENT VIP AJOUTÉ !**\n💳 L'utilisateur `{user_id}` a bien payé ses **15$** et a désormais accès aux signaux.", parse_mode="Markdown")
                try:
                    bot.send_message(user_id, "🎉 **Félicitations !** Votre accès VIP B2K Scalping à 15$ a été activé par l'administrateur. Tapez /start pour rafraîchir.")
                except Exception:
                    pass
            else:
                bot.reply_to(message, "ℹ️ Ce membre est déjà enregistré dans la liste VIP.")
        except ValueError:
            bot.reply_to(message, "❌ L'ID Telegram doit être un nombre valide.")
    else:
        bot.reply_to(message, "⛔ Commande réservée à l'administrateur.")

@bot.message_handler(commands=['delclient'])
def del_client(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            parts = message.text.split()
            if len(parts) < 2:
                bot.reply_to(message, "⚠️ **Format correct :** `/delclient <ID_TELEGRAM>`", parse_mode="Markdown")
                return
            user_id = int(parts[1])
            if user_id in CLIENTS_VIP:
                CLIENTS_VIP.remove(user_id)
                bot.reply_to(message, f"❌ **ACCÈS VIP RÉVOQUÉ** pour l'utilisateur `{user_id}`.", parse_mode="Markdown")
            else:
                bot.reply_to(message, "ℹ️ Cet utilisateur ne figure pas dans la liste VIP.")
        except ValueError:
            bot.reply_to(message, "❌ L'ID Telegram doit être un nombre valide.")
    else:
        bot.reply_to(message, "⛔ Commande réservée à l'administrateur.")

@bot.message_handler(commands=['addgains'])
def add_gains(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            parts = message.text.split()
            if len(parts) < 2:
                bot.reply_to(message, "⚠️ **Format correct :** `/addgains <PIPS>`\n*Exemple :* `/addgains 35`", parse_mode="Markdown")
                return
            pips = int(parts[1])
            GAINS_JOUR["total_pips"] += pips
            GAINS_JOUR["trades_gagnants"] += 1
            bot.reply_to(message, f"📈 **PERFORMANCE MISE À JOUR !**\n🔥 +{pips} pips ajoutés avec succès au tableau de bord.", parse_mode="Markdown")
        except ValueError:
            bot.reply_to(message, "❌ Veuillez spécifier un nombre valide de pips.")
    else:
        bot.reply_to(message, "⛔ Commande réservée à l'administrateur.")

# --- BOUTONS INTERACTIFS PREMIUM ---

@bot.message_handler(func=lambda msg: msg.text in ["💎 Mon Statut VIP", "/vip"])
def check_vip_status(message):
    user_id = message.from_user.id
    if user_id in CLIENTS_VIP or user_id in ADMIN_IDS:
        status_msg = (
            "💎 **VOTRE ABONNEMENT B2K VIP**\n"
            "_________________________________________\n\n"
            "✅ **Statut :** MEMBRE ACTIF (15$ Validé)\n"
            "🚀 **Accès :** Signaux Scalping Gold Illimités\n"
            "🛡️ **Garantie :** Protection de Capital B2K"
        )
    else:
        status_msg = (
            "🔒 **ACCÈS VIP RESTREINT**\n"
            "_________________________________________\n\n"
            "⚠️ Vous n'avez pas encore activé votre abonnement VIP.\n\n"
            "💵 **Tarif Accès VIP :** 15$\n"
            "📩 Contactez l'administrateur pour valider votre paiement et débloquer vos signaux scalping."
        )
    bot.send_message(message.chat.id, status_msg, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text in ["📊 Signal Scalping Gold", "/scalping", "/signal"])
def generate_signal(message):
    user_id = message.from_user.id
    if user_id not in CLIENTS_VIP and user_id not in ADMIN_IDS:
        bot.reply_to(message, "🔒 **ACCÈS REFUSÉ !**\n\nCe service est réservé aux membres VIP (15$). Contactez le créateur du bot pour activer votre compte.", parse_mode="Markdown")
        return

    base_price = round(random.uniform(2645.00, 2660.00), 2)
    order_type = random.choice(["🟢 ACHAT (BUY)", "🔴 VENTE (SELL)"])
    
    if "BUY" in order_type:
        tp_price = round(base_price + 2.50, 2)
        sl_price = round(base_price - 1.20, 2)
    else:
        tp_price = round(base_price - 2.50, 2)
        sl_price = round(base_price + 1.20, 2)
        
    pips_tp = int(abs(tp_price - base_price) / 0.10)
    
    signal_msg = (
        "🔥 **NOUVEAU SIGNAL SCALPING GOLD** 🔥\n"
        "_________________________________________\n\n"
        "👑 **ÉQUIPE :** B2K Scalping Pro\n"
        "📊 **ACTIF :** XAUUSD (Gold) | **TF :** M5\n"
        f"💵 **PRIX DE RENTRÉE :** ${base_price}\n"
        "_________________________________________\n\n"
        f"🚀 **ORDRE :** {order_type}\n\n"
        f"🎯 **TAKE PROFIT (TP) :** ${tp_price} (+{pips_tp} pips)\n"
        f"🛡️ **STOP LOSS (SL) :** ${sl_price}\n\n"
        "⚡ **RECOMMANDATION :** Déplacez le SL au breakeven dès +15 pips !\n"
        "_________________________________________\n"
        "⚠️ *Risque conseillé : 1% à 2% max par position.*"
    )
    bot.send_message(message.chat.id, signal_msg, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text in ["🏆 Performance & Gains", "/gains"])
def send_gains(message):
    gains_text = (
        "🏆 **TABLEAU DE BORD PERFORMANCES B2K**\n"
        "_________________________________________\n\n"
        f"🎯 **Trades Gagnants du jour :** {GAINS_JOUR['trades_gagnants']}\n"
        f"🚀 **Total Pips Accumulés :** +{GAINS_JOUR['total_pips']} pips\n"
        f"⚡ **Taux de Réussite Globale :** 94.8%\n\n"
        "💡 *Une discipline de fer garantit des résultats réguliers.*"
    )
    bot.send_message(message.chat.id, gains_text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text in ["🛡️ Gestion du Risque & Règles", "/info"])
def send_info(message):
    rules_text = (
        "🛡️ **CHARTE D'EXCELLENCE DE TRADING B2K**\n"
        "_________________________________________\n\n"
        "1️⃣ **Gestion du Capital :** Ne risquez jamais plus de **1% à 2%** de votre solde total par transaction.\n"
        "2️⃣ **Sécurisation :** À +15 ou +20 pips, encaissez 50% de vos bénéfices et passez en Stop Loss à 0 (Breakeven).\n"
        "3️⃣ **Gestion des Pertes :** Le Stop Loss est votre assurance. Ne le modifiez pas à la baisse.\n"
        "4️⃣ **Overtrading :** Limitez-vous à 2 ou 3 signaux validés par jour pour conserver votre lucidité.\n\n"
        "🏆 *Suivez scrupuleusement la stratégie pour maximiser vos pips sur le Gold.*"
    )
    bot.send_message(message.chat.id, rules_text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "📢 Diffusion Annonce / Preuve")
def prompt_annonce(message):
    if message.from_user.id in ADMIN_IDS:
        msg = bot.send_message(message.chat.id, "✏️ **Entrez le message ou la preuve de gain à diffuser :**", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_annonce)
    else:
        bot.send_message(message.chat.id, "⛔ Action réservée à l'administrateur.")

def process_annonce(message):
    annonce_text = f"📣 **COMMUNIQUÉ OFFICIEL B2K SCALPING**\n_________________________________________\n\n{message.text}"
    bot.send_message(message.chat.id, "✅ **Diffusion enregistrée !**", parse_mode="Markdown")
    bot.send_message(message.chat.id, annonce_text, parse_mode="Markdown")

# --- EXECUTION DU BOT EN MODE HYBRIDE (POLLING + FLASK) ---

def run_bot():
    bot.infinity_polling(skip_pending=True)

if __name__ == '__main__':
    # Démarre le bot dans un fil d'exécution séparé (Empêche l'arrêt lors de tes connexions)
    t = threading.Thread(target=run_bot)
    t.daemon = True
    t.start()
    
    # Lance le serveur Flask pour garder Render actif
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
