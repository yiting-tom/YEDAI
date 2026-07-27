## Context

`build_index()` 目前對每個 concept 呼叫 `field_texts()` 取出六個欄位、轉成詞元後只保留統計量，`DocMeta`（`index.py:27`）僅存 metadata。body 在建索引結束後就不存在於任何執行期結構中。

因此要提供全文，必須先決定：**內容從哪裡來。**

另一個現實約束：語料規模預計成長到約 220 萬個 concept、每個約 300 行（合計 30–40 GB markdown）。任何「把內容放進索引」的做法都要先通過這個尺度的檢驗。

## Goals / Non-Goals

**Goals:**

- 讓 agent 能以 `concept_id` 取回完整可讀內容，補上 data flow 的斷點
- 同時提供原始 markdown 與解析後結構，讓「直接餵給 LLM」與「程式化取用」兩種消費者都不必再自己解析
- 讀取邏輯與傳輸層分離，使後續 MCP server 能重用同一份實作

**Non-Goals:**

- 不做批次取用（`POST /concepts`）、`neighbors` 展開、限定範圍 `grep`——本變更只補最關鍵的單一端點
- 不做快取層。單檔讀取在本規模下不構成瓶頸，先量測再優化
- 不做存取控制與內容遮蔽

## Decisions

### D1. 全文於請求時從磁碟讀取，不存進索引

| | 存進索引 | **從磁碟讀（採用）** |
|---|---|---|
| 索引大小 | 2.2M concept 時 pickle 膨脹到 30–40 GB，載入時全進記憶體 | 索引維持只有統計量 |
| 內容更新 | 改一個 `.md` 就要重建索引才看得到新內容 | 立即反映，無須重建 |
| 讀取成本 | 記憶體命中 | 單檔 read，本規模下可忽略 |
| 真相來源 | 索引與檔案兩份，可能不一致 | 檔案是唯一真相 |

「檔案是唯一真相、索引是可重建的衍生物」與整個專案的設計原則一致（見 `okf-keyword-baseline` 的 design D4）。

代價是索引與檔案可能不同步（檔案在建索引後被移動或刪除），這用 410 明確回報，見 D4。

### D2. 索引新增 `by_id` 與 `bundle_roots`

要從 `concept_id` 定位檔案需要兩樣目前沒有的東西：

- `Index.by_id: dict[str, int]` — concept id → `docs` 的索引位置。目前 `docs` 只是 list，查 id 得線性掃描
- `Index.bundle_roots: dict[str, str]` — bundle id → 該 bundle 的絕對根目錄。`DocMeta.path` 是相對於 bundle 根目錄的路徑

**不把根目錄放進 `DocMeta`**：那會在 2.2M 筆資料裡重複同一個字串。以 bundle 為鍵的登錄表只有 bundle 數量級的條目。

這改變索引結構 → 格式版本 1 提升至 2，舊快取載入時明確報錯要求重建（`Index.load()` 已有版本檢查）。

### D3. 回傳原始 markdown 與解析結構兩者

- `raw` — 完整檔案內容（含 frontmatter）。agent 最常用的就是這個，直接餵進 context 即可
- `frontmatter` — 解析後的完整字典，讓程式化消費者不必再自己解析 YAML
- `sections` — 依 `## ` 切好的 `{heading, text}` 清單，支援「只讀根因段落」這類針對性取用

`raw` 與 `sections` 有內容重疊，這是刻意的：兩者服務不同消費者，而在單一 concept（約 3k tokens）的尺度上，重複一份的代價遠低於逼每個呼叫端各自實作解析。

### D4. 錯誤語意分成 404 與 410

| 情況 | 狀態碼 | 意義 |
|---|---|---|
| `concept_id` 不在索引中 | **404** | 這個 id 不存在（打錯、或屬於別份語料） |
| 在索引中但檔案已不存在 | **410** | 曾經存在、語料已變動 → 訊息明確指示重建索引 |

兩者混為 404 會讓「打錯 id」與「索引過期」無法區分，而後者需要的是完全不同的處置。

### D5. 解析路徑重用 `parser.parse_concept()`

不另寫解析邏輯。全文端點呼叫既有的 `parse_concept()`，因此無分隔線 frontmatter、未知欄位收進 `extra`、section 切分等既有行為自動一致，不會出現「檢索看到的結構」與「取全文看到的結構」不一致的情況。

### D6. 讀取邏輯放在獨立模組

`fulltext.py` 只依賴 `Index` 與 `parser`，不依賴 FastAPI。後續 MCP server 與 CLI 可直接重用，不必透過 HTTP。

## Risks / Trade-offs

- **路徑穿越** → `concept_id` 只用於查 `by_id`，實際路徑來自索引而非使用者輸入；仍額外驗證解析後的絕對路徑必須位於該 bundle 根目錄之下（防索引被竄改或人工編輯出錯）
- **索引與檔案不同步** → 以 410 明確回報並指示重建，而非回傳過期內容或含糊的 404
- **回應體積**（單一 concept 約 300 行，`raw` + `sections` 約 2 倍） → 本變更只做單筆取用，體積可控；批次取用時再評估是否需要欄位裁剪
- **格式版本提升迫使所有人重建索引** → 這是一次性成本，且 `Index.load()` 的錯誤訊息已明確指示重建指令

## Open Questions

- 是否需要 `?sections=根因,對策` 這類欄位裁剪參數——待 agent 實際使用後依 context 消耗量決定
- 批次取用的介面形狀（`POST /concepts` 帶 id 陣列 vs `GET /concepts?ids=`）留待後續變更
