## MODIFIED Requirements

### Requirement: 設定檔

系統 SHALL 支援以設定檔覆寫斷詞樣式、BM25 參數、欄位權重、融合權重、字典路徑、日誌路徑，以及 taxonomy 資源路徑。未提供設定檔時 MUST 使用內建預設值。

索引 SHALL 以具名集合宣告，取代單一索引路徑。每個索引宣告其語料來源、索引檔輸出路徑，以及選用的向量 collection、檢索設定與 query 前處理。索引層級未宣告的檢索設定 MUST 沿用全域值。

設定檔含已移除的單一索引路徑鍵時，系統 SHALL 報錯並印出新的宣告形狀，MUST NOT 靜默忽略——靜默忽略會使使用者以為索引已建立，實際上寫入非預期的位置。

#### Scenario: 設定檔覆寫權重

- **WHEN** 提供指定 `title` 權重的設定檔
- **THEN** 索引與檢索皆使用該權重

#### Scenario: 無設定檔

- **WHEN** 未提供設定檔
- **THEN** 系統以內建預設值運作

#### Scenario: 索引層級設定覆寫全域

- **WHEN** 某索引宣告與全域不同的欄位權重
- **THEN** 對該索引的檢索使用索引層級的值，其他索引仍用全域值

#### Scenario: 舊的單一索引路徑鍵被拒絕

- **WHEN** 設定檔仍使用已移除的單一索引路徑鍵
- **THEN** 系統報錯並印出具名索引集合的宣告形狀

### Requirement: CLI 索引建構指令

系統 SHALL 提供 CLI 指令建立索引快取，完成後顯示 bundle 數、concept 數、兩套詞彙空間的詞彙量、實體統計與解析失敗清單。

指令 MUST 接受索引名稱以只建構單一索引；未指定名稱時 MUST 依宣告的依賴順序建構全部索引，並分別顯示各索引的統計。

#### Scenario: 建立單一索引

- **WHEN** 使用者指定索引名稱執行索引指令
- **THEN** 僅該索引被建立並快取，終端顯示該索引的語料統計摘要

#### Scenario: 建立全部索引

- **WHEN** 使用者未指定索引名稱執行索引指令
- **THEN** 全部索引依依賴順序建立，終端分別顯示每個索引的統計摘要

#### Scenario: 顯示解析失敗

- **WHEN** 部分檔案解析失敗
- **THEN** 終端顯示失敗檔案清單與原因，並標示所屬索引

#### Scenario: 目錄不存在

- **WHEN** 某索引宣告的語料來源目錄不存在
- **THEN** CLI 回報明確錯誤含索引名稱，並以非零狀態碼結束

#### Scenario: 索引名稱不存在

- **WHEN** 使用者指定未宣告的索引名稱
- **THEN** CLI 報錯並列出可用的索引名稱，以非零狀態碼結束

### Requirement: CLI 查詢指令

系統 SHALL 提供 CLI 查詢指令，接受查詢字串、模式與回傳筆數。指令 MUST 接受索引名稱；未指定時 SHALL 對全部已載入索引執行分層檢索。

輸出 SHALL 依層分段顯示，每段標示索引名稱，段內以表格顯示排名、分數、concept id、type 與標題。無命中的層 MUST 仍顯示其標題並標示為空，不得從輸出中省略。

#### Scenario: 單一索引查詢

- **WHEN** 使用者指定索引名稱與模式 C 查詢並指定回傳 10 筆
- **THEN** 終端顯示該索引至多 10 筆結果，含排名、分數、concept id、type 與標題

#### Scenario: 分層查詢

- **WHEN** 使用者未指定索引名稱執行查詢
- **THEN** 終端依層分段顯示各索引的結果，每段標示索引名稱

#### Scenario: 空層仍顯示

- **WHEN** 某索引對該查詢無命中
- **THEN** 終端仍顯示該層的標題並標示為空

#### Scenario: 索引不存在

- **WHEN** 尚未建立索引即執行查詢
- **THEN** CLI 提示需先建立哪些索引並以非零狀態碼結束

### Requirement: HTTP 查詢端點

系統 SHALL 提供 HTTP `GET /search` 端點，接受查詢字串、模式與回傳筆數參數。模式參數 MUST 支援指定單一模式或要求多模式並排。回應 MUST 含查詢識別碼，供後續回饋關聯。

端點 MUST 接受選用的索引名稱參數。未提供時回應 MUST 為分層結構，每層標示索引名稱並含該層自己的結果清單；無命中的層 MUST 以空清單呈現，不得省略。提供時回應僅含該索引的結果。

端點 MUST 接受選用的跨索引融合參數，預設關閉。啟用時回應為單一排序清單，每一筆 MUST 標示來源索引名稱與其在該索引中的原始名次。

指定未宣告的索引名稱時 MUST 回應 HTTP 422 並列出可用名稱。

#### Scenario: 單模式查詢

- **WHEN** 呼叫 `/search` 並指定模式 `B`
- **THEN** 回應含該模式的排序結果與查詢識別碼

#### Scenario: 多模式並排

- **WHEN** 呼叫 `/search` 並要求比較模式
- **THEN** 回應含各可用模式的結果與模式間重疊度指標

#### Scenario: 分層回應

- **WHEN** 呼叫 `/search` 未指定索引名稱
- **THEN** 回應為分層結構，每層標示索引名稱

#### Scenario: 指定單一索引

- **WHEN** 呼叫 `/search` 並指定已宣告的索引名稱
- **THEN** 回應僅含該索引的結果

#### Scenario: 啟用跨索引融合

- **WHEN** 呼叫 `/search` 並要求跨索引融合
- **THEN** 回應為單一排序清單，每一筆含來源索引名稱與其原始名次

#### Scenario: 缺少查詢字串

- **WHEN** 呼叫 `/search` 未提供查詢字串
- **THEN** 回應 HTTP 422 驗證錯誤

#### Scenario: 無效模式

- **WHEN** 呼叫 `/search` 指定不存在的模式
- **THEN** 回應 HTTP 422 驗證錯誤

#### Scenario: 無效索引名稱

- **WHEN** 呼叫 `/search` 指定未宣告的索引名稱
- **THEN** 回應 HTTP 422 並列出可用的索引名稱

## ADDED Requirements

### Requirement: HTTP taxonomy 查表端點

系統 SHALL 提供以 defect 識別碼取回 taxonomy 條目的 HTTP 端點。查無條目時 MUST 回應 HTTP 404，MUST NOT 回傳近似結果。回應結構 MUST 納入 OpenAPI schema。

#### Scenario: 取回條目

- **WHEN** 以存在的 defect 識別碼呼叫該端點
- **THEN** 回應含該 defect 的 taxonomy 條目

#### Scenario: 查無條目

- **WHEN** 以不存在的 defect 識別碼呼叫該端點
- **THEN** 回應 HTTP 404，且回應內容不含任何其他 defect 的條目

#### Scenario: 出現在互動式文件

- **WHEN** 檢視互動式 API 文件
- **THEN** taxonomy 端點與其回應結構出現在文件中
