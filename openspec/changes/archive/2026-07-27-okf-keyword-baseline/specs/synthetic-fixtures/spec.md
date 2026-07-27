## ADDED Requirements

### Requirement: 產生格式相符的合成 OKF bundle

系統 SHALL 提供合成 bundle 產生器，輸出的目錄結構與檔案格式必須與真實 OKF bundle 一致：每個 bundle 含 `manifest.json` 與 `okf/` 目錄，`okf/` 下含 `index.md`、`summary.md`、`log.md`、`_assets/` 與若干 concept 檔。concept 的 frontmatter MUST 涵蓋規格定義的所有欄位。

#### Scenario: 產生指定數量的 bundle

- **WHEN** 使用者要求產生 30 個 bundle
- **THEN** 輸出目錄含 30 個 bundle 目錄，每個具備完整結構

#### Scenario: 產出可被解析器解析

- **WHEN** 對合成語料執行索引建構
- **THEN** 所有 concept 皆被成功解析，無解析失敗

#### Scenario: summary 使用無分隔線格式

- **WHEN** 檢視合成的 `summary.md`
- **THEN** 其 frontmatter 採用無 `---` 分隔線的格式，以覆蓋該解析路徑

### Requirement: 合成內容含可辨識的假實體

合成 concept 的內容 SHALL 大量使用假的機台識別碼、製程識別碼、flow 識別碼與缺陷代碼，且相似識別碼（僅末碼不同者）MUST 同時存在，以便驗證識別碼區辨行為。產生器 SHALL 同時輸出對應的實體字典檔。

#### Scenario: 含相似識別碼

- **WHEN** 檢視合成語料
- **THEN** 存在僅末碼不同的成對機台識別碼，且分屬不同 concept

#### Scenario: 產出配套字典

- **WHEN** 產生合成語料
- **THEN** 同時輸出可直接用於模式 C 的實體字典檔

### Requirement: 合成語料具備類型模板重複性

合成 concept SHALL 依類型套用固定的區段模板，使不同 concept 之間結構重複但內容不同，以重現真實語料的類型重複特性。

#### Scenario: 同類型共用區段結構

- **WHEN** 檢視兩個同類型的合成 concept
- **THEN** 兩者具有相同的 `## ` 區段標題序列，但區段內容不同

### Requirement: 產生結果可重現

產生器 SHALL 接受隨機種子參數，相同種子與參數 MUST 產生完全相同的輸出。

#### Scenario: 相同種子產生相同輸出

- **WHEN** 以相同種子執行產生器兩次
- **THEN** 兩次輸出的檔案內容完全相同

### Requirement: 明示合成資料的使用限制

產生器 SHALL 在輸出目錄與終端訊息中明確標示：合成資料僅供驗證程式正確性，不得用於調整參數或推論檢索效果。

#### Scenario: 輸出含使用限制說明

- **WHEN** 產生合成語料完成
- **THEN** 輸出目錄含說明檔，且終端訊息載明該限制
