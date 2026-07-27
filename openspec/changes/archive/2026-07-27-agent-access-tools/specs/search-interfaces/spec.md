## ADDED Requirements

### Requirement: HTTP 批次全文端點

系統 SHALL 提供 HTTP `POST /concepts` 端點，接受 `concept_id` 陣列並批次回傳完整內容，具部分成功語意。

#### Scenario: 批次取回

- **WHEN** 以三個既有 id 呼叫該端點
- **THEN** 回應 HTTP 200，含三筆完整內容與空的錯誤清單

#### Scenario: 部分失敗仍回 200

- **WHEN** 請求中混有既有與不存在的 id
- **THEN** 回應 HTTP 200，既有者在內容清單、不存在者在錯誤清單

#### Scenario: 超過上限回 422

- **WHEN** 請求的 id 數量超過上限
- **THEN** 回應 HTTP 422

#### Scenario: 空清單回 422

- **WHEN** 以空陣列呼叫
- **THEN** 回應 HTTP 422

### Requirement: HTTP 關聯展開端點

系統 SHALL 提供 HTTP `GET /concept/{concept_id}/neighbors` 端點，支援指定深度與方向，回傳關聯 concept 的摘要清單與懸空引用清單。

#### Scenario: 展開一跳

- **WHEN** 以既有 id 呼叫且深度為 1
- **THEN** 回應 HTTP 200，含關聯 concept 的摘要清單

#### Scenario: 起點不存在

- **WHEN** 以不存在的 id 呼叫
- **THEN** 回應 HTTP 404

#### Scenario: 深度超過上限

- **WHEN** 指定深度大於 2
- **THEN** 回應 HTTP 422

#### Scenario: 無效方向

- **WHEN** 指定不支援的方向值
- **THEN** 回應 HTTP 422

### Requirement: HTTP 限定範圍搜尋端點

系統 SHALL 提供 HTTP `GET /grep` 端點，必須指定 bundle 或 concept 範圍，支援字面與正則兩種比對模式。

#### Scenario: 指定範圍搜尋

- **WHEN** 指定一個 bundle 與一個字面樣式呼叫
- **THEN** 回應 HTTP 200，含該 bundle 內的命中清單

#### Scenario: 未指定範圍回 422

- **WHEN** 未提供任何 bundle 或 concept 範圍
- **THEN** 回應 HTTP 422，訊息指引先以檢索縮小範圍

#### Scenario: 無效正則回 422

- **WHEN** 開啟正則但樣式無法編譯
- **THEN** 回應 HTTP 422

#### Scenario: 範圍指向不存在的 bundle 回 404

- **WHEN** 指定的 bundle 不存在於索引
- **THEN** 回應 HTTP 404

### Requirement: 新端點出現在互動式文件

新增的批次、關聯展開與限定範圍搜尋端點 SHALL 出現在互動式 API 文件頁，並可直接送出測試請求。

#### Scenario: 文件頁列出新端點

- **WHEN** 於瀏覽器開啟服務的文件路徑
- **THEN** 頁面列出 `/concepts`、`/concept/{concept_id}/neighbors` 與 `/grep`
