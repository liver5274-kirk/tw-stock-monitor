#!/usr/bin/env python3
"""
3661 世芯-KY 五檔掛單即時監控 + 當沖分析欄位
每 3 秒抓一次，寫入 CSV（累積模式）
路徑: C:/Temp/財經分析2026/{日期}_3661.csv

cron 每分鐘觸發一次，腳本內循環 55 秒，每 3 秒取一筆（≈18 筆/分）
"""

import twstock
import csv
import os
import sys
import time as _time
from datetime import datetime, time

STOCK_ID = "3661"
INTERVAL = 3
LOOP_DURATION = 55
OUTPUT_DIR = "/mnt/c/Temp/財經分析2026"

RAW_HEADER = [
    "timestamp", "time",
    "price", "volume", "open", "high", "low",
    "bid1_price", "bid1_vol", "bid2_price", "bid2_vol",
    "bid3_price", "bid3_vol", "bid4_price", "bid4_vol",
    "bid5_price", "bid5_vol",
    "ask1_price", "ask1_vol", "ask2_price", "ask2_vol",
    "ask3_price", "ask3_vol", "ask4_price", "ask4_vol",
    "ask5_price", "ask5_vol",
]

CALC_HEADER = [
    # === 掛單力道 ===
    "bid_total_vol",      # 五檔買盤總量
    "ask_total_vol",      # 五檔賣盤總量
    "bid_ask_ratio",      # 買賣力比 (bid/ask, >1偏多 <1偏空)
    "spread",             # 價差 (ask1 - bid1)
    # === 掛單變化 (vs 上一筆) ===
    "price_delta",        # 成交價變動
    "vol_delta",          # 成交量增量 (判斷是否這3秒有成交)
    "bid1_vol_delta",     # 買一掛單量變化 (大單進出)
    "ask1_vol_delta",     # 賣一掛單量變化
    "bid_total_delta",    # 總買盤量變化
    "ask_total_delta",    # 總賣盤量變化
    # === 內外盤 ===
    "trade_side",         # 1=外盤(買進成交) -1=內盤(賣出成交) 0=平盤/無
    # === 漲跌幅 ===
    "change_pct",         # 漲跌幅% (vs 開盤價)
    "amplitude_pct",      # 盤中振幅% ((high-low)/open)
    # === 委買委賣 ===
    "bid_vol_pct",        # 買盤佔比% (bid/(bid+ask))
]

CSV_HEADER = RAW_HEADER + CALC_HEADER

TRADING_START = time(9, 0)
TRADING_END = time(13, 30)


def is_trading_time() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return TRADING_START <= now.time() <= TRADING_END


def safe_float(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def safe_int(s):
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def fetch_3661():
    data = twstock.realtime.get(STOCK_ID)
    if not data or not data.get("success"):
        return None

    rt = data["realtime"]
    bids_p = rt.get("best_bid_price", [])[:5]
    bids_v = rt.get("best_bid_volume", [])[:5]
    asks_p = rt.get("best_ask_price", [])[:5]
    asks_v = rt.get("best_ask_volume", [])[:5]

    now = datetime.now()

    raw = [
        now.isoformat(),
        now.strftime("%H:%M:%S"),
        rt.get("latest_trade_price", ""),
        rt.get("accumulate_trade_volume", ""),
        rt.get("open", ""),
        rt.get("high", ""),
        rt.get("low", ""),
    ]

    for i in range(5):
        raw.append(bids_p[i] if i < len(bids_p) else "")
        raw.append(bids_v[i] if i < len(bids_v) else "")

    for i in range(5):
        raw.append(asks_p[i] if i < len(asks_p) else "")
        raw.append(asks_v[i] if i < len(asks_v) else "")

    return raw


def compute_calcs(raw, prev):
    """
    prev = (bid_total, ask_total, price, bid1_vol, ask1_vol, cum_vol)
    當前這筆 vs 上一筆的差分
    """
    price = safe_float(raw[2])
    cum_vol = safe_int(raw[3])
    open_p = safe_float(raw[4])
    high_p = safe_float(raw[5])
    low_p = safe_float(raw[6])

    bid1_p = safe_float(raw[7])
    bid_vols = [safe_int(raw[i]) for i in range(8, 17, 2)]
    ask1_p = safe_float(raw[17])
    ask_vols = [safe_int(raw[i]) for i in range(18, 27, 2)]

    # --- 掛單力道 ---
    bid_total = sum(bid_vols)
    ask_total = sum(ask_vols)
    ratio = round(bid_total / ask_total, 2) if ask_total > 0 else 99.0
    spread = round(ask1_p - bid1_p, 1) if ask1_p > 0 and bid1_p > 0 else 0.0

    # --- 漲跌幅 ---
    change_pct = round((price - open_p) / open_p * 100, 2) if open_p > 0 else 0.0
    amplitude_pct = round((high_p - low_p) / open_p * 100, 2) if open_p > 0 else 0.0

    # --- 委買佔比 ---
    bid_vol_pct = round(bid_total / (bid_total + ask_total) * 100, 1) if (bid_total + ask_total) > 0 else 50.0

    # --- 變化量 (vs prev) ---
    if prev:
        price_delta = round(price - prev[2], 1)
        vol_delta = cum_vol - prev[5]
        bid1_delta = bid_vols[0] - prev[3]
        ask1_delta = ask_vols[0] - prev[4]
        bid_total_delta = bid_total - prev[0]
        ask_total_delta = ask_total - prev[1]
    else:
        price_delta = 0.0
        vol_delta = 0
        bid1_delta = 0
        ask1_delta = 0
        bid_total_delta = 0
        ask_total_delta = 0

    # --- 內外盤 ---
    if bid1_p > 0 and ask1_p > 0:
        if price >= ask1_p:
            trade_side = 1    # 外盤：成交在賣價 = 主動買進
        elif price <= bid1_p:
            trade_side = -1   # 內盤：成交在買價 = 主動賣出
        else:
            trade_side = 0    # 中間成交
    else:
        trade_side = 0

    calcs = [
        bid_total, ask_total, ratio, spread,
        price_delta, vol_delta, bid1_delta, ask1_delta,
        bid_total_delta, ask_total_delta,
        trade_side,
        change_pct, amplitude_pct,
        bid_vol_pct,
    ]

    next_prev = (bid_total, ask_total, price, bid_vols[0], ask_vols[0], cum_vol)
    return calcs, next_prev


def main():
    if not is_trading_time():
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    filepath = os.path.join(OUTPUT_DIR, f"{date_str}_3661.csv")

    start = _time.time()
    count = 0
    fail = 0
    prev = None

    while _time.time() - start < LOOP_DURATION:
        loop_start = _time.time()

        raw = fetch_3661()
        if raw is None:
            fail += 1
        else:
            calcs, prev = compute_calcs(raw, prev)
            row = raw + calcs

            file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
            with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(CSV_HEADER)
                writer.writerow(row)
            count += 1

        elapsed = _time.time() - loop_start
        sleep_for = INTERVAL - elapsed
        if sleep_for > 0:
            _time.sleep(sleep_for)

    if fail > 0:
        print(f"[{datetime.now():%H:%M:%S}] 3661: {count} 筆成功, {fail} 筆失敗", file=sys.stderr)


if __name__ == "__main__":
    main()
