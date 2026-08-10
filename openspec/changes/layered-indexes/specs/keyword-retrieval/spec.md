## MODIFIED Requirements

### Requirement: 索引建構與快取

系統 SHALL 從解析後的 bundle 建立記憶體索引，同時建立天真斷詞與識別碼保護斷詞兩套詞彙空間。索引 MUST 可序列化至磁碟並在後續執行中載入，避免重複解析。載入時 MUST 驗證索引與當前設定相容，不相容時 SHALL 提示重建。

索引建構 MUST 以**單一具名索引**為單位：一次建構讀入該索引宣告的語料來源，產生僅屬於該索引的統計，並序列化至該索引宣告的路徑。一份索引檔 MUST 只含一個索引。

索引 MUST 攜帶其所屬的索引名稱，且該名稱 MUST 納入索引簽章。載入時若索引檔內含名稱與設定宣告不符，SHALL 報錯要求重建。

索引 MUST 額外保存 `concept_id` 至文件位置的對照，以及各 bundle 識別碼至其根目錄的登錄，使任一 concept 的檔案位置可在不掃描語料的情況下被定位。bundle 根目錄 MUST 以 bundle 為單位登錄，不逐筆重複儲存於每個 concept 的中繼資料中。

索引 MUST 保存 concept 之間的 `related` 關聯邊，出向與入向皆須可直接查詢；入向邊 MUST 於建立索引時計算完成。指向語料中不存在 concept 的關聯條目 MUST 被保留為懸空引用，不得靜默丟棄。關聯邊的解析範圍 MUST 限於同一索引內——跨索引的 `related` 目標 MUST 被記為懸空引用，不得跨索引解析。

索引 MUST 帶有格式版本；載入版本不符的索引時 SHALL 明確報錯並要求重建，不得靜默接受。

#### Scenario: 建立索引後快取

- **WHEN** 使用者對某具名索引執行索引建構
- **THEN** 該索引被寫入其宣告的路徑，並回報 bundle 數、concept 數、詞彙量

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

#### Scenario: 關聯邊雙向可查

- **WHEN** concept A 的 `related` 指向同一索引內的 concept B
- **THEN** 索引中 A 的出向邊含 B，且 B 的入向邊含 A

#### Scenario: 懸空關聯被保留

- **WHEN** 某 concept 的 `related` 指向語料中不存在的 id
- **THEN** 該 id 被記錄為懸空引用，並計入語料統計

#### Scenario: 跨索引關聯不解析

- **WHEN** 索引 X 中某 concept 的 `related` 指向存在於索引 Y 的 concept
- **THEN** 該 id 於索引 X 中被記為懸空引用，X 的出向邊不含它

#### Scenario: 索引攜帶名稱且納入簽章

- **WHEN** 建構名為 `X` 的索引後載入
- **THEN** 索引可回報自身名稱為 `X`，且該名稱是簽章的一部分

#### Scenario: 索引名稱與宣告不符

- **WHEN** 某路徑上的索引檔內含名稱與設定宣告的名稱不同
- **THEN** 系統報錯並要求重建，不得靜默採用

#### Scenario: 舊格式索引被拒絕

- **WHEN** 載入格式版本與目前實作不符的索引檔
- **THEN** 系統報錯並指示重建索引

## ADDED Requirements

### Requirement: 檢索器綁定單一索引

`Searcher` SHALL 綁定單一索引，其所有計分 MUST 僅使用該索引的統計。跨索引的協調 MUST 由獨立的分層檢索層負責，MUST NOT 由 `Searcher` 內部合併多個索引的文件。

#### Scenario: 檢索器不跨索引

- **WHEN** 對綁定索引 X 的檢索器執行查詢
- **THEN** 結果中的每一筆皆來自索引 X

#### Scenario: 分數僅由所屬索引的統計決定

- **WHEN** 兩個索引含相同內容的文件但語料規模不同
- **THEN** 各自檢索器對該文件計出的分數依各自的統計計算，彼此無關
