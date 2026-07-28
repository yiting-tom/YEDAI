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

系統 SHALL 統計語料與查詢中實體來源的分佈，區分 `dict` 命中與 `regex` fallback 的數量與比例，作為字典覆蓋率缺口的量測依據。統計 MUST 同時提供全域數字與**依實體類型拆解**的數字。

拆解為必要而非便利：模式 C 的字典在不同類型上作用不同——對一般詞（缺陷名）是語義正規化，缺少時該腿歸零；對結構化識別碼（機台）是擋掉 regex 誤圈，缺少時僅精確度下降。單一比例會把兩者平均成無法解讀的中間值。

依類型拆解的統計 MUST 僅以實體類型名稱為鍵，MUST NOT 含任何實體的正規名稱或原始字串。

#### Scenario: 語料覆蓋率統計

- **WHEN** 索引建構完成
- **THEN** 系統可回報語料中不重複實體總數，以及其中來自字典與來自 regex fallback 的比例

#### Scenario: 查詢覆蓋率統計

- **WHEN** 累積若干次查詢後產出報告
- **THEN** 報告含查詢實體中字典命中與 regex fallback 的比例

#### Scenario: 依類型拆解

- **WHEN** 語料含 `tool_id` 與 `defect_code` 兩類實體
- **THEN** 統計可分別回報兩類各自的 dict 與 regex 數量

#### Scenario: 未命中字典者歸入 unknown 類型

- **WHEN** 某識別碼符合正則但不在任何字典中
- **THEN** 它計入 `unknown` 類型的 regex 計數，且其正規名稱不出現在統計中

### Requirement: CSV 實體來源

系統 SHALL 支援以 CSV 檔作為實體字典來源，來源於設定中宣告，每筆宣告含實體類型、檔案路徑與 schema 名稱。CSV 來源 MUST 可與既有 YAML 字典並存，兩者載入至同一份字典。

系統 MUST 依 schema 名稱以專用解析函式處理，MUST NOT 提供以欄位對應設定驅動的通用讀取器——欄位對應錯誤是靜默的，會產出看似正常實則整份錯誤的字典。

支援的 schema：

- `id_only`：單欄，值本身即正規名稱。值含 `#` 者為子層實體，其類型與宣告類型不同（例如宣告 `tool_id` 時，含 `#` 的列為 `chamber_id`）
- `module_code_name`：三欄 `Module, defect code, defect name`。`code` 為正規名稱，`name` 為別名，`Module` 為中繼資料且 MUST NOT 併入實體識別

#### Scenario: 載入單欄識別碼來源

- **WHEN** 設定宣告類型 `tool_id` 的 `id_only` 來源，檔案含 `aepol1`
- **THEN** `aepol1` 以類型 `tool_id`、正規名稱 `AEPOL1` 進入字典

#### Scenario: 同表中的子層實體自動歸類

- **WHEN** 同一 `id_only` 來源同時含 `aepol1` 與 `aepol1#pm1`
- **THEN** 前者類型為 `tool_id`，後者類型為 `chamber_id`

#### Scenario: 載入三欄缺陷來源

- **WHEN** `module_code_name` 來源含一列 `ETCH, PARTICLE, 微粒`
- **THEN** `PARTICLE` 為正規名稱，「微粒」為其別名，兩者皆對應同一實體

#### Scenario: Module 不影響實體識別

- **WHEN** 兩列的 `Module` 不同但 `defect code` 相同
- **THEN** 兩列對應到同一個實體，不因 Module 而分裂

#### Scenario: CSV 與 YAML 並存

- **WHEN** 同時提供 YAML 字典與 CSV 來源
- **THEN** 兩者的條目都可被查詢到

#### Scenario: 欄位數不符時明確失敗

- **WHEN** `module_code_name` 來源的某列欄位數不是三欄
- **THEN** 系統回報含檔名與列號的錯誤，而非靜默略過

#### Scenario: 來源檔不存在

- **WHEN** 設定宣告的 CSV 路徑不存在
- **THEN** 系統回報明確錯誤而非靜默忽略

#### Scenario: 未知 schema 名稱

- **WHEN** 設定宣告了不支援的 schema 名稱
- **THEN** 系統在載入時失敗並列出支援的名稱

### Requirement: 別名的語言分段註冊

實體別名 SHALL 以整串註冊，且當該串同時含中日韓字元與拉丁字元時，MUST 額外將各語言區塊分別註冊為別名。分段 MUST 切在中日韓與非中日韓字元的交界，MUST NOT 進一步切分區塊內的詞——別名是完整名稱而非詞元，拆開會讓常見詞成為缺陷代碼的別名。

此規則使系統不需事先知道來源的語言混合形式即可正確比對。

#### Scenario: 同格中英混合

- **WHEN** 別名為 `Particle 微粒`
- **THEN** `Particle 微粒`、`Particle`、`微粒` 三者皆對應到同一正規名稱

#### Scenario: 多詞英文名稱不被拆散

- **WHEN** 別名為 `Pattern Collapse 圖案倒塌`
- **THEN** 註冊 `Pattern Collapse` 與 `圖案倒塌`，MUST NOT 單獨註冊 `Pattern`

#### Scenario: 純中文別名

- **WHEN** 別名為「微粒」
- **THEN** 僅註冊「微粒」，不產生額外條目

#### Scenario: 純拉丁別名

- **WHEN** 別名為 `Particle`
- **THEN** 僅註冊 `Particle`，不產生額外條目

