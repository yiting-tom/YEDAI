## ADDED Requirements

### Requirement: HTTP 全文端點

系統 SHALL 提供 HTTP `GET /concept/{concept_id}` 端點，回傳該 concept 的完整內容，包含原始 markdown 全文、解析後的 frontmatter、section 清單、figures 與識別資訊。

#### Scenario: 取回既有 concept

- **WHEN** 以檢索結果中的 `concept_id` 呼叫 `/concept/{concept_id}`
- **THEN** 回應 HTTP 200，內容含原始 markdown 全文、frontmatter、section 清單與 figures

#### Scenario: concept id 不存在

- **WHEN** 以不存在的 `concept_id` 呼叫該端點
- **THEN** 回應 HTTP 404

#### Scenario: 索引過期，檔案已不存在

- **WHEN** `concept_id` 存在於索引但對應檔案已被移除
- **THEN** 回應 HTTP 410，且訊息指示需要重建索引

#### Scenario: 索引未載入

- **WHEN** 服務啟動時索引載入失敗，仍呼叫該端點
- **THEN** 回應 HTTP 503

#### Scenario: 檢索結果可直接串接取全文

- **WHEN** 先呼叫 `/search` 取得結果，再以其中任一筆的 `concept_id` 呼叫全文端點
- **THEN** 兩者的 `concept_id`、`bundle_id`、`type`、`title` 與路徑一致

#### Scenario: 端點出現在互動式文件

- **WHEN** 於瀏覽器開啟服務的文件路徑
- **THEN** 頁面列出 `/concept/{concept_id}` 端點，並可直接送出測試請求
