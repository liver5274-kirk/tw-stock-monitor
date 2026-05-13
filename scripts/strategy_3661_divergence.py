#!/usr/bin/env python3
"""
3661 世芯-KY 背離交易策略 v1
只在「五檔掛單極空 + 價格近高點」背離被打破時做多

進場條件（全部滿足）：
  A. 背離持續 ≥ 120 秒（買賣比 < 0.5 + 價格 > 日高 97% + 賣盤 ≥ 15 張）
  B. 賣盤瞬間蒸發 ≥ 30 張，且剩餘賣盤 < 20 張（確認不是假抽單）
  C. 抽單後 30 秒內，價格不跌破背離區間最低價

出場條件（任一觸發）：
  - 移動止損：從持倉最高點回檔 1.5%
  - 固定止盈：+5%
  - 買賣比翻多（>1.5）且獲利 > 0.5%
  - 尾盤 13:25 強制平倉

用法：
  python3 strategy_3661_divergence.py [--backtest] [--live]
"""

import csv
import os
import sys
from datetime import datetime, time

# ── 參數設定 ──
CSV_DIR = "/mnt/c/Temp/財經分析2026"
STOCK_ID = "3661"

# 進場參數
DIVERGENCE_MIN_SEC = 120     # 背離至少持續秒數
RATIO_BEARISH_MAX = 0.5      # 買賣比多低算極空
NEAR_HIGH_PCT = 0.97         # 價格在日高幾%內
ASK_MIN = 15                 # 賣盤至少幾張
EVAPORATE_MIN = 30           # 蒸發至少幾張
ASK_REMAIN_MAX = 20          # 蒸發後剩餘賣盤上限
PRICE_CONFIRM_SEC = 30       # 抽單後觀察秒數

# 出場參數
TRAILING_STOP_PCT = 1.5      # 移動止損%
TAKE_PROFIT_PCT = 5.0        # 固定止盈%
RATIO_BULLISH_MIN = 1.5      # 買賣比翻多門檻


class DivergenceStrategy:
    def __init__(self):
        self.position = None      # {"entry_p": float, "entry_t": str, "high_p": float}
        self.divergence_start = None
        self.divergence_low = None
        self.evaporate_time = None
        self.trades = []
        self.day_high = 0

    def update_day_high(self, h):
        if h > self.day_high:
            self.day_high = h

    def is_divergence(self, d):
        """Condition A: 背離"""
        if d["p"] is None or d["p"] <= 0:
            return False
        return (
            d["r"] > 0 and d["r"] < RATIO_BEARISH_MAX
            and d["ask"] >= ASK_MIN
            and d["p"] >= self.day_high * NEAR_HIGH_PCT
        )

    def check_entry(self, d, i, data):
        """Check if entry conditions are met"""
        if self.position is not None:
            return

        # Track divergence duration
        if self.is_divergence(d):
            if self.divergence_start is None:
                self.divergence_start = i
                self.divergence_low = d["p"]
            else:
                if d["p"] < self.divergence_low:
                    self.divergence_low = d["p"]
        else:
            self.divergence_start = None
            self.divergence_low = None
            self.evaporate_time = None
            return

        # Check duration
        duration_sec = (i - self.divergence_start) * 3  # ~3 sec per row
        if duration_sec < DIVERGENCE_MIN_SEC:
            return

        # Check evaporate (Condition B)
        if i == 0:
            return
        prev = data[i - 1]
        drop = prev.get("ask", 0) - d["ask"]
        if drop >= EVAPORATE_MIN and d["ask"] <= ASK_REMAIN_MAX:
            # 抽單訊號出現，記錄時間開始觀察
            if self.evaporate_time is None:
                self.evaporate_time = i
            return

        # Price confirmation (Condition C)
        if self.evaporate_time is not None:
            confirm_sec = (i - self.evaporate_time) * 3
            if confirm_sec >= PRICE_CONFIRM_SEC:
                # Check if price held above divergence low
                if d["p"] is not None and d["p"] >= self.divergence_low:
                    # ENTRY!
                    self.position = {
                        "entry_p": d["p"],
                        "entry_t": d["t"],
                        "high_p": d["p"],
                    }
                    self.divergence_start = None
                    self.divergence_low = None
                    self.evaporate_time = None
                    return True
                else:
                    # Failed confirmation, reset
                    self.evaporate_time = None

        return False

    def check_exit(self, d):
        """Check exit conditions, return (exit, reason)"""
        if self.position is None:
            return False, ""

        p = d["p"]
        if p is None or p <= 0:
            return False, ""

        # Update trailing high
        if p > self.position["high_p"]:
            self.position["high_p"] = p

        pnl_pct = (p - self.position["entry_p"]) / self.position["entry_p"] * 100
        trail_drop = (self.position["high_p"] - p) / self.position["high_p"] * 100

        # 移動止損
        if trail_drop >= TRAILING_STOP_PCT and pnl_pct > 0:
            return True, f"移動止損 (高點 {self.position['high_p']:.0f} → {p:.0f}, 回檔 {trail_drop:.1f}%)"

        # 固定止損
        if pnl_pct <= -2.0:
            return True, f"止損 -2%"

        # 固定止盈
        if pnl_pct >= TAKE_PROFIT_PCT:
            return True, f"止盈 +{pnl_pct:.1f}%"

        # 買賣比翻多
        if d["r"] > RATIO_BULLISH_MIN and pnl_pct > 0.5:
            return True, f"買賣比翻多 ({d['r']:.1f}x)"

        # 尾盤強制平倉
        t = datetime.strptime(d["t"], "%H:%M:%S").time()
        if t >= time(13, 25):
            return True, f"尾盤平倉"

        return False, ""

    def exit_position(self, d, reason):
        pnl = (d["p"] - self.position["entry_p"]) / self.position["entry_p"] * 100
        self.trades.append({
            "entry_t": self.position["entry_t"],
            "entry_p": self.position["entry_p"],
            "exit_t": d["t"],
            "exit_p": d["p"],
            "pnl_pct": pnl,
            "reason": reason,
        })
        self.position = None


def load_data(date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    path = os.path.join(CSV_DIR, f"{date_str}_3661.csv")
    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    data = []
    for r in rows[1:]:
        try:
            p = float(r[2]) if r[2] and r[2] != "-" else None
            data.append({
                "t": r[1],
                "p": p,
                "h": float(r[5]) if r[5] else 0,
                "l": float(r[6]) if r[6] else 0,
                "bid": int(float(r[27])) if r[27] else 0,
                "ask": int(float(r[28])) if r[28] else 0,
                "r": float(r[29]) if r[29] else 0,
            })
        except (ValueError, IndexError):
            continue

    # Forward-fill price
    last_p = None
    for d in data:
        if d["p"] is not None:
            last_p = d["p"]
        else:
            d["p"] = last_p

    return data


def backtest(data):
    strat = DivergenceStrategy()

    # First pass: find day high
    for d in data:
        strat.update_day_high(d["h"])

    # Second pass: run strategy
    for i, d in enumerate(data):
        strat.check_entry(d, i, data)
        if strat.position:
            exit_trigger, reason = strat.check_exit(d)
            if exit_trigger:
                strat.exit_position(d, reason)

    return strat


def print_report(strat):
    print(f"📊 3661 背離策略回測 — 日高 {strat.day_high:.0f}")
    print("=" * 60)
    print(f"進場規則: 背離≥{DIVERGENCE_MIN_SEC}s + 抽單≥{EVAPORATE_MIN}張 + 價格確認{PRICE_CONFIRM_SEC}s")
    print(f"出場規則: 移動止損{TRAILING_STOP_PCT}% / 止盈{TAKE_PROFIT_PCT}% / 買賣比翻多 / 13:25平倉")
    print()

    if not strat.trades:
        print("📭 今日無符合條件的交易訊號")
        return

    total_pnl = 0
    wins = 0
    for i, t in enumerate(strat.trades, 1):
        emoji = "🟢" if t["pnl_pct"] > 0 else "🔴"
        total_pnl += t["pnl_pct"]
        if t["pnl_pct"] > 0:
            wins += 1
        print(f"{emoji} 交易 #{i}")
        print(f"   買入: {t['entry_t']} @ {t['entry_p']:.0f}")
        print(f"   賣出: {t['exit_t']} @ {t['exit_p']:.0f}")
        print(f"   損益: {t['pnl_pct']:+.2f}%  原因: {t['reason']}")
        print()

    print(f"總交易: {len(strat.trades)} 筆")
    print(f"總損益: {total_pnl:+.2f}%")
    print(f"勝率:   {wins/len(strat.trades)*100:.0f}%")
    if strat.trades:
        avg_win = sum(t["pnl_pct"] for t in strat.trades if t["pnl_pct"] > 0)
        avg_loss = sum(t["pnl_pct"] for t in strat.trades if t["pnl_pct"] < 0)
        n_win = sum(1 for t in strat.trades if t["pnl_pct"] > 0)
        n_loss = sum(1 for t in strat.trades if t["pnl_pct"] < 0)
        if n_win > 0:
            print(f"平均獲利: +{avg_win/n_win:.2f}%")
        if n_loss > 0:
            print(f"平均虧損: {avg_loss/n_loss:.2f}%")


def live_check():
    """檢查當前是否有背離訊號（盤中即時用）
    只在偵測到背離時輸出（cron no_agent 模式：有 stdout 才會推送到 Telegram）
    """
    data = load_data()
    if not data:
        return  # 無資料，安靜退出

    strat = DivergenceStrategy()
    for d in data:
        strat.update_day_high(d["h"])

    # Check last N rows for current state
    recent = data[-40:]  # last ~2 min
    diverging = False
    div_count = 0
    for d in recent:
        if strat.is_divergence(d):
            diverging = True
            div_count += 1

    # 只有偵測到背離才輸出 → Telegram 才會收到通知
    if not diverging:
        return

    last = data[-1]
    print(f"🕵️ 3661 背離警報 [{last['t']}]")
    print("-" * 40)
    print(f"價格: {last['p']:.0f}" if last["p"] else "價格: -")
    print(f"日高: {strat.day_high:.0f}")
    print(f"買賣比: {last['r']:.2f}")
    print(f"買盤: {last['bid']} 張 / 賣盤: {last['ask']} 張")
    print(f"\n⚠ 偵測到背離訊號！(最近 {div_count} 筆符合)")
    print(f"  買賣比 < {RATIO_BEARISH_MAX} + 價格 > 日高 {NEAR_HIGH_PCT*100:.0f}% + 賣盤 ≥ {ASK_MIN}")
    print(f"  等待抽單確認...")


if __name__ == "__main__":
    if "--backtest" in sys.argv:
        data = load_data()
        if data:
            strat = backtest(data)
            print_report(strat)
        else:
            print("📭 無今日資料")
    else:
        live_check()
