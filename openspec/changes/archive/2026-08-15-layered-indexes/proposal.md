## Why

語料要從單一合成集合換成四類**性質不同**的查案知識：查案心法、closed cases、defect library、defect→module taxonomy。目前它們會全部落進同一個 `Index`，共用同一組 `df` / `avg_field_len`，而這在三件事上是錯的：

1. **idf 會隨時間漂移。** closed cases 持續累積至上萬筆，心法只有相對少量。混在同一套詞彙統計裡，心法的詞在全語料看起來都罕見、idf 被系統性高估；而且每進一批新案件，既有心法的排名就改變一次——沒有任何變更、沒有任何測試會紅，檢索品質卻退化了。`candidates` 過濾解不了這件事，因為 idf 仍是全域的。
2. **這四類該用不同的檢索方式。** 同一個查詢送進不同層意義不同：識別碼在 closed cases 是主訊號，在心法與 defect library 是雜訊。差異發生在 query 進入檢索之前，不是同一個 `Searcher` 加過濾器能表達的。
3. **taxonomy 根本不是文件集合。** 它是每個 defect 一條的判斷方法，存取方式是「以 defect 為鍵取回」，不是「回傳 top-k」。放進倒排索引會讓呼叫端拿到「最像的幾列」而不是「那一條」。

同時，taxonomy 的內容是 fab 專有知識，依本專案的公開邊界不得進入 repo；做成可抽換的查表資源，這條界線才守得住。

## What Changes

- **BREAKING** 設定從單一 `index_path` 純量改為具名索引集合。每個索引宣告自己的語料來源、輸出路徑、向量 collection，以及自己的檢索設定（預設模式、欄位權重、query 前處理）。
- **BREAKING** 索引格式版本提升。既有 `.index/*.pkl` 全部失效，必須重建。
- 每個索引持有**獨立的** `TermSpace` / `EntitySpace` 統計。跨索引不共用 `df`、`avg_field_len`、實體 idf。
- 檢索預設**分層回傳**：各層各自 top-n、各自帶分數與層標籤，不跨層排序。跨層 RRF 融合保留為顯式選項，供與分層做對照實驗，不作預設。
- 每層可宣告 query 前處理（例如是否保留識別碼），使同一個查詢字串在不同層以不同形式進入檢索。
- taxonomy 移出檢索路徑，改為以 defect 為鍵的查表資源；repo 內只保留 schema 與 example，實際內容走 `.local`。
- 新增回歸測試：**新增 closed cases 不改變心法層既有查詢的結果**。此測試在單一索引下必定失敗，是本次架構決定的可執行斷言。
- CLI / HTTP / MCP 取得選擇索引的方式；未指定時走分層全查。
- 報告依層拆解統計（語料規模、實體覆蓋率、詞彙量），全域數字保留但不再是唯一視角。

不在本次範圍（後續獨立 change）：closed cases 層的結構化比對、以歷史結案做 root-cause 回放評估、defect report 逐頁攝入、圖像檢索。

## Capabilities

### New Capabilities
- `layered-indexes`: 具名索引集合的宣告、建構、載入與隔離保證；分層檢索結果的形狀；每層獨立的檢索設定與 query 前處理。
- `defect-taxonomy-lookup`: 以 defect 為鍵的 taxonomy 查表資源——schema、載入、覆蓋率統計、查無條目時的行為。不進檢索索引。

### Modified Capabilities
- `keyword-retrieval`: 「索引建構與快取」從單一索引改為具名索引集合；新增跨索引統計隔離的要求；索引需帶所屬層的識別。
- `search-interfaces`: 設定檔 schema 變更（`index_path` → `indexes`）；CLI 索引建構與查詢指令需接受索引選擇；HTTP 查詢端點回應改為分層結構。
- `retrieval-telemetry`: 報告統計依層拆解；跨層融合與分層兩種模式的結果需可區分記錄。

## Impact

**設定與資料**
- `config.example.yaml` / `config.local.yaml`：`index_path` 移除，改為 `indexes` 對應表。
- 既有索引檔全部失效（格式版本提升），須以 `--rebuild` 重建。
- 新增 taxonomy 資源檔的 example 與 `.local` 對應，並確認 `.gitignore` 已涵蓋。

**程式**
- `config.py`：新增索引集合的設定型別與驗證；`index_signature` 需納入所屬層。
- `index.py`：`build_index` 以單一索引為單位；`Index` 帶層識別；格式版本提升。
- `search.py`：`Searcher` 綁定單一索引；新增分層檢索的協調層與結果型別；既有 `rrf()` 複用於可選的跨層融合。
- `cli.py`：`index` / `search` / `compare` 接受索引選擇；輸出改為分層呈現。
- `api.py` / `runtime.py` / `mcp_server.py`：載入多個索引；查詢端點回應結構變更。
- `vectors.py`：collection 依索引命名。
- `telemetry.py`：報告依層拆解。

**已知牽連**
- `runtime.py` 目前建 `Searcher` 時不帶 `vectors`，導致 HTTP / MCP 的 mode D/E 必定失敗（見 `docs/data-flow.md` 缺口表）。本次改動會重寫該處的載入路徑，順帶修掉是自然的，但不作為本 change 的目標。
- defect library 同時是 `EntityDictionary` 的來源，其更新會使其他層的 signature 失效。重建順序因此有依賴關係，需顯式處理而非依賴呼叫者記得。
- 公開邊界：module 清單、defect 名稱、taxonomy 內容皆為 fab 專有知識，只得存在於 `.local`；repo 內僅保留機制、schema 與形狀範例。
