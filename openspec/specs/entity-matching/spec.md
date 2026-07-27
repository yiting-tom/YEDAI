# entity-matching Specification

## Purpose
TBD - created by archiving change okf-keyword-baseline. Update Purpose after archive.
## Requirements
### Requirement: 載入實體字典

系統 SHALL 從 YAML 檔載入實體字典，格式為實體類型對應到條目清單，每個條目含 `canonical` 與選填的 `aliases`。字典 MUST 為選填——未提供時系統仍可運作，僅模式 C 退化為純 regex 抽取。

#### Scenario: 載入含別名的字典

- **WHEN** 字典定義 `tool_id` 下的 `TEL-05` 帶別名 `TEL05` 與「五號機」
- **THEN** 三種寫法皆對應到類型 `tool_id`、正規名稱 `TEL-05`

#### Scenario: 條目為純字串

- **WHEN** 字典條目直接寫成字串而非物件
- **THEN** 該字串同時作為正規名稱與唯一別名

#### Scenario: 未提供字典

- **WHEN** 未指定字典路徑
- **THEN** 系統以空字典運作，模式 C 僅使用 regex 抽取的識別碼

#### Scenario: 字典路徑不存在

- **WHEN** 指定的字典路徑不存在
- **THEN** 系統回報明確錯誤而非靜默忽略

### Requirement: 實體抽取與正規化

系統 SHALL 從文本抽取實體，來源分為兩類：命中字典者標記 `source=dict` 並帶有實體類型與正規名稱；未命中字典但符合識別碼正則樣式者標記 `source=regex`、類型為 `unknown`。含中文或空白的別名 MUST 以最長優先的字面掃描比對。同一實體在同一文本中 MUST 只計一次。

#### Scenario: 字典命中

- **WHEN** 文本含 `TEL-05` 且字典有此條目
- **THEN** 抽出實體的 `source` 為 `dict`，類型為 `tool_id`

#### Scenario: 字典未命中的識別碼

- **WHEN** 文本含符合識別碼樣式但字典沒有的字串
- **THEN** 抽出實體的 `source` 為 `regex`，類型為 `unknown`

#### Scenario: 中文別名最長優先

- **WHEN** 字典同時含別名「五號機」與「五號」
- **THEN** 文本中的「五號機」比對到「五號機」而非「五號」

#### Scenario: 重複實體去重

- **WHEN** 同一實體在文本中出現多次
- **THEN** 抽取結果中該實體僅出現一次

### Requirement: 實體腿計分

模式 C SHALL 依查詢實體與 concept 實體的交集計分，分數以實體的逆文件頻率加權，並依實體在 concept 中出現的欄位給予位置加權（標題與描述高於內文）。實體腿分數 MUST 正規化至 0 到 1 之間，代表查詢實體被涵蓋的加權比例。

#### Scenario: 完全涵蓋查詢實體且皆在最高權重欄位

- **WHEN** 某 concept 在最高權重欄位中含查詢的所有實體
- **THEN** 該 concept 的實體腿分數為 1.0

#### Scenario: 部分涵蓋查詢實體

- **WHEN** 某 concept 只含查詢實體的一部分
- **THEN** 該 concept 的實體腿分數嚴格小於完全涵蓋者

#### Scenario: 未涵蓋任何實體

- **WHEN** 某 concept 不含查詢中的任何實體
- **THEN** 該 concept 的實體腿分數為 0.0

#### Scenario: 罕見實體權重較高

- **WHEN** 查詢含一個高頻實體與一個罕見實體
- **THEN** 只命中罕見實體的 concept 分數高於只命中高頻實體的 concept

#### Scenario: 標題命中加權較高

- **WHEN** 實體出現在 concept A 的標題、出現在 concept B 的內文，其餘條件相同
- **THEN** concept A 的實體腿分數高於 concept B

### Requirement: 詞彙腿與實體腿融合

模式 C SHALL 將詞彙腿分數與實體腿分數各自正規化至 0 到 1 後線性加權合併，權重可由設定檔覆寫。系統 MUST NOT 使用僅依排名的融合方式，以保留兩條腿的分數資訊供分析。

#### Scenario: 融合權重可覆寫

- **WHEN** 設定檔指定詞彙腿權重 0.3、實體腿權重 0.7
- **THEN** 最終分數依此權重計算

#### Scenario: 兩腿分數可個別取得

- **WHEN** 檢視模式 C 的結果
- **THEN** 每筆結果的詞彙腿與實體腿分數皆可個別讀取

### Requirement: 選用的實體硬過濾

系統 SHALL 提供選用開關，開啟後模式 C 僅回傳包含查詢中所有實體的 concept。此開關預設關閉。

#### Scenario: 開啟硬過濾

- **WHEN** 查詢含兩個實體且開啟硬過濾
- **THEN** 結果只含同時包含這兩個實體的 concept

#### Scenario: 預設不過濾

- **WHEN** 未指定硬過濾
- **THEN** 結果依分數排序，不因缺少某實體而被排除

### Requirement: 字典覆蓋率量測

系統 SHALL 統計語料與查詢中實體來源的分佈，區分 `dict` 命中與 `regex` fallback 的數量與比例，作為字典覆蓋率缺口的量測依據。

#### Scenario: 語料覆蓋率統計

- **WHEN** 索引建構完成
- **THEN** 系統可回報語料中不重複實體總數，以及其中來自字典與來自 regex fallback 的比例

#### Scenario: 查詢覆蓋率統計

- **WHEN** 累積若干次查詢後產出報告
- **THEN** 報告含查詢實體中字典命中與 regex fallback 的比例

