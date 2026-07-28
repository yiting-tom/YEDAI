# retrieval-telemetry Specification

## Purpose
TBD - created by archiving change okf-keyword-baseline. Update Purpose after archive.
## Requirements
### Requirement: 完整查詢日誌

系統 SHALL 將每次查詢以 JSONL 格式追加寫入本機完整日誌，內容含查詢識別碼、時間戳、查詢原文、使用模式、抽出的實體、各模式的結果 concept id 與分數、結果筆數。此日誌 MUST 寫入預設被版控排除的目錄。

#### Scenario: 查詢被記錄

- **WHEN** 使用者執行一次查詢
- **THEN** 完整日誌新增一筆 JSONL 記錄，含查詢原文與結果 id 清單

#### Scenario: 日誌目錄被版控排除

- **WHEN** 檢視版控忽略設定
- **THEN** 完整日誌所在目錄被排除，不會被提交

#### Scenario: 查詢識別碼可供回饋關聯

- **WHEN** 查詢被記錄
- **THEN** 回傳結果含查詢識別碼，可供後續回饋事件關聯

### Requirement: 點選回饋記錄

系統 SHALL 接受針對特定查詢的點選回饋，記錄被點選的 concept id、其排名、來源模式與動作類型。回饋 MUST 能與原查詢透過查詢識別碼關聯。

#### Scenario: 記錄點選

- **WHEN** 使用者點選某次查詢結果中排名第 3 的項目
- **THEN** 系統記錄該點選事件，含查詢識別碼、concept id、排名 3 與來源模式

#### Scenario: 未知查詢識別碼

- **WHEN** 回饋事件引用不存在的查詢識別碼
- **THEN** 系統回報錯誤而非靜默接受

### Requirement: 去識別化統計報告

系統 SHALL 能從累積的日誌產出去識別化統計報告。報告 MUST NOT 包含任何查詢原文、concept 標題、描述、檔案路徑、實體名稱或其他語料內容，僅含數值、分佈與統計量。

#### Scenario: 報告不含內容

- **WHEN** 產出去識別化報告
- **THEN** 報告序列化結果中不出現任何查詢原文、concept 標題或實體名稱

#### Scenario: 報告可序列化為 JSON

- **WHEN** 請求報告
- **THEN** 回傳可序列化為 JSON 的結構，適合直接分享

### Requirement: 報告指標內容

去識別化報告 SHALL 至少包含下列指標：語料統計（bundle 數、concept 數、平均 concept 長度、兩套詞彙空間的詞彙量、解析失敗檔數）、查詢統計（查詢次數、查詢長度分佈、含實體查詢比例、零結果率）、實體統計（不重複實體數、字典命中與 regex fallback 比例，**以及依實體類型拆解的同一組比例**）、各模式分數分佈、模式間 top-k 重疊度（Jaccard 與 Kendall tau 的分佈）、點選排名分佈，以及該次實驗使用的設定參數。

依類型拆解的實體統計 MUST 僅以實體類型名稱為鍵。實體的正規名稱與原始字串 MUST NOT 出現在報告任何位置——類型名稱屬 schema，正規名稱屬語料內容，後者會使報告無法帶出受管制環境。

#### Scenario: 含模式間重疊度

- **WHEN** 累積若干次三模式並排查詢後產出報告
- **THEN** 報告含 A 對 B、A 對 C、B 對 C 的 top-k Jaccard 與 Kendall tau 統計量

#### Scenario: 含設定參數

- **WHEN** 產出報告
- **THEN** 報告含該次實驗使用的欄位權重、BM25 參數與融合權重，確保結果可重現

#### Scenario: 含零結果率

- **WHEN** 若干次查詢中有部分無命中
- **THEN** 報告含各模式的零結果比例

#### Scenario: 無查詢紀錄時

- **WHEN** 尚未有任何查詢即產出報告
- **THEN** 報告仍含語料統計，查詢相關指標為零或空，且不產生錯誤

#### Scenario: 含依類型拆解的實體覆蓋率

- **WHEN** 語料含多種實體類型
- **THEN** 報告可分別讀取各類型的字典命中數與 regex fallback 數

#### Scenario: 拆解結構不洩漏實體名稱

- **WHEN** 產出含依類型拆解的報告
- **THEN** 報告序列化結果中不出現任何實體的正規名稱或原始字串

### Requirement: 三模式並排時隨機化呈現順序

系統在三模式並排呈現時 SHALL 隨機化模式的呈現順序，並在日誌中記錄該次的實際呈現順序，以降低點選回饋的位置偏差。

#### Scenario: 呈現順序被記錄

- **WHEN** 執行三模式並排查詢
- **THEN** 日誌記錄該次三個模式的呈現順序

#### Scenario: 順序可固定以利測試

- **WHEN** 設定指定固定隨機種子
- **THEN** 呈現順序可重現

