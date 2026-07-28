# search-interfaces Specification

## Purpose
TBD - created by archiving change okf-keyword-baseline. Update Purpose after archive.
## Requirements
### Requirement: CLI 索引建構指令

系統 SHALL 提供 CLI 指令，接受 bundle 根目錄路徑並建立索引快取，完成後顯示 bundle 數、concept 數、兩套詞彙空間的詞彙量、實體統計與解析失敗清單。

#### Scenario: 建立索引

- **WHEN** 使用者對含 30 個 bundle 的目錄執行索引指令
- **THEN** 索引被建立並快取，終端顯示語料統計摘要

#### Scenario: 顯示解析失敗

- **WHEN** 部分檔案解析失敗
- **THEN** 終端顯示失敗檔案清單與原因

#### Scenario: 目錄不存在

- **WHEN** 指定的 bundle 根目錄不存在
- **THEN** CLI 回報明確錯誤並以非零狀態碼結束

### Requirement: CLI 查詢指令

系統 SHALL 提供 CLI 查詢指令，接受查詢字串、模式與回傳筆數，以表格顯示結果的排名、分數、concept id、type 與標題。

#### Scenario: 單模式查詢

- **WHEN** 使用者以模式 C 查詢並指定回傳 10 筆
- **THEN** 終端顯示至多 10 筆結果，含排名、分數、concept id、type 與標題

#### Scenario: 索引不存在

- **WHEN** 尚未建立索引即執行查詢
- **THEN** CLI 提示需先建立索引並以非零狀態碼結束

### Requirement: CLI 比較指令

系統 SHALL 提供 CLI 比較指令，對同一查詢執行三種模式並顯示各自排序結果與模式間重疊度指標。指令 MUST 支援從檔案批次讀入多個查詢，並輸出彙總結果。

#### Scenario: 單一查詢比較

- **WHEN** 使用者對一個查詢執行比較指令
- **THEN** 終端顯示三個模式的排序結果，以及兩兩之間的 Jaccard 與 Kendall tau

#### Scenario: 批次查詢比較

- **WHEN** 使用者提供含多個查詢的檔案
- **THEN** 系統逐一執行並輸出彙總的重疊度統計

### Requirement: CLI 報告指令

系統 SHALL 提供 CLI 指令產出去識別化統計報告，可輸出至終端或指定檔案。

#### Scenario: 產出報告至檔案

- **WHEN** 使用者執行報告指令並指定輸出路徑
- **THEN** 去識別化報告以 JSON 寫入該路徑

### Requirement: HTTP 查詢端點

系統 SHALL 提供 HTTP `GET /search` 端點，接受查詢字串、模式與回傳筆數參數。模式參數 MUST 支援指定單一模式或要求三模式並排。回應 MUST 含查詢識別碼，供後續回饋關聯。

#### Scenario: 單模式查詢

- **WHEN** 呼叫 `/search` 並指定模式 `B`
- **THEN** 回應含該模式的排序結果與查詢識別碼

#### Scenario: 三模式並排

- **WHEN** 呼叫 `/search` 並要求比較模式
- **THEN** 回應含三個模式各自的結果與模式間重疊度指標

#### Scenario: 缺少查詢字串

- **WHEN** 呼叫 `/search` 未提供查詢字串
- **THEN** 回應 HTTP 422 驗證錯誤

#### Scenario: 無效模式

- **WHEN** 呼叫 `/search` 指定不存在的模式
- **THEN** 回應 HTTP 422 驗證錯誤

### Requirement: HTTP 回饋端點

系統 SHALL 提供 HTTP `POST /feedback` 端點，接受查詢識別碼、被點選的 concept id、排名、來源模式與動作類型，並寫入日誌。

#### Scenario: 提交回饋

- **WHEN** 以有效查詢識別碼提交點選回饋
- **THEN** 回應成功且事件被記錄

#### Scenario: 無效查詢識別碼

- **WHEN** 以不存在的查詢識別碼提交回饋
- **THEN** 回應 HTTP 404

### Requirement: HTTP 狀態與報告端點

系統 SHALL 提供 `GET /stats` 回傳語料統計與索引狀態，`GET /report` 回傳去識別化統計報告，`GET /healthz` 回傳服務健康狀態。

#### Scenario: 查詢語料統計

- **WHEN** 呼叫 `/stats`
- **THEN** 回應含 bundle 數、concept 數、詞彙量、實體統計與解析失敗數

#### Scenario: 取得報告

- **WHEN** 呼叫 `/report`
- **THEN** 回應為去識別化統計報告，不含任何語料內容

#### Scenario: 健康檢查

- **WHEN** 呼叫 `/healthz`
- **THEN** 回應狀態正常並指出索引是否已載入

### Requirement: 互動式 API 文件

HTTP 服務 SHALL 提供互動式 API 文件頁面，可在瀏覽器中檢視所有端點並直接送出測試請求。

#### Scenario: 開啟文件頁

- **WHEN** 於瀏覽器開啟服務的文件路徑
- **THEN** 頁面列出 `/search`、`/feedback`、`/stats`、`/report`、`/healthz` 端點

#### Scenario: 由文件頁送出查詢

- **WHEN** 於文件頁對 `/search` 填入查詢字串並送出
- **THEN** 頁面顯示 HTTP 200 與含結果的回應內容

### Requirement: 設定檔

系統 SHALL 支援以設定檔覆寫斷詞樣式、BM25 參數、欄位權重、融合權重、字典路徑、索引快取路徑與日誌路徑。未提供設定檔時 MUST 使用內建預設值。

#### Scenario: 設定檔覆寫權重

- **WHEN** 提供指定 `title` 權重的設定檔
- **THEN** 索引與檢索皆使用該權重

#### Scenario: 無設定檔

- **WHEN** 未提供設定檔
- **THEN** 系統以內建預設值運作

### Requirement: HTTP 全文端點

系統 SHALL 提供 HTTP `GET /concept/{concept_id}` 端點，回傳該 concept 的完整內容，包含原始 markdown 全文、解析後的 frontmatter、section 清單、figures 與識別資訊。

#### Scenario: 取回既有 concept

- **WHEN** 以檢索結果中的 `concept_id` 呼叫 `/concept/{concept_id}`
- **THEN** 回應 HTTP 200，內容含原始 markdown 全文、frontmatter、section 清單與 figures

#### Scenario: concept id 不存在

- **WHEN** 以不存在的 `concept_id` 呼叫該端點
- **THEN** 回應 HTTP 404

#### Scenario: 索引過期，檔案已不存在

- **WHEN** `concept_id` 存在於索引但對應檔案已被移除
- **THEN** 回應 HTTP 410，且訊息指示需要重建索引

#### Scenario: 索引未載入

- **WHEN** 服務啟動時索引載入失敗，仍呼叫該端點
- **THEN** 回應 HTTP 503

#### Scenario: 檢索結果可直接串接取全文

- **WHEN** 先呼叫 `/search` 取得結果，再以其中任一筆的 `concept_id` 呼叫全文端點
- **THEN** 兩者的 `concept_id`、`bundle_id`、`type`、`title` 與路徑一致

#### Scenario: 端點出現在互動式文件

- **WHEN** 於瀏覽器開啟服務的文件路徑
- **THEN** 頁面列出 `/concept/{concept_id}` 端點，並可直接送出測試請求

### Requirement: HTTP 批次全文端點

系統 SHALL 提供 HTTP `POST /concepts` 端點，接受 `concept_id` 陣列並批次回傳完整內容，具部分成功語意。

#### Scenario: 批次取回

- **WHEN** 以三個既有 id 呼叫該端點
- **THEN** 回應 HTTP 200，含三筆完整內容與空的錯誤清單

#### Scenario: 部分失敗仍回 200

- **WHEN** 請求中混有既有與不存在的 id
- **THEN** 回應 HTTP 200，既有者在內容清單、不存在者在錯誤清單

#### Scenario: 超過上限回 422

- **WHEN** 請求的 id 數量超過上限
- **THEN** 回應 HTTP 422

#### Scenario: 空清單回 422

- **WHEN** 以空陣列呼叫
- **THEN** 回應 HTTP 422

### Requirement: HTTP 關聯展開端點

系統 SHALL 提供 HTTP `GET /concept/{concept_id}/neighbors` 端點，支援指定深度與方向，回傳關聯 concept 的摘要清單與懸空引用清單。

#### Scenario: 展開一跳

- **WHEN** 以既有 id 呼叫且深度為 1
- **THEN** 回應 HTTP 200，含關聯 concept 的摘要清單

#### Scenario: 起點不存在

- **WHEN** 以不存在的 id 呼叫
- **THEN** 回應 HTTP 404

#### Scenario: 深度超過上限

- **WHEN** 指定深度大於 2
- **THEN** 回應 HTTP 422

#### Scenario: 無效方向

- **WHEN** 指定不支援的方向值
- **THEN** 回應 HTTP 422

### Requirement: HTTP 限定範圍搜尋端點

系統 SHALL 提供 HTTP `GET /grep` 端點，必須指定 bundle 或 concept 範圍，支援字面與正則兩種比對模式。

#### Scenario: 指定範圍搜尋

- **WHEN** 指定一個 bundle 與一個字面樣式呼叫
- **THEN** 回應 HTTP 200，含該 bundle 內的命中清單

#### Scenario: 未指定範圍回 422

- **WHEN** 未提供任何 bundle 或 concept 範圍
- **THEN** 回應 HTTP 422，訊息指引先以檢索縮小範圍

#### Scenario: 無效正則回 422

- **WHEN** 開啟正則但樣式無法編譯
- **THEN** 回應 HTTP 422

#### Scenario: 範圍指向不存在的 bundle 回 404

- **WHEN** 指定的 bundle 不存在於索引
- **THEN** 回應 HTTP 404

### Requirement: 新端點出現在互動式文件

新增的批次、關聯展開與限定範圍搜尋端點 SHALL 出現在互動式 API 文件頁，並可直接送出測試請求。

#### Scenario: 文件頁列出新端點

- **WHEN** 於瀏覽器開啟服務的文件路徑
- **THEN** 頁面列出 `/concepts`、`/concept/{concept_id}/neighbors` 與 `/grep`

### Requirement: HTTP 資產下載端點

系統 SHALL 提供 HTTP `GET /concept/{concept_id}/asset` 端點，以 `path` 查詢參數指定相對路徑，回傳資產檔案內容並帶對應的 media type。

#### Scenario: 取回資產

- **WHEN** 以某 concept 的 `assets` 中的路徑呼叫該端點
- **THEN** 回應 HTTP 200，內容為該檔案的位元組，media type 對應其副檔名

#### Scenario: concept 不存在

- **WHEN** 以不存在的 `concept_id` 呼叫
- **THEN** 回應 HTTP 404

#### Scenario: 資產檔案不存在

- **WHEN** `concept_id` 存在但資產檔案不在磁碟上
- **THEN** 回應 HTTP 404

#### Scenario: 路徑逸出或違反資產目錄限制

- **WHEN** 路徑含 `..`、為絕對路徑，或不在允許的資產目錄之下
- **THEN** 回應 HTTP 403

#### Scenario: 缺少 path 參數

- **WHEN** 未提供 `path` 查詢參數
- **THEN** 回應 HTTP 422

#### Scenario: 以附件下載

- **WHEN** 指定 `download=true`
- **THEN** 回應含附件形式的內容處置標頭

#### Scenario: 索引未載入

- **WHEN** 服務啟動時索引載入失敗，仍呼叫該端點
- **THEN** 回應 HTTP 503

#### Scenario: 端點出現在互動式文件

- **WHEN** 於瀏覽器開啟服務的文件路徑
- **THEN** 頁面列出 `/concept/{concept_id}/asset` 端點

#### Scenario: 由 concept 全文串接取資產

- **WHEN** 先呼叫 `/concept/{id}` 取得 `assets` 陣列，再以其中任一項呼叫資產端點
- **THEN** 回應 HTTP 200

### Requirement: 端點路徑帶版本前綴

既有的檢索、內容、關聯、遙測與語料統計端點 SHALL 全部移至 `/v1` 前綴之下，其行為、參數與回應結構 MUST NOT 改變。

#### Scenario: 檢索端點

- **WHEN** 呼叫 `/v1/search` 並要求三模式並排
- **THEN** 回應內容與未版本化時完全相同

#### Scenario: 內容端點

- **WHEN** 依序呼叫 `/v1/concept/{id}`、`/v1/concepts`、`/v1/concept/{id}/asset`
- **THEN** 三者行為與未版本化時完全相同

#### Scenario: 關聯端點

- **WHEN** 呼叫 `/v1/concept/{id}/neighbors`
- **THEN** 行為與未版本化時完全相同

#### Scenario: 遙測端點

- **WHEN** 呼叫 `/v1/feedback` 與 `/v1/report`
- **THEN** 兩者行為與未版本化時完全相同

#### Scenario: 路由順序約束仍成立

- **WHEN** 呼叫 `/v1/concept/{id}/neighbors` 與 `/v1/concept/{id}/asset`
- **THEN** 兩者正確路由，`concept_id` 不會吞入尾段路徑

