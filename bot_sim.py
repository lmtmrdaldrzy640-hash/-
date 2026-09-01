# ==========================================
# AutoMT5 Bot - وضع التدريب
# سعر حقيقي + أموال افتراضية
# pip install requests
# ==========================================
import time
import datetime
import requests

SUPABASE_URL = "https://czhtuqypomoezqxjwybj.supabase.co"
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN6aHR1cXlwb21vZXpxeGp3eWJqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNTk4OTQsImV4cCI6MjEwMzgzNTg5NH0.pBzF1QE7h09tF8CdXrqOynX0If8SGa6JlrkUoDsYMd4"

email = input("ايميل التطبيق: ").strip()
password = input("كلمة مرور التطبيق: ")

r = requests.post(SUPABASE_URL + "/auth/v1/token?grant_type=password",
    headers={"apikey": ANON, "Content-Type": "application/json"},
    json={"email": email, "password": password})
if r.status_code >= 300:
    print("فشل الدخول:", r.text[:200]); exit()
a = r.json()
UID = a["user"]["id"]
SB = {"apikey": ANON, "Authorization": "Bearer " + a["access_token"],
      "Content-Type": "application/json", "Prefer": "return=representation"}
print("تم الدخول - وضع التدريب")

BALANCE = 1000.0
positions = []

def sb_get(t, q):
    return requests.get(SUPABASE_URL + "/rest/v1/" + t + "?" + q, headers=SB).json()

def sb_post(t, b):
    return requests.post(SUPABASE_URL + "/rest/v1/" + t, headers=SB, json=b).json()

def sb_patch(t, q, b):
    return requests.patch(SUPABASE_URL + "/rest/v1/" + t + "?" + q, headers=SB, json=b)

def blog(m, l="info"):
    print(m)
    try:
        sb_post("bot_logs", {"user_id": UID, "message": m, "log_level": l})
    except Exception:
        pass

def price():
    d = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT").json()
    return float(d["price"])

def candles(iv):
    k = requests.get("https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=" + iv + "&limit=100").json()
    return [float(x[4]) for x in k][:-1]

def rsi(c, p=14):
    g = l = 0.0
    for i in range(len(c) - p, len(c)):
        d = c[i] - c[i - 1]
        if d > 0: g += d
        else: l -= d
    return 100.0 if l == 0 else 100 - (100 / (1 + g / l))

def signal(iv, strat):
    c = candles(iv)
    if len(c) < 60: return 0
    maF = sum(c[-10:]) / 10
    maS = sum(c[-50:]) / 50
    r = rsi(c)
    if strat == "rsi_only":
        return 1 if r < 30 else (-1 if r > 70 else 0)
    if strat == "ma_only":
        return 1 if maF > maS else (-1 if maF < maS else 0)
    if maF > maS and 50 < r < 70: return 1
    if maF < maS and 30 < r < 50: return -1
    return 0

def recover():
    rows = sb_get("trades", "user_id=eq." + UID + "&status=eq.open")
    for t in rows:
        positions.append({"id": t["id"], "type": t["trade_type"], "open": float(t["open_price"]),
                          "sl": float(t["stop_loss"]), "tp": float(t["take_profit"]),
                          "units": float(t["volume"])})

def close(p, exit_px):
    d = 1 if p["type"] == "buy" else -1
    profit = round((exit_px - p["open"]) * d * p["units"], 2)
    sb_patch("trades", "id=eq." + p["id"], {
        "status": "closed", "profit": profit, "close_price": exit_px,
        "closed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    positions.remove(p)
    blog("أغلقت صفقة بنتيجة: " + str(profit) + "$", "info" if profit >= 0 else "error")

def open_trade(sig, px, s):
    sl_dist = px * 0.003
    risk = BALANCE * float(s["risk_percent"]) / 100
    units = risk / sl_dist
    t = "buy" if sig == 1 else "sell"
    sl = px - sl_dist if sig == 1 else px + sl_dist
    tp = px + 2 * sl_dist if sig == 1 else px - 2 * sl_dist
    row = sb_post("trades", {"user_id": UID, "symbol": "XAUUSD (تدريب)",
        "trade_type": t, "volume": round(units, 4), "open_price": px,
        "stop_loss": round(sl, 2), "take_profit": round(tp, 2),
        "profit": 0, "status": "open"})
    if isinstance(row, list) and row:
        positions.append({"id": row[0]["id"], "type": t, "open": px, "sl": sl, "tp": tp, "units": units})
        blog("فتحت صفقة " + t + " على الذهب بسعر " + str(round(px, 2)))

def main():
    recover()
    blog("بوت التدريب يعمل - سعر حقيقي وأموال افتراضية")
    while True:
        try:
            rows = sb_get("bot_settings", "user_id=eq." + UID)
            s = rows[0] if rows else None
            if not s or s["bot_status"] != "running":
                time.sleep(5); continue

            px = price()

            today = datetime.datetime.now(datetime.timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0).isoformat()
            closed = sb_get("trades", "user_id=eq." + UID + "&status=eq.closed&closed_at=gte." + today)
            day = sum(float(x.get("profit") or 0) for x in closed)
            if day <= -BALANCE * float(s["max_daily_loss_percent"]) / 100:
                sb_patch("bot_settings", "user_id=eq." + UID, {"bot_status": "stopped"})
                blog("توقف: بلغت حد الخسارة اليومية", "error")
                time.sleep(10); continue

            for p in list(positions):
                if p["type"] == "buy":
                    if px <= p["sl"]: close(p, p["sl"]); continue
                    if px >= p["tp"]: close(p, p["tp"]); continue
                else:
                    if px >= p["sl"]: close(p, p["sl"]); continue
                    if px <= p["tp"]: close(p, p["tp"]); continue

            if len(positions) < int(s["max_open_trades"]):
                iv = {"M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h"}.get(s.get("timeframe", "M15"), "15m")
                sig = signal(iv, s.get("strategy_type", "ma_rsi"))
                if sig != 0:
                    open_trade(sig, px, s)

            time.sleep(10)
        except Exception as e:
            print("خطأ:", e)
            time.sleep(10)

if __name__ == "__main__":
    main()
