## Why

YED 知識助理目前在 10~30 個 OKF bundle 規模下，靠 agent 的 grep/glob 檔案搜尋就能得到很好的結果，但語料預計成長到 10 萬個 bundle（約 220 萬個 concept）。在投入混合檢索、實體向量、issue family 等複雜架構之前，必須先建立**水位線**：純關鍵字檢索到底能做到多好。

關鍵未知數是「識別碼」——concept 文字主體是機台 id、製程 id、flow 等專有字詞，而一般斷詞會把 `TEL-05` 碎成 `tel` + `05`，使其與 `TEL-06` 難以區分。本變更要用可量測的方式回答：**識別碼到底需不需要特別處理？需要的話，斷詞層就夠了，還是必須維護實體字典？**

此外真實語料為公司機密無法外流，因此本工具必須同時產出**可分享的去識別化統計報告**，否則收集到的數據無法用於後續討論。

## What Changes

- 新增 OKF bundle 解析器，支援 `manifest.json` + `okf/*.md` 結構，容忍缺欄位、缺 frontmatter 分隔線、壞檔（單檔失敗不中斷整批）
- 新增三組並排的檢索模式，構成消融實驗（ablation）：
  - **模式 A**：天真 BM25F，識別碼被一般斷詞切碎（水位線）
  - **模式 B**：BM25F + 識別碼保護斷詞，識別碼正規化為單一 token
  - **模式 C**：模式 B + 實體字典精確匹配加權
- 新增實體字典載入與抽取，字典未命中但符合識別碼樣式者標記為 `unknown` 來源，用以量測**字典覆蓋率缺口**
- 新增 CLI：`index` / `search` / `compare` / `report` / `gen-synthetic`
- 新增 FastAPI HTTP 介面：`/search`（單模式或三模式並排）、`/feedback`（記錄點選，作為隱性相關性標註）、`/stats`、`/report`、`/healthz`
- 新增雙軌查詢遙測：本機完整日誌（含查詢內容，不外流）＋ 去識別化統計報告（零內容，僅分佈與模式間 top-k 重疊度等數值指標）
- 新增合成 OKF bundle 產生器，讓無真實資料時仍可端到端驗證

## Capabilities

### New Capabilities
- `okf-bundle-parsing`: 將 OKF bundle 目錄解析為結構化 concept 模型，含 frontmatter、section、figures，並容錯回報
- `keyword-retrieval`: BM25F 欄位加權檢索與 A/B/C 三模式消融，含識別碼保護斷詞
- `entity-matching`: 實體字典載入、正規化、抽取，以及模式 C 的實體匹配計分與字典覆蓋率量測
- `retrieval-telemetry`: 雙軌查詢日誌與去識別化統計報告產出
- `search-interfaces`: CLI 與 FastAPI 兩種操作介面
- `synthetic-fixtures`: 合成 OKF bundle 產生器，供無真實資料時驗證

### Modified Capabilities
（無，此為專案第一個變更）

## Impact

- **新增程式碼**：`src/yedai/`（parser、tokenizer、entities、index、search、telemetry、cli、api）、`scripts/gen_synthetic.py`、`tests/`
- **新增相依**：`pyyaml`、`fastapi`、`uvicorn`、`typer`、`rich`（皆為輕量、無外部服務）
- **不引入**：向量資料庫、embedding 模型、graph DB、Postgres——本變更刻意只做關鍵字檢索，作為後續架構決策的對照基準
- **資料安全**：真實 bundle 永不進入版控；完整日誌預設寫入 gitignored 目錄；僅去識別化報告設計為可外流
- **後續銜接**：本變更產出的數據將決定是否投入實體稀疏向量、混合檢索與 issue family 等後續架構
