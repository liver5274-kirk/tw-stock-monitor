#!/usr/bin/env python3
"""
3661 世芯-KY 即時監控 Dashboard
Streamlit 一鍵啟動 → 瀏覽器看盤

用法：
  pip install streamlit pandas plotly
  streamlit run dashboard_3661.py
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, time
import os
import glob

# ── 設定 ──
CSV_DIR = "/mnt/c/Temp/財經分析2026"
STOCK_ID = "3661"
STOCK_NAME = "世芯-KY"
REFRESH_SEC = 5

TRADING_START = time(9, 0)
TRADING_END = time(13, 30)


def is_trading_time():
    now = datetime.now()
    return now.weekday() < 5 and TRADING_START <= now.time() <= TRADING_END


def load_csv():
    """載入今日 CSV"""
    date_str = datetime.now().strftime("%Y%m%d")
    path = os.path.join(CSV_DIR, f"{date_str}_{STOCK_ID}.csv")
    if not os.path.exists(path):
        # 試找最近一天的
        files = sorted(glob.glob(os.path.join(CSV_DIR, f"*_{STOCK_ID}.csv")), reverse=True)
        if files:
            path = files[0]
        else:
            return None, None

    df = pd.read_csv(path, encoding="utf-8-sig")

    # 清理
    for col in ["timestamp", "time"]:
        if col in df.columns:
            try:
                df[col] = pd.to_datetime(df[col])
            except Exception:
                pass

    # 數值轉換
    for col in df.columns:
        if col in ["timestamp", "time", "trade_side"]:
            continue
        try:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        except Exception:
            pass

    return df, path


def detect_smoke_events(df):
    """掃描整個 DataFrame，回傳煙霧彈事件列表。
    每個事件: {time, price, signal, label, color}
    """
    events = []
    if len(df) < 2:
        return events

    rows = df.to_dict("records")

    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]

        prev_ask = prev.get("ask_total_vol", 0) or 0
        curr_ask = curr.get("ask_total_vol", 0) or 0
        prev_vol = prev.get("volume", 0) or 0
        curr_vol = curr.get("volume", 0) or 0
        prev_price = prev.get("price")
        curr_price = curr.get("price")
        ratio = curr.get("bid_ask_ratio", 0) or 0
        day_high = df["high"].max() if "high" in df.columns else 0

        t = curr.get("time")

        # 訊號 1: 賣盤暴增 + 價格不跌
        if prev_ask > 0 and curr_ask >= prev_ask * 1.5 and curr_ask >= 15:
            price_dropped = (
                prev_price and curr_price and prev_price > 0 and curr_price > 0
                and curr_price < prev_price
            )
            if not price_dropped:
                events.append({
                    "time": t, "price": curr_price,
                    "signal": "假賣壓",
                    "label": f"🔥 ask {int(prev_ask)}→{int(curr_ask)}",
                    "color": "#f59e0b",  # amber
                })

        # 訊號 2: 賣盤瞬間蒸發（抽單）
        drop = prev_ask - curr_ask
        if drop >= 15:
            vol_delta = curr_vol - prev_vol
            if vol_delta < drop * 0.5:
                events.append({
                    "time": t, "price": curr_price,
                    "signal": "抽單",
                    "label": f"🚨 -{int(drop)}張",
                    "color": "#ef4444",  # red
                })

        # 訊號 3: 買賣比極空 + 價格近高點
        if 0 < ratio < 0.3 and curr_ask >= 15 and day_high > 0 and curr_price:
            if curr_price >= day_high * 0.98:
                events.append({
                    "time": t, "price": curr_price,
                    "signal": "背離",
                    "label": f"⚠ ratio={ratio:.2f}",
                    "color": "#8b5cf6",  # purple
                })

    return events


# ── 頁面設定 ──
st.set_page_config(
    page_title=f"{STOCK_ID} {STOCK_NAME} Dashboard",
    page_icon="📈",
    layout="wide",
)

# 自動刷新
if is_trading_time():
    st.markdown(
        f'<meta http-equiv="refresh" content="{REFRESH_SEC}">',
        unsafe_allow_html=True,
    )

st.title(f"📈 {STOCK_ID} {STOCK_NAME} 即時監控")

# ── 載入資料 ──
df, csv_path = load_csv()

if df is None or df.empty:
    st.warning("無資料。請確認 CSV 監控正在運行。")
    st.stop()

# ── 頂端指標卡 ──
latest = df.iloc[-1]
first = df.iloc[0]

col1, col2, col3, col4, col5, col6 = st.columns(6)

price = latest.get("price", None)
open_p = first.get("open", df["price"].dropna().iloc[0] if not df["price"].dropna().empty else None)

change = price - open_p if price and open_p else 0
change_pct = (change / open_p * 100) if open_p and open_p != 0 else 0
ratio = latest.get("bid_ask_ratio", None)
spread = latest.get("spread", None)
day_high = df["high"].max() if "high" in df.columns else None
day_low = df["low"].min() if "low" in df.columns else None

color = "#22c55e" if change >= 0 else "#ef4444"

col1.metric("成交價", f"{price:.0f}" if price and not pd.isna(price) else "-",
            f"{change:+.0f} ({change_pct:+.2f}%)" if price else "")
col2.metric("日高", f"{day_high:.0f}" if day_high and not pd.isna(day_high) else "-")
col3.metric("日低", f"{day_low:.0f}" if day_low and not pd.isna(day_low) else "-")
col4.metric("買賣比", f"{ratio:.2f}x" if ratio and not pd.isna(ratio) else "-")
col5.metric("價差", f"{spread:.1f}" if spread and not pd.isna(spread) else "-")
col6.metric("資料筆數", f"{len(df):,}")

# 買賣比狀態燈
if ratio and not pd.isna(ratio):
    if ratio > 1.5:
        st.success(f"🟢 買盤強勢 (ratio={ratio:.2f})")
    elif ratio < 0.5:
        st.error(f"🔴 賣壓沉重 (ratio={ratio:.2f})")
    else:
        st.info(f"🟡 買賣均衡 (ratio={ratio:.2f})")

# ── 主圖：價格 + 成交量 ──
st.subheader("價格走勢")

# 掃描煙霧彈事件
smoke_events = detect_smoke_events(df)

fig1 = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.05,
    row_heights=[0.65, 0.35],
)

# 價格線
fig1.add_trace(
    go.Scatter(
        x=df["time"], y=df["price"],
        mode="lines",
        name="成交價",
        line=dict(color=color, width=2),
        connectgaps=False,
    ),
    row=1, col=1,
)

# 煙霧彈標記 — 依訊號類型分色
for sig_color, sig_name in [("#f59e0b", "假賣壓"), ("#ef4444", "抽單"), ("#8b5cf6", "背離")]:
    sig_events = [e for e in smoke_events if e["signal"] == sig_name]
    if sig_events:
        fig1.add_trace(
            go.Scatter(
                x=[e["time"] for e in sig_events],
                y=[e["price"] for e in sig_events],
                mode="markers+text",
                name=sig_name,
                marker=dict(
                    symbol="diamond",
                    size=14,
                    color=sig_color,
                    line=dict(width=1, color="white"),
                ),
                text=[e["label"] for e in sig_events],
                textposition="top center",
                textfont=dict(size=9),
                hovertemplate="%{text}<br>價格: %{y:.0f}<extra></extra>",
            ),
            row=1, col=1,
        )

# 日高日低參考線
if day_high and not pd.isna(day_high):
    fig1.add_hline(y=day_high, line_dash="dash", line_color="gray",
                   annotation_text=f"日高 {day_high:.0f}", row=1, col=1)
if day_low and not pd.isna(day_low):
    fig1.add_hline(y=day_low, line_dash="dash", line_color="gray",
                   annotation_text=f"日低 {day_low:.0f}", row=1, col=1)

# 成交量柱
colors_vol = ["#22c55e" if c >= 0 else "#ef4444"
              for c in df["price_delta"].fillna(0)]
fig1.add_trace(
    go.Bar(x=df["time"], y=df["volume"],
           name="成交量", marker_color=colors_vol,
           opacity=0.5),
    row=2, col=1,
)

fig1.update_layout(
    height=500, hovermode="x unified",
    showlegend=False,
    margin=dict(l=0, r=0, t=10, b=0),
)
fig1.update_yaxes(title_text="價格", row=1, col=1)
fig1.update_yaxes(title_text="量", row=2, col=1)

st.plotly_chart(fig1, use_container_width=True)

# ── 買賣力道圖 ──
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("買賣總量")

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=df["time"], y=df["bid_total_vol"],
        name="買盤", mode="lines",
        line=dict(color="#22c55e", width=2),
    ))
    fig2.add_trace(go.Scatter(
        x=df["time"], y=df["ask_total_vol"],
        name="賣盤", mode="lines",
        line=dict(color="#ef4444", width=2),
    ))
    fig2.update_layout(
        height=350, hovermode="x unified",
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig2, use_container_width=True)

with col_right:
    st.subheader("買賣比趨勢")

    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=df["time"], y=df["bid_ask_ratio"],
        name="買賣比", mode="lines",
        line=dict(color="#3b82f6", width=2),
        fill="tozeroy", fillcolor="rgba(59,130,246,0.1)",
    ))
    # 參考線
    fig3.add_hline(y=1.5, line_dash="dot", line_color="#22c55e",
                   annotation_text="偏多 1.5")
    fig3.add_hline(y=0.5, line_dash="dot", line_color="#ef4444",
                   annotation_text="偏空 0.5")
    fig3.add_hline(y=1.0, line_dash="dash", line_color="gray")

    fig3.update_layout(
        height=350, hovermode="x unified",
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig3, use_container_width=True)

# ── 五檔深度圖 ──
st.subheader("五檔掛單深度")

bid_cols = ["bid1_vol", "bid2_vol", "bid3_vol", "bid4_vol", "bid5_vol"]
ask_cols = ["ask1_vol", "ask2_vol", "ask3_vol", "ask4_vol", "ask5_vol"]
bid_price_cols = ["bid1_price", "bid2_price", "bid3_price", "bid4_price", "bid5_price"]
ask_price_cols = ["ask1_price", "ask2_price", "ask3_price", "ask4_price", "ask5_price"]

latest_bid_v = [latest.get(c, 0) or 0 for c in bid_cols]
latest_ask_v = [latest.get(c, 0) or 0 for c in ask_cols]
latest_bid_p = [latest.get(c, 0) or 0 for c in bid_price_cols]
latest_ask_p = [latest.get(c, 0) or 0 for c in ask_price_cols]

fig4 = go.Figure()

# 買盤 (綠色，正方向)
fig4.add_trace(go.Bar(
    y=[f"買{i+1}" for i in range(5)],
    x=latest_bid_v,
    name="買盤",
    orientation="h",
    marker_color="#22c55e",
    text=[f"{p:.0f} x {v}" for p, v in zip(latest_bid_p, latest_bid_v)],
    textposition="auto",
))

# 賣盤 (紅色，負方向)
fig4.add_trace(go.Bar(
    y=[f"賣{i+1}" for i in range(5)],
    x=[-v for v in latest_ask_v],
    name="賣盤",
    orientation="h",
    marker_color="#ef4444",
    text=[f"{p:.0f} x {v}" for p, v in zip(latest_ask_p, latest_ask_v)],
    textposition="auto",
))

fig4.update_layout(
    barmode="relative",
    height=300,
    margin=dict(l=0, r=0, t=10, b=0),
    xaxis_title="← 賣盤掛量  │  買盤掛量 →",
    showlegend=False,
)

st.plotly_chart(fig4, use_container_width=True)

# ── 煙霧彈事件摘要 ──
if smoke_events:
    st.subheader(f"🕵️ 煙霧彈事件 ({len(smoke_events)} 次)")
    cols = st.columns([1, 1, 1, 2])
    cols[0].markdown("**時間**")
    cols[1].markdown("**訊號**")
    cols[2].markdown("**價格**")
    cols[3].markdown("**說明**")
    for e in smoke_events[-20:]:  # 顯示最近 20 筆
        t_str = e["time"].strftime("%H:%M:%S") if hasattr(e["time"], "strftime") else str(e["time"])
        p_str = f"{e['price']:.0f}" if e["price"] and not pd.isna(e["price"]) else "-"
        emoji = {"假賣壓": "🔥", "抽單": "🚨", "背離": "⚠"}.get(e["signal"], "")
        cols2 = st.columns([1, 1, 1, 2])
        cols2[0].code(t_str)
        cols2[1].markdown(f"{emoji} **{e['signal']}**")
        cols2[2].code(p_str)
        cols2[3].caption(e["label"])
    if len(smoke_events) > 20:
        st.caption(f"... 及其他 {len(smoke_events) - 20} 筆事件")
else:
    st.info("🟢 今日無煙霧彈事件")

# ── 底部資訊 ──
st.caption(f"資料來源: `{csv_path}` | 更新時間: {datetime.now().strftime('%H:%M:%S')} | 自動刷新: {'🟢 開啟' if is_trading_time() else '⏸ 已暫停（非交易時間）'}")
