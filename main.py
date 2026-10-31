import os
import time
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

import requests
from flask import Flask
import telebot
from telebot import types

# ====================================================
# CONFIGURATION (variables d'environnement Render)
# ====================================================
TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "trading_v28.db")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)       # TON chat_id Telegram
VERSION = "v29.0 Mentor IA"
PRICE_USD = os.getenv("PRICE_USD", "15")
PRICE_HTG = os.getenv("PRICE_HTG", "2 000")

# Les 3 marchés analysés
ASSETS = {
    "BTCUSD": {"label": "₿ BTC/USD", "src": "binance", "sym": "BTCUSDT", "dec": 2,
               "note": "Binance BTCUSDT (très proche de ton MT5)"},
    "XAUUSD": {"label": "🥇 XAU/USD (Or)", "src": "binance", "sym": "PAXGUSDT", "dec": 2,
               "note": "Binance PAXGUSDT (or tokenisé : l'écart avec ton MT5 peut atteindre plusieurs $)"},
    "EURUSD": {"label": "💶 EUR/USD", "src": "yahoo", "sym": "EURUSD=X", "dec": 5,
               "note": "Yahoo Finance (données gratuites, légère différence possible avec XM)"},
}

# Timeframes : codes Binance / Bybit / Yahoo (interval, range), durée d'une bougie, timeframe supérieur
TF_INFO = {
    "M1": {"bin": "1m", "bybit": "1", "yahoo": ("1m", "5d"), "secs": 60, "up": "M15", "style": "Scalping ultra-rapide"},
    "M5": {"bin": "5m", "bybit": "5", "yahoo": ("5m", "5d"), "secs": 300, "up": "H1", "style": "Scalping ultra-rapide"},
    "M15": {"bin": "15m", "bybit": "15", "yahoo": ("15m", "1mo"), "secs": 900, "up": "H1", "style": "Scalping / day-trading"},
    "H1": {"bin": "1h", "bybit": "60", "yahoo": ("60m", "3mo"), "secs": 3600, "up": "H4", "style": "Scalping / day-trading"},
    "H4": {"bin": "4h", "bybit": "240", "yahoo": ("60m", "6mo"), "secs": 14400, "up": "D1", "style": "Swing / vision de la journée"},
    "D1": {"bin": "1d", "bybit": "D", "yahoo": ("1d", "2y"), "secs": 86400, "up": None, "style": "Swing / vision globale"},
}

DISCLAIMER = ("⚠️ _Outil pédagogique : aucun indicateur ne prédit l'avenir et ceci n'est pas un conseil financier. "
              "Risque max 1-2 % du capital par trade._")

# ====================================================
# SERVEUR FLASK
# ====================================================
app = Flask(__name__)


@app.route('/')
def home():
    return f"B2K AI Trading Mentor {VERSION} - Opérationnel !"


def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


threading.Thread(target=run_flask, daemon=True).start()

# ====================================================
# BASE DE DONNÉES
# ====================================================
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
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                symbol TEXT,
                tf TEXT,
                verdict TEXT,
                created_ms INTEGER
            )
        ''')
        conn.commit()
        conn.close()


init_db()

# ====================================================
# BOT TELEGRAM
# ====================================================
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown", threaded=True, num_threads=16)

testing_as_user = {}


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
            return bot.send_message(chat_id, plain, parse_mode=None,
                                    **{k: v for k, v in kwargs.items() if k != "parse_mode"})
        except Exception as e:
            print("Erreur envoi:", e)


def set_native_commands():
    commands = [
        types.BotCommand("start", "Menu principal 📊"),
        types.BotCommand("menu", "Choisir un marché ⚡"),
        types.BotCommand("payment", "Abonnement VIP (20$) 💳"),
        types.BotCommand("test", "Mode Test Admin ⚙️"),
        types.BotCommand("stats", "Statistiques d'usage 📈"),
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


def log_analysis(chat_id, symbol, tf, verdict):
    with db_lock:
        conn = db()
        conn.execute("INSERT INTO analyses (chat_id, symbol, tf, verdict, created_ms) VALUES (?,?,?,?,?)",
                     (chat_id, symbol, tf, verdict, int(time.time() * 1000)))
        conn.commit()
        conn.close()

# ====================================================
# DONNÉES DE MARCHÉ
# ====================================================
BINANCE_BASES = ("https://api.binance.com", "https://data-api.binance.vision")


def _pack(rows):
    """rows = [(time_s, high, low, close)] -> dict"""
    rows = rows[-300:]
    return {"t": [r[0] for r in rows], "h": [r[1] for r in rows],
            "l": [r[2] for r in rows], "c": [r[3] for r in rows]}


def _binance(sym, tf):
    for base in BINANCE_BASES:
        try:
            r = requests.get(f"{base}/api/v3/klines", timeout=8,
                             params={"symbol": sym, "interval": TF_INFO[tf]["bin"], "limit": 300})
            if r.status_code == 200:
                rows = [(int(x[0]) // 1000, float(x[2]), float(x[3]), float(x[4])) for x in r.json()]
                if len(rows) >= 60:
                    return rows
        except Exception:
            pass
    try:
        r = requests.get("https://api.bybit.com/v5/market/kline", timeout=8,
                         params={"category": "linear", "symbol": sym, "interval": TF_INFO[tf]["bybit"], "limit": 300})
        if r.status_code == 200:
            rows = [(int(x[0]) // 1000, float(x[2]), float(x[3]), float(x[4])) for x in reversed(r.json()["result"]["list"])]
            if len(rows) >= 60:
                return rows
    except Exception:
        pass
    return None


def _aggregate(rows, secs):
    out = {}
    for t, h, l, c in rows:
        k = t // secs
        if k not in out:
            out[k] = [k * secs, h, l, c]
        else:
            out[k][1] = max(out[k][1], h)
            out[k][2] = min(out[k][2], l)
            out[k][3] = c
    return [tuple(v) for _, v in sorted(out.items())]


def _yahoo(sym, tf):
    interval, rng = TF_INFO[tf]["yahoo"]
    for host in ("query1", "query2"):
        try:
            r = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}", timeout=10,
                             params={"interval": interval, "range": rng},
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                continue
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            rows = [(int(t), h, l, c) for t, h, l, c in zip(res["timestamp"], q["high"], q["low"], q["close"])
                    if h is not None and l is not None and c is not None]
            if tf == "H4":
                rows = _aggregate(rows, 14400)
            if len(rows) >= 60:
                return rows
        except Exception:
            pass
    return None


def fetch_candles(asset, tf):
    cfg = ASSETS[asset]
    rows = _binance(cfg["sym"], tf) if cfg["src"] == "binance" else _yahoo(cfg["sym"], tf)
    return _pack(rows) if rows else None

# ====================================================
# INDICATEURS
# ====================================================
def sma(values, n):
    return sum(values[-n:]) / n


def ema_series(values, n):
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    out = [e]
    for v in values[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes, n=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def macd(closes, fast=12, slow=26, sig=9):
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    ef = ef[len(ef) - len(es):]
    line = [a - b for a, b in zip(ef, es)]
    sg = ema_series(line, sig)
    hist_now = line[-1] - sg[-1]
    hist_prev = line[-2] - sg[-2] if len(sg) >= 2 else hist_now
    return line[-1], sg[-1], hist_now, hist_prev


def bollinger(closes, n=20, k=2):
    window = closes[-n:]
    mid = sum(window) / n
    sd = (sum((x - mid) ** 2 for x in window) / n) ** 0.5
    upper, lower = mid + k * sd, mid - k * sd
    pct_b = 0.5 if upper == lower else (closes[-1] - lower) / (upper - lower)
    return pct_b, mid


def stochastic(highs, lows, closes, n=14, d=3):
    ks = []
    for end in range(len(closes) - d + 1, len(closes) + 1):
        hh = max(highs[end - n:end])
        ll = min(lows[end - n:end])
        ks.append(50.0 if hh == ll else (closes[end - 1] - ll) / (hh - ll) * 100)
    return ks[-1], sum(ks) / len(ks)


def true_ranges(highs, lows, closes):
    return [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))]


def atr(highs, lows, closes, n=14):
    trs = true_ranges(highs, lows, closes)
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def adx_di(highs, lows, closes, n=14):
    trs = true_ranges(highs, lows, closes)
    pdm, mdm = [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm.append(up if (up > dn and up > 0) else 0)
        mdm.append(dn if (dn > up and dn > 0) else 0)
    s_tr, s_p, s_m = sum(trs[:n]), sum(pdm[:n]), sum(mdm[:n])
    dxs = []
    pdi = mdi = 0.0
    for i in range(n, len(trs) + 1):
        if i > n:
            s_tr = s_tr - s_tr / n + trs[i - 1]
            s_p = s_p - s_p / n + pdm[i - 1]
            s_m = s_m - s_m / n + mdm[i - 1]
        pdi = 100 * s_p / s_tr if s_tr else 0
        mdi = 100 * s_m / s_tr if s_tr else 0
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0)
    adx_v = sum(dxs[:n]) / n
    for dx in dxs[n:]:
        adx_v = (adx_v * (n - 1) + dx) / n
    return adx_v, pdi, mdi


def cci(highs, lows, closes, n=20):
    tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    w = tp[-n:]
    m = sum(w) / n
    md = sum(abs(x - m) for x in w) / n
    return 0.0 if md == 0 else (tp[-1] - m) / (0.015 * md)


def williams_r(highs, lows, closes, n=14):
    hh, ll = max(highs[-n:]), min(lows[-n:])
    return -50.0 if hh == ll else (hh - closes[-1]) / (hh - ll) * -100


def momentum_roc(closes, n=10):
    return (closes[-1] - closes[-1 - n]) / closes[-1 - n] * 100


def analyze(highs, lows, closes):
    """Retourne (liste de (nom, vote, détail), atr). vote: +1 achat, -1 vente, 0 neutre."""
    votes = []

    r = rsi(closes)
    if r < 30:
        v = 1
    elif r > 70:
        v = -1
    else:
        v = 1 if r > 55 else (-1 if r < 45 else 0)
    votes.append(("RSI 14", v, f"{r:.1f}"))

    m_line, m_sig, h_now, h_prev = macd(closes)
    v = 1 if (m_line > m_sig and h_now >= h_prev) else (-1 if (m_line < m_sig and h_now <= h_prev) else 0)
    votes.append(("MACD", v, f"hist {h_now:+.2f}"))

    pb, _mid = bollinger(closes)
    v = 1 if pb < 0.2 else (-1 if pb > 0.8 else 0)
    votes.append(("Bollinger", v, f"%B {pb:.2f}"))

    e9 = ema_series(closes, 9)[-1]
    e21 = ema_series(closes, 21)[-1]
    v = 1 if e9 > e21 else -1
    votes.append(("EMA 9/21", v, "haussier" if v == 1 else "baissier"))

    e50 = ema_series(closes, 50)[-1]
    e200 = ema_series(closes, 200)[-1] if len(closes) >= 210 else sma(closes, min(100, len(closes)))
    v = 1 if (closes[-1] > e50 and e50 > e200) else (-1 if (closes[-1] < e50 and e50 < e200) else 0)
    votes.append(("Tendance EMA 50/200", v, "haussière" if v == 1 else ("baissière" if v == -1 else "mixte")))

    k, d = stochastic(highs, lows, closes)
    if k > 80:
        v = -1
    elif k < 20:
        v = 1
    else:
        v = 1 if k > d else -1
    votes.append(("Stochastique", v, f"K {k:.0f} / D {d:.0f}"))

    adx_v, pdi, mdi = adx_di(highs, lows, closes)
    v = (1 if pdi > mdi else -1) if adx_v > 20 else 0
    votes.append(("ADX / DI", v, f"ADX {adx_v:.0f}"))

    c = cci(highs, lows, closes)
    v = 1 if c < -100 else (-1 if c > 100 else 0)
    votes.append(("CCI 20", v, f"{c:.0f}"))

    w = williams_r(highs, lows, closes)
    v = 1 if w < -80 else (-1 if w > -20 else 0)
    votes.append(("Williams %R", v, f"{w:.0f}"))

    roc = momentum_roc(closes)
    v = 1 if roc > 0.05 else (-1 if roc < -0.05 else 0)
    votes.append(("Momentum ROC", v, f"{roc:+.2f}%"))

    return votes, atr(highs, lows, closes)

# ====================================================
# ANALYSE (ZigZag, supports/résistances, régime de marché)
# ====================================================
TREND_NAMES = {"EMA 9/21", "Tendance EMA 50/200", "MACD", "ADX / DI", "Momentum ROC"}


def fmt(asset, x):
    return f"{x:.{ASSETS[asset]['dec']}f}"


def dist_txt(asset, x):
    if asset == "EURUSD":
        return f"{x / 0.0001:.1f} pips"
    return f"{x:.2f} $"


def dir_word(v, caps=False):
    w = "haussière" if v > 0 else ("baissière" if v < 0 else "indécise")
    return w.upper() if caps else w


def rsi_series(closes, n=14):
    out = [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out[i + 1] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def zigzag(highs, lows, thr):
    """Sommets/creux importants : un pivot est confirmé quand le prix repart d'au moins `thr` en sens inverse.
    Retourne (pivots confirmés [(index, prix, 'H'/'L')], extrême en cours ou None)."""
    piv = []
    trend = 0
    ext_hi = (0, highs[0])
    ext_lo = (0, lows[0])
    for i in range(1, len(highs)):
        h, l = highs[i], lows[i]
        if trend == 0:
            if h > ext_hi[1]:
                ext_hi = (i, h)
            if l < ext_lo[1]:
                ext_lo = (i, l)
            if ext_hi[0] != i and ext_hi[1] - l >= thr:
                piv.append((ext_hi[0], ext_hi[1], "H"))
                trend = -1
                ext_lo = (i, l)
            elif ext_lo[0] != i and h - ext_lo[1] >= thr:
                piv.append((ext_lo[0], ext_lo[1], "L"))
                trend = 1
                ext_hi = (i, h)
        elif trend == 1:
            if h > ext_hi[1]:
                ext_hi = (i, h)
            elif ext_hi[1] - l >= thr:
                piv.append((ext_hi[0], ext_hi[1], "H"))
                trend = -1
                ext_lo = (i, l)
        else:
            if l < ext_lo[1]:
                ext_lo = (i, l)
            elif h - ext_lo[1] >= thr:
                piv.append((ext_lo[0], ext_lo[1], "L"))
                trend = 1
                ext_hi = (i, h)
    ext = (ext_hi[0], ext_hi[1], "H") if trend == 1 else ((ext_lo[0], ext_lo[1], "L") if trend == -1 else None)
    return piv, ext


def quick_trend(d):
    c = d["c"]
    e50 = ema_series(c, 50)[-1]
    e200 = ema_series(c, 200)[-1] if len(c) >= 210 else sma(c, min(100, len(c)))
    p = c[-1]
    if p > e50 > e200:
        return 1
    if p < e50 < e200:
        return -1
    return 0


def market_note(asset, last_ts, tf):
    if asset == "BTCUSD":
        return ""
    now = datetime.now(timezone.utc)
    wd, hr = now.weekday(), now.hour
    weekend = wd == 5 or (wd == 4 and hr >= 22) or (wd == 6 and hr < 22)
    if weekend:
        if asset == "XAUUSD":
            return "⚠️ Le marché de l'or est fermé (week-end). Les prix PAXG bougent encore : analyse à titre pédagogique."
        return "⚠️ Le Forex est fermé (week-end) : les données datent de vendredi soir."
    if time.time() - last_ts > 3 * TF_INFO[tf]["secs"] + 900:
        return "⚠️ Les dernières données semblent anciennes : le marché est peut-être calme ou fermé."
    return ""


def full_analysis(asset, tf):
    d = fetch_candles(asset, tf)
    if not d or len(d["c"]) < 120:
        return None
    H, L, C, T = d["h"], d["l"], d["c"], d["t"]
    n = len(C)
    price = C[-1]
    votes, atr_v = analyze(H, L, C)
    adx_v, pdi, mdi = adx_di(H, L, C)
    e50 = ema_series(C, 50)[-1]
    e200 = ema_series(C, 200)[-1] if n >= 210 else None
    macd_line = macd(C)[0]
    rsi_v = rsi(C)
    rs = rsi_series(C)

    trs = true_ranges(H, L, C)
    atr_ratio = (sum(trs[-14:]) / 14) / (sum(trs[-100:]) / 100) if sum(trs[-100:]) else 1.0
    bws = []
    for end in range(n - 100, n + 1):
        w = C[end - 20:end]
        m = sum(w) / 20
        sd = (sum((x - m) ** 2 for x in w) / 20) ** 0.5
        bws.append(4 * sd / m if m else 0)
    bw_pct = sum(1 for x in bws[:-1] if x < bws[-1]) / (len(bws) - 1)

    piv, ext = zigzag(H, L, 2.5 * atr_v)
    hp = [p for p in piv if p[2] == "H"]
    lp = [p for p in piv if p[2] == "L"]
    structure = 0
    if len(hp) >= 2 and len(lp) >= 2:
        hh = hp[-1][1] > hp[-2][1]
        hl = lp[-1][1] > lp[-2][1]
        structure = 1 if (hh and hl) else (-1 if (not hh and not hl) else 0)
    levels = [p[1] for p in piv] + ([ext[1]] if ext else [])
    above = [x for x in levels if x > price]
    below = [x for x in levels if x < price]
    res = min(above) if above else None
    sup = max(below) if below else None

    def touches(lv):
        return sum(1 for x in levels if abs(x - lv) <= 0.5 * atr_v)

    div = 0
    if len(hp) >= 2 and n - hp[-1][0] <= 60:
        r1, r2 = rs[hp[-2][0]], rs[hp[-1][0]]
        if r1 is not None and r2 is not None and hp[-1][1] > hp[-2][1] and r2 < r1 - 2:
            div = -1
    if div == 0 and len(lp) >= 2 and n - lp[-1][0] <= 60:
        r1, r2 = rs[lp[-2][0]], rs[lp[-1][0]]
        if r1 is not None and r2 is not None and lp[-1][1] < lp[-2][1] and r2 > r1 + 2:
            div = 1

    checks = [("Prix vs EMA 50", 1 if price > e50 else -1)]
    if e200:
        checks.append(("EMA 50 vs EMA 200", 1 if e50 > e200 else -1))
    checks.append(("Structure ZigZag", structure))
    checks.append(("Force directionnelle (DI, ADX>20)", (1 if pdi > mdi else -1) if adx_v > 20 else 0))
    checks.append(("MACD vs zéro", 1 if macd_line > 0 else -1))
    up = sum(1 for _, v in checks if v > 0)
    dn = sum(1 for _, v in checks if v < 0)
    direction = 1 if up - dn >= 2 else (-1 if dn - up >= 2 else 0)

    buys = sum(1 for v in votes if v[1] > 0)
    sells = sum(1 for v in votes if v[1] < 0)
    t_sum = sum(v[1] for v in votes if v[0] in TREND_NAMES)
    o_sum = sum(v[1] for v in votes if v[0] not in TREND_NAMES)

    mline, msig, mh, mhp = macd(C)
    stk, std = stochastic(H, L, C)
    pbv, _mid = bollinger(C)
    raw = {"rsi": rsi_v, "stoch": (stk, std), "macd": (mline, msig, mh), "macd_prev": mhp, "pb": pbv,
           "e9": ema_series(C, 9)[-1], "e21": ema_series(C, 21)[-1], "e50": e50, "e200": e200,
           "cci": cci(H, L, C), "wr": williams_r(H, L, C), "roc": momentum_roc(C)}

    htf = None
    up_tf = TF_INFO[tf]["up"]
    if up_tf:
        d2 = fetch_candles(asset, up_tf)
        if d2 and len(d2["c"]) >= 60:
            htf = (up_tf, quick_trend(d2))

    return {
        "raw": raw, "asset": asset, "tf": tf, "price": price, "t": T[-1], "atr": atr_v, "votes": votes,
        "adx": adx_v, "pdi": pdi, "mdi": mdi, "rsi": rsi_v, "atr_ratio": atr_ratio, "bw_pct": bw_pct,
        "piv": piv, "ext": ext, "structure": structure, "res": res, "sup": sup,
        "res_t": touches(res) if res else 0, "sup_t": touches(sup) if sup else 0,
        "div": div, "checks": checks, "up": up, "dn": dn, "dir": direction,
        "buys": buys, "sells": sells, "neut": len(votes) - buys - sells,
        "t_sum": t_sum, "o_sum": o_sum, "htf": htf,
        "contradiction": t_sum * o_sum < 0 and abs(t_sum) >= 2 and abs(o_sum) >= 2,
        "note": market_note(asset, T[-1], tf),
    }

# ====================================================
# RAPPORT
# ====================================================


def vote_icon(v):
    return "🟢" if v > 0 else ("🔴" if v < 0 else "⚪")


def regime_text(a):
    adx_v = a["adx"]
    side = "haussière" if a["pdi"] > a["mdi"] else "baissière"
    if adx_v >= 25:
        return f"📈 *Tendance forte* {side} (ADX {adx_v:.0f})"
    if adx_v >= 20:
        return f"↗️ *Tendance modérée* {side} (ADX {adx_v:.0f})"
    return f"↔️ *Range* : pas de direction claire, marché piégeux (ADX {adx_v:.0f})"


def agreement_label(a):
    m = max(a["buys"], a["sells"])
    return "forte" if m >= 7 else ("moyenne" if m >= 5 else "faible")


def build_report(a):
    asset, tf, price, atr_v = a["asset"], a["tf"], a["price"], a["atr"]
    cfg = ASSETS[asset]
    when = datetime.fromtimestamp(a["t"], timezone.utc).strftime("%d/%m %H:%M UTC")
    vol = "élevée" if a["atr_ratio"] > 1.3 else ("faible" if a["atr_ratio"] < 0.7 else "normale")
    if a["bw_pct"] < 0.2:
        bb = "compression (squeeze) : le marché se tend, un mouvement peut suivre, sans dire dans quel sens"
    elif a["bw_pct"] > 0.8:
        bb = "bandes très larges : le mouvement est déjà étendu"
    else:
        bb = "largeur normale"

    p1 = [
        f"📊 *ANALYSE {cfg['label']} | {tf}*",
        f"_{TF_INFO[tf]['style']}_ | Prix : `{fmt(asset, price)}` | Bougie {when}",
        f"📡 {cfg['note']}",
    ]
    if a["note"]:
        p1.append(a["note"])
    p1 += [
        "───────────────────────────",
        "🩺 *ÉTAT DE SANTÉ DU MARCHÉ*",
        regime_text(a),
        f"🌊 Volatilité : *{vol}* (ATR {dist_txt(asset, atr_v)})",
        f"🎈 Bollinger : {bb}",
    ]
    st = {1: "sommets et creux de plus en plus hauts (haussière)",
          -1: "sommets et creux de plus en plus bas (baissière)",
          0: "mixte, pas de structure claire"}[a["structure"]]
    p1.append(f"🧭 Structure ZigZag : {st}")
    p1 += ["", "🔬 *LES 10 INDICATEURS*", "*Famille Tendance*"]
    for name, v, det in a["votes"]:
        if name in TREND_NAMES:
            p1.append(f"{vote_icon(v)} {name} : {det}")
    p1.append("*Famille Oscillateurs (surachat / survente)*")
    for name, v, det in a["votes"]:
        if name not in TREND_NAMES:
            p1.append(f"{vote_icon(v)} {name} : {det}")
    p1.append(f"\n🗳️ Accord : *{a['buys']}* haussiers | *{a['sells']}* baissiers | {a['neut']} neutres")
    if a["contradiction"]:
        side_t = "haussière" if a["t_sum"] > 0 else "baissière"
        side_o = "haussiers" if a["o_sum"] > 0 else "baissiers"
        p1.append(f"⚠️ *Contradiction* : la famille Tendance est {side_t} mais les Oscillateurs sont {side_o}.")

    # --- Page 2 ---
    r = a["rsi"]
    if r >= 70:
        zone = "SURACHAT"
    elif r <= 30:
        zone = "SURVENTE"
    elif r >= 55:
        zone = "zone haussière"
    elif r <= 45:
        zone = "zone baissière"
    else:
        zone = "neutre"
    p2 = ["📉 *RSI EN DÉTAIL*", f"RSI 14 : `{r:.1f}` → {zone}"]
    if a["div"] == -1:
        p2.append("🔻 Divergence baissière : le prix fait un sommet plus haut mais le RSI un sommet plus bas (essoufflement).")
    elif a["div"] == 1:
        p2.append("🔺 Divergence haussière : le prix fait un creux plus bas mais le RSI un creux plus haut (la pression vendeuse faiblit).")
    near_res = a["res"] and (a["res"] - price) / atr_v < 1
    near_sup = a["sup"] and (price - a["sup"]) / atr_v < 1
    if r >= 65 and near_res:
        p2.append("📍 RSI élevé + résistance proche : configuration classique de rejet possible, pas une certitude.")
    elif r <= 35 and near_sup:
        p2.append("📍 RSI bas + support proche : configuration classique de rebond possible, pas une certitude.")

    p2 += ["", "🧱 *SUPPORTS / RÉSISTANCES (pivots ZigZag)*"]
    if a["res"]:
        p2.append(f"Résistance : `{fmt(asset, a['res'])}` (à {(a['res'] - price) / atr_v:.1f} ATR ≈ {dist_txt(asset, a['res'] - price)}, repère touché {a['res_t']}×)")
    else:
        p2.append("Résistance : aucune au-dessus (le prix est au plus haut de la période)")
    if a["sup"]:
        p2.append(f"Support : `{fmt(asset, a['sup'])}` (à {(price - a['sup']) / atr_v:.1f} ATR ≈ {dist_txt(asset, price - a['sup'])}, repère touché {a['sup_t']}×)")
    else:
        p2.append("Support : aucun en dessous (le prix est au plus bas de la période)")
    last = a["piv"][-3:] + ([a["ext"]] if a["ext"] else [])
    if last:
        names = {"H": "sommet", "L": "creux"}
        seq = " → ".join(f"{names[k]} {fmt(asset, p)}" + (" (en cours)" if (a["ext"] and (i, p, k) == a["ext"]) else "")
                         for i, p, k in last)
        p2.append(f"Derniers pivots : {seq}")

    p2 += ["", "🏁 *BILAN*"]
    strong = max(a["up"], a["dn"]) >= 4
    word = dir_word(a["dir"], caps=strong or a["dir"] == 0)
    if a["dir"] != 0 and not strong:
        word = "plutôt " + word
    total = len(a["checks"])
    p2.append(f"Tendance de fond : *{word}*")
    for name, v in a["checks"]:
        p2.append(f"{'✅' if v > 0 else ('❌' if v < 0 else '➖')} {name}")
    p2.append(f"(✅ haussier / ❌ baissier / ➖ neutre | {a['up']} haussiers, {a['dn']} baissiers sur {total})")
    p2.append(f"Robustesse : accord *{agreement_label(a)}* ({max(a['buys'], a['sells'])}/10 indicateurs dans le même sens)")
    if a["htf"]:
        p2.append(f"Timeframe supérieur ({a['htf'][0]}) : {dir_word(a['htf'][1])}")
    p2.append("ℹ️ _La robustesse mesure l'accord entre indicateurs. Ce n'est pas une probabilité de gain._")
    p2.append("")
    p2.append(DISCLAIMER)
    return "\n".join(p1), "\n".join(p2)

# ====================================================
# MENTOR : explications et questions
# ====================================================


def lessons_text(a):
    asset, price, atr_v = a["asset"], a["price"], a["atr"]
    out = ["🎓 *LE MENTOR T'EXPLIQUE*", "───────────────────────────"]
    if a["adx"] < 20:
        out.append(f"*Pourquoi « range » ?* L'ADX est à {a['adx']:.0f} (sous 20) : le prix n'a pas de direction. "
                   "Dans ce cas les croisements de moyennes et le MACD donnent beaucoup de faux signaux. "
                   "Les niveaux (plafond / plancher) comptent plus que les indicateurs de tendance.")
    elif a["adx"] >= 25:
        out.append(f"*Pourquoi « tendance forte » ?* L'ADX est à {a['adx']:.0f} (au-dessus de 25). "
                   "Dans une tendance forte, un RSI en surachat peut y rester longtemps : "
                   "vendre uniquement parce que le RSI dépasse 70 est une erreur classique de débutant.")
    else:
        out.append(f"*Tendance modérée.* L'ADX ({a['adx']:.0f}) est entre 20 et 25 : une tendance naît peut-être, "
                   "mais elle n'est pas encore confirmée. On attend de voir si l'ADX monte.")
    if a["contradiction"]:
        out.append("*Pourquoi la contradiction compte ?* Quand les indicateurs de tendance et les oscillateurs "
                   "ne sont pas d'accord, le marché est souvent en pleine hésitation ou sur le point de se replier. "
                   "Ce n'est pas un signal d'entrée : c'est un signal de prudence.")
    if a["bw_pct"] < 0.2:
        out.append("*Le squeeze Bollinger :* des bandes serrées veulent dire que la volatilité est basse. "
                   "Les périodes calmes précèdent souvent des mouvements plus forts, mais la direction reste inconnue : "
                   "on attend la cassure.")
    r = a["rsi"]
    if r >= 70 or r <= 30:
        out.append(f"*RSI {r:.0f} :* hors de la zone 30-70, le mouvement est étiré. Cela signifie « essoufflement possible », "
                   "pas « le prix va se retourner ». Cherche une confirmation : bougie de rejet, divergence, niveau proche.")
    else:
        out.append(f"*RSI {r:.0f} :* il est entre 30 et 70. Au-dessus de 55 la dynamique est plutôt haussière, "
                   "sous 45 plutôt baissière. Le RSI sert surtout à repérer l'essoufflement aux extrêmes.")
    if a["res"] or a["sup"]:
        out.append("*Supports et résistances :* ce sont d'anciens sommets / creux importants, trouvés par le ZigZag. "
                   "Plus un niveau a été touché, plus il est suivi par les traders, mais chaque test l'use un peu. "
                   "Un niveau cassé change souvent de rôle (une résistance cassée devient support).")
    if a["htf"] and a["dir"] != 0 and a["htf"][1] != 0 and a["htf"][1] != a["dir"]:
        out.append(f"*Conflit de timeframes :* {a['tf']} est {dir_word(a['dir'])} mais {a['htf'][0]} est {dir_word(a['htf'][1])}. "
                   "Le timeframe supérieur domine en général : aller contre lui demande plus de prudence.")
    out.append("*La règle d'or :* avant d'entrer, écris où ton idée est fausse (ton invalidation) et combien tu risques. "
               "Si tu ne peux pas répondre, tu n'as pas de trade.")
    return "\n\n".join(out)


def _bullets(items):
    return "\n".join("• " + x for x in items) if items else "• (rien de net dans les indicateurs)"


def question_level(a):
    price, atr_v, asset = a["price"], a["atr"], a["asset"]
    cands = []
    if a["res"]:
        cands.append(((a["res"] - price) / atr_v, 1, a["res"], a["res_t"]))
    if a["sup"]:
        cands.append(((price - a["sup"]) / atr_v, -1, a["sup"], a["sup_t"]))
    if not cands:
        return None
    dist, toward, lv, tch = min(cands)
    name = "résistance" if toward == 1 else "support"
    brk, hold = [], []
    if a["dir"] == toward:
        brk.append(f"la tendance de fond est {dir_word(a['dir'])}, donc va vers ce niveau")
    elif a["dir"] == -toward:
        hold.append(f"la tendance de fond est {dir_word(a['dir'])}, donc va dans le sens opposé à la cassure")
    if a["adx"] >= 25 and ((a["pdi"] > a["mdi"]) == (toward == 1)):
        brk.append(f"l'ADX ({a['adx']:.0f}) montre une tendance forte vers le niveau")
    if a["adx"] < 20:
        hold.append(f"l'ADX ({a['adx']:.0f}) indique un range : les niveaux tiennent plus souvent")
    if a["htf"] and a["htf"][1] == toward:
        brk.append(f"le {a['htf'][0]} va dans le même sens")
    elif a["htf"] and a["htf"][1] == -toward:
        hold.append(f"le {a['htf'][0]} va dans le sens contraire")
    if (toward == 1 and a["rsi"] >= 65) or (toward == -1 and a["rsi"] <= 35):
        hold.append(f"le RSI ({a['rsi']:.0f}) est déjà essoufflé")
    if a["div"] == -toward:
        hold.append("une divergence du RSI signale un essoufflement")
    net = (a["buys"] - a["sells"]) * toward
    if net >= 2:
        brk.append("la majorité des indicateurs pousse vers le niveau")
    elif net <= -2:
        hold.append("la majorité des indicateurs pousse dans l'autre sens")

    if toward == 1:
        confirm = (f"✅ *Cassure confirmée* : une bougie qui *clôture* au-dessus de `{fmt(asset, lv)}`, idéalement avec un retest réussi.\n"
                   f"🛑 *Rejet* : longue mèche haute puis clôture sous `{fmt(asset, lv)}`.")
    else:
        confirm = (f"✅ *Cassure confirmée* : une bougie qui *clôture* sous `{fmt(asset, lv)}`, idéalement avec un retest échoué.\n"
                   f"🛑 *Rebond* : longue mèche basse puis clôture au-dessus de `{fmt(asset, lv)}`.")
    tail = ("\n\n_Aucune liste d'arguments ne garantit le résultat. Si le prix clôture de l'autre côté du niveau, "
            "ton idée est fausse : tu sors. C'est ça, l'invalidation._")

    def fb(head, mine_t, mine, other_t, other):
        return (f"🎓 *{head}*\n\n*{mine_t}*\n{_bullets(mine)}\n\n*{other_t}*\n{_bullets(other)}\n\n{confirm}{tail}")

    q = (f"Le prix `{fmt(asset, price)}` est à {dist:.1f} ATR ({dist_txt(asset, dist * atr_v)}) de la {name} "
         f"`{fmt(asset, lv)}` (repère touché {tch}×).\n\nSelon toi, cette {name} va-t-elle *tenir* ou *casser* ?")
    opts = [
        ("🧱 Elle va tenir", fb("Tu penses qu'elle va tenir.", "Ce qui va dans ton sens :", hold, "Ce qui va contre :", brk)),
        ("💥 Elle va casser", fb("Tu penses qu'elle va casser.", "Ce qui va dans ton sens :", brk, "Ce qui va contre :", hold)),
        ("⏳ J'attends confirmation", fb("Attendre est une vraie décision de trader.", "Arguments pour la cassure :", brk, "Arguments pour le rejet :", hold)),
    ]
    return {"q": q, "opts": opts}


def question_context(a):
    asset, tf = a["asset"], a["tf"]
    htf = a["htf"]
    tail = "\n\n_Dans tous les cas : stop défini avant d'entrer, risque 1-2 % max._"
    if htf and a["dir"] != 0 and htf[1] != 0 and htf[1] != a["dir"]:
        q = (f"Sur {tf}, la tendance est *{dir_word(a['dir'])}*, mais sur {htf[0]} elle est *{dir_word(htf[1])}*.\n\n"
             "Comment lis-tu cette situation ?")
        opts = [
            (f"Je suis le {htf[0]}", f"🎓 *Suivre le timeframe supérieur* est l'approche la plus prudente : le {tf} n'est alors qu'un repli "
                                       f"dans la tendance du {htf[0]}. On cherche une entrée quand le {tf} repart dans le sens du {htf[0]}.{tail}"),
            (f"Je suis le {tf}", f"🎓 *Suivre le {tf} contre le {htf[0]}* est un trade à contre-tendance : possible, mais les objectifs doivent être "
                                   f"plus proches et la taille plus petite, car le {htf[0]} peut reprendre la main à tout moment.{tail}"),
            ("Je reste à l'écart", f"🎓 *Ne rien faire* est souvent le meilleur trade quand les timeframes se contredisent. "
                                    f"On attend que les deux s'alignent.{tail}"),
        ]
        return {"q": q, "opts": opts}
    r = a["rsi"]
    if r >= 70 or r <= 30:
        extreme = "SURACHAT" if r >= 70 else "SURVENTE"
        q = (f"Le RSI est à {r:.0f} ({extreme}) et l'ADX à {a['adx']:.0f}.\n\nComment l'interprètes-tu ?")
        if a["adx"] >= 25:
            why = "la tendance est forte et le RSI peut rester extrême longtemps"
        else:
            why = "le marché est moins directionnel, donc le retour vers la moyenne est plus plausible"
        opts = [
            ("Retournement probable", f"🎓 Un RSI extrême n'est pas un signal de retournement à lui seul. Avec un ADX de {a['adx']:.0f}, "
                                      f"{why}. Cherche une confirmation (divergence, bougie de rejet, niveau).{tail}"),
            ("La tendance continue", f"🎓 C'est cohérent quand l'ADX est fort (ici {a['adx']:.0f}) : en tendance, le RSI colle aux extrêmes. "
                                      f"Le risque : un essoufflement soudain. Place ton invalidation avant d'agir.{tail}"),
            ("J'attends un signal", f"🎓 Prudent : le RSI extrême est une *alerte*, pas un ordre. Attends une bougie de confirmation.{tail}"),
        ]
        return {"q": q, "opts": opts}
    q = (f"L'ADX est à {a['adx']:.0f} et {a['buys']} indicateurs sont haussiers contre {a['sells']} baissiers.\n\n"
         "Quelle approche te semble la plus cohérente ?")
    rng = a["adx"] < 20
    if rng:
        t1 = "Avec un ADX sous 20, il n'y a pas vraiment de courant à suivre : les entrées « de tendance » se font souvent piéger."
        t2 = "C'est l'approche classique quand l'ADX est bas : acheter près du support, vendre près de la résistance, avec un stop juste derrière le niveau."
    else:
        t1 = "Logique si la tendance est confirmée : on cherche une entrée sur repli dans le sens dominant plutôt que de courir après le prix."
        t2 = "Risqué ici : l'ADX montre un début de tendance, et les rebonds de range se font balayer quand la tendance démarre."
    t3 = ("Toujours valable : une cassure avec clôture et ADX qui monte confirme qu'un mouvement démarre. "
          "Tu paies un peu plus cher l'entrée, mais tu évites les faux départs.")
    opts = [
        ("Trader dans le sens du courant", "🎓 " + t1 + tail),
        ("Jouer les rebonds du range", "🎓 " + t2 + tail),
        ("Attendre une cassure", "🎓 " + t3 + tail),
    ]
    return {"q": q, "opts": opts}


def build_questions(a):
    qs = []
    q1 = question_level(a)
    if q1:
        qs.append(q1)
    qs.append(question_context(a))
    return qs

# ====================================================
# ENVOI DU RAPPORT
# ====================================================
reports = {}


def store_report(a):
    now = time.time()
    for k in [k for k, (ts, _) in reports.items() if now - ts > 7200]:
        reports.pop(k, None)
    if len(reports) > 300:
        reports.pop(min(reports, key=lambda k: reports[k][0]), None)
    rid = secrets.token_hex(3)
    reports[rid] = (now, a)
    return rid


def get_report(rid):
    item = reports.get(rid)
    return item[1] if item else None


def report_markup(rid, asset, tf):
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(
        types.InlineKeyboardButton("🧑‍🏫 Mode Coach : questions", callback_data=f"co_{rid}_0"),
        types.InlineKeyboardButton("🔍 Mes indicateurs en clair", callback_data=f"ip_{rid}"),
        types.InlineKeyboardButton("🎓 Explique-moi ce rapport", callback_data=f"ls_{rid}"),
        types.InlineKeyboardButton("🔄 Réanalyser", callback_data=f"rep_{asset}_{tf}"),
        types.InlineKeyboardButton("⏱️ Changer de timeframe", callback_data=f"as_{asset}"),
        types.InlineKeyboardButton("Menu Principal", callback_data="back_home"),
    )
    return m


def run_analysis(chat_id, asset, tf):
    wait = safe_send(chat_id, f"⏳ Analyse de {ASSETS[asset]['label']} en {tf}...")
    try:
        a = full_analysis(asset, tf)
    except Exception as e:
        print("Erreur analyse:", e)
        a = None
    if wait is not None:
        clean_delete_message(chat_id, wait.message_id)
    if not a:
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("🔄 Réessayer", callback_data=f"rep_{asset}_{tf}"),
              types.InlineKeyboardButton("Menu", callback_data="back_home"))
        safe_send(chat_id, "⚠️ Impossible de récupérer les données de marché pour le moment. Réessaie dans un instant.",
                  reply_markup=m)
        return
    consume_trial(chat_id)
    log_analysis(chat_id, asset, tf, dir_word(a["dir"]))
    rid = store_report(a)
    last_a[chat_id] = a
    p1, p2 = build_report(a)
    safe_send(chat_id, p1)
    safe_send(chat_id, p2, reply_markup=report_markup(rid, asset, tf))


def send_question(chat_id, rid, qi):
    a = get_report(rid)
    if not a:
        safe_send(chat_id, "⌛ Cette analyse est trop ancienne. Relance-en une depuis /menu.")
        return
    qs = build_questions(a)
    if qi >= len(qs):
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("🎓 Explique-moi ce rapport", callback_data=f"ls_{rid}"),
              types.InlineKeyboardButton("🔄 Nouvelle analyse", callback_data=f"rep_{a['asset']}_{a['tf']}"),
              types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
        safe_send(chat_id, "🏁 *Séance terminée.* Retiens : on ne devine pas le marché, on lit le contexte, "
                           "on définit son invalidation et on gère le risque.", reply_markup=m)
        return
    q = qs[qi]
    m = types.InlineKeyboardMarkup(row_width=1)
    for i, (label, _fb) in enumerate(q["opts"]):
        m.add(types.InlineKeyboardButton(label, callback_data=f"aw_{rid}_{qi}_{i}"))
    safe_send(chat_id, f"🧑‍🏫 *QUESTION {qi + 1}/{len(qs)}*\n───────────────────────────\n{q['q']}", reply_markup=m)


def send_answer(chat_id, rid, qi, oi):
    a = get_report(rid)
    if not a:
        safe_send(chat_id, "⌛ Cette analyse est trop ancienne. Relance-en une depuis /menu.")
        return
    qs = build_questions(a)
    if qi >= len(qs) or oi >= len(qs[qi]["opts"]):
        return
    nxt = "➡️ Question suivante" if qi + 1 < len(qs) else "🏁 Terminer"
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton(nxt, callback_data=f"co_{rid}_{qi + 1}"))
    safe_send(chat_id, qs[qi]["opts"][oi][1], reply_markup=m)

# ====================================================
# COMMANDES ET ADMINISTRATION
# ====================================================


@bot.message_handler(commands=['adminrubenb2k'])
def admin_secret_cmd(message):
    chat_id = message.chat.id
    if ADMIN_ID:
        safe_send(chat_id, "⛔ L'admin est défini par variable d'environnement.")
        return
    with db_lock:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT chat_id FROM users WHERE is_admin=1")
        row = cur.fetchone()
        if row and row[0] != chat_id:
            conn.close()
            safe_send(chat_id, "⛔ Clé administrative déjà verrouillée.")
            return
        exists = cur.execute("SELECT 1 FROM users WHERE chat_id=?", (chat_id,)).fetchone()
        if not exists:
            cur.execute("INSERT INTO users (chat_id, trials_left, is_paid, is_admin) VALUES (?, 3, 0, 0)", (chat_id,))
        cur.execute("UPDATE users SET is_admin=1, is_paid=1 WHERE chat_id=?", (chat_id,))
        conn.commit()
        conn.close()
    safe_send(chat_id, "🔑 **ACCÈS ADMINISTRATEUR ACTIVÉ !**\n\nBienvenue Ruben (@b2k_ruben).")


@bot.message_handler(commands=['vip'])
def activate_vip_user(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        deny_admin(chat_id)
        return
    try:
        target_id = int(message.text.split()[1])
        get_user(target_id)
        with db_lock:
            conn = db()
            conn.execute("UPDATE users SET is_paid=1 WHERE chat_id=?", (target_id,))
            conn.commit()
            conn.close()
        safe_send(chat_id, f"✅ **Utilisateur ID {target_id} activé VIP !**")
        try:
            bot.send_message(target_id, "⭐ **Ton accès VIP B2K est activé !** Tape /menu pour commencer.")
        except Exception:
            pass
    except Exception:
        safe_send(chat_id, "Format : `/vip CHAT_ID`")


@bot.message_handler(commands=['test'])
def toggle_test_mode(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        deny_admin(chat_id)
        return
    now = not testing_as_user.get(chat_id, False)
    testing_as_user[chat_id] = now
    if now:
        with db_lock:
            conn = db()
            conn.execute("UPDATE users SET trials_left=3 WHERE chat_id=?", (chat_id,))
            conn.commit()
            conn.close()
    status = "ACTIVÉ (Simulation 3 essais client)" if now else "DÉSACTIVÉ (Mode Admin)"
    safe_send(chat_id, f"⚙️ **MODE TEST UTILISATEUR :** {status}")


@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        deny_admin(chat_id)
        return
    with db_lock:
        conn = db()
        users = conn.execute("SELECT COUNT(*), COALESCE(SUM(is_paid),0) FROM users").fetchone()
        total = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        day = conn.execute("SELECT COUNT(*) FROM analyses WHERE created_ms > ?",
                           (int((time.time() - 86400) * 1000),)).fetchone()[0]
        by_sym = conn.execute("SELECT symbol, COUNT(*) FROM analyses GROUP BY symbol ORDER BY 2 DESC").fetchall()
        by_tf = conn.execute("SELECT tf, COUNT(*) FROM analyses GROUP BY tf ORDER BY 2 DESC").fetchall()
        conn.close()
    lines = [
        f"📈 *STATISTIQUES D'USAGE | {VERSION}*",
        "───────────────────────────",
        f"👥 Utilisateurs : {users[0]} (dont VIP/admin : {users[1]})",
        f"🔬 Analyses : {total} au total, {day} sur les dernières 24 h",
    ]
    if by_sym:
        lines.append("Marchés : " + " | ".join(f"{s} {c}" for s, c in by_sym))
    if by_tf:
        lines.append("Timeframes : " + " | ".join(f"{s} {c}" for s, c in by_tf))
    safe_send(chat_id, "\n".join(lines))


@bot.message_handler(commands=['annonce'])
def broadcast_annonce(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        deny_admin(chat_id)
        return
    msg = safe_send(chat_id, "📢 **ENVOI D'ANNONCE**\n\nEnvoie le message ou la photo à diffuser à tous les utilisateurs :\n(Tape /menu pour annuler)")
    if msg:
        bot.register_next_step_handler(msg, process_broadcast)


def process_broadcast(message):
    if message.text and message.text.startswith("/"):
        safe_send(message.chat.id, "↩️ Annonce annulée.")
        return
    with db_lock:
        conn = db()
        all_users = conn.execute("SELECT chat_id FROM users").fetchall()
        conn.close()
    count = 0
    for (uid,) in all_users:
        try:
            if message.photo:
                bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption, parse_mode=None)
            else:
                bot.send_message(uid, message.text, parse_mode=None)
            count += 1
        except Exception:
            pass
        time.sleep(0.05)
    safe_send(message.chat.id, f"✅ **Annonce diffusée avec succès à {count} utilisateur(s).**")


@bot.message_handler(commands=['payment'])
def payment_info(message):
    send_payment_message(message.chat.id)


def send_payment_message(chat_id):
    text = (
        "💳 **ACTIVATION ACCÈS VIP B2K**\n"
        "───────────────────────────\n"
        f"💰 **Tarif Abonnement :** **{PRICE_USD} USD** ou **{PRICE_HTG} HTG**\n\n"
        "📌 **Moyens de paiement :**\n"
        "• **Crypto :** USDT (TRC20 / BEP20)\n"
        "• **Local Haïti :** MonCash / NatCash\n\n"
        "📲 **Pour activer votre compte :**\n"
        "📩 **Telegram Direct :** [@b2k_ruben](https://t.me/b2k_ruben)\n"
        "📱 **WhatsApp Direct :** +50943528461\n\n"
        f"🆔 Ton ID à communiquer : `{chat_id}`"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📲 Contacter @b2k_ruben", url="https://t.me/b2k_ruben"))
    markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    safe_send(chat_id, text, reply_markup=markup, disable_web_page_preview=True)


def send_trial_over(chat_id):
    text = (
        "⛔ **VOTRE ESSAI GRATUIT EST TERMINÉ !**\n"
        "───────────────────────────\n"
        f"Débloquez votre accès VIP illimité pour {PRICE_USD} $ USD / {PRICE_HTG} HTG.\n\n"
        "📩 Telegram : [@b2k_ruben](https://t.me/b2k_ruben)\n"
        "📱 WhatsApp : +50943528461"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"💳 Payer mon accès ({PRICE_USD}$)", callback_data="show_payment"))
    markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    safe_send(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

# ====================================================
# MENU PRINCIPAL
# ====================================================


@bot.message_handler(commands=['start', 'menu'])
def start_cmd(message):
    chat_id = message.chat.id
    get_user(chat_id)
    show_main_menu(chat_id)


def show_main_menu(chat_id):
    trials, is_paid, admin = get_user(chat_id)
    is_testing = testing_as_user.get(chat_id, False)
    text = (
        "👋 *Salut ! Moi c'est ton pote trader B2K.*\n"
        "───────────────────────────\n"
        "Je t'analyse le marché, je t'explique chaque indicateur (RSI, MACD, Bollinger, ZigZag...), "
        "je t'apprends à placer ton stop loss et ton take profit, et je peux même regarder la capture de ton graphique MT5.\n\n"
        "*Quel actif tu veux trader aujourd'hui ?*"
    )
    if is_testing or (not is_paid and not admin):
        text += f"\n\n🎁 *Analyses gratuites restantes :* `{trials}/3`"
    else:
        text += "\n\n⭐ *Statut :* `Abonné VIP Actif`"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🗣️ Séance guidée avec ton pote trader", callback_data="se0"),
        types.InlineKeyboardButton(ASSETS["EURUSD"]["label"] + " (Forex)", callback_data="as_EURUSD"),
        types.InlineKeyboardButton(ASSETS["BTCUSD"]["label"] + " (Crypto)", callback_data="as_BTCUSD"),
        types.InlineKeyboardButton(ASSETS["XAUUSD"]["label"], callback_data="as_XAUUSD"),
        types.InlineKeyboardButton("📸 Analyser mon graphique MT5 (photo)", callback_data="photo_help"),
        types.InlineKeyboardButton("📚 Apprendre les indicateurs", callback_data="lr_menu"),
        types.InlineKeyboardButton(f"💳 Abonnement VIP ({PRICE_USD}$)", callback_data="show_payment"),
    )
    safe_send(chat_id, text, reply_markup=markup)

# ====================================================
# CALLBACKS
# ====================================================


@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    data = call.data

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    # --- Actions qui gardent le rapport à l'écran ---
    if data.startswith("co_"):
        try:
            _, rid, qi = data.split("_")
            send_question(chat_id, rid, int(qi))
        except ValueError:
            pass
        return

    if data.startswith("aw_"):
        try:
            _, rid, qi, oi = data.split("_")
            send_answer(chat_id, rid, int(qi), int(oi))
        except ValueError:
            pass
        return

    if data.startswith("ls_"):
        a = get_report(data.split("_")[1])
        if not a:
            safe_send(chat_id, "⌛ Cette analyse est trop ancienne. Relance-en une depuis /menu.")
            return
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("🧑‍🏫 Mode Coach", callback_data=f"co_{data.split('_')[1]}_0"),
              types.InlineKeyboardButton("✖ Fermer", callback_data="close"))
        safe_send(chat_id, lessons_text(a), reply_markup=m)
        return

    if data.startswith("ip_"):
        a = get_report(data.split("_")[1])
        if not a:
            safe_send(chat_id, "⌛ Cette analyse est trop ancienne. Relance-en une depuis /menu.")
            return
        m = types.InlineKeyboardMarkup()
        m.add(types.InlineKeyboardButton("📚 Cours complet", callback_data="lr_menu"),
              types.InlineKeyboardButton("✖ Fermer", callback_data="close"))
        safe_send(chat_id, indicators_plain(a), reply_markup=m)
        return

    if data == "close":
        clean_delete_message(chat_id, message_id)
        return

    # --- Navigation : on remplace le message précédent ---
    clean_delete_message(chat_id, message_id)

    if data == "back_home":
        show_main_menu(chat_id)
        return

    if data == "show_payment":
        send_payment_message(chat_id)
        return

    if handle_extra(chat_id, data):
        return

    if data.startswith("as_"):
        asset = data.split("_")[1]
        if asset not in ASSETS:
            show_main_menu(chat_id)
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("⚡ M1", callback_data=f"rep_{asset}_M1"),
            types.InlineKeyboardButton("⚡ M5", callback_data=f"rep_{asset}_M5"),
            types.InlineKeyboardButton("🚀 M15", callback_data=f"rep_{asset}_M15"),
            types.InlineKeyboardButton("🚀 H1", callback_data=f"rep_{asset}_H1"),
            types.InlineKeyboardButton("🧭 H4", callback_data=f"rep_{asset}_H4"),
            types.InlineKeyboardButton("🧭 D1", callback_data=f"rep_{asset}_D1"),
        )
        markup.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
        safe_send(chat_id,
                  f"📌 **{ASSETS[asset]['label']}**\nChoisis ton style :\n"
                  "⚡ *M1-M5* : scalping ultra-rapide\n"
                  "🚀 *M15-H1* : scalping et day-trading\n"
                  "🧭 *H4-D1* : vision de fond (swing)",
                  reply_markup=markup)
        return

    if data.startswith("rep_"):
        try:
            _, asset, tf = data.split("_")
        except ValueError:
            return
        if asset not in ASSETS or tf not in TF_INFO:
            show_main_menu(chat_id)
            return
        if not has_access(chat_id):
            send_trial_over(chat_id)
            return
        threading.Thread(target=run_analysis, args=(chat_id, asset, tf), daemon=True).start()
        return



# ====================================================
# COURS : LES INDICATEURS EXPLIQUÉS
# ====================================================
LEARN = {
    "rsi": ("📉 RSI", (
        "📉 *LE RSI (Relative Strength Index)*\n"
        "Il mesure, de 0 à 100, la force des hausses par rapport aux baisses sur les 14 dernières bougies.\n\n"
        "*Comment l'identifier :* une ligne sous le graphique avec 3 repères : 30, 50 et 70.\n\n"
        "*Comment le lire :*\n"
        "• RSI au-dessus de 70 : SURACHAT. Les acheteurs sont essoufflés, un repli devient possible.\n"
        "• RSI sous 30 : SURVENTE. Les vendeurs sont essoufflés, un rebond devient possible.\n"
        "• Autour de 50 : équilibre. Au-dessus de 55 la dynamique est plutôt haussière, sous 45 plutôt baissière.\n\n"
        "*Le piège :* en tendance forte, le RSI reste longtemps entre 40 et 80 (haussier) ou 20 et 60 (baissier). "
        "Un RSI à 75 n'est PAS un ordre de vente.\n\n"
        "*Divergence :* le prix fait un nouveau sommet mais le RSI un sommet plus bas = essoufflement. "
        "Même idée à l'envers sur les creux.\n\n"
        "*Bonne pratique :* RSI sous 30 + support + bougie de rejet = bonne raison de surveiller un rebond. Un seul signal ne suffit jamais."
    )),
    "macd": ("📊 MACD", (
        "📊 *LE MACD*\n"
        "Il compare deux moyennes mobiles (12 et 26) pour mesurer le momentum et la tendance.\n\n"
        "*Comment l'identifier :* deux lignes (MACD et signal) et un histogramme autour d'une ligne zéro.\n\n"
        "*Comment le lire :*\n"
        "• MACD au-dessus de la ligne signal : momentum haussier. En dessous : baissier.\n"
        "• MACD au-dessus de zéro : tendance de fond haussière. Sous zéro : baissière.\n"
        "• Histogramme qui grandit : le mouvement accélère. Qui rétrécit : il s'essouffle.\n\n"
        "*Le piège :* c'est un indicateur lent. En range il croise sans arrêt et donne de faux signaux."
    )),
    "bb": ("🎈 Bandes de Bollinger", (
        "🎈 *LES BANDES DE BOLLINGER*\n"
        "Une moyenne de 20 bougies avec une bande haute et une bande basse à 2 écarts-types. "
        "Environ 95 % des prix restent à l'intérieur.\n\n"
        "*Comment l'identifier :* 3 lignes qui enveloppent les bougies, qui s'écartent quand le marché bouge et se resserrent quand il est calme.\n\n"
        "*Comment le lire :*\n"
        "• %B = 1 : le prix touche la bande haute. %B = 0 : bande basse. 0,5 : au milieu.\n"
        "• Bandes très serrées (squeeze) : marché calme, un mouvement fort suit souvent, sans dire dans quel sens.\n"
        "• Bandes très larges : le mouvement est déjà étendu.\n\n"
        "*Le piège :* toucher la bande haute n'est pas un signal de vente. En tendance forte, le prix « marche » le long de la bande."
    )),
    "stoch": ("🎚️ Stochastique", (
        "🎚️ *LE STOCHASTIQUE*\n"
        "Il montre où la clôture se situe dans l'amplitude des 14 dernières bougies, de 0 à 100.\n\n"
        "*Comment l'identifier :* deux lignes, %K (rapide) et %D (la moyenne de %K), avec des repères à 20 et 80.\n\n"
        "*Comment le lire :*\n"
        "• %K à 89 : la clôture est tout près du plus haut récent, donc SURACHAT (au-dessus de 80).\n"
        "• %K à 15 : près du plus bas récent, donc SURVENTE (sous 20).\n"
        "• %K qui repasse sous %D en zone haute : signe d'essoufflement. %K qui repasse au-dessus de %D en zone basse : la pression vendeuse faiblit.\n\n"
        "*Le piège :* comme le RSI, il peut rester en surachat très longtemps dans une tendance forte. Il est rapide et donne beaucoup de signaux : on le filtre avec la tendance."
    )),
    "zz": ("🧭 ZigZag", (
        "🧭 *LE ZIGZAG*\n"
        "Il relie uniquement les sommets et les creux importants et ignore le bruit des petites bougies. Il sert à lire la structure du marché.\n\n"
        "*Comment l'identifier :* une ligne brisée qui monte et descend sur le graphique.\n\n"
        "*Comment le lire :*\n"
        "• Sommets de plus en plus hauts ET creux de plus en plus hauts : structure HAUSSIÈRE.\n"
        "• Sommets et creux de plus en plus bas : structure BAISSIÈRE.\n"
        "• Si le dernier creux d'une hausse est cassé, la tendance peut changer.\n"
        "• Les anciens sommets / creux deviennent des résistances / supports.\n\n"
        "*Le piège :* le dernier segment se redessine tant que le pivot n'est pas confirmé. Dans ce bot, un pivot n'est confirmé que quand le prix repart de 2,5 ATR en sens inverse."
    )),
    "mom": ("🚀 Momentum / ROC", (
        "🚀 *LE MOMENTUM (ROC)*\n"
        "Il mesure de combien le prix a varié en pourcentage sur les N dernières bougies (ici 10).\n\n"
        "*Comment le lire :*\n"
        "• Au-dessus de zéro : le prix est plus haut qu'il y a 10 bougies (momentum haussier). Sous zéro : baissier.\n"
        "• Il grandit : le mouvement accélère. Il diminue alors que le prix monte encore : l'élan faiblit.\n\n"
        "*Le piège :* il réagit vite, donc il bouge beaucoup dans un marché sans direction."
    )),
    "ma": ("〰️ Moyennes mobiles", (
        "〰️ *LES MOYENNES MOBILES (EMA)*\n"
        "Elles lissent le prix. L'EMA donne plus de poids aux bougies récentes, donc elle réagit plus vite que la SMA.\n\n"
        "*Comment les lire :*\n"
        "• EMA 9 au-dessus de EMA 21 : court terme haussier (et inversement).\n"
        "• Prix au-dessus de EMA 50, elle-même au-dessus de EMA 200 : tendance de fond haussière. L'inverse : baissière.\n"
        "• Les moyennes servent aussi de support / résistance dynamique : le prix rebondit souvent dessus dans une tendance.\n\n"
        "*Le piège :* en range, le prix les traverse sans arrêt et chaque croisement est un faux signal."
    )),
    "adx": ("💪 ADX (force de tendance)", (
        "💪 *L'ADX*\n"
        "Il mesure la FORCE de la tendance, pas sa direction.\n\n"
        "*Comment le lire :*\n"
        "• Sous 20 : RANGE, pas de tendance. Les indicateurs de tendance (EMA, MACD) trompent.\n"
        "• 20 à 25 : une tendance naît peut-être.\n"
        "• Au-dessus de 25 : tendance forte. Au-dessus de 40 : très forte, parfois proche de l'épuisement.\n"
        "• La direction vient des lignes +DI et -DI : +DI au-dessus de -DI = haussier.\n\n"
        "C'est le premier indicateur à regarder : il te dit quel type d'outil utiliser."
    )),
    "cci": ("📐 CCI et Williams %R", (
        "📐 *CCI ET WILLIAMS %R*\n"
        "Deux oscillateurs qui mesurent à quel point le prix s'éloigne de sa moyenne.\n\n"
        "• *CCI* : au-dessus de +100 = surachat, sous -100 = survente, entre les deux = normal.\n"
        "• *Williams %R* : va de 0 à -100. Au-dessus de -20 = surachat, sous -80 = survente.\n\n"
        "Williams %R est le stochastique à l'envers : mêmes signaux, autre échelle. "
        "Comme tous les oscillateurs, ils signalent un essoufflement possible, pas un retournement certain."
    )),
    "sr": ("🧱 Supports et résistances", (
        "🧱 *SUPPORTS ET RÉSISTANCES*\n"
        "• *Support* : zone où le prix a déjà rebondi vers le haut (plancher).\n"
        "• *Résistance* : zone où il a déjà été repoussé vers le bas (plafond).\n\n"
        "*Comment les identifier :* repère les anciens sommets et creux importants (le ZigZag les trouve), "
        "les zones où le prix a réagi plusieurs fois.\n\n"
        "*Comment les lire :* plus un niveau est touché, plus il compte, mais chaque test l'use. "
        "Quand il casse avec une clôture nette, il change de rôle : une résistance cassée devient un support."
    )),
    "cdl": ("🕯️ Bougies de confirmation", (
        "🕯️ *LES BOUGIES DE CONFIRMATION*\n"
        "Ce sont les bougies qui te montrent que le marché réagit à un niveau.\n\n"
        "• *Pin bar / marteau* : petit corps et longue mèche. Mèche basse sur un support = les acheteurs ont repoussé les vendeurs. Mèche haute sur une résistance = rejet.\n"
        "• *Avalement* : une bougie qui englobe entièrement la précédente, dans le sens opposé. Signe de reprise de contrôle.\n"
        "• *Doji* : ouverture et clôture presque égales = indécision.\n"
        "• *Clôture au-delà d'un niveau* : c'est la vraie confirmation de cassure. Une simple mèche ne compte pas.\n\n"
        "*Règle :* on attend la clôture de la bougie. Une bougie en cours peut encore tout changer."
    )),
    "sl": ("🛡️ Stop Loss et Take Profit", (
        "🛡️ *STOP LOSS ET TAKE PROFIT*\n\n"
        "*Le stop loss = l'endroit où ton idée est fausse.* Pas un nombre de pips au hasard.\n"
        "• Achat : place-le sous le dernier creux ou support, avec une marge de 0,5 à 1 ATR (et le spread).\n"
        "• Vente : au-dessus du dernier sommet ou résistance, avec la même marge.\n"
        "• Trop serré : le bruit normal du marché te sort. Trop large : tu perds trop.\n\n"
        "*Le take profit :* au prochain support / résistance, ou à 1,5 à 2 fois ton risque. "
        "Si le niveau est trop proche pour atteindre 1,5 fois le risque, ne prends pas le trade.\n\n"
        "*Le spread* est un coût : un objectif trop proche est perdu d'avance.\n\n"
        "*La taille :* risque 1 % du capital au maximum. Lot = (capital × 1 %) / (distance du stop × valeur du point). "
        "Avec un petit capital, utilise le plus petit lot (0.01).\n\n"
        "*Règles d'or :* ne jamais éloigner son stop une fois placé, ne jamais trader sans stop."
    )),
    "val": ("📋 Tableau des seuils", (
        "📋 *AIDE-MÉMOIRE : LES SEUILS*\n"
        "• RSI : sous 30 survente | 30-70 normal | au-dessus de 70 surachat\n"
        "• Stochastique %K : sous 20 survente | au-dessus de 80 surachat (89 = surachat)\n"
        "• CCI : sous -100 survente | au-dessus de +100 surachat\n"
        "• Williams %R : sous -80 survente | au-dessus de -20 surachat\n"
        "• Bollinger %B : 0 = bande basse | 1 = bande haute\n"
        "• ADX : sous 20 range | au-dessus de 25 tendance forte\n"
        "• MACD : au-dessus de zéro haussier | en dessous baissier\n"
        "• EMA 9 > EMA 21 : court terme haussier | prix > EMA 50 > EMA 200 : tendance de fond haussière\n\n"
        "Quand plusieurs indicateurs disent la même chose ET que le contexte (tendance, niveau) est d'accord, "
        "l'idée est plus solide. Quand ils se contredisent, on attend."
    )),
}

LEARN_KEYS = [("rsi", "rsi"), ("macd", "macd"), ("bollinger", "bb"), ("bande", "bb"), ("stoch", "stoch"),
              ("zigzag", "zz"), ("zig zag", "zz"), ("momentum", "mom"), ("roc", "mom"), ("moyenne", "ma"),
              ("ema", "ma"), ("sma", "ma"), ("adx", "adx"), ("tendance", "adx"), ("range", "adx"),
              ("cci", "cci"), ("williams", "cci"), ("support", "sr"), ("résistance", "sr"), ("resistance", "sr"),
              ("bougie", "cdl"), ("chandelier", "cdl"), ("pin bar", "cdl"), ("stop", "sl"), ("take profit", "sl"),
              ("lot", "sl"), ("seuil", "val"), ("surachat", "val"), ("survente", "val")]


def learn_menu_markup():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(*[types.InlineKeyboardButton(title, callback_data=f"lr_{k}") for k, (title, _t) in LEARN.items()])
    m.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    return m


def kb_lookup(text):
    t = (text or "").lower()
    for word, key in LEARN_KEYS:
        if word in t:
            return key
    return None


# ====================================================
# TES INDICATEURS EN CLAIR (valeurs réelles expliquées)
# ====================================================
def indicators_plain(a):
    w = a["raw"]
    out = ["🔍 *TES INDICATEURS EN CLAIR*", "───────────────────────────"]
    r = w["rsi"]
    if r >= 70:
        t = f"{r:.0f} : SURACHAT (au-dessus de 70). Les acheteurs sont essoufflés. En tendance forte il peut y rester : on cherche une confirmation avant de conclure."
    elif r <= 30:
        t = f"{r:.0f} : SURVENTE (sous 30). Les vendeurs sont essoufflés, un rebond est possible. Confirme avec un support et une bougie de rejet."
    elif r >= 55:
        t = f"{r:.0f} : zone haussière (entre 55 et 70). Les acheteurs dominent sans excès."
    elif r <= 45:
        t = f"{r:.0f} : zone baissière (entre 30 et 45). Les vendeurs dominent sans excès."
    else:
        t = f"{r:.0f} : neutre (45-55). Pas d'avantage net."
    out.append(f"*RSI* {t}")
    k, d = w["stoch"]
    if k >= 80:
        t = f"%K {k:.0f} / %D {d:.0f} : SURACHAT (au-dessus de 80). La clôture est près du plus haut récent."
    elif k <= 20:
        t = f"%K {k:.0f} / %D {d:.0f} : SURVENTE (sous 20). La clôture est près du plus bas récent."
    else:
        t = f"%K {k:.0f} / %D {d:.0f} : zone neutre (20-80)."
    t += " %K au-dessus de %D = momentum court terme haussier." if k > d else " %K sous %D = momentum court terme baissier."
    out.append(f"*Stochastique* {t}")
    ml, ms, mh = w["macd"]
    grow = abs(mh) > abs(w["macd_prev"])
    t = ("la ligne MACD est " + ("au-dessus de" if ml > ms else "sous") + " sa ligne signal (momentum " +
         ("haussier" if ml > ms else "baissier") + ") et " + ("au-dessus de" if ml > 0 else "sous") +
         " zéro (tendance de fond " + ("haussière" if ml > 0 else "baissière") + "). L'histogramme " +
         ("grandit : le mouvement accélère." if grow else "rétrécit : le mouvement s'essouffle."))
    out.append(f"*MACD* {t}")
    pb = w["pb"]
    if pb >= 1:
        t = f"%B {pb:.2f} : le prix est au-dessus de la bande haute. Mouvement très étiré."
    elif pb >= 0.8:
        t = f"%B {pb:.2f} : le prix colle à la bande haute (étiré vers le haut)."
    elif pb <= 0:
        t = f"%B {pb:.2f} : le prix est sous la bande basse. Mouvement très étiré."
    elif pb <= 0.2:
        t = f"%B {pb:.2f} : le prix colle à la bande basse (étiré vers le bas)."
    else:
        t = f"%B {pb:.2f} : le prix est dans la zone centrale."
    out.append(f"*Bollinger* {t}")
    e9, e21, e50, e200 = w["e9"], w["e21"], w["e50"], w["e200"]
    t = f"EMA 9 {'au-dessus' if e9 > e21 else 'sous'} EMA 21 (court terme {'haussier' if e9 > e21 else 'baissier'})."
    if e200:
        if a["price"] > e50 > e200:
            t += " Prix > EMA 50 > EMA 200 : tendance de fond haussière."
        elif a["price"] < e50 < e200:
            t += " Prix < EMA 50 < EMA 200 : tendance de fond baissière."
        else:
            t += " EMA 50 / 200 mélangées avec le prix : tendance de fond pas alignée."
    out.append(f"*Moyennes mobiles* {t}")
    adx_v = a["adx"]
    out.append(f"*ADX* {adx_v:.0f} : " + ("range, les indicateurs de tendance trompent." if adx_v < 20 else
                                          ("tendance naissante." if adx_v < 25 else "tendance forte.")) +
               f" Direction : {'+DI domine (haussier)' if a['pdi'] > a['mdi'] else '-DI domine (baissier)'}.")
    c, wr, roc = w["cci"], w["wr"], w["roc"]
    t1 = "surachat" if c > 100 else ("survente" if c < -100 else "normal")
    t2 = "surachat" if wr > -20 else ("survente" if wr < -80 else "normal")
    out.append(f"*CCI* {c:.0f} : {t1} (repères ±100). *Williams %R* {wr:.0f} : {t2} (repères -20 / -80).")
    out.append(f"*Momentum* {roc:+.2f} % sur 10 bougies : " + ("le prix est plus haut qu'il y a 10 bougies." if roc > 0 else "le prix est plus bas qu'il y a 10 bougies."))
    n_over = sum([r >= 70, k >= 80, c > 100, wr > -20])
    n_under = sum([r <= 30, k <= 20, c < -100, wr < -80])
    if n_over >= 3:
        out.append("🔔 *Plusieurs oscillateurs en surachat en même temps* : le mouvement est étiré. Ça ne veut pas dire « vends », ça veut dire « méfie-toi d'acheter ici ».")
    elif n_under >= 3:
        out.append("🔔 *Plusieurs oscillateurs en survente en même temps* : le mouvement est étiré vers le bas. Méfie-toi de vendre ici, surveille un rebond sur un support.")
    return "\n\n".join(out)


# ====================================================
# GEMINI (analyse de photo + discussion libre)
# ====================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
CHAT_DAILY_CAP = int(os.getenv("CHAT_DAILY_CAP", "30"))

PERSONA = (
    "Tu es « B2K Mentor », un pote de trading bienveillant et éducatif sur Telegram. Tu tutoies, tu es chaleureux, "
    "direct et tu parles simplement, comme un ami qui s'y connaît. Tu réponds dans la langue de l'utilisateur (français par défaut). "
    "Tu aides à comprendre les marchés (EUR/USD, BTC/USD, XAU/USD surtout) : RSI, MACD, Bollinger, stochastique, ZigZag, "
    "momentum, moyennes mobiles, ADX, supports/résistances, bougies, placement du stop loss et du take profit, gestion du risque. "
    "Quand tu expliques un indicateur, donne les seuils et comment l'identifier sur le graphique (RSI 30/70, stochastique 20/80, CCI ±100, "
    "Williams -20/-80, ADX 20/25, MACD vs zéro). "
    "Règles : tu ne prédis jamais l'avenir, tu ne promets aucun gain, tu ne donnes pas d'ordre d'achat ou de vente garanti. "
    "Tu présentes des scénarios (ce qui confirmerait, ce qui invaliderait) et tu insistes sur l'invalidation, le stop et le risque de 1-2 % du capital. "
    "Tu poses souvent une question de relance pour faire réfléchir (stratégie, timeframe, où serait son stop). "
    "Réponses courtes (150 mots maximum sauf demande de cours détaillé). Texte simple : pas de markdown, pas d'astérisques, pas de tableaux, quelques emojis."
)

PHOTO_PROMPT = (
    "Voici une capture d'écran d'un graphique de trading (probablement MetaTrader 5). Analyse-la comme un mentor pédagogue, en français, "
    "en texte simple (pas de markdown, pas d'astérisques), 350 mots maximum, avec ces sections courtes et des emojis :\n"
    "1) Ce que je vois : actif et timeframe si lisibles, indicateurs affichés.\n"
    "2) Tendance et structure : sommets/creux, haussière, baissière ou range.\n"
    "3) Supports et résistances visibles (donne les niveaux de prix s'ils sont lisibles sur l'axe).\n"
    "4) Bougies importantes : rebonds, rejets (mèches), avalements, dojis, et ce qu'elles signifient.\n"
    "5) Lecture des indicateurs visibles (RSI, MACD, etc.) avec les seuils.\n"
    "6) Scénarios : ce qui confirmerait une hausse, ce qui confirmerait une baisse, et où l'idée serait invalidée.\n"
    "Règles : ne prédis pas l'avenir, ne promets rien, ne donne pas d'ordre d'achat/vente garanti. "
    "Si l'image est floue ou n'est pas un graphique, dis-le simplement. Termine par UNE question pour faire réfléchir l'utilisateur."
)


def clean_ai(text):
    for ch in ("*", "_", "`", "[", "]"):
        text = text.replace(ch, "")
    return text.strip()


def gemini_call(contents, system):
    """Retourne (texte, erreur)."""
    if not GEMINI_API_KEY:
        return None, "no_key"
    body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1500}}
    last = "erreur inconnue"
    for model in [GEMINI_MODEL] + [m for m in ("gemini-2.5-flash", "gemini-2.0-flash") if m != GEMINI_MODEL]:
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                              json=body, timeout=60)
        except Exception as e:
            last = f"réseau : {e}"
            continue
        if r.status_code == 200:
            try:
                parts = r.json()["candidates"][0]["content"]["parts"]
                txt = "".join(p.get("text", "") for p in parts).strip()
                if txt:
                    return txt, None
                last = "réponse vide"
            except Exception:
                last = "réponse illisible"
            continue
        last = f"HTTP {r.status_code} ({model}) {r.text[:150]}"
        if r.status_code == 429:
            return None, "quota"
        if r.status_code in (401, 403):
            return None, "key"
    return None, last


def ai_error_text(err):
    if err == "quota":
        return "⏳ Je suis très sollicité en ce moment (limite gratuite atteinte). Réessaie dans une minute."
    if err == "key":
        return "⚠️ La clé Gemini est refusée. L'administrateur doit vérifier GEMINI_API_KEY sur Render."
    return "⚠️ Je n'arrive pas à analyser ça pour le moment. Réessaie dans un instant."


def no_ai_text(chat_id):
    t = ("🤖 L'analyse de photo et la discussion libre ne sont pas encore activées sur ce bot.")
    if is_admin(chat_id):
        t += ("\n\n*Admin :* crée une clé gratuite sur aistudio.google.com (Get API key, sans carte bancaire), "
              "puis ajoute-la sur Render dans la variable `GEMINI_API_KEY` et redéploie.")
    return t


awaiting_photo = {}
chat_hist = {}
chat_count = {}
last_a = {}


def run_photo_analysis(message):
    chat_id = message.chat.id
    wait = safe_send(chat_id, "🔎 Je regarde ton graphique, 10 secondes...")
    try:
        fid = message.photo[-1].file_id
        info = bot.get_file(fid)
        raw = bot.download_file(info.file_path)
        import base64
        b64 = base64.b64encode(raw).decode()
    except Exception as e:
        print("Erreur photo:", e)
        if wait is not None:
            clean_delete_message(chat_id, wait.message_id)
        safe_send(chat_id, "⚠️ Je n'ai pas réussi à télécharger ta photo. Renvoie-la (en photo, pas en fichier).")
        return
    user_text = PHOTO_PROMPT
    if message.caption:
        user_text += f"\nMessage de l'utilisateur avec la photo : {message.caption[:300]}"
    contents = [{"role": "user", "parts": [{"text": user_text}, {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]}]
    txt, err = gemini_call(contents, PERSONA)
    if wait is not None:
        clean_delete_message(chat_id, wait.message_id)
    if not txt:
        print("Erreur Gemini photo:", err)
        safe_send(chat_id, ai_error_text(err))
        if is_admin(chat_id):
            safe_send(chat_id, f"(admin) détail : {err}", parse_mode=None)
        return
    consume_trial(chat_id)
    log_analysis(chat_id, "PHOTO", "-", "photo")
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("📸 Analyser un autre graphique", callback_data="photo_help"),
          types.InlineKeyboardButton("📚 Apprendre les indicateurs", callback_data="lr_menu"),
          types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    safe_send(chat_id, "📸 *ANALYSE DE TON GRAPHIQUE*\n───────────────────────────\n" + clean_ai(txt) + "\n\n" + DISCLAIMER,
              reply_markup=m)


def chat_allowed(chat_id):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d, n = chat_count.get(chat_id, (today, 0))
    if d != today:
        n = 0
    if n >= CHAT_DAILY_CAP:
        return False
    chat_count[chat_id] = (today, n + 1)
    return True


def context_line(chat_id):
    a = last_a.get(chat_id)
    if not a:
        return ""
    r = a["raw"]
    return (f"[Contexte : dernière analyse de l'utilisateur = {a['asset']} {a['tf']}, prix {a['price']:.5g}, tendance de fond {dir_word(a['dir'])}, "
            f"ADX {a['adx']:.0f}, RSI {r['rsi']:.0f}, stochastique K {r['stoch'][0]:.0f}, "
            f"résistance {a['res'] if a['res'] else 'aucune'}, support {a['sup'] if a['sup'] else 'aucun'}.]\n")


def run_chat(chat_id, text):
    hist = chat_hist.setdefault(chat_id, [])
    hist.append({"role": "user", "parts": [{"text": context_line(chat_id) + text[:800]}]})
    del hist[:-8]
    while hist and hist[0]["role"] != "user":
        hist.pop(0)
    txt, err = gemini_call(hist, PERSONA)
    if not txt:
        hist.pop()
        print("Erreur Gemini chat:", err)
        safe_send(chat_id, ai_error_text(err))
        return
    hist.append({"role": "model", "parts": [{"text": txt}]})
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("📚 Cours", callback_data="lr_menu"),
          types.InlineKeyboardButton("Menu", callback_data="back_home"))
    safe_send(chat_id, clean_ai(txt), reply_markup=m)


# ====================================================
# SÉANCE AVEC TON POTE TRADER (questions guidées)
# ====================================================
STYLES = {
    "sc": ("⚡ Scalping", "M5", "M15", "des trades de quelques minutes"),
    "dt": ("🚀 Day-trading", "M15", "H1", "des trades de quelques heures dans la journée"),
    "sw": ("🧭 Swing", "H4", "D1", "des trades de plusieurs jours"),
}


def session_start(chat_id):
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton(ASSETS["EURUSD"]["label"], callback_data="se1_EURUSD"),
          types.InlineKeyboardButton(ASSETS["BTCUSD"]["label"], callback_data="se1_BTCUSD"),
          types.InlineKeyboardButton(ASSETS["XAUUSD"]["label"], callback_data="se1_XAUUSD"),
          types.InlineKeyboardButton("🤷 Je ne sais pas encore", callback_data="se1_UNK"))
    safe_send(chat_id, "Salut ! 👋 Moi c'est ton pote trader.\n\n*Quel actif tu veux trader aujourd'hui ?*\n"
                       "_EUR/USD est le plus stable, BTC/USD le plus nerveux, l'or a de gros mouvements._", reply_markup=m)


def session_style(chat_id, asset):
    if asset == "UNK":
        safe_send(chat_id, "Pas de souci ! Pour débuter, l'*EUR/USD* est le plus calme et le plus facile à lire. "
                           "Si tu aimes quand ça bouge, prends le *BTC/USD*. On part sur l'EUR/USD ?")
        asset = "EURUSD"
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("⚡ Scalping (quelques minutes)", callback_data=f"se2_{asset}_sc"),
          types.InlineKeyboardButton("🚀 Day-trading (quelques heures)", callback_data=f"se2_{asset}_dt"),
          types.InlineKeyboardButton("🧭 Swing (quelques jours)", callback_data=f"se2_{asset}_sw"),
          types.InlineKeyboardButton("🤷 Je ne sais pas, explique-moi", callback_data=f"se2_{asset}_un"))
    safe_send(chat_id, f"Top, on bosse sur *{ASSETS[asset]['label']}*.\n\n*Quel type de stratégie tu veux utiliser ?* "
                       "Comment tu préfères trader ?", reply_markup=m)


def session_level(chat_id, asset, style):
    if style == "un":
        safe_send(chat_id,
                  "Petite explication :\n"
                  "⚡ *Scalping* : tu entres et sors en quelques minutes (M1-M5). Beaucoup d'occasions, mais beaucoup de bruit, "
                  "et le spread pèse lourd sur des petits objectifs. Demande de la concentration.\n"
                  "🚀 *Day-trading* : trades de quelques heures (M15-H1). Bon équilibre pour apprendre.\n"
                  "🧭 *Swing* : trades de plusieurs jours (H4-D1). Peu de trades, plus de recul, moins de stress.\n\n"
                  "Je te conseille le *day-trading* pour commencer. On y va avec ça.")
        style = "dt"
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("🌱 Débutant", callback_data=f"se3_{asset}_{style}_b"),
          types.InlineKeyboardButton("🌿 Je connais les bases", callback_data=f"se3_{asset}_{style}_i"),
          types.InlineKeyboardButton("🌳 Expérimenté", callback_data=f"se3_{asset}_{style}_x"))
    safe_send(chat_id, "*Dernière question : tu te situes où ?* Je m'adapte à ton niveau.", reply_markup=m)


def session_plan(chat_id, asset, style, lvl):
    name, tf, htf, desc = STYLES[style]
    atr_txt = ""
    try:
        d = fetch_candles(asset, tf)
        if d and len(d["c"]) > 30:
            av = atr(d["h"], d["l"], d["c"])
            atr_txt = (f"\n\n📏 *Exemple en direct :* sur {ASSETS[asset]['label']} en {tf}, l'ATR (la taille moyenne d'une bougie) "
                       f"vaut {dist_txt(asset, av)}. Un stop typique = environ 1,5 ATR ≈ {dist_txt(asset, 1.5 * av)}, "
                       f"et un objectif à 2 fois le risque ≈ {dist_txt(asset, 3 * av)}. "
                       "C'est un ordre de grandeur, pas un ordre à passer.")
    except Exception:
        pass
    steps = (
        f"{name} sur {ASSETS[asset]['label']} : {desc}.\n\n"
        f"*Ma méthode en 4 étapes :*\n"
        f"1️⃣ *Contexte* : regarde le {htf} pour connaître la tendance de fond. On évite d'aller contre.\n"
        f"2️⃣ *Niveaux* : repère les supports et résistances sur le {tf} (le ZigZag les trouve).\n"
        f"3️⃣ *Confirmation* : attends une bougie qui confirme (rejet, avalement, clôture au-delà du niveau) et un RSI / stochastique cohérents.\n"
        f"4️⃣ *Stop et objectif* : le stop est là où ton idée est fausse (derrière le dernier pivot + 0,5 à 1 ATR), "
        f"l'objectif au prochain niveau, avec un ratio d'au moins 1,5 pour 1."
    )
    if lvl == "b":
        steps += ("\n\n🌱 *Pour bien démarrer :*\n"
                  "• Un *stop loss* est l'ordre qui ferme ton trade si le marché va contre toi. Sans lui, une seule erreur peut vider ton compte.\n"
                  "• Un *take profit* ferme ton trade quand tu as atteint ton objectif.\n"
                  "• Risque 1 % de ton capital par trade, pas plus. Avec un petit capital, lot 0.01.\n"
                  "• Commence en démo et note chaque trade : pourquoi tu es entré, où était ton stop.")
    elif lvl == "x":
        steps += "\n\n🌳 Pour ton niveau : concentre-toi sur la confluence (niveau + tendance du TF supérieur + confirmation) et sur l'espérance, pas sur le taux de réussite."
    steps += atr_txt
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton(f"📊 Analyser {ASSETS[asset]['label']} en {tf}", callback_data=f"rep_{asset}_{tf}"),
          types.InlineKeyboardButton(f"🧭 Voir le contexte {htf}", callback_data=f"rep_{asset}_{htf}"),
          types.InlineKeyboardButton("📚 Apprendre les indicateurs", callback_data="lr_menu"),
          types.InlineKeyboardButton("📸 Envoyer mon graphique MT5", callback_data="photo_help"),
          types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    safe_send(chat_id, steps + "\n\n*Prêt ? Je t'analyse le marché maintenant ?*", reply_markup=m)


def photo_help(chat_id):
    awaiting_photo[chat_id] = True
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    safe_send(chat_id,
              "📸 *ANALYSE DE TON GRAPHIQUE MT5*\n───────────────────────────\n"
              "Fais une capture d'écran de ton graphique (M1, M5, ce que tu veux) et envoie-la-moi *en photo* (pas en fichier).\n\n"
              "💡 Ajoute une légende si tu veux, par exemple : « M1 XAUUSD, je pense à un achat, ça te dit quoi ? »\n\n"
              "Je te dirai ce que je vois : tendance, supports et résistances, bougies de confirmation, rebonds, indicateurs affichés. "
              "Pour que ce soit lisible : zoome pour voir 50 à 100 bougies et garde l'axe des prix visible.", reply_markup=m)


def handle_extra(chat_id, data):
    """Boutons du mentor : retourne True si le callback a été traité."""
    if data == "photo_help":
        photo_help(chat_id)
        return True
    if data in ("lr_menu", "show_book"):
        safe_send(chat_id, "📚 *ACADÉMIE B2K*\nQu'est-ce que tu veux comprendre ? Je t'explique comment l'identifier et comment le lire :",
                  reply_markup=learn_menu_markup())
        return True
    if data.startswith("lr_"):
        key = data[3:]
        if key in LEARN:
            m = types.InlineKeyboardMarkup(row_width=1)
            m.add(types.InlineKeyboardButton("📚 Autres sujets", callback_data="lr_menu"),
                  types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
            safe_send(chat_id, LEARN[key][1], reply_markup=m)
        return True
    if data == "se0":
        session_start(chat_id)
        return True
    parts = data.split("_")
    if parts[0] == "se1" and len(parts) == 2:
        session_style(chat_id, parts[1] if parts[1] in ASSETS else "UNK")
        return True
    if parts[0] == "se2" and len(parts) == 3 and parts[1] in ASSETS:
        session_level(chat_id, parts[1], parts[2] if parts[2] in ("sc", "dt", "sw", "un") else "dt")
        return True
    if parts[0] == "se3" and len(parts) == 4 and parts[1] in ASSETS and parts[2] in STYLES:
        threading.Thread(target=session_plan, args=(chat_id, parts[1], parts[2], parts[3]), daemon=True).start()
        return True
    return False


# ====================================================
# MESSAGES LIBRES ET PHOTOS
# ====================================================
@bot.message_handler(content_types=['photo'])
def photo_cmd(message):
    chat_id = message.chat.id
    get_user(chat_id)
    awaiting_photo.pop(chat_id, None)
    if not has_access(chat_id):
        send_trial_over(chat_id)
        return
    if not GEMINI_API_KEY:
        safe_send(chat_id, no_ai_text(chat_id))
        return
    threading.Thread(target=run_photo_analysis, args=(message,), daemon=True).start()


@bot.message_handler(content_types=['text'])
def free_text(message):
    chat_id = message.chat.id
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return
    get_user(chat_id)
    if GEMINI_API_KEY and has_access(chat_id) and chat_allowed(chat_id):
        threading.Thread(target=run_chat, args=(chat_id, text), daemon=True).start()
        return
    key = kb_lookup(text)
    if key:
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("📚 Autres sujets", callback_data="lr_menu"),
              types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
        safe_send(chat_id, LEARN[key][1], reply_markup=m)
        return
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add(types.InlineKeyboardButton("🗣️ Parler avec ton pote trader", callback_data="se0"),
          types.InlineKeyboardButton("📚 Apprendre un indicateur", callback_data="lr_menu"),
          types.InlineKeyboardButton("Menu Principal", callback_data="back_home"))
    safe_send(chat_id, "Je suis là ! 😄 Demande-moi par exemple « c'est quoi le RSI ? », « comment placer mon stop loss ? », "
                       "ou lance une séance guidée.", reply_markup=m)


if __name__ == '__main__':
    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
