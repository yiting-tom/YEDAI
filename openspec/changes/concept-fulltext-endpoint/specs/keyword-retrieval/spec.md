## MODIFIED Requirements

### Requirement: 索引建構與快取

系統 SHALL 從解析後的 bundle 建立記憶體索引，同時建立天真斷詞與識別碼保護斷詞兩套詞彙空間。索引 MUST 可序列化至磁碟並在後續執行中載入，避免重複解析。載入時 MUST 驗證索引與當前設定相容，不相容時 SHALL 提示重建。

索引 MUST 額外保存 `concept_id` 至文件位置的對照，以及各 bundle 識別碼至其根目錄的登錄，使任一 concept 的檔案位置可在不掃描語料的情況下被定位。bundle 根目錄 MUST 以 bundle 為單位登錄，不得逐筆重複儲存於每個 concept 的中繼資料中。

索引 MUST 帶有格式版本；載入版本不符的索引時 SHALL 明確報錯並要求重建，不得靜默接受。

#### Scenario: 建立索引後快取

- **WHEN** 使用者對 bundle 根目錄執行索引建構
- **THEN** 索引被寫入磁碟快取，並回報 bundle 數、concept 數、詞彙量

#### Scenario: 重複執行載入快取

- **WHEN** 快取存在且設定未變更
- **THEN** 系統載入快取而不重新解析檔案

#### Scenario: 設定變更後提示重建

- **WHEN** 快取存在但斷詞設定已變更
- **THEN** 系統提示快取失效並要求重建

#### Scenario: 依 concept id 定位文件

- **WHEN** 以既有的 `concept_id` 查詢索引
- **THEN** 系統回傳該 concept 的中繼資料位置，無須線性掃描全部文件

#### Scenario: bundle 根目錄可還原

- **WHEN** 取得某 concept 的 `bundle_id` 與相對路徑
- **THEN** 可由索引中的 bundle 根目錄登錄組合出該檔案的絕對路徑

#### Scenario: 舊格式索引被拒絕

- **WHEN** 載入格式版本與目前實作不符的索引檔
- **THEN** 系統報錯並指示重建索引
