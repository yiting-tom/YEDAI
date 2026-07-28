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

系統 SHALL 從文本抽取實體，來源分為兩類：命中字典者標記 `source=dict` 並帶有實體類型與正規名稱；未命中字典但符合識別碼正則樣式者標記 `source=regex`。含中文或空白的別名 MUST 以最長優先的字面掃描比對。同一實體在同一文本中 MUST 只計一次。

regex fallback 的實體類型 SHALL 由**比對到的樣式**決定：樣式可宣告一個「形狀決定的類型」，命中該樣式者帶該類型；未宣告者帶 `unknown`。

樣式 MUST NOT 在形狀無法唯一決定類型時宣告類型。多個類型共用同一形狀時猜測型別，會讓覆蓋率統計得到一個自信而錯誤的分母——那比沒有分母更難察覺。

層級展開產生的父層詞元 SHALL 使用樣式另行宣告的「父層類型」，而非沿用子層類型：`AEPOL1#PM1` 是 `chamber_id`，其父層 `AEPOL1` 是 `tool_id`，兩者不同。

#### Scenario: 字典命中

- **WHEN** 文本含 `TEL-05` 且字典收錄該識別碼
- **THEN** 抽出實體的 `source` 為 `dict`，類型為 `tool_id`

#### Scenario: 形狀不決定類型者歸入 unknown

- **WHEN** 文本含符合通用識別碼樣式但不在字典中的字串，且該樣式未宣告類型
- **THEN** 抽出實體的 `source` 為 `regex`，類型為 `unknown`

#### Scenario: 形狀決定類型者帶該類型

- **WHEN** 文本含 `TSK04#PM3`，該字串不在任何字典中
- **THEN** 抽出實體的 `source` 為 `regex`，類型為 `chamber_id`

#### Scenario: 父層帶自己的類型

- **WHEN** 文本含 `TSK04#PM3`，兩者皆不在字典中
- **THEN** 抽出 `chamber_id` 的 `TSK04#PM3` 與 `tool_id` 的 `TSK04`，兩者 `source` 皆為 `regex`

#### Scenario: 字典優先於形狀

- **WHEN** 字典把某個含 `#` 的識別碼收錄為另一個類型
- **THEN** 以字典的類型為準——字典是人維護的，形狀是從樣式推的

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

依類型拆解的 `dictionary_coverage` SHALL 只在該類型的**分母可測**時給出數值，否則 MUST 為 `null`。分母可測的條件是：該類型的每一次出現都必然被某個宣告了該類型的樣式圈到。

哪些類型分母可測 MUST 由**建索引當時實際使用的樣式**導出，MUST NOT 寫成固定常數——使用者換掉樣式清單時，一組不再成立的完整性宣稱不會報錯，只會讓比例繼續看起來可信。該清單 MUST 隨統計一併輸出，否則讀報告的人無從判斷一個 `null` 是「沒有這種實體」還是「分母不可測」。

不可測時給出比例即等於宣稱「字典已完整覆蓋」——因為未覆蓋的部分根本沒被算進分母。這個偏誤的方向是「字典夠用、不必維護」，正好是使用者最不該被誤導的方向。`null` 是誠實的答案：我們不知道。

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

#### Scenario: 分母可測的類型給出真實比例

- **WHEN** 語料含 360 個腔體，其中 180 個在字典中
- **THEN** `chamber_id` 的 `dictionary_coverage` 為 `0.5`，而非 `1.0`

#### Scenario: 分母不可測的類型給 null

- **WHEN** 語料含 `tool_id` 實體，而機台可以裸寫、其形狀無法與其他類型區分
- **THEN** `tool_id` 回報 dict 與 regex 計數，但 `dictionary_coverage` 為 `null`

#### Scenario: 可測類型隨樣式清單改變

- **WHEN** 設定只保留作業序號一條樣式
- **THEN** 可測類型只剩 `op_no`，其餘類型的 `dictionary_coverage` 皆為 `null`

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

### Requirement: 類型宣告不得在設定路徑上遺失

設定檔的 `identifier_patterns` 是字串清單，承載不了類型宣告。系統 SHALL 在建構斷詞器時把設定中的樣式字串**逐條**對回內建樣式，相同者沿用其類型宣告。

逐條而非整份比對：使用者新增一條自訂樣式，MUST NOT 使其餘樣式的宣告一併失效。使用者自訂的樣式沒有宣告，其命中歸入 `unknown`——系統確實無從得知那些是什麼類型。

這一條是必要的：宣告若在「設定 → 斷詞器」之間被丟掉，覆蓋率會退回恆為 1.0，而且沒有任何地方會報錯——正是本能力要修的失效形式。

#### Scenario: 預設設定保留宣告

- **WHEN** 以預設設定建構斷詞器
- **THEN** `chamber_id` 在可測類型清單中

#### Scenario: 新增自訂樣式不影響其他宣告

- **WHEN** 設定為內建樣式清單再加一條自訂樣式
- **THEN** 內建樣式的類型宣告全部保留，自訂樣式無宣告

