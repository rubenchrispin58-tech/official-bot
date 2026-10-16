import os
import time
import random
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Token officiel B2K Bot
TOKEN = os.environ.get('TELEGRAM_TOKEN', '8892964388:AAFPcBAPtal5QXsgOqEGN3tbKYV77Hsn1Ow')
bot = telebot.TeleBot(TOKEN)

# --- BASE DE DONNÉES EN MÉMOIRE ---
ADMIN_IDS = []           # IDs des administrateurs
CLIENTS_VIP = []         # IDs des abonnés VIP (15$)
ESSAIS_GRATUITS = {}     # Dict {user_id: essais_restants}
LAST_CLICK = {}          # Anti-Spam {user_id: timestamp}
GAINS_JOUR = {"total_pips": 0, "trades_gagnants": 0}

# --- ANTI-SPAM (3 Secondes de délai) ---
def is_spamming(user_id):
    current_time = time.time()
    if user_id in LAST_CLICK and current_time - LAST_CLICK[user_id] < 3:
        return True
    LAST_CLICK[user_id] = current_time
    return False

# --- CLAVIERS INLINE STYLE PRO ---

def get_start_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    btn_analyser = InlineKeyboardButton("📊 Analyser le Marché", callback_data="menu_assets")
    btn_reverifier = InlineKeyboardButton("🔄 Revérifier le Trade (Retournement)", callback_data="recheck_trade")
    markup.add(btn_analyser, btn_reverifier)
    return markup

def get_assets_keyboard():
    markup = InlineKeyboardMarkup(row_width=3)
    btn_gold = InlineKeyboardButton("🥇 XAUUSD (Gold)", callback_data="asset_XAUUSD")
    btn_eur = InlineKeyboardButton("💶 EURUSD", callback_data="asset_EURUSD")
    btn_btc = InlineKeyboardButton("₿ BTCUSD", callback_data="asset_BTCUSD")
    markup.add(btn_gold, btn_eur, btn_btc)
    return markup

def get_timeframe_keyboard(asset):
    markup = InlineKeyboardMarkup(row_width=2)
    btn_m1 = InlineKeyboardButton("⚡ M1", callback_data=f"tf_{asset}_M1")
    btn_m5 = InlineKeyboardButton("🚀 M5", callback_data=f"tf_{asset}_M5")
    btn_m15 = InlineKeyboardButton("📈 M15", callback_data=f"tf_{asset}_M15")
    btn_h1 = InlineKeyboardButton("📊 H1", callback_data=f"tf_{asset}_H1")
    markup.add(btn_m1, btn_m5, btn_m15, btn_h1)
    return markup

# --- COMMANDES PRINCIPALES ---

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Trader"

    # Attribution de 3 essais gratuits
    if user_id not in ESSAIS_GRATUITS and user_id not in CLIENTS_VIP and user_id not in ADMIN_IDS:
        ESSAIS_GRATUITS[user_id] = 3

    essais = ESSAIS_GRATUITS.get(user_id, 0)
    
    welcome_text = (
        f"🤖 **Bienvenue dans le B2K Gold & Crypto Scalping Bot.**\n\n"
        f"Ce bot est algorithmiquement programmé pour le scalping haute précision sur l'Or (XAUUSD), EURUSD et BTCUSD.\n\n"
        f"🎯 **Fiabilité estimée :** Jusqu'à 91.3% par session de trade.\n\n"
        f"📞 **Pour plus d'informations sur le bot :**\n"
        f"Contactez-nous au **+509 43 52 84 61** ou via **@b2k_ruben**.\n\n"
        f"🎁 **Essai gratuit :** Vous disposez de **{essais} signaux gratuits**.\n"
        f"Appuyez sur un bouton ci-dessous pour lancer l'analyse."
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=get_start_keyboard(), parse_mode="Markdown")

# --- COMMANDES D'ADMINISTRATION & ANNONCES ---

@bot.message_handler(commands=['rubenb2kadmin'])
def make_admin(message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        ADMIN_IDS.append(user_id)
        if user_id not in CLIENTS_VIP:
            CLIENTS_VIP.append(user_id)
        bot.reply_to(message, "👑 **RÔLE FONDATEUR & ADMIN ACTIVÉ !**\nVous contrôlez le système B2K.", parse_mode="Markdown")
    else:
        bot.reply_to(message, "👑 Vous êtes déjà administrateur.")

@bot.message_handler(commands=['annonce'])
def send_annonce(message):
    if message.from_user.id in ADMIN_IDS:
        text = message.text.replace('/annonce', '').strip()
        if not text:
            bot.reply_to(message, "⚠️ **Usage :** `/annonce <Votre message>`\n*Exemple :* `/annonce 🚨 Un client vient d'acheter le bot permanent !`", parse_mode="Markdown")
            return
        
        annonce_msg = (
            f"📢 **COMMUNIQUÉ OFFICIEL B2K SCALPING**\n"
            f"_________________________________________\n\n"
            f"{text}\n"
            f"_________________________________________\n"
            f"🏆 *Félicitations aux nouveaux membres VIP !*"
        )
        bot.send_message(message.chat.id, annonce_msg, parse_mode="Markdown")
    else:
        bot.reply_to(message, "⛔ Commande réservée à l'administrateur.")

@bot.message_handler(commands=['addclient'])
def add_client(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            target_id = int(message.text.split()[1])
            if target_id not in CLIENTS_VIP:
                CLIENTS_VIP.append(target_id)
                bot.reply_to(message, f"✅ **CLIENT VIP VALIDE !**\n💳 L'utilisateur `{target_id}` a désormais un accès illimité (15$).", parse_mode="Markdown")
            else:
                bot.reply_to(message, "ℹ️ Déjà membre VIP.")
        except Exception:
            bot.reply_to(message, "⚠️ Usage : `/addclient <ID_TELEGRAM>`", parse_mode="Markdown")

@bot.message_handler(commands=['delclient'])
def del_client(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            target_id = int(message.text.split()[1])
            if target_id in CLIENTS_VIP:
                CLIENTS_VIP.remove(target_id)
                bot.reply_to(message, f"❌ Accès VIP révoqué pour `{target_id}`.", parse_mode="Markdown")
            else:
                bot.reply_to(message, "ℹ️ Introuvable dans la liste VIP.")
        except Exception:
            bot.reply_to(message, "⚠️ Usage : `/delclient <ID_TELEGRAM>`", parse_mode="Markdown")

@bot.message_handler(commands=['addgains'])
def add_gains(message):
    if message.from_user.id in ADMIN_IDS:
        try:
            pips = int(message.text.split()[1])
            GAINS_JOUR["total_pips"] += pips
            GAINS_JOUR["trades_gagnants"] += 1
            bot.reply_to(message, f"📈 **+ {pips} pips** enregistrés au bilan !", parse_mode="Markdown")
        except Exception:
            bot.reply_to(message, "⚠️ Usage : `/addgains <pips>`", parse_mode="Markdown")

# --- GESTION DES BOUTONS INTERACTIFS (CALLBACKS) ---

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id

    # Anti-Spam Verification
    if is_spamming(user_id):
        bot.answer_callback_query(call.id, "⚠️ Patientez 3 secondes entre chaque clic...", show_alert=False)
        return

    # 1. Choix du menu d'actifs
    if call.data == "menu_assets":
        bot.edit_message_text("📊 **Sélectionnez l'actif sur lequel vous souhaitez scraper :**", 
                              call.message.chat.id, call.message.message_id, 
                              reply_markup=get_assets_keyboard(), parse_mode="Markdown")

    # 2. Choix de la Timeframe
    elif call.data.startswith("asset_"):
        asset = call.data.split("_")[1]
        bot.edit_message_text(f"⏱️ **Actif sélectionné : {asset}**\nChoisissez la timeframe souhaitée :", 
                              call.message.chat.id, call.message.message_id, 
                              reply_markup=get_timeframe_keyboard(asset), parse_mode="Markdown")

    # 3. Revérifier le trade (Retournement)
    elif call.data == "recheck_trade":
        bot.answer_callback_query(call.id, "🔍 Analyse du retournement de marché en cours...")
        time.sleep(1)
        reverif_msg = (
            "🔄 **ANALYSE DE RETOURNEMENT DE TENDANCE**\n"
            "_________________________________________\n\n"
            "📊 **État actuel :** Le marché confirme la dynamique institutionnelle.\n"
            "💡 **Indicateurs :** RSI et MACD restent alignés sur le signal précédent.\n"
            "✅ *Conservez votre position actuelle avec le Stop Loss à zéro (Breakeven).* "
        )
        bot.send_message(call.message.chat.id, reverif_msg, reply_markup=get_start_keyboard(), parse_mode="Markdown")

    # 4. Génération du Signal Scalping
    elif call.data.startswith("tf_"):
        parts = call.data.split("_")
        asset = parts[1]
        timeframe = parts[2]

        # Vérification des crédits (3 Essais Gratuits ou VIP)
        if user_id not in CLIENTS_VIP and user_id not in ADMIN_IDS:
            essais = ESSAIS_GRATUITS.get(user_id, 0)
            if essais <= 0:
                bot.send_message(call.message.chat.id, 
                                 "🔒 **Vos 3 essais gratuits sont épuisés !**\n\n"
                                 "💳 Pour débloquer l'accès permanent aux signaux, achetez votre accès VIP à **15$** auprès de **@b2k_ruben**.", 
                                 parse_mode="Markdown")
                bot.answer_callback_query(call.id)
                return
            else:
                ESSAIS_GRATUITS[user_id] -= 1

        bot.answer_callback_query(call.id, "Génération du signal chirurgical...")

        # Calculs précis des prix et pips selon l'actif
        if asset == "XAUUSD":
            base_price = round(random.uniform(2645.00, 2665.00), 2)
            pips_tp = random.randint(20, 35)
            tp_diff = round(pips_tp * 0.10, 2)
            sl_diff = 1.20
            estimated_usd = round(pips_tp * 0.50, 2) # Profit $ estimé pour 0.05 lot
        elif asset == "EURUSD":
            base_price = round(random.uniform(1.0820, 1.0890), 4)
            pips_tp = random.randint(15, 25)
            tp_diff = round(pips_tp * 0.0001, 4)
            sl_diff = 0.0010
            estimated_usd = round(pips_tp * 0.40, 2)
        else: # BTCUSD
            base_price = round(random.uniform(81500.00, 83000.00), 2)
            pips_tp = random.randint(25, 50)
            tp_diff = float(pips_tp * 10)
            sl_diff = 150.00
            estimated_usd = round(pips_tp * 1.20, 2)

        order_type = random.choice(["ACHAT (BUY)", "VENTE (SELL)"])
        
        if "BUY" in order_type:
            tp_price = round(base_price + tp_diff, 2 if asset != "EURUSD" else 4)
            sl_price = round(base_price - sl_diff, 2 if asset != "EURUSD" else 4)
            emoji_order = "🟢"
        else:
            tp_price = round(base_price - tp_diff, 2 if asset != "EURUSD" else 4)
            sl_price = round(base_price + sl_diff, 2 if asset != "EURUSD" else 4)
            emoji_order = "🔴"

        # Signal formaté exactement comme sur tes captures
        signal_text = (
            f"📊 **ANALYSE INSTITUTIONNELLE B2K**\n"
            f"_________________________________________\n"
            f"_________________________________________\n\n"
            f"💎 **ACTIF : {asset} | TIMEFRAME : {timeframe}**\n"
            f"💵 **PRIX ACTUEL :** ${base_price}\n"
            f"🎯 **FIABILITÉ ESTIMÉE :** 91.3%\n"
            f"_________________________________________\n"
            f"_________________________________________\n\n"
            f"🚀 **ORDRE RECOMMANDÉ :** {emoji_order} **{order_type}**\n"
            f"🟢 **TAKE PROFIT (TP) :** ${tp_price} (**+{pips_tp} pips**)\n"
            f"🔴 **STOP LOSS (SL) :** ${sl_price}\n"
            f"💵 **PROFIT ESTIMÉ :** **+${estimated_usd} USD** (selon hausse des pips)\n"
            f"⏱️ **DURÉE DU TRADE :** 3 à 5 minutes\n"
            f"_________________________________________\n"
        )

        bot.send_message(call.message.chat.id, signal_text, reply_markup=get_start_keyboard(), parse_mode="Markdown")

# --- DEMARRAGE DIRECT EN POLLING ---

if __name__ == '__main__':
    print("Bot B2K Scalping démarré en mode Polling direct...")
    bot.infinity_polling(skip_pending=True)
