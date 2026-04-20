"""
银价突破监控 - 今日专用
银价 > 80 或 < 79 时立即弹窗提醒
每 5 分钟检查一次，自动在今天结束时退出
"""
import ctypes
import urllib.request
import ssl
import json
import time
from datetime import datetime, date

ALERT_HIGH = 80.0
ALERT_LOW  = 79.0
CHECK_INTERVAL = 30  # 30 秒

def show_popup(title, message):
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x40 | 0x1000)  # 置顶

def fetch_price():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {"User-Agent": "Mozilla/5.0"}

    # 优先 TradingView
    try:
        from tvDatafeed import TvDatafeed, Interval
        tv = TvDatafeed()
        xag = tv.get_hist(symbol='XAGUSD', exchange='OANDA', interval=Interval.in_1_hour, n_bars=1)
        return float(xag['close'].iloc[-1]), "TradingView/OANDA"
    except Exception:
        pass

    # 备用 gold-api.com
    req = urllib.request.Request("https://api.gold-api.com/price/XAG", headers=headers)
    with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
        return json.loads(r.read())["price"], "gold-api.com"

def main():
    today = date.today()
    last_alert_high = False  # 避免重复提醒同一方向
    last_alert_low  = False

    show_popup(
        "银价监控已启动",
        f"监控范围：银价 突破 {ALERT_HIGH} 或 跌破 {ALERT_LOW} USD/盎司\n"
        f"检查频率：每 5 分钟\n"
        f"有效期至今天结束（{today}）"
    )

    while date.today() == today:
        try:
            price, source = fetch_price()
            now = datetime.now().strftime("%H:%M")

            if price > ALERT_HIGH and not last_alert_high:
                show_popup(
                    "🚨 银价突破警报",
                    f"银价已突破 {ALERT_HIGH} USD！\n\n"
                    f"当前价格：{price:.3f} USD / 盎司\n"
                    f"数据来源：{source}\n"
                    f"时间：{now}"
                )
                last_alert_high = True
                last_alert_low  = False  # 重置另一方向

            elif price < ALERT_LOW and not last_alert_low:
                show_popup(
                    "🚨 银价跌破警报",
                    f"银价已跌破 {ALERT_LOW} USD！\n\n"
                    f"当前价格：{price:.3f} USD / 盎司\n"
                    f"数据来源：{source}\n"
                    f"时间：{now}"
                )
                last_alert_low  = True
                last_alert_high = False  # 重置另一方向

            else:
                # 价格回到区间内，重置标志（允许下次再次突破时提醒）
                if ALERT_LOW <= price <= ALERT_HIGH:
                    last_alert_high = False
                    last_alert_low  = False

        except Exception as e:
            # 静默跳过单次失败，连续失败会在下一轮重试
            pass

        time.sleep(CHECK_INTERVAL)

    show_popup("银价监控结束", f"今日（{today}）监控已自动结束。")

if __name__ == "__main__":
    main()
