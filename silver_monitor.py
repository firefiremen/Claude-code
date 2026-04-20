import ctypes
import urllib.request
import ssl
import json
import time
from datetime import datetime

# ========== 配置 ==========
TARGET_HIGH = 80.0        # 上方目标价（涨到提醒）
TARGET_LOW  = 79.0        # 下方目标价（跌到提醒）
CHECK_INTERVAL = 60       # 检测间隔（秒）
# ==========================

def fetch_silver_price():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json"}
    for attempt in range(3):
        try:
            req = urllib.request.Request("https://api.gold-api.com/price/XAG", headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                return json.loads(r.read())["price"]
        except Exception:
            if attempt < 2:
                time.sleep(5)
    raise Exception("gold-api.com 连续3次失败")

def show_alert(price, direction):
    if direction == "up":
        title = "银价突破上方目标！"
        detail = f"突破 ↑{TARGET_HIGH} USD"
    else:
        title = "银价跌破下方目标！"
        detail = f"跌破 ↓{TARGET_LOW} USD"
    msg = (
        f"{detail}\n\n"
        f"当前价：{price:.3f} USD\n"
        f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    ctypes.windll.user32.MessageBoxW(0, msg, title, 0x40 | 0x1000)

print(f"银价监测启动 | 上方目标：≥{TARGET_HIGH}  下方目标：≤{TARGET_LOW} | 间隔：{CHECK_INTERVAL}秒")
print("按 Ctrl+C 停止\n")

alerted_high = False
alerted_low  = False
while True:
    try:
        price = fetch_silver_price()
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] 银价：{price:.3f} USD  区间：↓{TARGET_LOW} ~ ↑{TARGET_HIGH}")

        if price >= TARGET_HIGH and not alerted_high:
            show_alert(price, "up")
            alerted_high = True
            print(">>> 上方目标触发！")

        if price <= TARGET_LOW and not alerted_low:
            show_alert(price, "down")
            alerted_low = True
            print(">>> 下方目标触发！")

        # 价格回到区间内重置
        if alerted_high and price < TARGET_HIGH - 0.3:
            alerted_high = False
            print(">>> 上方提醒重置")
        if alerted_low and price > TARGET_LOW + 0.3:
            alerted_low = False
            print(">>> 下方提醒重置")

        time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        print("\n监测已停止")
        break
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 请求失败：{e}，30秒后重试")
        time.sleep(30)
