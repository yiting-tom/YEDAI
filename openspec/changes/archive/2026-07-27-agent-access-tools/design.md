## Context

現有介面是**量測工具的形狀**：一次一個查詢、一次一筆全文。agent 的實際行為不是這樣——它批次讀、沿關聯跳、在範圍縮小後回頭做字面搜尋。

整個專案的收斂點在前期討論就已確立：

> 不要用 RAG 取代 agentic file search，用檢索把 N 個 bundle 縮到 2~3 個，
> 然後在那個縮小的範圍裡跑原本就有效的 agentic file search。

前半段（縮範圍）已經有了，後半段（在縮小範圍裡做字面搜尋）完全沒有。本變更補齊後半段，並把整條路徑包成 agent 可直接呼叫的工具。

## Goals / Non-Goals

**Goals:**

- 讓 agent 能以「菜單 → 批次取全文 → 沿關聯跳 → 範圍內字面搜尋」完成一輪完整工作
- HTTP 與 MCP 兩個介面共用同一份核心實作，不出現行為分歧
- 工具說明本身就引導正確用法，降低 agent 誤用（例如直接把 grep 當全域搜尋）

**Non-Goals:**

- 不做寫入路徑（`propose` / `amend` / `retire`）
- 不做任意深度的圖查詢或圖演算法——`related` 展開上限 2 跳
- 不做結果快取
- 不做存取控制

## Decisions

### D1. `grep` 強制限定範圍，拒絕全域搜尋

`grep` **必須**指定 `bundle_ids` 或 `concept_ids` 至少其一，否則回絕。

這不是效能保護，是**設計意圖的強制執行**。全域 grep 在 10 萬 bundle（30–40 GB）上要跑一到兩分鐘，而且回傳數百條命中讓 agent 無從分流——那正是這整套系統要解決的問題。允許無範圍 grep 等於提供一條繞過檢索層的退路，agent 會用它，然後我們回到原點。

錯誤訊息明確指示：先用 `search` 縮範圍，再用其 `bundle_id` 呼叫 `grep`。

### D2. `grep` 預設字面比對，正則需明確開啟

| | 預設 | 開啟 `regex=true` |
|---|---|---|
| 比對方式 | 字面子字串 | Python 正則 |
| 病態回溯風險 | 無 | 有 |

使用者提供的正則可能觸發災難性回溯，而 Python 的 `re` 沒有執行時間上限。緩解：正則為選擇性開啟、範圍已強制限定、檔案數與結果數皆有上限，且無效正則回報明確錯誤而非 500。

不外呼 `ripgrep`：範圍已縮到數個 bundle，Python 的效能綽綽有餘，而外呼會引入外部相依與子行程介面。

### D3. 關聯邊存進索引，出向與入向都存

`related` 目前只存在於 frontmatter，`DocMeta` 沒有保留，所以索引無法回答「誰指向我」。

新增 `Index.related_out: dict[str, list[str]]` 與 `Index.related_in: dict[str, list[str]]`，皆以 `concept_id` 為鍵。入向在建索引時一併算好——它是 agent 最常需要但最難自己拼出來的資訊（「還有哪些文件引用了這個概念」）。

**懸空引用**（`related` 指向語料中不存在的 id）單獨列出而非靜默丟棄。以模型產生的 concept 來說，這個數字本身就是語料品質的訊號。

索引結構改變 → 格式版本 2 → 3。

### D4. 批次取全文採部分成功語意

`POST /concepts` 回傳 `{concepts: [...], errors: [{concept_id, reason}]}`。

單一 id 不存在就讓整批失敗，會逼 agent 退回逐筆呼叫，等於白做。上限 50 筆——超過的話 agent 應該先縮範圍，而不是把整個 bundle 拉進 context。

### D5. `runtime.py` 統一載入路徑

目前 `api.py:_load_state()` 自己組裝 config → dictionary → index → searcher → store。MCP server 需要一模一樣的東西。複製一份必然在某次修改後分歧。

抽出 `Runtime.load()`，兩個介面都用它。`api.py` 的既有行為（載入失敗仍能回應 `/healthz`）保持不變。

### D6. MCP 工具說明負責引導用法

MCP 工具的 description 是 agent 唯一的使用說明。三件事必須寫進去：

1. `search` 只回菜單，要內容得呼叫 `get_concept` / `get_concepts`
2. `grep` 必須先有範圍，範圍從 `search` 結果的 `bundle_id` 來
3. 建議流程：`search` → 挑 3~7 筆 → `get_concepts` → 需要時 `neighbors` 或 `grep`

工具描述若只寫「搜尋 concept」，agent 會把 `search` 當成唯一入口，然後抱怨資訊不足。

### D7. MCP 用 stdio

claude-agent-sdk 的標準接法。不需要另起 HTTP 服務、不佔連接埠、程序生命週期由呼叫端管理。HTTP 介面繼續存在，服務的是人與量測腳本。

## Risks / Trade-offs

- **使用者正則造成病態回溯** → 正則需明確開啟、範圍強制限定、檔案與結果數上限；無效正則回 422 而非 500
- **批次取全文回應體積**（50 × 4 KB ≈ 200 KB） → 上限 50 筆，且 `include_raw=false` 可只取結構化欄位
- **入向邊的建構成本**（需掃過全部 `related`） → 與 concept 數線性，建索引本來就要走一遍
- **兩個介面的行為分歧** → D5 的共用 runtime 是唯一防線；測試須同時覆蓋 HTTP 與 MCP 兩條路徑
- **格式版本再次提升迫使重建索引** → 一次性成本，錯誤訊息已明確指示

## Open Questions

- `neighbors` 是否需要依 `type` 過濾（例如「只展開 spec_definition 類的鄰居」）——待 agent 實際使用後決定
- MCP 是否需要 `list_bundles` 工具取代 glob——目前 `stats` 已含 type 分佈，先觀察是否足夠
