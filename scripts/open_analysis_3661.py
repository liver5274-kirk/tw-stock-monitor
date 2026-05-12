#!/usr/bin/env python3
"""
3661 世芯-KY 開盤即時分析 (GitHub Actions 版)
9:00 CST 執行，五檔買賣盤＋當沖訊號研判
"""
import sys
import twstock
from datetime import datetime, timezone, timedelta
from telegram_utils import send_message

CODE = "3661"
CST = timezone(timedelta(hours=8))


def fmt_p(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def fmt_v(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def main():
    data = twstock.realtime.get(CODE)
    if not data or not data.get("success"):
        msg = "❌ 無法取得 3661 即時資料（可能尚未開盤或 API 異常）"
        send_message(msg)
        return

    info = data["info"]
    rt = data["realtime"]

    price = fmt_p(rt.get("latest_trade_price", "-"))
    vol = fmt_v(rt.get("trade_volume", 0))
    accum_vol = fmt_v(rt.get("accumulate_trade_volume", 0))
    open_p = fmt_p(rt.get("open", "-"))
    high = fmt_p(rt.get("high", "-"))
    low = fmt_p(rt.get("low", "-"))
    now_str = info.get("time", datetime.now(CST).strftime("%H:%M:%S"))

    # 五檔
    bids_p = rt.get("best_bid_price", [])[:5]
    bids_v = rt.get("best_bid_volume", [])[:5]
    asks_p = rt.get("best_ask_price", [])[:5]
    asks_v = rt.get("best_ask_volume", [])[:5]

    bids = [(fmt_p(bids_p[i]) if i < len(bids_p) else None,
             fmt_v(bids_v[i]) if i < len(bids_v) else 0) for i in range(5)]
    asks = [(fmt_p(asks_p[i]) if i < len(asks_p) else None,
             fmt_v(asks_v[i]) if i < len(asks_v) else 0) for i in range(5)]

    bid_total = sum(b[1] for b in bids if b[1])
    ask_total = sum(a[1] for a in asks if a[1])
    ratio = bid_total / ask_total if ask_total > 0 else float("inf")
    spread = (asks[0][0] - bids[0][0]) if asks[0][0] and bids[0][0] else None
    spread_pct = (spread / price * 100) if spread and price else None

    # 訊號
    signals = []
    if ratio > 2.0:
        signals.append("🔥 強烈偏多 — 買盤總量是賣盤 2 倍以上")
    elif ratio > 1.5:
        signals.append("📈 偏多 — 買盤力道明顯大於賣盤")
    elif ratio < 0.5:
        signals.append("🔥 強烈偏空 — 賣盤總量是買盤 2 倍以上")
    elif ratio < 0.8:
        signals.append("📉 偏空 — 賣壓略大於買盤")
    else:
        signals.append("⚖ 買賣力道接近均衡")

    if spread_pct and spread_pct > 0.5:
        signals.append(f"⚠ 買賣價差偏大 ({spread_pct:.2f}%)，流動性較差")

    # 組訊息
    name = info.get("name", CODE)
    msg = f"📊 <b>{name} ({CODE}) 開盤即時分析</b>\n"
    msg += f"⏰ {now_str}\n"
    msg += "━" * 25 + "\n"
    msg += f"成交價: {price:.0f}\n" if price else ""
    msg += f"成交量: {vol:,} 張 (累計 {accum_vol:,})\n"
    msg += f"開盤價: {open_p:.0f}\n" if open_p else ""
    msg += f"最高價: {high:.0f}\n" if high else ""
    msg += f"最低價: {low:.0f}\n" if low else ""
    msg += "━" * 25 + "\n"
    msg += "<b>五檔買盤 / 賣盤</b>\n"
    for i in range(5):
        bp, bv = bids[i]
        ap, av = asks[i]
        bp_s = f"{bp:.0f}" if bp else "-"
        ap_s = f"{ap:.0f}" if ap else "-"
        msg += f"  #{i+1} {bp_s:>6} x {bv:>5,}  │  {ap_s:>6} x {av:>5,}\n"

    msg += "━" * 25 + "\n"
    msg += f"買盤總量: {bid_total:,} 張\n"
    msg += f"賣盤總量: {ask_total:,} 張\n"
    msg += f"買賣比: {ratio:.2f}x\n"
    if spread:
        msg += f"價差: {spread:.1f} 元"
        if spread_pct:
            msg += f" ({spread_pct:.2f}%)"
        msg += "\n"
    msg += "\n"
    for s in signals:
        msg += f"• {s}\n"
    msg += f"\n<i>由 GitHub Actions 自動產生</i>"

    send_message(msg)


if __name__ == "__main__":
    main()
