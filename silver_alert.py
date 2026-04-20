import ctypes
import urllib.request
import ssl
import json
import time
from datetime import datetime

# 金银比历史参考区间
RATIO_HIGH = 90
RATIO_LOW  = 50

# 银价突破提醒阈值
SILVER_ALERT_HIGH = 80.0
SILVER_ALERT_LOW  = 78.0

# 突破提醒冷却时间（秒），避免同一方向反复弹窗
ALERT_COOLDOWN = 1800  # 30 分钟

# 常规报价间隔（秒）
HOURLY_INTERVAL = 3600

# 价格检查间隔（秒）
CHECK_INTERVAL = 60


def fetch_from_tradingview():
    from tvDatafeed import TvDatafeed, Interval
    tv = TvDatafeed()
    xag = tv.get_hist(symbol='XAGUSD', exchange='OANDA', interval=Interval.in_1_hour, n_bars=1)
    xau = tv.get_hist(symbol='XAUUSD', exchange='OANDA', interval=Interval.in_1_hour, n_bars=1)
    return float(xag['close'].iloc[-1]), float(xau['close'].iloc[-1]), "TradingView / OANDA"


def fetch_from_goldapi():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {"User-Agent": "Mozilla/5.0"}
    def get(symbol):
        req = urllib.request.Request(f"https://api.gold-api.com/price/{symbol}", headers=headers)
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            return json.loads(r.read())["price"]
    return get("XAG"), get("XAU"), "gold-api.com"


def fetch_price():
    for fetcher in [fetch_from_tradingview, fetch_from_goldapi]:
        try:
            return fetcher()
        except Exception:
            pass
    return None, None, None


def ratio_signal(ratio):
    if ratio >= RATIO_HIGH:
        return f"⚠️ 偏高（>{RATIO_HIGH}）：历史上银相对低估，有均值回归机会"
    elif ratio <= RATIO_LOW:
        return f"⚠️ 偏低（<{RATIO_LOW}）：银相对高估，需谨慎追涨"
    else:
        return f"正常区间（{RATIO_LOW}~{RATIO_HIGH}）：无明显异动"


def show_popup(title, message, icon=0x40):
    ctypes.windll.user32.MessageBoxW(0, message, title, icon)


def show_regular_report(silver, gold, source):
    ratio = gold / silver
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = (
        f"现货银价：{silver:.3f} USD / 盎司\n"
        f"现货金价：{gold:.2f} USD / 盎司\n"
        f"\n"
        f"金银比：{ratio:.1f}\n"
        f"{ratio_signal(ratio)}\n"
        f"\n"
        f"数据来源：{source}\n"
        f"时间：{now}"
    )
    show_popup("贵金属价格提醒", msg)


if __name__ == "__main__":
    last_hourly = 0.0
    last_alert_high = 0.0
    last_alert_low = 0.0

    while True:
        now_ts = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        silver, gold, source = fetch_price()

        if silver is not None:
            # 突破提醒（带冷却）
            if silver >= SILVER_ALERT_HIGH and (now_ts - last_alert_high) > ALERT_COOLDOWN:
                show_popup(
                    "🚨 银价突破提醒",
                    f"⚡ 银价突破 ${SILVER_ALERT_HIGH}！\n当前：{silver:.3f} USD / 盎司\n时间：{now_str}",
                    0x30
                )
                last_alert_high = now_ts

            elif silver < SILVER_ALERT_LOW and (now_ts - last_alert_low) > ALERT_COOLDOWN:
                show_popup(
                    "🚨 银价跌破提醒",
                    f"⚡ 银价跌破 ${SILVER_ALERT_LOW}！\n当前：{silver:.3f} USD / 盎司\n时间：{now_str}",
                    0x30
                )
                last_alert_low = now_ts

            # 每小时常规报价
            if (now_ts - last_hourly) >= HOURLY_INTERVAL:
                show_regular_report(silver, gold, source)
                last_hourly = now_ts

        time.sleep(CHECK_INTERVAL)
