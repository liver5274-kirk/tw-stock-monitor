#!/usr/bin/env python3
"""
2454 聯發科 (MediaTek) 盤中風險監控腳本 — twstock 即時版
==========================================================
使用 twstock 即時報價 + 本地狀態檔累積 VWAP 與量能歷史。

與 Yahoo Finance v8 版的差異：
  - 即時性：twstock 近乎即時 (<5s)，遠優於 Yahoo ~20 分鐘延遲
  - VWAP：由累積 snapshot 計算 (Σ price×vol_delta / Σ vol_delta)
  - 反彈失敗：由狀態檔偵測「曾 > VWAP 後跌落」
  - 量能：由狀態檔累積 vol_delta，比較近期 vs 基準期
  - 限制：需頻繁執行 (建議每 1 分鐘) 累積足夠歷史

狀態檔：~/.hermes/scripts/state_2454_risk.json（跨日自動重置）

5 條件加權計分 (0-100)：
  1. 現價 < VWAP (30分) — 跌破累積平均成本
  2. 量能加速度 > 2.5倍 (25分) — 近期 vol_delta 異常放大
  3. 價格在當日振幅底部 15%，附振幅濾網 >1.5% (15分)
  4. 近 10 筆記錄中曾 > VWAP 後跌落 (20分) — 反彈失敗
  5. 現價 < 開盤價 (10分) — 日K黑K

部署：cronjob */1 9-13 * * 1-5, no_agent=True
"""

import sys
import json
import csv
import os
import time as time_mod
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path

try:
    import twstock
except ImportError:
    print("[FATAL] twstock not installed. Run: pip install twstock", file=sys.stderr)
    sys.exit(1)

# ═══════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════
CODE = "2454"
NAME = "聯發科"
STATE_FILE = Path(os.path.expanduser("~/.hermes/scripts/state_2454_risk.json"))
OUTPUT_DIR = Path("/mnt/c/Temp/財經分析2026")
CSV_FILE_TEMPLATE = "{date}_{code}_risk.csv"

CST = timezone(timedelta(hours=8))

# Risk thresholds
RISK_HIGH = 70       # 極度危險
RISK_MEDIUM = 40     # 危險 (cron notification floor)

# Minimum snapshots before scoring (roughly N minutes of data)
MIN_SNAPSHOTS = 10

# Volume acceleration params
VOL_RECENT = 6       # last N snapshots for "recent" volume
VOL_BASELINE = 20    # baseline window (snapshots before recent window)
VOL_SPIKE_RATIO = 2.5

# Amplitude filter
MIN_RANGE_PCT = 1.5  # percent

# Rebound lookback: check last N snapshots for VWAP touch
REBOUND_LOOKBACK = 10

# Data staleness: ignore snapshots older than this (seconds)
MAX_SNAPSHOT_AGE = 120  # 2 minutes

# ═══════════════════════════════════════════════
# Time utilities
# ═══════════════════════════════════════════════

def now_cst():
    return datetime.now(CST)


def today_str():
    return now_cst().strftime("%Y%m%d")


def is_trading_time():
    """Check if currently in TWSE trading hours (Mon-Fri 9:00-13:30 CST)."""
    now = now_cst()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 0) <= t <= dtime(13, 35)  # include 5 min post-close buffer


# ═══════════════════════════════════════════════
# State file management
# ═══════════════════════════════════════════════

def load_state():
    """
    Load state from JSON file. Returns fresh state if file missing or date changed.

    State structure:
    {
      "date": "20260513",
      "snapshots": [
        {"time": "09:01:15", "ts": 1768300000.0, "price": 1500.0,
         "cum_vol": 500000, "vol_delta": 500000},
        ...
      ],
      "vwap_pv": 750000000.0,   # cumulative price × volume
      "vwap_vol": 500000.0,     # cumulative volume
      "day_open": 1495.0,
      "day_high": 1510.0,
      "day_low": 1490.0
    }
    """
    today = today_str()

    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            if state.get("date") == today:
                return state
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # corrupted → reset

    # Fresh state
    return {
        "date": today,
        "snapshots": [],
        "vwap_pv": 0.0,
        "vwap_vol": 0.0,
        "day_open": None,
        "day_high": None,
        "day_low": None,
    }


def save_state(state):
    """Persist state to JSON file. Creates parent dir if needed."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════
# Data fetching (twstock)
# ═══════════════════════════════════════════════

def fetch_twstock():
    """
    Fetch real-time data for CODE from twstock.

    Returns dict with keys: price, open, high, low, cum_vol, bid1_price, ask1_price
    Returns None on failure or non-trading hours.
    """
    try:
        data = twstock.realtime.get(CODE)
    except Exception as e:
        print(f"[ERROR] twstock.realtime.get() exception: {e}", file=sys.stderr)
        return None

    if not data or not data.get("success"):
        print("[WARN] twstock returned success=False or empty", file=sys.stderr)
        return None

    rt = data.get("realtime", {})
    if not rt:
        return None

    # Price: handle '-' fallback
    price_str = rt.get("latest_trade_price", "-")
    if price_str == "-" or price_str is None:
        print("[WARN] twstock latest_trade_price is '-' (feed gap)", file=sys.stderr)
        return None

    try:
        price = float(price_str)
    except (ValueError, TypeError):
        print(f"[WARN] twstock price parse error: {price_str}", file=sys.stderr)
        return None

    # OHLCV
    open_p = _safe_float(rt.get("open"))
    high_p = _safe_float(rt.get("high"))
    low_p = _safe_float(rt.get("low"))
    cum_vol = _safe_float(rt.get("accumulate_trade_volume"), 0)

    # Bid/Ask (for extra diagnostics)
    bid1 = _safe_float(rt.get("best_bid_price", [None])[0] if rt.get("best_bid_price") else None)
    ask1 = _safe_float(rt.get("best_ask_price", [None])[0] if rt.get("best_ask_price") else None)

    if None in (price, open_p, high_p, low_p):
        print("[WARN] twstock missing OHLC data", file=sys.stderr)
        return None

    return {
        "price": price,
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "cum_vol": cum_vol,
        "bid1": bid1,
        "ask1": ask1,
    }


def _safe_float(val, default=None):
    """Safely convert to float, handling None, '-', empty strings."""
    if val is None or val == "-" or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════
# State update & VWAP
# ═══════════════════════════════════════════════

def update_state(state, snap):
    """
    Add a new snapshot to state and recompute VWAP.

    snap: dict from fetch_twstock()
    Mutates state in place.
    """
    now = now_cst()
    now_ts = now.timestamp()

    # Update day OHLC
    if state["day_open"] is None:
        state["day_open"] = snap["open"]
    state["day_high"] = max(state["day_high"] or snap["high"], snap["high"])
    state["day_low"] = min(state["day_low"] or snap["low"], snap["low"])

    # Volume delta
    prev_cum_vol = 0.0
    if state["snapshots"]:
        prev_cum_vol = state["snapshots"][-1]["cum_vol"]

    vol_delta = snap["cum_vol"] - prev_cum_vol
    if vol_delta < 0:
        # cum_vol reset or data glitch — use 0 to avoid negative
        vol_delta = 0.0

    # Append snapshot
    state["snapshots"].append({
        "time": now.strftime("%H:%M:%S"),
        "ts": now_ts,
        "price": snap["price"],
        "cum_vol": snap["cum_vol"],
        "vol_delta": vol_delta,
    })

    # Prune stale snapshots (older than MAX_SNAPSHOT_AGE from most recent)
    if state["snapshots"]:
        cutoff = now_ts - MAX_SNAPSHOT_AGE
        state["snapshots"] = [s for s in state["snapshots"] if s["ts"] >= cutoff]

    # Recompute VWAP from all snapshots
    # VWAP ≈ Σ(price × vol_delta) / Σ(vol_delta)
    total_pv = 0.0
    total_vol = 0.0
    for s in state["snapshots"]:
        if s["vol_delta"] > 0:
            total_pv += s["price"] * s["vol_delta"]
            total_vol += s["vol_delta"]

    state["vwap_pv"] = total_pv
    state["vwap_vol"] = total_vol


def get_vwap(state):
    """Return current approximate VWAP from state."""
    if state["vwap_vol"] > 0:
        return state["vwap_pv"] / state["vwap_vol"]
    # Fallback: use typical price of current OHLC
    if state["day_high"] and state["day_low"] and state["snapshots"]:
        return (state["day_high"] + state["day_low"] + state["snapshots"][-1]["price"]) / 3.0
    return None


# ═══════════════════════════════════════════════
# Risk scoring engine
# ═══════════════════════════════════════════════

def compute_risk(state, snap):
    """
    Compute risk score (0-100) from state history + current snapshot.

    Returns dict or None if insufficient data.
    """
    snapshots = state["snapshots"]
    n = len(snapshots)

    if n < MIN_SNAPSHOTS:
        return {
            "skip": True,
            "reason": f"資料不足 ({n} 筆快照，需 >= {MIN_SNAPSHOTS})",
        }

    current_price = snap["price"]
    vwap = get_vwap(state)
    if vwap is None:
        return {"skip": True, "reason": "VWAP 無法計算"}

    day_open = state["day_open"]
    day_high = state["day_high"]
    day_low = state["day_low"]
    day_range = day_high - day_low if day_high and day_low else 0
    day_range_pct = (day_range / day_open * 100) if day_open and day_open > 0 else 0

    # Volume baseline
    recent_vols = [s["vol_delta"] for s in snapshots[-VOL_RECENT:]]
    baseline_start = max(0, n - VOL_RECENT - VOL_BASELINE)
    baseline_end = n - VOL_RECENT
    baseline_vols = [s["vol_delta"] for s in snapshots[baseline_start:baseline_end]]
    avg_recent_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 0
    avg_baseline_vol = sum(baseline_vols) / len(baseline_vols) if baseline_vols else avg_recent_vol

    score = 0
    flags = {}
    details = {}

    # ── Condition 1: Price < VWAP (+30) ──
    cond1 = current_price < vwap
    flags["跌破VWAP"] = cond1
    details["vwap"] = round(vwap, 1)
    details["vwap_delta_pct"] = round((current_price - vwap) / vwap * 100, 2)
    if cond1:
        score += 30

    # ── Condition 2: Volume acceleration > 2.5x (+25) ──
    # Recent avg volume > baseline avg × 2.5
    vol_spike = False
    vol_ratio = 0.0
    if avg_baseline_vol > 0:
        vol_ratio = avg_recent_vol / avg_baseline_vol
        vol_spike = vol_ratio >= VOL_SPIKE_RATIO

    flags["爆量>2.5倍"] = vol_spike
    details["vol_ratio"] = round(vol_ratio, 1)
    details["avg_recent_vol"] = int(avg_recent_vol)
    details["avg_baseline_vol"] = int(avg_baseline_vol)
    if vol_spike:
        score += 25

    # ── Condition 3: Near day low 15% (+15) ──
    cond3_enabled = day_range_pct > MIN_RANGE_PCT
    near_low = False
    near_low_pct = 0
    if day_range > 0:
        near_low_pct = round((current_price - day_low) / day_range * 100, 1)
        if cond3_enabled:
            near_low = near_low_pct <= 15.0

    flags["近低點15%"] = near_low
    details["range_pct"] = round(day_range_pct, 2)
    details["amplitude_filter"] = cond3_enabled
    details["near_low_pct"] = near_low_pct
    if near_low:
        score += 15

    # ── Condition 4: Failed VWAP rebound (+20) ──
    # Check last REBOUND_LOOKBACK snapshots:
    #   - Any snapshot had price > VWAP (touched)
    #   - Current price < VWAP (fell back)
    lookback = min(REBOUND_LOOKBACK, n)
    touched_vwap = False
    for i in range(lookback, 0, -1):
        s = snapshots[-i]
        # Use approximate VWAP at that point (cumulative at that time)
        # Simplified: check if price was above current VWAP level
        # Better: compute VWAP at each snapshot from state
        if s["price"] > vwap:
            touched_vwap = True
            break

    failed_rebound = touched_vwap and current_price < vwap

    flags["反彈失敗"] = failed_rebound
    details["touched_vwap"] = touched_vwap
    details["rebound_lookback"] = lookback
    if failed_rebound:
        score += 20

    # ── Condition 5: Price < Open (+10) ──
    cond5 = current_price < day_open
    flags["黑K(跌破開盤)"] = cond5
    details["open_delta_pct"] = round((current_price - day_open) / day_open * 100, 2)
    if cond5:
        score += 10

    # ── Risk Level ──
    if score >= RISK_HIGH:
        level = "🔴 極度危險"
    elif score >= RISK_MEDIUM:
        level = "🟠 危險"
    else:
        level = "🟢 正常"

    return {
        "skip": False,
        "timestamp": now_cst().strftime("%Y-%m-%d %H:%M:%S"),
        "code": CODE,
        "name": NAME,
        "price": current_price,
        "vwap": round(vwap, 1),
        "open": day_open,
        "high": day_high,
        "low": day_low,
        "range_pct": round(day_range_pct, 2),
        "cum_vol": snap["cum_vol"],
        "vol_delta_recent": int(avg_recent_vol),
        "vol_baseline": int(avg_baseline_vol),
        "score": score,
        "level": level,
        "flags": flags,
        "details": details,
        "snapshots": n,
    }


# ═══════════════════════════════════════════════
# Report formatting
# ═══════════════════════════════════════════════

def format_report(risk):
    """Format a human-readable risk report."""
    lines = []
    lines.append(f"📊 {risk['name']}({risk['code']}) 盤中風險監控 — {risk['timestamp']}")
    lines.append(f"")
    lines.append(f"現價: {risk['price']}  |  VWAP: {risk['vwap']}  |  開盤: {risk['open']}")
    lines.append(f"最高: {risk['high']}  |  最低: {risk['low']}  |  振幅: {risk['range_pct']}%")
    lines.append(f"累積量: {risk['cum_vol']:,}  |  近6筆均量: {risk['vol_delta_recent']:,}  |  基準均量: {risk['vol_baseline']:,}")
    lines.append(f"")
    lines.append(f"**風險分數: {risk['score']}/100 → {risk['level']}**")
    lines.append(f"")

    condition_specs = [
        ("跌破VWAP",     "📉 跌破VWAP",        30),
        ("爆量>2.5倍",   "💥 爆量加速",        25),
        ("近低點15%",    "📌 近低點15%",       15),
        ("反彈失敗",     "🔄 反彈失敗(真)",    20),
        ("黑K(跌破開盤)", "⚫ 跌破開盤價",      10),
    ]

    active_count = 0
    for flag_key, label, weight in condition_specs:
        triggered = risk["flags"].get(flag_key, False)
        status = "✅" if triggered else "⬜"
        lines.append(f"  {status} {label} ({weight}分)")
        if triggered:
            active_count += 1

    details = risk["details"]
    lines.append(f"")

    if not details.get("amplitude_filter", True):
        lines.append(f"  ⚠️ 振幅濾網關閉 (今日振幅 {risk['range_pct']}% < {MIN_RANGE_PCT}%)")
    if not details.get("touched_vwap", False):
        lines.append(f"  ℹ️ 近{details.get('rebound_lookback','?')}筆未觸及VWAP，反彈失敗不成立")

    if risk["flags"].get("跌破VWAP"):
        lines.append(f"  📏 VWAP偏離: {details['vwap_delta_pct']}%")
    if risk["flags"].get("爆量>2.5倍"):
        lines.append(f"  📊 量能倍數: {details['vol_ratio']}x")
    if risk["flags"].get("黑K(跌破開盤)"):
        lines.append(f"  📏 開盤偏離: {details['open_delta_pct']}%")

    lines.append(f"")
    if risk["score"] >= RISK_HIGH:
        lines.append(f"🔴🔴 **高分警告**: {active_count}/5 條件觸發，多個轉弱訊號同時成立。")
    elif risk["score"] >= RISK_MEDIUM:
        lines.append(f"🟠 **注意**: {active_count}/5 條件觸發，部分轉弱訊號出現。")
    else:
        lines.append(f"🟢 目前無明顯轉弱訊號 ({active_count}/5 條件觸發)。")

    lines.append(f"")
    lines.append(f"資料源: twstock | {risk['snapshots']} 筆快照 | 閾值: {RISK_MEDIUM}/{RISK_HIGH}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════
# CSV logging
# ═══════════════════════════════════════════════

def log_to_csv(risk):
    """Append risk assessment to daily CSV."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / CSV_FILE_TEMPLATE.format(date=today_str(), code=CODE)

    row = [
        risk["timestamp"], risk["code"], risk["price"], risk["vwap"],
        risk["open"], risk["high"], risk["low"], risk["range_pct"],
        risk["cum_vol"], risk["vol_delta_recent"], risk["vol_baseline"],
        1 if risk["flags"].get("跌破VWAP") else 0,
        1 if risk["flags"].get("爆量>2.5倍") else 0,
        1 if risk["flags"].get("近低點15%") else 0,
        1 if risk["flags"].get("反彈失敗") else 0,
        1 if risk["flags"].get("黑K(跌破開盤)") else 0,
        risk["score"], risk["level"], risk["snapshots"],
    ]
    header = [
        "timestamp", "code", "price", "vwap", "open", "high", "low",
        "range_pct", "cum_vol", "vol_delta_recent", "vol_baseline",
        "cond1_vwap", "cond2_volume", "cond3_nearlow",
        "cond4_rebound", "cond5_black",
        "score", "level", "snapshots",
    ]

    file_exists = csv_path.exists()
    try:
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(header)
            writer.writerow(row)
    except Exception as e:
        print(f"[ERROR] CSV write failed: {e}", file=sys.stderr)


# ═══════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════

def main():
    # 1. Trading hours gate
    if not is_trading_time():
        # Outside trading hours: silently skip (no output, no error)
        sys.exit(0)

    # 2. Fetch real-time data
    snap = fetch_twstock()
    if snap is None:
        print("[WARN] twstock fetch failed — skipping this tick", file=sys.stderr)
        sys.exit(1)

    # 3. Load state
    state = load_state()

    # 4. Update state with new snapshot
    update_state(state, snap)
    save_state(state)

    # 5. Compute risk
    risk = compute_risk(state, snap)

    # 6. Handle insufficient data
    if risk is None or risk.get("skip"):
        reason = risk.get("reason", "unknown") if risk else "compute_risk returned None"
        print(f"[INFO] {reason} — 略過本次評估", file=sys.stderr)
        sys.exit(2)

    # 7. Always log to CSV
    log_to_csv(risk)

    # 8. Output decision
    is_interactive = sys.stdout.isatty()

    if is_interactive:
        # Interactive: always show full report
        print(format_report(risk))
    else:
        # Cron mode: silent watchdog — only print when score >= MEDIUM
        if risk["score"] >= RISK_MEDIUM:
            print(format_report(risk))
        # else: silent (no stdout → no Telegram message)

    sys.exit(0)


if __name__ == "__main__":
    main()
