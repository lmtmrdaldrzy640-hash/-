# ==========================================
# AutoMT5 Bot - جسر MetaApi
# يعمل على الهاتف عبر Termux
# pip install requests
# ==========================================
import time
import requests

SUPABASE_URL = "https://czhtuqypomoezqxjwybj.supabase.co"
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN6aHR1cXlwb21vZXpxeGp3eWJqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNTk4OTQsImV4cCI6MjEwMzgzNTg5NH0.pBzF1QE7h09tF8CdXrqOynX0If8SGa6JlrkUoDsYMd4"
META = "https://metaapi.cloud/api/v1"
SYMBOL = "XAUUSD"

token = input("MetaApi Token: ").strip()
account_id = input("Account ID: ").strip()
email = input("ايميل التطبيق: ").strip()
password = input("كلمة مرور التطبيق: ")

H = {"auth-token": token}

r = requests.post(SUPABASE_URL + "/auth/v1/token?grant_type=password",
    headers={"apikey": ANON, "Content-Type": "application/json"},
    json={"email": email, "password": password})
if r.status_code >= 300:
    print("فشل دخول التطبيق:", r.text[:200]); exit()
auth = r.json()
UID = auth["user"]["id"]
SB = {"apikey": ANON, "Authorization": "Bearer " + auth["access_token"],
      "Content-Type": "application/json", "Prefer": "return=representation"}
print("تم تسجيل الدخول إلى التطبيق")

def sb_get(table, q):
    return requests.get(SUPABASE_URL + "/rest/v1/" + table + "?" + q, headers=SB).json()

def sb_patch(table, q, body):
    return requests.patch(SUPABASE_URL + "/rest/v1/" + table + "?" + q, headers=SB, json=body)

def sb_post(table, body):
    return requests.post(SUPABASE_URL + "/rest/v1/" + table, headers=SB, json=body)

def blog(msg, level="info"):
    print(msg)
    try:
        sb_post("bot_logs", {"user_id": UID, "message": msg, "log_level": level})
    except Exception:
        pass

def meta(path, method="GET", body=None):
    r = requests.request(method, META + path, headers=H, json=body)
    if r.status_code >= 300:
        raise Exception("MetaApi " + str(r.status_code) + ": " + r.text[:200])
    return r.json() if r.text else {}

def get_candles(tf):
    d = meta("/users/current/accounts/" + account_id + "/symbols/" + SYMBOL + "/candles?timeframe=" + tf + "&limit=100")
    return d if isinstance(d, list) else d.get("candles", [])

def rsi(closes, period=14):
    g = l = 0.0
    for i in range(len(closes) - period, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0: g += diff
        else: l -= diff
    if l == 0: return 100.0
    return 100 - (100 / (1 + g / l))

def signal(tf, strategy):
    c = get_candles(tf)
    closes = [float(x["close"]) for x in c][:-1]
    if len(closes) < 60: return 0
    maF = sum(closes[-10:]) / 10
    maS = sum(closes[-50:]) / 50
    r = rsi(closes)
    if strategy == "rsi_only":
        if r < 30: return 1
        if r > 70: return -1
        return 0
    if strategy == "ma_only":
        if maF > maS: return 1
        if maF < maS: return -1
        return 0
    if maF > maS and 50 < r < 70: return 1
    if maF < maS and 30 < r < 50: return -1
    return 0

def open_order(sig, s, balance, contract):
    pr = meta("/users/current/accounts/" + account_id + "/symbols/" + SYMBOL + "/current-price")
    price = float(pr.get("marketPrice") or pr.get("bid") or pr.get("ask"))
    sl_dist = price * 0.003
    risk = balance * float(s["risk_percent"]) / 100
    volume = max(0.01, round(risk / (sl_dist * contract), 2))
    side = "buy" if sig == 1 else "sell"
    sl = round(price - sl_dist, 2) if sig == 1 else round(price + sl_dist, 2)
    tp = round(price + 2 * sl_dist, 2) if sig == 1 else round(price - 2 * sl_dist, 2)
    meta("/users/current/accounts/" + account_id + "/orders", "POST", {
        "symbol": SYMBOL, "side": side, "volume": volume, "type": "MARKET",
        "stopLoss": sl, "takeProfit": tp, "comment": "AutoMT5", "magic": 202609})
    sb_post("trades", {"user_id": UID, "symbol": SYMBOL, "trade_type": side,
        "volume": volume, "open_price": price, "stop_loss": sl,
        "take_profit": tp, "profit": 0, "status": "open"})
    blog("فتحت صفقة " + side + " حجم " + str(volume) + " سعر " + str(round(price, 2)))

def main():
    info = meta("/users/current/accounts/" + account_id + "/account-information")
    print("متصل! الرصيد:", info.get("balance"))
    blog("المحرك اتصل بـ MT5 عبر MetaApi")
    day_start = float(info["balance"])
    contract = 100
    try:
        sym = meta("/users/current/accounts/" + account_id + "/symbols/" + SYMBOL)
        contract = float(sym.get("contractSize", 100))
    except Exception:
        pass

    while True:
        try:
            rows = sb_get("bot_settings", "user_id=eq." + UID)
            s = rows[0] if rows else None
            if not s or s["bot_status"] != "running":
                time.sleep(5); continue

            info = meta("/users/current/accounts/" + account_id + "/account-information")
            balance = float(info["balance"]); equity = float(info["equity"])

            if equity - day_start <= -balance * float(s["max_daily_loss_percent"]) / 100:
                sb_patch("bot_settings", "user_id=eq." + UID, {"bot_status": "stopped"})
                blog("توقف البوت: حد الخسارة اليومية", "error")
                time.sleep(10); continue

            positions = meta("/users/current/accounts/" + account_id + "/positions")
            tf = {"M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h"}.get(s.get("timeframe", "M15"), "15m")

            if len(positions) < int(s["max_open_trades"]):
                sig = signal(tf, s.get("strategy_type", "ma_rsi"))
                if sig != 0:
                    open_order(sig, s, balance, contract)

            time.sleep(15)
        except Exception as e:
            blog("خطأ: " + str(e), "error")
            time.sleep(15)

if __name__ == "__main__":
    main()
