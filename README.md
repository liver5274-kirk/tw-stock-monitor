# 3661 世芯-KY 即時監控系統

> 全自動台股五檔掛單監控 × AI 煙霧彈偵測 × 即時看盤儀表板

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub Actions](https://img.shields.io/badge/deploy-GitHub_Actions-2088FF.svg)](.github/workflows/)

---

## 一句話說完

**這是幫一個台股當沖交易者做的全自動監控系統。**

他每天盯盤 3661 世芯-KY，想知道主力什麼時候在「做手腳」——掛假單騙散戶、瞬間抽單、大單進場。以前靠肉眼盯五檔螢幕，現在全自動：每秒記錄、AI 判斷、異常直接推送到手機。

---

## 解決了什麼問題

| 沒有這個系統之前 | 有這個系統之後 |
|---|---|
| 手動盯五檔螢幕 4.5 小時 | 全自動記錄，事後分析 |
| 主力掛假單看不出來 | AI 即時偵測煙霧彈，推播到 Telegram |
| 不知道大單何時進場 | 每 3 秒記錄掛單變化，delta 一目了然 |
| 盤後回想「今天發生什麼事」 | CSV 完整記錄，Excel 直接拉圖 |
| 開盤錯過關鍵 5 分鐘 | 9:00 自動分析買賣力道 |

---

## 架構總覽

```
┌──────────────────────────────────────────────────────────┐
│                    資料來源層                              │
│  twstock Python API  ←→  TWSE 台灣證交所即時資料           │
└────────────┬─────────────────────────────┬───────────────┘
             │                             │
     ┌───────▼────────┐           ┌────────▼──────────┐
     │  WSL Cronjob    │           │  GitHub Actions    │
     │  (本機 24/7)    │           │  (雲端備援)        │
     │                 │           │                    │
     │ • 高頻 CSV 記錄  │           │ • 煙霧彈偵測       │
     │ • 背離策略       │           │ • 開盤分析         │
     │ • 盤前預熱       │           │ • 盤後摘要         │
     └───────┬────────┘           └────────┬──────────┘
             │                             │
             │    ┌────────────────────────┘
             │    │
     ┌───────▼────▼───────┐
     │   Telegram Bot     │  ← 即時推播到手機
     │   (@SK_Kirk)       │
     └────────────────────┘
             │
     ┌───────▼────────────┐
     │  Streamlit 看盤     │  ← 瀏覽器即時圖表
     │  dashboard_3661.py │
     └────────────────────┘
```

雙軌部署：WSL 本機負責高頻記錄（3 秒/筆），GitHub Actions 負責雲端備援分析。電腦關機也不漏訊號。

---

## 六大功能模組

### 1. 高頻五檔記錄（每 3 秒一筆）

`monitor_3661.py` — 交易時段每分鐘觸發，內部循環 55 秒，每 3 秒抓一次 twstock 即時資料。

一天約 5,400 筆資料，包含：

| 原始欄位 | 計算欄位 |
|----------|----------|
| 五檔買價/量 × 5 | 買賣力比 (bid/ask ratio) |
| 五檔賣價/量 × 5 | 價差 (spread) |
| 即時成交價 | 大單進場訊號 (delta ≥ 100) |
| 累積成交量 | 內外盤判斷 |
| 開高低 | 漲跌幅 / 振幅 |

```csv
timestamp,time,price,volume,...,bid_ask_ratio,spread,price_delta,bid1_vol_delta,...
2026-05-13T09:00:03,09:00:03,4985.0,125341,...,1.45,5.0,0.0,0,...
2026-05-13T09:00:06,09:00:06,4990.0,125358,...,2.10,5.0,+5.0,128,...
                                                            ↑ 大買單進場！
```

### 2. 煙霧彈偵測（4 種訊號）

`smoke_detect_3661.py` — 每 5 分鐘雙次快照比對，偵測主力假動作：

| 訊號 | 邏輯 | 範例 |
|------|------|------|
| 🔥 假賣壓 | 賣盤暴增 1.5x 但價格不跌 | ask: 30→91 張，price 沒動 → 假的 |
| 🚨 抽單 | 賣盤瞬間消失但成交量沒跟上 | ask: 91→12 張，僅成交 18 張 → 61 張是抽單 |
| ⚠ 背離 | 買賣比極空(<0.3)但價格逼近日高 | ratio=0.15，價格在日高 98% → 假的 |
| 📊 整數防守 | 整數價位掛單重複刷新 ≥5 次 | 5000 元賣盤一直取消又掛 → 畫線 |

**偵測到 → 即時推播 Telegram：**

<img src="docs/smoke-alert-example.png" alt="煙霧彈 Telegram 推播範例" width="400">

### 3. 開盤分析

`open_analysis_3661.py` — 每天 9:00 自動跑，產出即時五檔分析報表：

```
📊 3661 世芯-KY 開盤即時分析 [09:00:15]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💰 成交價: 4985.0  成交量: 125,341
📈 開: 4970  高: 4995  低: 4965

📋 五檔掛單
    賣5  5020  × 12    買5  4940  × 28
    賣4  5010  × 18    買4  4950  × 35
    賣3  5000  × 45    買3  4955  × 22
    賣2  4995  × 31    買2  4960  × 41
    賣1  4990  × 15    買1  4965  × 53

📊 買盤 179 張 vs 賣盤 121 張  → 買賣力比 1.48 (偏多)
💡 價差: 5.0  (流動性良好)
```

### 4. 盤後摘要

`daily_summary_3661.py` — 13:35 收盤後自動推送當日總結：

- OHLCV 完整走勢
- 今日高低點與振幅
- 煙霧彈訊號回顧
- 買賣力比變化趨勢
- 大單進出統計

### 5. Streamlit 即時看盤儀表板

`dashboard_3661.py` — 一鍵啟動，瀏覽器看盤：

```
streamlit run dashboard_3661.py
```

功能：
- **即時價格線圖**（Plotly，含煙霧彈事件標記 🔶🔴🟣）
- **買賣力道對比圖**（bid/ask 比例趨勢 + 參考線）
- **五檔深度橫條圖**（買賣掛單視覺化）
- **價差趨勢圖**（絕對值 + 百分比，流動性警報線）
- **大單進場標記**（bid1_vol_delta ≥ 100 的三角形標示）
- **多日疊圖對比**（可選 2/3/5/10 天走勢疊加）
- **暗黑模式**（深夜看盤友善）

<img src="docs/dashboard-screenshot.png" alt="Streamlit 看盤畫面" width="800">

### 6. 背離交易策略

`strategy_3661_divergence.py` — 基於買賣力比與價格的背離訊號，自動判斷進出場時機：

- 買賣力比急升但價格未跟 → 潛在買點
- 買賣力比驟降但價格在高檔 → 潛在賣點
- 全日 CSV 連續資料分析（需 WSL 本機執行）

---

## 技術棧

| 層 | 技術 |
|----|------|
| 資料來源 | twstock (Python TWSE API wrapper) |
| 排程引擎 | WSL Cron + GitHub Actions |
| 資料儲存 | CSV (UTF-8 BOM, Excel 友善) |
| 視覺化 | Streamlit + Plotly |
| 推播通道 | Telegram Bot API |
| 語言 | Python 3.11+ |
| 部署 | WSL2 (Ubuntu) + GitHub Actions |

---

## 快速開始

### 前置需求

```bash
pip install twstock streamlit pandas plotly
```

### 1. 啟動高頻記錄（本機）

```bash
# 放在 crontab 每分鐘執行（交易時段 9:00-13:30）
python monitor_3661.py
```

CSV 輸出到 `C:\Temp\財經分析2026\{日期}_3661.csv`

### 2. 啟動看盤儀表板

```bash
streamlit run dashboard_3661.py
```

瀏覽器打開 `http://localhost:8501`

### 3. 設定 Telegram 推播

在 GitHub Secrets 設定：
- `TELEGRAM_BOT_TOKEN`: 你的 Bot Token
- `TELEGRAM_CHAT_ID`: 接收訊息的 Chat ID

GitHub Actions 會自動在交易時段執行分析並推播。

---

## 專案結構

```
tw-stock-monitor/
├── scripts/
│   ├── monitor_3661.py          # 高頻五檔記錄（WSL cron）
│   ├── smoke_detect_3661.py     # 煙霧彈偵測（GitHub Actions）
│   ├── open_analysis_3661.py    # 開盤分析
│   ├── daily_summary_3661.py    # 盤後摘要
│   ├── strategy_3661_divergence.py  # 背離交易策略（WSL）
│   ├── monitor_2454_risk.py     # 聯發科風險評分（參考）
│   └── telegram_utils.py        # Telegram 發送共用模組
├── dashboard_3661.py            # Streamlit 看盤儀表板
├── .github/workflows/
│   ├── open-analysis.yml        # 9:00 開盤分析
│   ├── smoke-detect.yml         # 每5分煙霧彈偵測
│   └── daily-summary.yml        # 13:35 盤後摘要
├── docs/
│   ├── dashboard-screenshot.png # 儀表板截圖
│   └── smoke-alert-example.png  # 推播範例
└── requirements.txt
```

---

## 實際成效

- 每日自動記錄 **5,400+** 筆五檔資料
- 煙霧彈偵測命中率：曾成功預警主力抽單（ask 91→12 張，僅成交 18 張）
- 開盤分析 9:00 準時推送，零遺漏
- 雙軌部署（WSL + GitHub Actions），電腦關機仍可收到雲端分析

---

## 為什麼這個專案能展示我的能力

這是從 **需求訪談 → 系統設計 → 實作 → 部署 → 維運** 的完整案例：

1. **理解領域知識**：不是只寫 code，而是理解台股五檔掛單、當沖手法、主力行為模式
2. **系統架構**：雙軌部署、容錯設計、CSV fallback、時區轉換
3. **自動化維運**：從 crontab 到 GitHub Actions，從本機到雲端
4. **即時資料處理**：3 秒級高頻寫入、delta 計算、訊號觸發
5. **使用者介面**：Streamlit 儀表板從 4 面板擴展到暗黑模式+多日對比

---

## 聯繫

- GitHub: [@liver5274-kirk](https://github.com/liver5274-kirk)
- Telegram: [@SK_Kirk](https://t.me/SK_Kirk)
- Email: kirk.shangkuan@gmail.com

---

*本專案僅供學習與展示用途，不構成任何投資建議。*
