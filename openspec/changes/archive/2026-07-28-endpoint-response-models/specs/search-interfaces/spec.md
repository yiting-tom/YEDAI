## ADDED Requirements

### Requirement: 回應結構納入 OpenAPI schema

每個回傳 JSON 的 HTTP 端點 SHALL 宣告回應模型，使產出的 OpenAPI 文件描述該端點回應的欄位與型別。回傳二進位檔案的端點 MUST 改以檔案回應類別宣告，不受此要求約束。

回應模型 MUST 如實描述既有輸出，MUST NOT 改變任何端點的回應內容——模型與輸出不符時，應修正模型。

#### Scenario: 檢索端點的回應結構可讀

- **WHEN** 讀取 OpenAPI 文件中 `/v1/search` 的 200 回應
- **THEN** 可看到 `query_id`、`results`、`entities`、`overlaps` 等欄位及其型別

#### Scenario: 巢狀結構被展開

- **WHEN** 檢視 `/v1/search` 回應中 `results` 的結構
- **THEN** 可看到每個模式含 `hits` 清單，且單筆 hit 的欄位（含 `score`、`lexical_score`、`entity_score`、`index_line`）皆有描述

#### Scenario: 批次端點的部分成功語意可見

- **WHEN** 檢視 `/v1/concepts` 的回應結構
- **THEN** 可看到 `concepts` 與 `errors` 兩個清單，且 `errors` 的項目含 `concept_id`、`reason`、`detail`

#### Scenario: 資產端點不宣告 JSON 模型

- **WHEN** 檢視 `/v1/concept/{concept_id}/asset` 的回應
- **THEN** 它以檔案回應描述，不含 JSON schema

#### Scenario: 回應內容不因建模而改變

- **WHEN** 對建模前後的同一組請求比較回應內容
- **THEN** 兩者完全相同

### Requirement: 文件與回應模型同步

文件 SHALL 涵蓋每個回應模型的頂層欄位，並以測試強制。測試 MUST 在 schema 新增欄位而文件未同步時失敗。

#### Scenario: 新增回應欄位而未更新文件

- **WHEN** 回應模型新增一個頂層欄位，但 `docs/api.md` 未提及
- **THEN** 文件同步測試失敗
