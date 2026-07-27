# concept-graph Specification

## Purpose
TBD - created by archiving change agent-access-tools. Update Purpose after archive.
## Requirements
### Requirement: 保存 concept 關聯邊

索引 SHALL 保存 concept 之間的 `related` 關聯邊，同時包含出向（該 concept 指向誰）與入向（誰指向該 concept）。入向邊 MUST 於建立索引時一併計算，不得要求查詢時掃描全部文件。

#### Scenario: 出向邊可查

- **WHEN** 某 concept 的 frontmatter 的 `related` 列出兩個 concept id
- **THEN** 索引中該 concept 的出向邊含這兩個 id

#### Scenario: 入向邊可查

- **WHEN** concept A 的 `related` 指向 concept B
- **THEN** 索引中 concept B 的入向邊含 A

#### Scenario: 入向邊不需掃描全部文件

- **WHEN** 查詢某 concept 的入向邊
- **THEN** 系統直接自索引取得，不遍歷全部 concept

### Requirement: 展開 concept 關聯

系統 SHALL 提供依 `concept_id` 展開關聯的能力，可指定展開深度與方向。深度 MUST 至少支援 1 與 2，且 MUST 拒絕超過 2 的深度。方向 MUST 支援出向、入向與雙向。

#### Scenario: 展開一跳

- **WHEN** 以深度 1 展開某 concept
- **THEN** 回傳其直接關聯的 concept 清單，每筆含 id、type、title、description 與 `index_line` 格式的摘要行

#### Scenario: 展開兩跳

- **WHEN** 以深度 2 展開某 concept
- **THEN** 回傳結果標示各 concept 距起點的跳數，且不含起點自身

#### Scenario: 深度超過上限

- **WHEN** 指定深度大於 2
- **THEN** 系統拒絕並回報錯誤

#### Scenario: 指定方向

- **WHEN** 指定只展開入向
- **THEN** 結果只含指向起點的 concept

#### Scenario: 起點不存在

- **WHEN** 以不存在的 `concept_id` 展開
- **THEN** 系統回報查無此 concept

#### Scenario: 沒有任何關聯

- **WHEN** 某 concept 既無出向也無入向關聯
- **THEN** 回傳空的關聯清單而非錯誤

### Requirement: 回報懸空關聯

系統 SHALL 將指向語料中不存在 concept 的 `related` 條目單獨列為懸空引用，不得靜默丟棄。

#### Scenario: 懸空引用被列出

- **WHEN** 某 concept 的 `related` 含一個語料中不存在的 id
- **THEN** 展開結果將該 id 列於懸空引用清單，且不出現在正常關聯清單中

#### Scenario: 語料層級的懸空統計

- **WHEN** 建立索引完成
- **THEN** 語料統計含懸空關聯的總數

