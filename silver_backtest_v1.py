"""
Silver (XAG/USD) 回测 - v1
策略：5日高点回撤 $1 做空
止盈：$3 / 止损：$1.5
时间范围：2020-01-01 至今
"""

import yfinance as yf
import pandas as pd
#测试

# ── 参数 ──────────────────────────────────────────────
TICKER       = "SI=F"      # 银期货（与伦敦银走势一致）
START        = "2020-01-01"
END          = "2026-04-15"
HIGH_WINDOW  = 5           # N日高点窗口
ENTRY_DROP   = 1.0         # 从高点回撤多少触发开空 ($)
TAKE_PROFIT  = 3.0         # 止盈 ($)
STOP_LOSS    = 1.5         # 止损 ($)
# ─────────────────────────────────────────────────────

def run_backtest():
    print("正在下载数据...")
    df = yf.download(TICKER, start=START, end=END, auto_adjust=True, progress=False)

    if df.empty:
        print("数据下载失败，尝试备用 ticker XAGUSD=X")
        df = yf.download("XAGUSD=X", start=START, end=END, auto_adjust=True, progress=False)

    if df.empty:
        print("数据下载失败，请检查网络")
        return

    df = df[["High", "Low", "Close"]].copy()
    df.columns = ["High", "Low", "Close"]
    df.dropna(inplace=True)
    print(f"数据范围：{df.index[0].date()} → {df.index[-1].date()}，共 {len(df)} 个交易日")

    # 计算 N 日滚动高点（不含当日）
    df["roll_high"] = df["High"].shift(1).rolling(HIGH_WINDOW).max()

    trades = []
    in_trade = False

    for i in range(HIGH_WINDOW + 1, len(df)):
        row = df.iloc[i]
        date = df.index[i]

        if not in_trade:
            roll_high = row["roll_high"]
            if pd.isna(roll_high):
                continue
            # 触发条件：当日收盘 <= 近N日高点 - $1
            if row["Close"] <= roll_high - ENTRY_DROP:
                entry_price = row["Close"]
                entry_date  = date
                in_trade    = True

        else:
            # 止盈：价格继续下跌 $TP
            if row["Low"] <= entry_price - TAKE_PROFIT:
                exit_price = entry_price - TAKE_PROFIT
                pnl = TAKE_PROFIT
                result = "止盈"
                trades.append({
                    "入场日": entry_date.date(),
                    "出场日": date.date(),
                    "入场价": round(entry_price, 3),
                    "出场价": round(exit_price, 3),
                    "盈亏":   round(pnl, 3),
                    "结果":   result,
                    "持仓天数": (date - entry_date).days
                })
                in_trade = False

            # 止损：价格反弹 $SL
            elif row["High"] >= entry_price + STOP_LOSS:
                exit_price = entry_price + STOP_LOSS
                pnl = -STOP_LOSS
                result = "止损"
                trades.append({
                    "入场日": entry_date.date(),
                    "出场日": date.date(),
                    "入场价": round(entry_price, 3),
                    "出场价": round(exit_price, 3),
                    "盈亏":   round(pnl, 3),
                    "结果":   result,
                    "持仓天数": (date - entry_date).days
                })
                in_trade = False

    if not trades:
        print("没有触发任何交易信号")
        return

    result_df = pd.DataFrame(trades)

    # ── 统计 ──────────────────────────────────────────
    total      = len(result_df)
    wins       = (result_df["盈亏"] > 0).sum()
    losses     = (result_df["盈亏"] < 0).sum()
    win_rate   = wins / total * 100
    total_pnl  = result_df["盈亏"].sum()
    avg_win    = result_df[result_df["盈亏"] > 0]["盈亏"].mean()
    avg_loss   = result_df[result_df["盈亏"] < 0]["盈亏"].mean()
    max_streak_loss = 0
    streak = 0
    for pnl in result_df["盈亏"]:
        if pnl < 0:
            streak += 1
            max_streak_loss = max(max_streak_loss, streak)
        else:
            streak = 0

    print("\n" + "="*50)
    print(f"  策略：{HIGH_WINDOW}日高点回撤 ${ENTRY_DROP} 做空")
    print(f"  止盈 ${TAKE_PROFIT}  /  止损 ${STOP_LOSS}  (盈亏比 {TAKE_PROFIT/STOP_LOSS:.1f}:1)")
    print("="*50)
    print(f"  总交易次数：{total}")
    print(f"  胜率：      {win_rate:.1f}%  ({wins}胜 {losses}负)")
    print(f"  总盈亏：    ${total_pnl:.2f}/oz")
    print(f"  平均盈利：  ${avg_win:.2f}")
    print(f"  平均亏损：  ${avg_loss:.2f}")
    print(f"  最大连亏：  {max_streak_loss} 次")
    print("="*50)

    print("\n【所有交易记录】")
    print(result_df.to_string(index=False))

    # 保存结果
    out_path = "D:/Fire Bro/scripts/silver_backtest_v1_result.csv"
    result_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存至 {out_path}")


if __name__ == "__main__":
    run_backtest()
