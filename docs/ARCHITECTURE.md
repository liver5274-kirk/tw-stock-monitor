# 系統架構說明

## 整體設計原則

雙軌部署：WSL 本機 + GitHub Actions 雲端。各司其職，互不干擾。

### 部署分工

```
WSL Cron (本機)                    GitHub Actions (雲端)
─────────────────                  ─────────────────────
monitor_3661.py      高頻記錄      smoke_detect_3661.py   煙霧彈
  ↓ 每分鐘,內部3s×18次              ↓ 每5分鐘,雙次快照
  ↓ 寫入CSV (持久化)                ↓ 即時分析,推送Telegram
                                  
strategy_3661_divergence.py 背離   open_analysis_3661.py  開盤
  ↓ 每5分鐘,全日CSV掃描              ↓ 9:00,單次即時分析
  ↓ 需要連續歷史資料                 ↓ 推送Telegram
                                  
pre_market_warmup.py     預熱      daily_summary_3661.py  盤後
  ↓ 8:58,喚醒cron daemon            ↓ 13:35,全日摘要
  ↓ 確保9:00不遺漏                  ↓ 推送Telegram
```

### 為什麼要雙軌？

| 考量 | WSL Cron | GitHub Actions |
|------|----------|----------------|
| 寫入檔案 | ✅ 持久化CSV | ❌ 無狀態 |
| 高頻(秒級) | ✅ 內部循環 | ❌ 最小5分鐘 |
| 24/7 可用 | ❌ 電腦關機就停 | ✅ 雲端常駐 |
| 部署難度 | 低 | 低 |
| 成本 | 0 | 0 (public repo) |

兩者互補：WSL 負責「記錄」，GitHub Actions 負責「備援分析」。

---

## 資料流

```
TWSE 證交所 ──→ twstock.realtime.get('3661')
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
    原始五檔      即時成交價     累積成交量
    (買5賣5)     (含開高低)     (當日累積)
         │            │            │
         └────────────┼────────────┘
                      ▼
              compute_calcs()
          ┌───┴───────────────────┐
          │ bid_ask_ratio         │ ← 買賣力道
          │ spread                │ ← 流動性
          │ bid1_vol_delta        │ ← 大單進場
          │ ask_total_delta       │ ← 掛單變化
          │ trade_side (±1/0)     │ ← 內外盤
          │ change_pct, amp_pct   │ ← 漲跌振幅
          └───┬───────────────────┘
              ▼
        CSV (UTF-8 BOM)
    C:\Temp\財經分析2026\{日期}_3661.csv
              │
     ┌────────┼────────┐
     ▼        ▼        ▼
  Streamlit  Excel   後續分析腳本
  即時看盤   手動分析   (smoke/strategy)
```

---

## 時間軸（交易日的 Cron 排程）

```
08:58 ─ pre_market_warmup    喚醒 cron daemon + 預熱 twstock import
09:00 ─ open_analysis        開盤五檔分析 → Telegram
09:00 ─ monitor_3661 (start) 每分鐘觸發，內部 3s 循環
09:00 ─ smoke_detect (start) 每 5 分鐘雙次快照
09:00 ─ strategy_divergence   每 5 分鐘掃描全日 CSV
    ⋮
13:30 ─ monitor_3661 (end)   最後一輪寫入
13:30 ─ smoke_detect (end)
13:30 ─ strategy_divergence (end)
13:35 ─ daily_summary        盤後摘要 → Telegram
```

Cron 表達式轉換：

| 時區 | 交易時段 | Cron |
|------|---------|------|
| CST (本地) | 週一～五 9:00-13:30 | `*/1 9-13 * * 1-5` |
| UTC (GitHub) | 週一～五 1:00-5:30 | `*/5 1-5 * * 1-5` |

---

## 煙霧彈偵測演算法

假掛單偵測的核心假設：**真正的賣壓會讓價格下跌，如果賣單暴增但價格不動，那就是假的。**

```
雙次快照法 (12 秒間隔):

Snapshot 1 ──── 12 秒 ────→ Snapshot 2
   │                              │
   ├─ ask_total: 30               ├─ ask_total: 91  ← +203%
   ├─ price: 4985                 ├─ price: 4985    ← 沒跌
   └─ volume: 125,341             └─ volume: 125,359 ← 只成交18張

判斷: 賣盤暴增但價格不跌 → 🔥 假賣壓訊號
```

四個訊號的觸發閾值與權重：

| 訊號 | 條件 | 可信度 |
|------|------|--------|
| 假賣壓 | ask_spike ≥ 1.5x AND ask ≥ 15張 AND price 不跌 | 中 |
| 抽單 | ask_drop ≥ 15張 AND vol_delta < drop × 0.5 | 高 |
| 背離 | ratio < 0.3 AND price ≥ high × 0.98 | 中高 |
| 整數防守 | 同價位 refresh ≥ 5次/數分鐘 | 低 (需 CSV 版) |

---

## CSV 規格

### 檔案命名
`{YYYYMMDD}_{STOCK_ID}.csv`  → 例：`20260513_3661.csv`

### 編碼
`UTF-8 with BOM` — 確保 Excel 直接開啟時中文欄位正確顯示

### 欄位定義（共 38 欄）

**原始欄位 (1-16)**
| # | 欄位 | 類型 | 說明 |
|----|------|------|------|
| 1 | timestamp | ISO 8601 | 2026-05-13T09:00:03 |
| 2 | time | HH:MM:SS | 09:00:03 |
| 3 | price | float/str | 即時成交價 (可能為 '-') |
| 4 | volume | int | 累積成交量 |
| 5 | open | float | 開盤價 |
| 6 | high | float | 日最高 |
| 7 | low | float | 日最低 |
| 8-9 | bid1_price, bid1_vol | float, int | 買一價/量 |
| 10-11 | bid2_price, bid2_vol | ... | ... |
| ... | ... | ... | 買二～買五 |
| 18-19 | ask1_price, ask1_vol | float, int | 賣一價/量 |
| ... | ... | ... | 賣二～賣五 |

**計算欄位 (17-38)**
| # | 欄位 | 公式 | 用途 |
|----|------|------|------|
| 17 | bid_total_vol | Σ(bid1..5 vol) | 買盤總量 |
| 18 | ask_total_vol | Σ(ask1..5 vol) | 賣盤總量 |
| 19 | bid_ask_ratio | bid/ask | >1.5偏多, <0.5偏空 |
| 20 | spread | ask1-bid1 | 流動性指標 |
| 21 | price_delta | price - prev_price | 跳動方向 |
| 22 | vol_delta | cum_vol - prev_cum_vol | 成交增量 |
| 23 | bid1_vol_delta | bid1 - prev_bid1 | 大單進場 |
| 24 | ask1_vol_delta | ask1 - prev_ask1 | 倒貨訊號 |
| 25 | bid_total_delta | bid_total - prev | 掛單堆積 |
| 26 | ask_total_delta | ask_total - prev | 掛單撤單 |
| 27 | trade_side | 1/-1/0 | 外盤/內盤/平盤 |
| 28 | change_pct | (price-open)/open | 漲跌幅 |
| 29 | amplitude_pct | (high-low)/open | 振幅 |
| 30 | bid_vol_pct | bid/(bid+ask) | 買盤佔比 |

---

## 容錯設計

1. **twstock feed 中斷**：`latest_trade_price` 可能回傳 `-`，CSV 保留原始值，分析腳本 fallback 到前一筆有效價格
2. **非交易時段**：所有腳本第一行檢查 `is_trading_time()`，非交易時段安靜退出
3. **GitHub Actions 延遲**：排程不保證準時，所有分析腳本自帶時間驗證
4. **Cron daemon 冷啟動**：WSL 重開後 cron 可能數分鐘後才啟動，`pre_market_warmup.py` 在 8:58 喚醒
5. **Telegram 發送失敗**：`telegram_utils.py` 自帶 timeout + fallback stdout

---

## 性能數據

| 指標 | 數值 |
|------|------|
| twstock API 回應時間 | ~0.17 秒/次 |
| 每日資料筆數 | ~5,400 筆 |
| CSV 檔案大小 | ~500KB/日 |
| Streamlit 載入時間 | <2 秒 (含 Plotly 渲染) |
| GitHub Actions 執行時間 | <30 秒 (含 pip install twstock) |
| 雙次快照延遲 | 12 秒 |

---

## 擴展性

要監控其他股票，只需修改 `STOCK_ID` 變數：

```python
STOCK_ID = "2330"  # 台積電
STOCK_ID = "2454"  # 聯發科
```

已有 `monitor_2454_risk.py` 作為聯發科風險評分的參考實作。
