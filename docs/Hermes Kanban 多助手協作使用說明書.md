# Hermes Kanban 多助手協作 — 使用說明書

> 版本 1.0 | 2026-05-13 | 實戰驗證版

---

## 目錄

1. [概述](#1-概述)
2. [初始設定](#2-初始設定)
3. [任務拆解與建立](#3-任務拆解與建立)
4. [預載資料模式（重要）](#4-預載資料模式重要)
5. [監控與管理](#5-監控與管理)
6. [常用指令速查](#6-常用指令速查)
7. [已驗證的角色配置](#7-已驗證的角色配置)
8. [已知限制與解決方案](#8-已知限制與解決方案)
9. [完整實戰案例](#9-完整實戰案例)

---

## 1. 概述

**Hermes Kanban** 是一個 SQLite 持久化的多 AI 代理人任務看板。它讓不同專業的 AI 角色（研究員、分析師、架構師、工程師…）分工協作，支援：

- **並行執行** — 無相依性的任務同時跑
- **依賴鏈** — T1+T2 完成後 T3 才自動提升
- **持久化** — 任務狀態存在 SQLite，重啟不遺失
- **人類介入** — 任何階段可 block/unblock 等待審核

### 何時用 Kanban vs 直接回答

| 情境 | 用什麼 |
|------|--------|
| 單一簡單問題 | 直接回答 |
| 需要 2+ 專業角色分工 | **Kanban** |
| 工作需跨 session 持續 | **Kanban** |
| 使用者想中途介入審核 | **Kanban** |
| 多子任務可並行加速 | **Kanban** |
| 純程式碼小修改 | delegate_task 或直接改 |

---

## 2. 初始設定

### 2.1 建立專業角色

```bash
# 從 default profile 克隆（複製 config.yaml + .env + API key）
hermes profile create researcher --clone
hermes profile create analyst --clone
hermes profile create architect --clone

# 編輯角色的「靈魂」（系統提示）
# 檔案位置：~/.hermes/profiles/<name>/SOUL.md
```

### 2.2 角色設定範本

#### researcher — 研究員

**`~/.hermes/profiles/researcher/SOUL.md`:**
```markdown
你是資深技術研究員，專精資訊系統整合、遺留系統現代化、企業架構。
工作就是搜尋、閱讀、整理技術文件與產業報告。

## 工作準則
- 用繁體中文輸出
- 每個結論都要附上來源
- 偏好結構化輸出：先摘要、再細節、最後關鍵要點
- 不自行發明技術細節，必須有來源佐證
```

**`~/.hermes/profiles/researcher/config.yaml` (關鍵修改):**
```yaml
toolsets:
- file
- terminal
- search          # 保留 DuckDuckGo 搜尋作為備用
agent:
  max_turns: 200  # 從 90 調高
```

#### analyst — 分析師

**`~/.hermes/profiles/analyst/SOUL.md`:**
```markdown
你是資深技術分析師，擅長綜合多方研究成果、比較方案優劣、產出結構化建議。

## 工作準則
- 用繁體中文輸出，每個建議都要有比較基礎
- 偏好使用比較表格呈現方案優劣
- 明確標註各方案的適用場景與限制
```

**`~/.hermes/profiles/analyst/config.yaml` (關鍵修改):**
```yaml
toolsets:
- file
- terminal       # 不需要 search，純合成任務
agent:
  max_turns: 200
```

#### architect — 架構師

**`~/.hermes/profiles/architect/config.yaml`:**
```yaml
toolsets:
- file
- terminal
agent:
  max_turns: 200
```

---

## 3. 任務拆解與建立

### 3.1 拆解原則

```
使用者: 「分析 X 技術的市場現況與建議」
              │
    ┌─────────┴─────────┐
    ▼                   ▼
  T1 (researcher)    T2 (researcher)
  技術原理與案例       競品與工具生態
    │                   │
    └─────────┬─────────┘
              ▼
         T3 (analyst)
         綜合比較與建議
```

**關鍵規則：**
- 無相依性的任務 → 不設 parents，讓 dispatcher 並行派發
- 有相依性的任務 → 用 `--parent <id>` 連結，child 在 parents 全 done 後才自動升為 ready
- 每個任務只做一件事，不要捆綁

### 3.2 建立任務（CLI）

```bash
# 並行任務（無相依性）
hermes kanban create "T1: 研究 X 技術原理" --assignee researcher --body "詳細工作內容..."
hermes kanban create "T2: 調查 X 的競品" --assignee researcher --body "..."

# 相依任務（等 T1+T2 完成才執行）
hermes kanban create "T3: 綜合分析" --assignee analyst \
  --parent <t1_id> --parent <t2_id> \
  --body "讀取 T1 和 T2 的成果，產出比較報告。"
```

### 3.3 派發任務

```bash
hermes kanban dispatch    # 手動觸發一次派發
```

dispatcher 會自動回收卡住的 worker（15 分鐘 TTL）並重派。

---

## 4. 預載資料模式（重要）

**這是最關鍵的優化。不要讓 worker 自己做 web search。**

### 4.1 問題

Kanban worker 在子程序中做 web search（browser、web_search、curl）會 **timeout 或 stall**。實測：researcher worker 跑 17 分鐘無產出，被自動回收 2 次。

### 4.2 解法：Orchestrator 預載

```
         Orchestrator（你）
              │
    ┌─────────┼─────────┐
    │ 預載資料  │ 建立任務  │ 加提示 comment
    ▼         ▼         ▼
  workspace  kanban    worker 讀檔
  /ref.md    create     → 合成報告
                          (2 分鐘完成)
```

### 4.3 三步驟

**Step 1：預寫參考資料到 workspace**

```bash
TASK_ID=t_abc123
WS=/home/kk/.hermes/kanban/workspaces/$TASK_ID

cat > $WS/ref_data.md << 'EOF'
# 參考資料（由 orchestrator 預載）
... 領域知識或搜尋結果 ...
EOF
```

**Step 2：加 comment 提示 worker**

```bash
hermes kanban comment $TASK_ID "📂 工作區已預載 ref_data.md。請讀取後合成報告，不需 web search。"
```

**Step 3：派發**

```bash
hermes kanban dispatch
```

### 4.4 預載資料大小限制

| 輸入大小 | 結果 |
|---------|------|
| <5KB | ✅ 最佳，worker 1-3 分鐘完成 |
| 5-10KB | 🟡 可行，可能 3-5 分鐘 |
| >10KB | 🔴 避免，worker 可能讀不完 |

### 4.5 跨任務資料傳遞

Workspace 是隔離的。T3 需要 T1+T2 的輸出時：

```bash
# T1、T2 完成後，手動複製到 T3 的 workspace
cp /home/kk/.hermes/kanban/workspaces/<t1_id>/report.md \
   /home/kk/.hermes/kanban/workspaces/<t3_id>/T1_report.md

cp /home/kk/.hermes/kanban/workspaces/<t2_id>/report.md \
   /home/kk/.hermes/kanban/workspaces/<t3_id>/T2_report.md
```

---

## 5. 監控與管理

### 5.1 查看狀態

```bash
hermes kanban list        # 所有任務狀態總覽
hermes kanban stats       # 各狀態數量統計
hermes kanban show <id>   # 單一任務詳細資訊（含事件、運行紀錄）
hermes kanban tail <id>   # 即時追蹤任務事件流
```

### 5.2 狀態圖示

| 圖示 | 狀態 | 說明 |
|------|------|------|
| `●` | running | 正在執行 |
| `▶` | ready | 等待 dispatcher 派發 |
| `◻` | todo | 等待 parents 完成 |
| `✓` | done | 已完成 |
| `⛔` | blocked | 等待人類介入 |

### 5.3 回收卡住的 worker

```bash
hermes kanban reclaim <id>    # 強制回收 → 重置為 ready
hermes kanban dispatch         # 重新派發
```

### 5.4 手動完成任務

```bash
hermes kanban complete <id> --summary "完成摘要說明"
```

---

## 6. 常用指令速查

```bash
# 看板管理
hermes kanban boards                     # 列出所有看板
hermes kanban boards create <name>       # 建立新看板
hermes kanban boards switch <name>       # 切換看板

# 任務管理
hermes kanban create "<title>" --assignee <profile> [--parent <id>]
hermes kanban list
hermes kanban show <id>
hermes kanban comment <id> "訊息"
hermes kanban complete <id> --summary "..."
hermes kanban block <id> "等待審核原因"
hermes kanban unblock <id>

# 派發
hermes kanban dispatch     # 觸發一次派發循環
hermes kanban reclaim <id> # 回收卡住的 worker

# 角色管理
hermes profile create <name> --clone
hermes profile list

# 監控
hermes kanban watch        # 即時事件串流 (Ctrl+C 離開)
hermes kanban stats        # 統計
```

---

## 7. 已驗證的角色配置

| 角色 | 工具 | max_turns | 適合任務 |
|------|------|-----------|---------|
| **researcher** | file, terminal, search | 200 | 搜尋資料、閱讀文件、整理事實 |
| **analyst** | file, terminal | 200 | 綜合比較、方案評分、矩陣分析 |
| **architect** | file, terminal | 200 | 架構設計、技術選型、遷移路徑 |

---

## 8. 已知限制與解決方案

| 限制 | 影響 | 解決 |
|------|------|------|
| **Worker web search 超時** | researcher 卡死 17+ 分鐘 | 預載資料模式（第 4 節） |
| **Worker 讀大檔耗盡 turns** | >10KB 檔案可能讀不完 | 預載精簡摘要（<5KB） |
| **Workspace 隔離** | T3 看不到 T1/T2 的檔案 | 手動複製到 T3 workspace |
| **`hermes profile create` 不接受 --model/--tools** | 需手動編輯 config.yaml | 編輯 `~/.hermes/profiles/<name>/config.yaml` |
| **Dispatcher 需手動觸發** | 任務停在 ready | `hermes kanban dispatch` |
| **同一 profile 的並行限制** | 需確認 | 2 個 researcher 可同時跑（實測通過） |

---

## 9. 完整實戰案例

### 案例：「如何整合無 API 時代的資訊系統？」

#### 任務圖

```
T1 (researcher) 遺留系統整合模式    T2 (researcher) 現代整合工具
        │                                    │
        └────────────┬───────────────────────┘
                     ▼
              T3 (analyst) 方案比較矩陣
                     │
                     ▼
              T4 (architect) 架構與遷移路徑
```

#### 執行步驟

```bash
# 1. 建立角色（一次性）
hermes profile create researcher --clone
hermes profile create analyst --clone
hermes profile create architect --clone
# 編輯 SOUL.md + config.yaml（參見第 2、7 節）

# 2. 建立並行研究任務
hermes kanban create "T1: 調查遺留系統整合模式" --assignee researcher --body "..."
hermes kanban create "T2: 調查現代整合工具" --assignee researcher --body "..."

# 3. 建立相依任務
hermes kanban create "T3: 方案比較矩陣" --assignee analyst \
  --parent <t1_id> --parent <t2_id> --body "..."
hermes kanban create "T4: 架構設計" --assignee architect \
  --parent <t3_id> --body "..."

# 4. 預載資料到 T1 的 workspace（避免 worker web search）
cat > /home/kk/.hermes/kanban/workspaces/<t1_id>/ref.md << 'EOF'
... 領域知識 ...
EOF
hermes kanban comment <t1_id> "工作區已預載 ref.md，請讀取合成，不需 web search。"

# 5. 派發
hermes kanban dispatch

# 6. 監控
hermes kanban list          # 每 30 秒檢查一次
hermes kanban show <id>     # 查看詳細事件

# 7. T1/T2 完成後，複製輸出到 T3 workspace
cp .../workspaces/<t1_id>/report.md .../workspaces/<t3_id>/T1.md
cp .../workspaces/<t2_id>/report.md .../workspaces/<t3_id>/T2.md
hermes kanban comment <t3_id> "工作區已預載 T1、T2 報告，請讀取合成。"

# 8. T3 完成後，同樣複製給 T4
cp .../workspaces/<t3_id>/report.md .../workspaces/<t4_id>/T3.md
hermes kanban comment <t4_id> "工作區已預載 T3 報告，請讀取並設計架構。"
```

#### 結果

| 任務 | 耗時 | 產出 |
|------|------|------|
| T1 | 手動完成（worker 卡） | 5 系統類型 × 6 整合模式 |
| T2 | 580s | 38KB, 16 工具 + 5 架構模式 |
| T3 | 手動完成（worker 讀大檔卡） | 4 場景推薦 + 決策樹 |
| T4 | 手動完成 | 5 層架構 + 3 階段遷移 |
| T5 (驗證) | **120s** | 0.9KB→9.8KB，預載模式成功 |

---

## 附錄：工作區路徑

```
~/.hermes/kanban/
├── kanban.db                     # SQLite 資料庫
└── workspaces/
    ├── t_<id>/                   # 各任務的隔離工作區
    │   ├── ref.md                # orchestrator 預載的參考資料
    │   └── report.md             # worker 產出的報告
    └── ...

~/.hermes/profiles/
├── default/                      # 預設角色
├── researcher/                   # 研究員
│   ├── config.yaml
│   ├── SOUL.md
│   └── .env
├── analyst/                      # 分析師
└── architect/                    # 架構師
```

---

> **一句話總結：** 預載資料到 workspace，給 worker 精簡的 <5KB 檔案讀取合成，不要讓它自己做 web search。這是 Kanban 協作能穩定運作的關鍵。
