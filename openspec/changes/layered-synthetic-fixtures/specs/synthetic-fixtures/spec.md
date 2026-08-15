## MODIFIED Requirements

### Requirement: 產生格式相符的合成 OKF bundle

系統 SHALL 提供合成 bundle 產生器，輸出的目錄結構與檔案格式必須與真實 OKF bundle 一致：每個 bundle 含 `manifest.json` 與 `okf/` 目錄，`okf/` 下含 `index.md`、`summary.md`、`log.md`、`_assets/` 與若干 concept 檔。concept 的 frontmatter MUST 涵蓋規格定義的所有欄位。

產出的語料 MUST 依層分置於各自的目錄之下，每層是一份獨立的語料根目錄，可直接作為單一具名索引的 `source`。

#### Scenario: 語料依層分置

- **WHEN** 產生合成資料集
- **THEN** 輸出目錄下每一層各有一個語料根目錄，其下才是 bundle 目錄

#### Scenario: 每層的 bundle 數量

- **WHEN** 使用者要求每層產生 10 個 bundle
- **THEN** 由 defect 全集決定內容的那一層不受此數量影響，其餘各層各含 10 個 bundle 目錄

#### Scenario: 產出可被解析器解析

- **WHEN** 對任一層的合成語料執行索引建構
- **THEN** 該層所有 concept 皆被成功解析，無解析失敗

#### Scenario: summary 使用無分隔線格式

- **WHEN** 檢視任一層合成的 `summary.md`
- **THEN** 其 frontmatter 採用無 `---` 分隔線的格式，以覆蓋該解析路徑

#### Scenario: concept 識別碼不跨層相撞

- **WHEN** 一次產生全部層的語料
- **THEN** 任兩層之間不存在相同的 `concept_id`

### Requirement: 合成語料具備類型模板重複性

合成 concept SHALL 依類型套用固定的區段模板，使不同 concept 之間結構重複但內容不同，以重現真實語料的類型重複特性。

各層 SHALL 使用各自的模板集合，不共用同一組模板。層與層之間的文本長度與識別碼密度 MUST 有可觀察的差異——三層文本性質相同時，統計隔離與 query 前處理的效果在此資料集上無法被觀察到。

#### Scenario: 同類型共用區段結構

- **WHEN** 檢視同一層中兩個同類型的合成 concept
- **THEN** 兩者具有相同的 `## ` 區段標題序列，但區段內容不同

#### Scenario: 各層模板不同

- **WHEN** 比較不同層的 concept 區段標題
- **THEN** 各層使用各自的標題序列，不出現另一層的模板

#### Scenario: 識別碼密度依層不同

- **WHEN** 統計各層 concept 中出現的識別碼數量
- **THEN** 識別碼密集的層其每篇平均識別碼數明顯高於稀少的層

### Requirement: 合成內容含可辨識的假實體

合成 concept 的內容 SHALL 大量使用假的機台識別碼、製程識別碼、flow 識別碼與缺陷代碼，且相似識別碼（僅末碼不同者）MUST 同時存在，以便驗證識別碼區辨行為。

產生器 SHALL 同時輸出可直接使用的實體來源：YAML 實體字典，以及 CSV 實體來源——單欄的識別碼清單（含層級分隔符的列）與三欄的 `Module, defect code, defect name`。

#### Scenario: 含相似識別碼

- **WHEN** 檢視合成語料
- **THEN** 存在僅末碼不同的成對機台識別碼，且分屬不同 concept

#### Scenario: 產出配套字典

- **WHEN** 產生合成語料
- **THEN** 同時輸出可直接用於模式 C 的實體字典檔

#### Scenario: 產出 CSV 實體來源

- **WHEN** 產生合成語料
- **THEN** 同時輸出單欄與三欄兩種 schema 的 CSV，且皆可被實體來源載入器讀入而不報錯

#### Scenario: 單欄 CSV 含層級列

- **WHEN** 檢視單欄的 CSV 實體來源
- **THEN** 其中含帶層級分隔符的列，且其父層識別碼亦單獨成列

### Requirement: 明示合成資料的使用限制

產生器 SHALL 在輸出目錄與終端訊息中明確標示：合成資料僅供驗證程式正確性，不得用於調整參數或推論檢索效果。該標示 MUST 出現在產出的設定檔與各查表資源的檔頭，而非僅在單一說明檔。

#### Scenario: 輸出含使用限制說明

- **WHEN** 產生合成語料完成
- **THEN** 輸出目錄含說明檔，且終端訊息載明該限制

#### Scenario: 產物檔頭含使用限制

- **WHEN** 檢視產出的設定檔與查表資源
- **THEN** 每份檔案的檔頭皆載明該限制

## ADDED Requirements

### Requirement: defect 全集為衍生產物的單一來源

產生器 SHALL 以一份 defect 全集（識別碼、別名、類別）為單一事實來源，由它衍生實體字典、CSV 實體來源、taxonomy 資源、defect 全集檔，以及以每個 defect 一條為結構的那一層語料。

各衍生產物中的 defect 識別碼 MUST 一致；任何一份產物出現不在全集中的 defect 即為錯誤。

#### Scenario: 衍生產物的鍵一致

- **WHEN** 比對字典、CSV、taxonomy 與 defect 全集檔中的 defect 識別碼
- **THEN** 四者的識別碼集合彼此相容，不存在僅出現於其中一份的識別碼

#### Scenario: 登錄層涵蓋全集

- **WHEN** 檢視以每個 defect 一條為結構的那一層語料
- **THEN** 全集中的每個 defect 皆有對應的 concept

### Requirement: taxonomy 產物具備覆蓋率缺口

產生器輸出的 taxonomy 資源 SHALL 刻意不完整：defect 全集中 MUST 同時存在有完整條目者、有條目但無判斷方法者，以及完全無條目者。

覆蓋率恆為滿的資料集無法暴露覆蓋率統計本身的錯誤，因此缺口是這份產物的必要性質而非瑕疵。

#### Scenario: 三種狀態皆存在

- **WHEN** 比對產出的 taxonomy 與 defect 全集
- **THEN** 存在有 method 的 defect、有條目但無 method 的 defect，以及不在 taxonomy 中的 defect

#### Scenario: 覆蓋率不為滿

- **WHEN** 以產出的兩份檔案計算 taxonomy 覆蓋率
- **THEN** 有條目的 defect 數小於 defect 總數

### Requirement: 產出可直接使用的設定

產生器 SHALL 在輸出目錄產出一份設定檔，其宣告的具名索引、實體來源與查表資源路徑皆指向同次產出的檔案，使用者 MUST 能以該設定直接建構全部索引而不需手工修改路徑。

設定中各層的宣告 MUST 反映該層的性質，至少包含 query 前處理與預設模式的差異。

#### Scenario: 設定可直接建索引

- **WHEN** 以產出的設定檔執行建構全部索引
- **THEN** 全部索引成功建立，無路徑錯誤

#### Scenario: 各層宣告反映其性質

- **WHEN** 檢視產出設定中的索引宣告
- **THEN** 識別碼為雜訊的那一層宣告剝除識別碼，識別碼為主訊號的那一層宣告保留

#### Scenario: 設定含依賴宣告

- **WHEN** 檢視產出設定中的索引宣告
- **THEN** 以其他層為實體字典來源的層宣告了該依賴
