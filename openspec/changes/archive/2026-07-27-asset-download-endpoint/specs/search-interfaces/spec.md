## ADDED Requirements

### Requirement: HTTP 資產下載端點

系統 SHALL 提供 HTTP `GET /concept/{concept_id}/asset` 端點，以 `path` 查詢參數指定相對路徑，回傳資產檔案內容並帶對應的 media type。

#### Scenario: 取回資產

- **WHEN** 以某 concept 的 `assets` 中的路徑呼叫該端點
- **THEN** 回應 HTTP 200，內容為該檔案的位元組，media type 對應其副檔名

#### Scenario: concept 不存在

- **WHEN** 以不存在的 `concept_id` 呼叫
- **THEN** 回應 HTTP 404

#### Scenario: 資產檔案不存在

- **WHEN** `concept_id` 存在但資產檔案不在磁碟上
- **THEN** 回應 HTTP 404

#### Scenario: 路徑逸出或違反資產目錄限制

- **WHEN** 路徑含 `..`、為絕對路徑，或不在允許的資產目錄之下
- **THEN** 回應 HTTP 403

#### Scenario: 缺少 path 參數

- **WHEN** 未提供 `path` 查詢參數
- **THEN** 回應 HTTP 422

#### Scenario: 以附件下載

- **WHEN** 指定 `download=true`
- **THEN** 回應含附件形式的內容處置標頭

#### Scenario: 索引未載入

- **WHEN** 服務啟動時索引載入失敗，仍呼叫該端點
- **THEN** 回應 HTTP 503

#### Scenario: 端點出現在互動式文件

- **WHEN** 於瀏覽器開啟服務的文件路徑
- **THEN** 頁面列出 `/concept/{concept_id}/asset` 端點

#### Scenario: 由 concept 全文串接取資產

- **WHEN** 先呼叫 `/concept/{id}` 取得 `assets` 陣列，再以其中任一項呼叫資產端點
- **THEN** 回應 HTTP 200
