# tw-stock-monitor

台灣股市即時監控 — 3661 世芯-KY 五檔掛單、煙霧彈偵測、開盤分析

## 架構

| 腳本 | 觸發時間 (CST) | 說明 |
|------|---------------|------|
| `open_analysis_3661.py` | 9:00 | 開盤五檔買賣盤即時分析 |
| `smoke_detect_3661.py` | 每 5 分鐘 9:00-13:30 | 煙霧彈偵測（假賣壓/抽單/背離） |
| `daily_summary_3661.py` | 13:35 | 盤後摘要（OHLCV + 走勢判斷） |

所有腳本透過 GitHub Actions 排程自動執行，結果直接推送到 Telegram。

## 設定

### 1. GitHub Secrets

在 repo Settings → Secrets and variables → Actions 設定：

- `TELEGRAM_BOT_TOKEN`: Telegram Bot Token
- `TELEGRAM_CHAT_ID`: 接收訊息的 Chat ID（例如 `7563516842`）

### 2. 手動測試

在 Actions 頁面選擇 workflow → **Run workflow** 手動觸發。

## 注意事項

- GitHub Actions 排程使用 **UTC 時區**，workflow 中已轉換為 CST
- GitHub 不保證排程準時執行，可能有數分鐘延遲
- 背離交易策略 (`strategy_3661_divergence.py`) 需要全日 CSV 連續資料，仍保留在 WSL 執行
- CSV 高頻記錄 (`monitor_3661.py`) 保留在 WSL 本機執行
