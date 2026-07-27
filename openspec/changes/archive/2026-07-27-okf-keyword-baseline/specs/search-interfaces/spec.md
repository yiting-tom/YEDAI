## ADDED Requirements

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
