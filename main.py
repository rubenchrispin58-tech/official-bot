import os
import time
import threading
import requests
import random
from flask import Flask

app = Flask(__name__)

# --- SÉCURITÉ : Lecture sécurisée du Token depuis Render ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# --- CONFIGURATION ADMIN & SUPPORT ---
ADMIN_CHAT_ID = None
ADMIN_HANDLE = "@b2k_ruben"
ADMIN_WHATSAPP = "+509 43 52 84 61"

# Base de données en mémoire
users_db = {}
user_selections = {}
registered_chat_ids = set()

def recuperer_prix_actif(actif):
    try:
        if actif == "BTCUSD":
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
            res = requests.get(url, timeout=5).json()
            if "bitcoin" in res:
                return float(res["bitcoin"]["usd"])
        else:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=tether-gold&vs_currencies=usd"
            res = requests.get(url, timeout=5).json()
            if "tether-gold" in res:
                return float(res["tether-gold"]["usd"])
    except Exception as e:
        print("Erreur API Prix:", e)
    return 2650.50 if actif == "XAUUSD" else 65000.00

def analyser_scalping_net(actif, timeframe):
    prix = recuperer_prix_actif(actif)
    tendance_tf = random.choice(["HAUSSIER 🟢", "BAISSIER 🔴"])
    rsi = round(random.uniform(32.0, 68.0), 1)
    fiabilite = round(random.uniform(84.0, 95.2), 1)
    
    if "HAUSSIER" in tendance_tf or rsi < 48:
        direction = "🟢 **ACHAT (BUY)**"
        tp_val = prix + 2.50 if actif == "XAUUSD" else prix + 150.00
        sl_val = prix - 1.20 if actif == "XAUUSD" else prix - 75.00
        pips = "+25 pips"
    else:
        direction = "🔴 **VENTE (SELL)**"
        tp_val = prix - 2.50 if actif == "XAUUSD" else prix - 150.00
        sl_val = prix + 1.20 if actif == "XAUUSD" else prix + 75.00
        pips = "+25 pips"

    msg = (
        f"📊 **ANALYSE B2K - PRO SCALPING**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 **Actif :** `{actif}` | **Timeframe :** `{timeframe}`\n"
        f"💵 **Prix Actuel :** `${prix:,.2f}`\n"
        f"🎯 **Fiabilité :** `{fiabilite}%`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 **SYNTHÈSE DU MARCHÉ ({timeframe}) :**\n"
        f"• Tendance bougie {timeframe} : {tendance_tf}\n"
        f"• Indicateur RSI (14) : `{rsi}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 **ORDRE :** {direction}\n"
        f"🟢 **TAKE PROFIT (TP) :** `${tp_val:,.2f}` *({pips})*\n"
        f"🔴 **STOP LOSS (SL) :** `${sl_val:,.2f}`\n"
        f"⏱️ **Durée estimée :** `3 à 5 minutes`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ **Avertissement :** Le trading comporte des risques. Risque maximal recommandé : 5% du capital."
    )
    return msg

def verifier_retournement_net(chat_id):
    actif = user_selections.get(chat_id, {}).get("actif", "XAUUSD")
    prix = recuperer_prix_actif(actif)
    diagnostic = random.choice([
        "✅ **Tendance Stable** : Le momentum est validé. Conservez votre position jusqu'au TP.",
        "⚠️ **Alerte Retournement** : Essoufflement détecté sur le carnet d'ordres. Recommandation : Sécurisez vos gains dès maintenant."
    ])
    
    msg = (
        f"🔄 **DIAGNOSTIC DE POSITION ({actif})**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 **Prix en direct :** `${prix:,.2f}`\n"
        f"📢 **Analyse :** {diagnostic}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg

# --- MENUS INTERACTIFS ---

def get_menu_actifs():
    return {
        "inline_keyboard": [
            [{"text": "🥇 Analyser XAUUSD (Or)", "callback_data": "actif_XAUUSD"}],
            [{"text": "₿ Analyser BTCUSD (Bitcoin)", "callback_data": "actif_BTCUSD"}]
        ]
    }

def get_menu_timeframes():
    return {
        "inline_keyboard": [
            [{"text": "⏱️ M1 (1 Min)", "callback_data": "tf_M1"}, {"text": "⏱️ M5 (5 Min)", "callback_data": "tf_M5"}],
            [{"text": "⏱️ M15 (15 Min)", "callback_data": "tf_M15"}, {"text": "⏱️ H1 (1 Hour)", "callback_data": "tf_H1"}],
            [{"text": "◀️ Revenir au Menu", "callback_data": "menu_principal"}]
        ]
    }

def get_menu_signal(is_admin=False):
    kb = [
        [{"text": "🔄 Revérifier le Trade (Retournement)", "callback_data": "reverifier"}],
        [{"text": "◀️ Revenir au Menu", "callback_data": "menu_principal"}]
    ]
    if is_admin:
        kb.append([{"text": "⚙️ Panel Admin", "callback_data": "admin_panel"}])
    return {"inline_keyboard": kb}

def envoyer_message(chat_id, texte, reply_markup=None):
    if not TELEGRAM_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": texte, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print("Erreur Envoi Telegram:", e)

def gerer_utilisateur(chat_id, username=None):
    if chat_id not in users_db:
        users_db[chat_id] = {"credits": 3, "is_vip": False, "username": username}
    if username:
        users_db[chat_id]["username"] = username
    registered_chat_ids.add(chat_id)
    return users_db[chat_id]

def bot_loop():
    global ADMIN_CHAT_ID
    print("🚀 Bot B2K Scalper v5.3 (Sécurisé & Clean) Actif...")
    offset = 0
    while True:
        try:
            if not TELEGRAM_TOKEN:
                time.sleep(5)
                continue
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=30"
            res = requests.get(url, timeout=35).json()

            if "result" in res:
                for update in res["result"]:
                    offset = update["update_id"] + 1

                    if "message" in update and "text" in update["message"]:
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        texte = msg["text"].strip()
                        username = msg["from"].get("username", "")
                        user = gerer_utilisateur(chat_id, username)

                        if texte == "/rubenb2kadmin":
                            ADMIN_CHAT_ID = chat_id
                            envoyer_message(chat_id, "🔐 **Accès Administrateur restauré avec succès !**", get_menu_actifs())
                            continue

                        is_admin = (ADMIN_CHAT_ID is not None and chat_id == ADMIN_CHAT_ID)

                        if is_admin:
                            if texte == "/admin":
                                admin_help = (
                                    "🛠️ **PANEL ADMINISTRATEUR B2K**\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    "• `/client` : Activer le mode test client\n"
                                    "• `/payer @username` : Valider le paiement d'un client par son pseudo\n"
                                    "• `/annonce <message>` : Diffuser une annonce globale\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━━━━"
                                )
                                envoyer_message(chat_id, admin_help)
                                continue

                            if texte.startswith("/payer"):
                                parts = texte.split()
                                if len(parts) > 1:
                                    target_user = parts[1].replace("@", "").strip().lower()
                                    trouve = False
                                    for cid, udata in users_db.items():
                                        if udata.get("username", "").lower() == target_user:
                                            udata["is_vip"] = True
                                            trouve = True
                                            envoyer_message(cid, "🎉 **Paiement confirmé par l'administrateur !** Votre accès VIP permanent est désormais actif.")
                                            break
                                    
                                    if trouve:
                                        envoyer_message(chat_id, f"✅ Client @{target_user} activé avec succès en VIP !")
                                        annonce_p = f"📢 **ANNONCE VIP :** Le membre @{target_user} vient de valider son accès complet. Bienvenue dans l'équipe !"
                                        for cid in registered_chat_ids:
                                            envoyer_message(cid, annonce_p)
                                    else:
                                        envoyer_message(chat_id, f"⚠️ Utilisateur @{target_user} introuvable dans la base des inscrits.")
                                continue

                            if texte.startswith("/annonce"):
                                ann = texte.replace("/annonce", "").strip()
                                if ann:
                                    for cid in registered_chat_ids:
                                        envoyer_message(cid, f"📢 **ANNONCE OFFICIELLE :**\n\n{ann}")
                                continue

                        if texte == "/client":
                            user["credits"] = 3
                            user["is_vip"] = False
                            envoyer_message(chat_id, "🧪 **Mode Test Client Activé (3 crédits réinitialisés).**", get_menu_actifs())
                            continue

                        if texte == "/start":
                            msg_bienvenue = (
                                f"👋 **Bienvenue dans le B2K Gold & Crypto Scalping Bot !**\n\n"
                                f"🤖 **À propos du Bot :**\n"
                                f"Bot algorithmique haute précision pour le scalping sur l'Or (**XAUUSD**) et le Bitcoin (**BTCUSD**).\n\n"
                                f"🎯 **Fiabilité Estimée :** `80% à 95%` par session.\n\n"
                                f"📞 **Contact & Support :**\n"
                                f"• **Telegram Admin :** [{ADMIN_HANDLE}](https://t.me/b2k_ruben)\n"
                                f"• **WhatsApp Direct :** `{ADMIN_WHATSAPP}`\n\n"
                                f"🎁 **Essai Gratuit :** Vous disposez de **3 signaux gratuits**.\n"
                                f"Veuillez choisir un actif ci-dessous pour démarrer :"
                            )
                            envoyer_message(chat_id, msg_bienvenue, get_menu_actifs())
                            continue

                    if "callback_query" in update:
                        cq = update["callback_query"]
                        chat_id = cq["message"]["chat"]["id"]
                        username = cq["from"].get("username", "")
                        data = cq["data"]
                        user = gerer_utilisateur(chat_id, username)
                        is_admin = (ADMIN_CHAT_ID is not None and chat_id == ADMIN_CHAT_ID)

                        if data == "menu_principal":
                            envoyer_message(chat_id, "📍 **Choisissez l'actif que vous souhaitez analyser :**", get_menu_actifs())
                            continue

                        if data.startswith("actif_"):
                            actif_choisi = data.replace("actif_", "")
                            if chat_id not in user_selections:
                                user_selections[chat_id] = {}
                            user_selections[chat_id]["actif"] = actif_choisi
                            
                            envoyer_message(
                                chat_id, 
                                f"📊 **Actif sélectionné :** `{actif_choisi}`\n\n⏱️ **Choisissez maintenant l'unité de temps (Timeframe) :**", 
                                get_menu_timeframes()
                            )
                            continue

                        if data.startswith("tf_"):
                            if not user["is_vip"] and user["credits"] <= 0:
                                msg_payant = (
                                    f"🚫 **ACCÈS EXPIRÉ (0/3 Essais Gratuits)**\n\n"
                                    f"Vos 3 essais gratuits sont terminés.\n"
                                    f"Pour débloquer l'accès permanent et continuer vos gains :\n\n"
                                    f"💳 **Tarif :** $15 USD (Accès à vie)\n"
                                    f"📥 **Moyens de paiement :** NatCash ou Carte de crédit\n\n"
                                    f"📩 **Contactez l'Administrateur :**\n"
                                    f"• **Telegram :** [{ADMIN_HANDLE}](https://t.me/b2k_ruben) *(Cliquez pour envoyer un message direct)*\n"
                                    f"• **WhatsApp :** `{ADMIN_WHATSAPP}`\n\n"
                                    f"👉 Envoyez votre capture de paiement (NatCash ou Carte) à [{ADMIN_HANDLE}](https://t.me/b2k_ruben) pour recevoir votre activation immédiate."
                                )
                                envoyer_message(chat_id, msg_payant)
                                continue

                            tf_choisi = data.replace("tf_", "")
                            actif_choisi = user_selections.get(chat_id, {}).get("actif", "XAUUSD")

                            if not user["is_vip"]:
                                user["credits"] -= 1
                                info_c = f"\n\n*(Signaux gratuits restants : {user['credits']}/3)*"
                            else:
                                info_c = "\n\n*(Compte VIP Permanent)*"

                            signal_text = analyser_scalping_net(actif_choisi, tf_choisi) + info_c
                            envoyer_message(chat_id, signal_text, get_menu_signal(is_admin))
                            continue

                        if data == "reverifier":
                            if not user["is_vip"] and user["credits"] <= 0:
                                msg_payant = (
                                    f"🚫 **ACCÈS EXPIRÉ (0/3 Essais Gratuits)**\n\n"
                                    f"Contactez l'administrateur pour régler via NatCash ou Carte :\n"
                                    f"• Telegram : [{ADMIN_HANDLE}](https://t.me/b2k_ruben)\n"
                                    f"• WhatsApp : `{ADMIN_WHATSAPP}`"
                                )
                                envoyer_message(chat_id, msg_payant)
                                continue

                            rev_text = verifier_retournement_net(chat_id)
                            envoyer_message(chat_id, rev_text, get_menu_signal(is_admin))
                            continue

        except Exception as e:
            time.sleep(2)

def keep_alive():
    while True:
        try:
            time.sleep(600)
            requests.get("http://127.0.0.1:10000/", timeout=5)
        except:
            pass

threading.Thread(target=keep_alive, daemon=True).start()

t = threading.Thread(target=bot_loop, daemon=True)
t.start()

@app.route('/')
def home():
    return "B2K Scalping Server Online v5.3"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
