## ADDED Requirements

### Requirement: 端點路徑帶版本前綴

既有的檢索、內容、關聯、遙測與語料統計端點 SHALL 全部移至 `/v1` 前綴之下，其行為、參數與回應結構 MUST NOT 改變。

#### Scenario: 檢索端點

- **WHEN** 呼叫 `/v1/search` 並要求三模式並排
- **THEN** 回應內容與未版本化時完全相同

#### Scenario: 內容端點

- **WHEN** 依序呼叫 `/v1/concept/{id}`、`/v1/concepts`、`/v1/concept/{id}/asset`
- **THEN** 三者行為與未版本化時完全相同

#### Scenario: 關聯端點

- **WHEN** 呼叫 `/v1/concept/{id}/neighbors`
- **THEN** 行為與未版本化時完全相同

#### Scenario: 遙測端點

- **WHEN** 呼叫 `/v1/feedback` 與 `/v1/report`
- **THEN** 兩者行為與未版本化時完全相同

#### Scenario: 路由順序約束仍成立

- **WHEN** 呼叫 `/v1/concept/{id}/neighbors` 與 `/v1/concept/{id}/asset`
- **THEN** 兩者正確路由，`concept_id` 不會吞入尾段路徑
