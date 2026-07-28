## MODIFIED Requirements

### Requirement: 類型宣告不得在設定路徑上遺失

設定的 `identifier_patterns` 每一項 SHALL 可以是樣式字串，或一個帶宣告的 mapping，欄位為 `pattern`（必填）、`type`、`parent_type`、`shape_complete`。

給字串時，系統 SHALL 把它**逐條**對回內建樣式，相同者沿用其類型宣告。逐條而非整份比對：使用者新增一條自訂樣式，MUST NOT 使其餘樣式的宣告一併失效。既不是內建、也未帶宣告的樣式，其命中歸入 `unknown`——系統確實無從得知那些是什麼類型。

這一條是必要的：宣告若在「設定 → 斷詞器」之間被丟掉，覆蓋率會退回恆為 1.0，而且沒有任何地方會報錯。

支援 mapping 形式的理由是保密邊界。敏感的識別碼組成規則必須能住在未進版控的本機設定，而只收字串會迫使使用者在「斷詞正確」與「統計正確」之間二選一——那是一個不該存在的選擇。

mapping 中 `shape_complete` 為真但 `type` 未給時 MUST 視為設定錯誤：沒有類型的完整性宣稱無法對應到任何分母。

#### Scenario: 預設設定保留宣告

- **WHEN** 以預設設定建構斷詞器
- **THEN** `chamber_id` 在可測類型清單中

#### Scenario: 新增自訂樣式不影響其他宣告

- **WHEN** 設定為內建樣式清單再加一條自訂樣式
- **THEN** 內建樣式的類型宣告全部保留，自訂樣式無宣告

#### Scenario: 設定為自訂樣式宣告類型

- **WHEN** 設定以 mapping 給出一條樣式並宣告 `type` 與 `parent_type`
- **THEN** 該樣式的命中帶該類型，其層級展開的父層帶宣告的父層類型

#### Scenario: 設定宣告分母可測

- **WHEN** 設定的 mapping 宣告 `shape_complete: true` 與一個類型
- **THEN** 該類型出現在可測類型清單中，其覆蓋率比例得以計算

#### Scenario: 宣告完整性卻未給類型

- **WHEN** 設定的 mapping 給了 `shape_complete: true` 但沒有 `type`
- **THEN** 系統回報設定錯誤而非靜默忽略

#### Scenario: 樣式字串仍然可用

- **WHEN** 設定沿用字串清單形式
- **THEN** 行為與先前相同
