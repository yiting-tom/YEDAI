## ADDED Requirements

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

## MODIFIED Requirements

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
