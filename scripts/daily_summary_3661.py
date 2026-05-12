#!/usr/bin/env python3
"""
3661 世芯-KY 盤後摘要 (GitHub Actions 版)
每日 13:35 CST 執行，從 twstock + Yahoo Finance 抓取當日摘要
"""
import sys
import json
import urllib.request
import twstock
from datetime import datetime, time, timedelta, timezone
from telegram_utils import send_message, format_escape

CODE = "3661"
CST = timezone(timedelta(hours=8))


def fetch_twstock():
    """從 twstock 抓收盤資料"""
    data = twstock.realtime.get(CODE)
    if not data or not data.get("success"):
        return None

    rt = data["realtime"]

    def _p(v):
        try: return float(v)
        except: return None

    def _v(v):
        try: return int(float(v))
        except: return 0

    return {
        "name": data["info"].get("name", CODE),
        "time": data["info"].get("time", ""),
        "price": _p(rt.get("latest_trade_price", "-")),
        "open": _p(rt.get("open", "-")),
        "high": _p(rt.get("high", "-")),
        "low": _p(rt.get("low", "-")),
        "volume": _v(rt.get("accumulate_trade_volume", 0)),
    }


def fetch_yahoo_ohlcv():
    """從 Yahoo Finance v8 抓當日 OHLCV"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{CODE}.TW?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result = data["chart"]["result"][0]
        meta = result["meta"]
        return {
            "open": meta.get("regularMarketOpen"),
            "high": meta.get("regularMarketDayHigh"),
            "low": meta.get("regularMarketDayLow"),
            "close": meta.get("regularMarketPrice"),
            "prev_close": meta.get("previousClose"),
            "volume": meta.get("regularMarketVolume", 0),
        }
    except Exception as e:
        print(f"[yahoo] 查詢失敗: {e}")
        return None


def main():
    now_cst = datetime.now(CST)

    # 非交易日跳過
    if now_cst.weekday() >= 5:
        return

    # 從 twstock 抓
    ts = fetch_twstock()
    yh = fetch_yahoo_ohlcv()

    if not ts and not yh:
        msg = "⚠ 無法取得 3661 今日資料"
        send_message(msg)
        return

    # 合併資料（優先 twstock）
    open_p = ts["open"] if ts and ts["open"] else (yh["open"] if yh else None)
    high = ts["high"] if ts and ts["high"] else (yh["high"] if yh else None)
    low = ts["low"] if ts and ts["low"] else (yh["low"] if yh else None)
    close_p = ts["price"] if ts and ts["price"] else (yh["close"] if yh else None)
    volume = ts["volume"] if ts and ts["volume"] else (yh["volume"] if yh else 0)
    prev_close = yh["prev_close"] if yh else None

    if not close_p:
        send_message("⚠ 3661 今日無收盤價")
        return

    change = close_p - prev_close if prev_close else (close_p - open_p if open_p else 0)
    change_pct = (change / prev_close * 100) if prev_close else 0
    amplitude = ((high - low) / open_p * 100) if open_p and high and low and open_p > 0 else 0
    volume_k = volume / 1000 if volume else 0

    date_str = now_cst.strftime("%Y-%m-%d")

    # 走勢判斷
    if change_pct > 2:
        trend = "🟢 強勢上漲"
    elif change_pct > 0:
        trend = "🟢 溫和上漲"
    elif change_pct > -2:
        trend = "🟡 震盪整理"
    else:
        trend = "🔴 弱勢下跌"

    msg = f"📊 <b>3661 世芯-KY 盤後摘要</b> — {date_str}\n"
    msg += "━" * 25 + "\n"
    msg += f"開盤  {open_p:>8.0f}\n" if open_p else ""
    msg += f"收盤  {close_p:>8.0f}  ({change:+.0f} / {change_pct:+.2f}%)\n"
    if prev_close:
        msg += f"昨收  {prev_close:>8.0f}\n"
    msg += f"最高  {high:>8.0f}\n" if high else ""
    msg += f"最低  {low:>8.0f}\n" if low else ""
    if amplitude:
        msg += f"振幅  {amplitude:>8.2f}%\n"
    msg += f"成交量 {volume_k:>7.1f}K 張\n" if volume_k else ""
    msg += "\n"
    msg += f"💡 盤勢: {trend}\n"
    if amplitude and amplitude > 5:
        msg += "⚠ 高波動日 (振幅&gt;5%)\n"

    msg += f"\n<i>由 GitHub Actions 自動產生</i>"
    send_message(msg)


if __name__ == "__main__":
    main()
