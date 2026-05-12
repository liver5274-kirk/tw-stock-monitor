#!/usr/bin/env python3
"""
3661 世芯-KY 煙霧彈偵測器 (GitHub Actions 版)
直接從 twstock API 抓取即時資料，兩次快照比對
替代原本讀 CSV 的版本，適合在 GitHub Actions 獨立運行
"""
import sys
import time
import twstock
from datetime import datetime, time as dtime
from telegram_utils import send_message, format_escape

CODE = "3661"
SNAPSHOT_INTERVAL = 12  # 兩次快照間隔秒數
TRADING_START = dtime(9, 0)
TRADING_END = dtime(13, 30)

# 閾值
THRESH = {
    "ask_spike_ratio": 1.5,
    "ask_spike_min": 15,
    "evaporate_min": 15,
    "evaporate_vol_ratio": 0.5,
    "ratio_bearish": 0.3,
    "near_high_pct": 0.98,
    "round_vol_min": 10,
}


def is_trading_time():
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return TRADING_START <= now.time() <= TRADING_END


def fetch_snapshot():
    """抓取 twstock 即時資料，回傳 dict"""
    data = twstock.realtime.get(CODE)
    if not data or not data.get("success"):
        return None

    rt = data["realtime"]

    def _p(v):
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _v(v):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return 0

    bids_p = rt.get("best_bid_price", [])[:5]
    bids_v = rt.get("best_bid_volume", [])[:5]
    asks_p = rt.get("best_ask_price", [])[:5]
    asks_v = rt.get("best_ask_volume", [])[:5]

    bid_total = sum(_v(bids_v[i]) if i < len(bids_v) else 0 for i in range(5))
    ask_total = sum(_v(asks_v[i]) if i < len(asks_v) else 0 for i in range(5))

    return {
        "time": data["info"].get("time", datetime.now().strftime("%H:%M:%S")),
        "price": _p(rt.get("latest_trade_price", "-")),
        "high": _p(rt.get("high", "-")),
        "low": _p(rt.get("low", "-")),
        "vol": _v(rt.get("accumulate_trade_volume", 0)),
        "bid_total": bid_total,
        "ask_total": ask_total,
        "ratio": bid_total / ask_total if ask_total > 0 else 0,
        "asks": [(_p(asks_p[i]) if i < len(asks_p) else None,
                   _v(asks_v[i]) if i < len(asks_v) else 0) for i in range(5)],
    }


def detect(prev, curr):
    """比對兩次快照，回傳警報清單"""
    alerts = []

    if not prev or not curr:
        return alerts

    # 訊號 1: 賣盤暴增 + 價格不跌
    if prev["ask_total"] > 0:
        spike = curr["ask_total"] / prev["ask_total"]
        if spike >= THRESH["ask_spike_ratio"] and curr["ask_total"] >= THRESH["ask_spike_min"]:
            price_dropped = (
                prev["price"] and curr["price"] and curr["price"] < prev["price"]
            )
            if not price_dropped:
                alerts.append(
                    f"🔥 [假賣壓] {curr['time']} 賣盤 {prev['ask_total']}→{curr['ask_total']} "
                    f"暴增 {spike:.1f}x，價格未跌 → 假賣壓"
                )

    # 訊號 2: 賣盤瞬間蒸發（抽單）
    drop = prev["ask_total"] - curr["ask_total"]
    if drop >= THRESH["evaporate_min"]:
        vol_delta = curr["vol"] - prev["vol"]
        if vol_delta < drop * THRESH["evaporate_vol_ratio"]:
            alerts.append(
                f"🚨 [抽單] {curr['time']} 賣盤 {prev['ask_total']}→{curr['ask_total']} "
                f"蒸發 {drop} 張，成交僅增 {vol_delta} 張 → 抽單！"
            )

    # 訊號 3: 買賣比極空 + 價格近高點
    if curr["high"] and curr["high"] > 0 and curr["price"]:
        near_high = curr["high"] * THRESH["near_high_pct"]
        if (0 < curr["ratio"] < THRESH["ratio_bearish"]
                and curr["ask_total"] >= THRESH["ask_spike_min"]
                and curr["price"] >= near_high):
            alerts.append(
                f"⚠ [背離] {curr['time']} 買賣比 {curr['ratio']:.2f} (極空)  "
                f"日高 {curr['high']:.0f} 賣盤 {curr['ask_total']} 張 → 極空但價近高！"
            )

    return alerts


def main():
    if not is_trading_time():
        return  # 非交易時間，安靜退出

    # 第一次快照
    s1 = fetch_snapshot()
    if not s1:
        print("[smoke] 無法取得第一次 twstock 資料")
        return

    # 等待後第二次快照
    time.sleep(SNAPSHOT_INTERVAL)

    s2 = fetch_snapshot()
    if not s2:
        print("[smoke] 無法取得第二次 twstock 資料")
        return

    alerts = detect(s1, s2)

    if not alerts:
        return  # 無訊號，安靜退出

    now = datetime.now().strftime("%H:%M:%S")
    msg = f"🕵️ <b>3661 世芯-KY 煙霧彈偵測</b> [{now}]\n"
    msg += "━" * 30 + "\n"
    for a in alerts:
        msg += format_escape(a) + "\n"

    send_message(msg)


if __name__ == "__main__":
    main()
