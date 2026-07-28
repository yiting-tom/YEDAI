# keyword-retrieval Specification

## Purpose
TBD - created by archiving change okf-keyword-baseline. Update Purpose after archive.
## Requirements
### Requirement: 提供三種消融檢索模式

系統 SHALL 提供三種可獨立呼叫的檢索模式：模式 `A` 為天真 BM25F（識別碼被一般斷詞切碎）、模式 `B` 為 BM25F 搭配識別碼保護斷詞、模式 `C` 為模式 B 再加上實體字典匹配計分。三種模式 MUST 可對同一查詢分別執行並取得各自的排序結果。

#### Scenario: 指定單一模式檢索

- **WHEN** 使用者以模式 `B` 查詢
- **THEN** 系統僅使用識別碼保護斷詞的索引計分，回傳排序後的結果清單

#### Scenario: 三模式並排比較

- **WHEN** 使用者要求比較模式
- **THEN** 系統對同一查詢分別執行 A、B、C，回傳三組排序結果與其間的重疊度指標

#### Scenario: 模式 A 切碎識別碼

- **WHEN** 查詢含 `TEL-05` 且以模式 A 執行
- **THEN** 該識別碼被切分為 `tel` 與 `05` 兩個詞元參與計分

#### Scenario: 模式 B 保護識別碼

- **WHEN** 查詢含 `TEL-05` 且以模式 B 執行
- **THEN** 該識別碼被正規化為單一詞元參與計分，與 `TEL-06` 不共享詞元

### Requirement: 識別碼保護斷詞

系統 SHALL 提供可設定的識別碼正則樣式清單，將符合樣式的字串整段圈出並正規化（移除連字號、底線、空白並轉大寫）為單一詞元。正規化 MUST 使 `TEL-05`、`TEL05`、`tel 05`、`TEL_05` 對應至同一詞元，且與 `TEL-06` 對應至不同詞元。

識別碼中的 `#` MUST 被保留為正規化後詞元的一部分，不得比照連字號移除——它標示父子層級的分界，移除後該分界無法可靠還原。

#### Scenario: 識別碼變體正規化一致

- **WHEN** 文本中出現 `TEL-05`、`TEL05`、`tel 05`
- **THEN** 三者產生相同的正規化詞元

#### Scenario: 相鄰識別碼不混淆

- **WHEN** 語料中同時存在 `TEL-05` 與 `TEL-06`
- **THEN** 兩者的正規化詞元不同，且不共享任何詞元

#### Scenario: 樣式清單可覆寫

- **WHEN** 設定檔提供自訂識別碼正則樣式清單
- **THEN** 系統使用自訂清單取代預設清單

#### Scenario: 含 `#` 的識別碼整段圈出

- **WHEN** 文本含 `aepol1#pm1`
- **THEN** 該字串被視為單一識別碼，不被 `#` 切成兩段

#### Scenario: `#` 在正規化後保留

- **WHEN** 對 `aepol1#pm1` 正規化
- **THEN** 結果為 `AEPOL1#PM1`，`#` 未被移除

### Requirement: 中英混合斷詞

系統 SHALL 對中日韓字元序列產生 unigram 與 bigram 詞元，對拉丁字母與數字序列產生小寫詞元。斷詞 MUST NOT 依賴外部中文詞典。

#### Scenario: 中文產生 bigram

- **WHEN** 文本含連續中文字元「量測結果」
- **THEN** 產生 unigram（量、測、結、果）與 bigram（量測、測結、結果）詞元

#### Scenario: 英數轉小寫

- **WHEN** 文本含 `Particle`
- **THEN** 產生詞元 `particle`

### Requirement: BM25F 欄位加權計分

系統 SHALL 以 BM25F 計分，將 concept 切分為 `title`、`description`、`tags`、`headings`、`figures`、`body` 六個欄位，各欄位獨立做長度正規化後依權重合併詞頻，再計算單次 BM25 分數。欄位權重與 BM25 參數 MUST 可由設定檔覆寫。

#### Scenario: 標題命中權重高於內文

- **WHEN** 查詢詞僅出現在 concept A 的標題、僅出現在 concept B 的內文，其餘條件相同
- **THEN** concept A 的分數高於 concept B

#### Scenario: 權重可覆寫

- **WHEN** 設定檔指定 `title` 權重為 5.0
- **THEN** 計分使用 5.0 而非預設值

#### Scenario: 使用的權重被記錄

- **WHEN** 執行檢索
- **THEN** 該次使用的欄位權重與 BM25 參數可從結果或遙測中取得，確保實驗可重現

### Requirement: 索引建構與快取

系統 SHALL 從解析後的 bundle 建立記憶體索引，同時建立天真斷詞與識別碼保護斷詞兩套詞彙空間。索引 MUST 可序列化至磁碟並在後續執行中載入，避免重複解析。載入時 MUST 驗證索引與當前設定相容，不相容時 SHALL 提示重建。

索引 MUST 額外保存 `concept_id` 至文件位置的對照，以及各 bundle 識別碼至其根目錄的登錄，使任一 concept 的檔案位置可在不掃描語料的情況下被定位。bundle 根目錄 MUST 以 bundle 為單位登錄，不得逐筆重複儲存於每個 concept 的中繼資料中。

索引 MUST 保存 concept 之間的 `related` 關聯邊，出向與入向皆須可直接查詢；入向邊 MUST 於建立索引時計算完成。指向語料中不存在 concept 的關聯條目 MUST 被保留為懸空引用，不得靜默丟棄。

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

#### Scenario: 關聯邊雙向可查

- **WHEN** concept A 的 `related` 指向 concept B
- **THEN** 索引中 A 的出向邊含 B，且 B 的入向邊含 A

#### Scenario: 懸空關聯被保留

- **WHEN** 某 concept 的 `related` 指向語料中不存在的 id
- **THEN** 該 id 被記錄為懸空引用，並計入語料統計

#### Scenario: 舊格式索引被拒絕

- **WHEN** 載入格式版本與目前實作不符的索引檔
- **THEN** 系統報錯並指示重建索引

### Requirement: 檢索結果內容

檢索結果 SHALL 對每一筆回傳 concept id、bundle id、type、title、description、檔案路徑、排名與分數。模式 C 的結果 MUST 額外分別回傳詞彙腿分數與實體腿分數，使兩者貢獻可個別觀察。結果 SHALL 可產出與 `index.md` 相同的行格式。

#### Scenario: 結果含分數細項

- **WHEN** 以模式 C 檢索
- **THEN** 每筆結果同時含最終分數、詞彙腿分數與實體腿分數

#### Scenario: 零結果

- **WHEN** 查詢在語料中無任何命中
- **THEN** 系統回傳空結果清單而非錯誤，且該次查詢被記錄為零結果

#### Scenario: 結果數量上限

- **WHEN** 使用者指定回傳筆數上限
- **THEN** 系統回傳不超過該上限的結果

### Requirement: 模式間重疊度指標

系統 SHALL 能計算任兩個模式在同一查詢下 top-k 結果的重疊度，至少包含 Jaccard 相似度與排名相關性（Kendall tau）。

#### Scenario: 完全相同的排序

- **WHEN** 兩個模式回傳完全相同順序的 top-10
- **THEN** Jaccard 為 1.0，Kendall tau 為 1.0

#### Scenario: 無交集的排序

- **WHEN** 兩個模式的 top-10 沒有任何共同 concept
- **THEN** Jaccard 為 0.0

### Requirement: 父子層級識別碼展開

含層級分隔符 `#` 的識別碼 SHALL 同時產生子層詞元與父層詞元，使針對父層的查詢能命中僅提及子層的文件。展開 MUST 同時作用於詞彙腿的斷詞輸出與實體抽取的識別碼列舉，兩者不得分歧。

展開 MUST 僅依字串結構進行，不得依賴實體字典——字典覆蓋率是本實驗的待測變數，不可作為其他機制的前提。

#### Scenario: 腔體識別碼產生父層詞元

- **WHEN** 文本含 `aepol1#pm1`
- **THEN** 產生 `ID:AEPOL1#PM1` 與 `ID:AEPOL1` 兩個詞元

#### Scenario: 查父層命中子層文件

- **WHEN** 查詢 `aepol1`，而某文件僅提及 `aepol1#pm1`
- **THEN** 該文件被檢索到

#### Scenario: 不同機台的同名腔體不混淆

- **WHEN** 語料中同時存在 `aepol1#pm1` 與 `aepol6#pm1`
- **THEN** 兩者的子層詞元不同；查詢 `aepol1#pm1` 不命中僅含 `aepol6#pm1` 的文件

#### Scenario: 實體抽取同步展開

- **WHEN** 對含 `aepol1#pm1` 的文本抽取實體
- **THEN** 抽取結果同時含子層與父層兩個識別碼

#### Scenario: 字典為空時展開仍成立

- **WHEN** 未提供任何實體字典，文本含 `aepol1#pm1`
- **THEN** 父層詞元仍被產生

#### Scenario: 無層級分隔符者不受影響

- **WHEN** 文本含 `aepol1`
- **THEN** 僅產生單一詞元，不產生額外的展開詞元

