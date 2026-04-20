"""
Silver (XAG/USD) 回测 - v2
策略：2日涨幅 > 8% 做空（超涨反弹）
止盈：$1.5 / 止损：$1.5 / 最长持仓：5天
手续费：0.5% 往返
时间范围：2020-01-01 至今
"""

import yfinance as yf
import pandas as pd

# ── 参数 ──────────────────────────────────────────────
TICKER        = "SI=F"
START         = "2020-01-01"
END           = "2026-04-15"
GAIN_DAYS     = 2       # 计算涨幅的天数
GAIN_THRESH   = 0.08    # 涨幅触发阈值（8%）
TAKE_PROFIT   = 1.5     # 止盈 ($)
STOP_LOSS     = 1.5     # 止损 ($)
MAX_HOLD_DAYS = 5       # 最长持仓天数，超时平仓
COMMISSION    = 0.005   # 手续费 0.5% 往返
# ─────────────────────────────────────────────────────

def run_backtest():
    print("正在下载数据...")
    df = yf.download(TICKER, start=START, end=END, auto_adjust=True, progress=False)
    if df.empty:
        df = yf.download("XAGUSD=X", start=START, end=END, auto_adjust=True, progress=False)
    if df.empty:
        print("数据下载失败")
        return

    df = df[["High", "Low", "Close"]].copy()
    df.columns = ["High", "Low", "Close"]
    df.dropna(inplace=True)
    print(f"数据范围：{df.index[0].date()} → {df.index[-1].date()}，共 {len(df)} 个交易日")

    # 计算 N 日涨幅
    df["gain_nd"] = df["Close"].pct_change(GAIN_DAYS)

    trades = []
    in_trade = False

    for i in range(GAIN_DAYS + 1, len(df)):
        row  = df.iloc[i]
        date = df.index[i]

        if not in_trade:
            if pd.isna(row["gain_nd"]):
                continue
            # 触发：N日涨幅超过阈值
            if row["gain_nd"] >= GAIN_THRESH:
                entry_price = row["Close"]
                entry_fee   = entry_price * COMMISSION
                entry_date  = date
                entry_idx   = i
                in_trade    = True

        else:
            days_held = i - entry_idx

            hit_tp = row["Low"]  <= entry_price - TAKE_PROFIT
            hit_sl = row["High"] >= entry_price + STOP_LOSS
            timeout = days_held >= MAX_HOLD_DAYS

            if hit_tp:
                exit_price, result = entry_price - TAKE_PROFIT, "止盈"
                gross_pnl = TAKE_PROFIT
            elif hit_sl:
                exit_price, result = entry_price + STOP_LOSS, "止损"
                gross_pnl = -STOP_LOSS
            elif timeout:
                exit_price, result = row["Close"], "超时平仓"
                gross_pnl = entry_price - row["Close"]
            else:
                continue

            exit_fee = exit_price * COMMISSION
            net_pnl  = round(gross_pnl - entry_fee - exit_fee, 3)

            trades.append({
                "入场日":   entry_date.date(),
                "出场日":   date.date(),
                "入场价":   round(entry_price, 3),
                "出场价":   round(exit_price, 3),
                "毛盈亏":   round(gross_pnl, 3),
                "手续费":   round(entry_fee + exit_fee, 3),
                "净盈亏":   net_pnl,
                "结果":     result,
                "持仓天数": days_held,
                "触发涨幅": f"{df.iloc[entry_idx]['gain_nd']*100:.1f}%"
            })
            in_trade = False

    if not trades:
        print("没有触发任何交易信号")
        return

    result_df = pd.DataFrame(trades)

    # ── 统计 ──────────────────────────────────────────
    total     = len(result_df)
    wins      = (result_df["净盈亏"] > 0).sum()
    losses    = (result_df["净盈亏"] < 0).sum()
    neutral   = (result_df["净盈亏"] == 0).sum()
    win_rate  = wins / total * 100
    total_pnl = result_df["净盈亏"].sum()
    total_fee = result_df["手续费"].sum()

    by_result = result_df.groupby("结果")["净盈亏"].agg(["count", "sum", "mean"])

    streak, max_win_streak, max_loss_streak = 0, 0, 0
    prev = None
    for pnl in result_df["净盈亏"]:
        cur = "w" if pnl > 0 else "l"
        if cur == prev:
            streak += 1
        else:
            streak = 1
        if cur == "w":
            max_win_streak = max(max_win_streak, streak)
        else:
            max_loss_streak = max(max_loss_streak, streak)
        prev = cur

    print("\n" + "="*55)
    print(f"  策略：{GAIN_DAYS}日涨幅 >{GAIN_THRESH*100:.0f}% 做空（超涨反弹）")
    print(f"  止盈 ${TAKE_PROFIT}  /  止损 ${STOP_LOSS}  /  最长持仓 {MAX_HOLD_DAYS}天")
    print("="*55)
    print(f"  总交易次数：{total}")
    print(f"  胜率：      {win_rate:.1f}%  ({wins}胜 {losses}负 {neutral}平)")
    print(f"  总净盈亏：  ${total_pnl:.2f}/oz  (手续费合计 ${total_fee:.2f})")
    print(f"  最大连胜：  {max_win_streak} 次")
    print(f"  最大连亏：  {max_loss_streak} 次")
    print("-"*55)
    print("  分类统计：")
    print(by_result.rename(columns={"count":"次数","sum":"合计盈亏","mean":"平均盈亏"}).to_string())
    print("="*55)

    print("\n【所有交易记录】")
    print(result_df.to_string(index=False))

    out_path = "D:/Fire Bro/scripts/silver_backtest_v2_result.csv"
    result_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存至 {out_path}")


if __name__ == "__main__":
    run_backtest()
