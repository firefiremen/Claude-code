"""每日盘前 OI 墙报告：图发邮箱（OI 数据源默认 Yahoo，期权行情可读 TradingView）"""
import argparse
import http.cookiejar
import io
import json
import math
import os
import shutil
import smtplib
import ssl
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Task Scheduler 跑时工作目录是 system32，确保能 import 同目录的 config.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER

TICKERS      = ["NVDA", "GLD", "SLV", "SOXX", "SNDK", "MU"]
N_EXP        = 4        # 取最近 4 个到期日合并 OI
PRICE_RANGE  = 0.20     # 图上只画 spot ± 20% 范围内的 strike
TOP_LABELS   = 3        # 标注 OI 最大的前 3 个 strike
REQUEST_GAP  = 0.6      # 每次请求间隔（秒）
DATA_SOURCE  = "yahoo"  # yahoo / tradingview / auto
TV_EXCHANGE  = "NASDAQ"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_session = {"opener": None, "crumb": None}


def _build_opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx),
    )
    opener.addheaders = [
        ("User-Agent", UA),
        ("Accept", "application/json,text/plain,*/*"),
        ("Accept-Language", "en-US,en;q=0.9"),
        ("Connection", "close"),
    ]
    return opener


def yahoo_session():
    """惰性建立 Yahoo 会话（cookie + crumb）。"""
    if _session["opener"] is not None and _session["crumb"]:
        return _session["opener"], _session["crumb"]

    opener = _build_opener()
    # 拿 A3 cookie；fc.yahoo.com 通常返回 404，但 cookie 已经下来了
    try:
        opener.open("https://fc.yahoo.com", timeout=15).read()
    except urllib.error.HTTPError:
        pass
    with opener.open("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=15) as r:
        crumb = r.read().decode().strip()
    if not crumb:
        raise RuntimeError("Yahoo crumb 为空")
    _session["opener"] = opener
    _session["crumb"]  = crumb
    return opener, crumb


def yahoo_get(url):
    """带重试的 GET，crumb 失效时刷新一次。"""
    last_err = None
    for attempt in range(3):
        try:
            opener, _ = yahoo_session()
            with opener.open(url, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (401, 403):
                _session["opener"] = None
                _session["crumb"]  = None
            time.sleep(1.5)
        except Exception as e:
            last_err = e
            time.sleep(1.5)
    raise last_err


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _pick(row, *names):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def tradingview_cmd(*args):
    """运行 opencli TradingView，只读拉取行情。"""
    if not shutil.which("opencli"):
        raise RuntimeError("opencli 未安装，无法读取 TradingView")
    cmd = ["opencli", "tradingview", *args, "-f", "json"]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


def fetch_tradingview_quote(symbol, exchange=TV_EXCHANGE):
    rows = tradingview_cmd("quote", "--ticker", symbol, "--exchange", exchange)
    if not rows:
        raise RuntimeError(f"{symbol} TradingView quote 为空")
    row = rows[0]
    spot = _to_float(row.get("close"))
    if spot is None:
        raise RuntimeError(f"{symbol} TradingView quote 无 close 字段")
    return spot, row


def fetch_tradingview_oi(symbol, exchange=TV_EXCHANGE):
    """从 TradingView 期权链提取 OI；若当前 opencli 字段无 OI，会抛出明确错误。"""
    spot, quote = fetch_tradingview_quote(symbol, exchange)
    rows = tradingview_cmd("options-chain", "--ticker", symbol, "--exchange", exchange)

    call_oi = defaultdict(int)
    put_oi = defaultdict(int)
    exp_seen = []
    for row in rows:
        expiry = row.get("expiry")
        if expiry not in exp_seen:
            exp_seen.append(expiry)
        if expiry not in exp_seen[:N_EXP]:
            continue

        strike = _to_float(row.get("strike"))
        oi = _to_int(_pick(row, "openInterest", "open_interest", "oi", "OI"))
        opt_type = str(row.get("type", "")).lower()
        if strike is None or oi is None or oi <= 0:
            continue
        if opt_type == "call":
            call_oi[strike] += oi
        elif opt_type == "put":
            put_oi[strike] += oi

    if not call_oi and not put_oi:
        sample_fields = ", ".join(rows[0].keys()) if rows else "no rows"
        raise RuntimeError(
            f"{symbol} TradingView 期权链未返回 OI 字段；可用字段: {sample_fields}"
        )

    lo, hi = spot * (1 - PRICE_RANGE), spot * (1 + PRICE_RANGE)
    call_oi = {k: v for k, v in call_oi.items() if lo <= k <= hi and v > 0}
    put_oi = {k: v for k, v in put_oi.items() if lo <= k <= hi and v > 0}
    return spot, call_oi, put_oi, quote


def fetch_yahoo_oi(symbol):
    """从 Yahoo 拉期权链，按 N_EXP 个到期日合并 OI。返回 (spot, call_oi, put_oi)。"""
    _, crumb = yahoo_session()
    base = f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}"
    first = yahoo_get(f"{base}?crumb={urllib.parse.quote(crumb)}")
    res = first["optionChain"]["result"][0]
    q = res["quote"]
    spot = (q.get("regularMarketPrice")
            or q.get("preMarketPrice")
            or q.get("postMarketPrice"))
    if spot is None:
        raise RuntimeError(f"{symbol} 无法获取现价")

    exp_ts_list = res.get("expirationDates", [])[:N_EXP]
    today = datetime.now().date()

    call_oi = defaultdict(int)
    put_oi  = defaultdict(int)

    def absorb(blocks):
        for blk in blocks:
            for c in blk.get("calls", []):
                call_oi[float(c["strike"])] += int(c.get("openInterest") or 0)
            for p in blk.get("puts", []):
                put_oi[float(p["strike"])] += int(p.get("openInterest") or 0)

    # 第一次响应里通常已经带了第一个到期的 calls/puts
    absorb(res.get("options", []))
    seen_first = bool(res.get("options"))

    for i, ts in enumerate(exp_ts_list):
        exp_date = datetime.fromtimestamp(ts, timezone.utc).date()
        if exp_date < today:
            continue
        if i == 0 and seen_first:
            continue
        time.sleep(REQUEST_GAP)
        d = yahoo_get(f"{base}?date={ts}&crumb={urllib.parse.quote(crumb)}")
        absorb(d["optionChain"]["result"][0].get("options", []))

    lo, hi = spot * (1 - PRICE_RANGE), spot * (1 + PRICE_RANGE)
    call_oi = {k: v for k, v in call_oi.items() if lo <= k <= hi and v > 0}
    put_oi  = {k: v for k, v in put_oi.items()  if lo <= k <= hi and v > 0}
    return spot, call_oi, put_oi


def fetch_oi(symbol, source=DATA_SOURCE):
    """按数据源拉 OI。auto 会先尝试 TradingView OI，缺字段时回退 Yahoo。"""
    if source == "yahoo":
        spot, call_oi, put_oi = fetch_yahoo_oi(symbol)
        return spot, call_oi, put_oi, "Yahoo"

    if source == "tradingview":
        spot, call_oi, put_oi, _ = fetch_tradingview_oi(symbol)
        return spot, call_oi, put_oi, "TradingView"

    try:
        spot, call_oi, put_oi, _ = fetch_tradingview_oi(symbol)
        return spot, call_oi, put_oi, "TradingView"
    except Exception as tv_err:
        spot, call_oi, put_oi = fetch_yahoo_oi(symbol)
        return spot, call_oi, put_oi, f"Yahoo (TV fallback: {tv_err})"


def top_n(d, n=TOP_LABELS):
    return sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]


def plot_one(ax, symbol, spot, call_oi, put_oi, source_name):
    all_strikes = sorted(set(call_oi) | set(put_oi))
    if not all_strikes:
        ax.text(0.5, 0.5, f"{symbol} no data", ha="center", transform=ax.transAxes)
        return

    width = (max(all_strikes) - min(all_strikes)) / max(len(all_strikes), 1) * 0.8
    call_vals = [call_oi.get(s, 0) for s in all_strikes]
    put_vals  = [-put_oi.get(s, 0) for s in all_strikes]

    ax.bar(all_strikes, call_vals, color="#9b6dff", label="Call OI", width=width)
    ax.bar(all_strikes, put_vals,  color="#5dd39e", label="Put OI",  width=width)
    ax.axvline(spot, color="#22d3ee", linestyle="--", linewidth=1.4)
    ax.axhline(0, color="white", linewidth=0.6)

    for s, v in top_n(call_oi):
        ax.annotate(f"{s:g}", xy=(s, v), xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=8, color="#c4a8ff")
    for s, v in top_n(put_oi):
        ax.annotate(f"{s:g}", xy=(s, -v), xytext=(0, -11), textcoords="offset points",
                    ha="center", fontsize=8, color="#86e0b8")

    ax.set_title(f"{symbol}  spot={spot:.2f}  [{source_name.split(' (')[0]}]", fontsize=11)
    ax.set_xlabel("Strike")
    ax.set_ylabel("OI  (Call up / Put down)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.2)


def build_report(tickers=None, source=DATA_SOURCE):
    tickers = tickers or TICKERS
    plt.style.use("dark_background")
    ncols = 2
    nrows = math.ceil(len(tickers) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(16, 5 * nrows))
    axes_flat = axes.flat if hasattr(axes, "flat") else [axes]
    summary_lines = []

    for ax, sym in zip(axes_flat, tickers):
        try:
            spot, call_oi, put_oi, source_name = fetch_oi(sym, source)
            plot_one(ax, sym, spot, call_oi, put_oi, source_name)
            top_c = ", ".join(f"{k:g}({int(v):,})" for k, v in top_n(call_oi))
            top_p = ", ".join(f"{k:g}({int(v):,})" for k, v in top_n(put_oi))
            summary_lines.append(
                f"{sym}  spot={spot:.2f}  source={source_name}\n"
                f"  Call OI 墙: {top_c}\n  Put  OI 墙: {top_p}"
            )
        except Exception as e:
            ax.text(0.5, 0.5, f"{sym} ERROR\n{e}", ha="center",
                    transform=ax.transAxes, color="red")
            summary_lines.append(f"{sym}: failed - {e}")
            traceback.print_exc()
        time.sleep(REQUEST_GAP)

    for ax in list(axes_flat)[len(tickers):]:
        ax.axis("off")

    fig.suptitle(f"OI Wall Report  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                 fontsize=14, y=0.995)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf, "\n\n".join(summary_lines)


def send_email(image_buf, summary_text):
    msg = MIMEMultipart()
    msg["Subject"] = f"[OI 墙] {datetime.now().strftime('%Y-%m-%d')} {'/'.join(TICKERS)}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECEIVER

    body = MIMEText(
        summary_text + "\n\n（图见附件，紫色 Call OI 朝上，绿色 Put OI 朝下，青色虚线为现价）",
        "plain", "utf-8"
    )
    msg.attach(body)

    img = MIMEImage(image_buf.read(), name="oi_wall.png")
    img.add_header("Content-Disposition", "attachment", filename="oi_wall.png")
    msg.attach(img)

    with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
        s.login(EMAIL_SENDER, EMAIL_PASSWORD)
        s.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
    print(f"[邮件] 已发送至 {EMAIL_RECEIVER}")


def parse_args():
    parser = argparse.ArgumentParser(description="Build and email an OI wall report.")
    parser.add_argument(
        "--tickers",
        default=",".join(TICKERS),
        help="Comma-separated tickers. Default: %(default)s",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "yahoo", "tradingview"),
        default=DATA_SOURCE,
        help="OI data source. TradingView currently depends on whether opencli returns OI fields.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print report without sending email.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        args = parse_args()
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        buf, summary = build_report(tickers=tickers, source=args.source)
        print(summary)
        if args.dry_run:
            print("[dry-run] 未发送邮件")
        else:
            send_email(buf, summary)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
