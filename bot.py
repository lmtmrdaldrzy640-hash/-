# ==========================================
# AutoMT5 Bot - محرك التداول
# يشغَّل على جهاز ويندوز عليه MetaTrader 5
# pip install MetaTrader5 supabase
# ==========================================

import time
import datetime
import MetaTrader5 as mt5
from supabase import create_client

SUPABASE_URL = "https://czhtuqypomoezqxjwybj.supabase.co"
SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN6aHR1cXlwb21vZXpxeGp3eWJqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNTk4OTQsImV4cCI6MjEwMzgzNTg5NH0.pBzF1QE7h09tF8CdXrqOynX0If8SGa6JlrkUoDsYMd4";

print("AutoMT5 Bot - المحرك")
email = input("ايميل التطبيق: ")
password = input("كلمة المرور: ")

sb = create_client(SUPABASE_URL, SUPABASE_ANON)
auth = sb.auth.sign_in_with_password({"email": email, "password": password})
UID = auth.user.id
print("تم تسجيل الدخول بنجاح")

TIMEFRAMES = {
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
}

def get_settings():
    d = sb.table("bot_settings").select("*").eq("user_id", UID).execute().data
    return d[0] if d else None

def get_account():
    d = sb.table("mt5_accounts").select("*").eq("user_id", UID).execute().data
    return d[0] if d else None

def log(msg, level="info"):
    print(msg)
    try:
        sb.table("bot_logs").insert(
            {"user_id": UID, "message": msg, "log_level": level}).execute()
    except Exception:
        pass

def connect_mt5(acc):
    if not mt5.initialize():
        return False
    ok = mt5.login(login=int(acc["mt5_login"]),
                   password=acc["mt5_password"],
                   server=acc["mt5_server"])
    return bool(ok)

def rsi(closes, period=14):
    gains, losses = 0.0, 0.0
    for i in range(-period - 1, 0):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    return 100 - (100 / (1 + gains / losses))

def signal(symbol, tf):
    rates = mt5.copy_rates_from_pos(symbol, tf, 1, 100)
    if rates is None or len(rates) < 60:
        return 0
    closes = [float(r["close"]) for r in rates]
    ma_fast = sum(closes[-10:]) / 10
    ma_slow = sum(closes[-50:]) / 50
    r = rsi(closes)
    if ma_fast > ma_slow and 50 < r < 70:
        return 1
    if ma_fast < ma_slow and 30 < r < 50:
        return -1
    return 0

def calc_lot(symbol, sl_points, risk_amount):
    info = mt5.symbol_info(symbol)
    if info is None or info.trade_tick_value <= 0:
        return 0.01
    point_value = info.trade_tick_value * (info.point / info.trade_tick_size)
    lot = risk_amount / (sl_points * point_value) if point_value > 0 else 0.01
    lot = max(info.volume_min, min(info.volume_max, round(lot, 2)))
    return lot

def open_trade(symbol, sig, s, balance):
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return
    sl_points, tp_points = 300, 600
    risk_amount = balance * float(s["risk_percent"]) / 100
    volume = calc_lot(symbol, sl_points, risk_amount)
    if sig == 1:
        price, otype = tick.ask, mt5.ORDER_TYPE_BUY
        sl, tp = price - sl_points * info.point, price + tp_points * info.point
        ttype = "buy"
    else:
        price, otype = tick.bid, mt5.ORDER_TYPE_SELL
        sl, tp = price + sl_points * info.point, price - tp_points * info.point
        ttype = "sell"
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": otype,
        "price": price,
        "sl": round(sl, info.digits),
        "tp": round(tp, info.digits),
        "deviation": 20,
        "magic": 202609,
        "comment": "AutoMT5",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
        sb.table("trades").insert({
            "user_id": UID, "symbol": symbol, "trade_type": ttype,
            "volume": volume, "open_price": price,
            "stop_loss": round(sl, info.digits),
            "take_profit": round(tp, info.digits),
            "profit": 0, "status": "open"
        }).execute()
        log("تم فتح صفقة " + ttype + " على " + symbol + " بحجم " + str(volume))
    else:
        log("فشل فتح صفقة: " + str(res), "error")

def daily_profit():
    now = datetime.datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start, now)
    if deals is None:
        return 0.0
    return sum(d.profit + d.swap + d.commission for d in deals if d.entry == mt5.DEAL_ENTRY_OUT)

def main():
    acc = get_account()
    if not acc:
        print("لا يوجد حساب MT5 محفوظ في التطبيق")
        return
    if not connect_mt5(acc):
        print("فشل الاتصال بـ MT5")
        return
    log("تم تشغيل المحرك والاتصال بـ MT5")

    while True:
        try:
            s = get_settings()
            if s is None or s["bot_status"] != "running":
                time.sleep(5)
                continue

            acc_info = mt5.account_info()
            if acc_info is None:
                time.sleep(5)
                continue

            # فحص الخسارة اليومية
            max_loss_amount = acc_info.balance * float(s["max_daily_loss_percent"]) / 100
            if daily_profit() <= -max_loss_amount:
                sb.table("bot_settings").update({"bot_status": "stopped"}).eq("user_id", UID).execute()
                log("تم إيقاف البوت: وصلت الحد الأقصى للخسارة اليومية", "error")
                time.sleep(10)
                continue

            positions = mt5.positions_get() or ()
            tf = TIMEFRAMES.get(s["timeframe"], mt5.TIMEFRAME_M15)
            symbols = [x.strip() for x in str(s["symbols"]).split(",") if x.strip()]

            if len(positions) < int(s["max_open_trades"]):
                for symbol in symbols:
                    if any(p.symbol == symbol for p in positions):
                        continue
                    sig = signal(symbol, tf)
                    if sig != 0:
                        open_trade(symbol, sig, s, acc_info.balance)

            time.sleep(10)
        except Exception as e:
            log("خطأ: " + str(e), "error")
            time.sleep(10)

if __name__ == "__main__":
    main()
