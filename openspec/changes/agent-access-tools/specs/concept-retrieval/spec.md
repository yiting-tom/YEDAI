## ADDED Requirements

### Requirement: 批次取回多個 concept 全文

系統 SHALL 提供一次取回多個 concept 完整內容的能力，每筆的內容與單筆取回一致。批次 MUST 有筆數上限，超過上限時 MUST 拒絕請求。

#### Scenario: 一次取回多筆

- **WHEN** 以三個既有 `concept_id` 批次請求
- **THEN** 回傳三筆完整內容，順序與請求一致

#### Scenario: 超過筆數上限

- **WHEN** 請求的 id 數量超過上限
- **THEN** 系統拒絕該請求並說明上限

#### Scenario: 空清單

- **WHEN** 以空的 id 清單請求
- **THEN** 系統拒絕該請求

#### Scenario: 可省略原始全文

- **WHEN** 指定不包含原始全文
- **THEN** 回傳結果含結構化欄位但不含原始 markdown 全文

### Requirement: 批次取回採部分成功語意

批次取回中單一 `concept_id` 失敗 MUST NOT 影響其餘項目。失敗項目 MUST 逐筆回報其 id 與原因，且原因 MUST 區分「不存在」與「檔案已移除」。

#### Scenario: 部分 id 不存在

- **WHEN** 批次請求中混有既有與不存在的 id
- **THEN** 既有者正常回傳，不存在者列於錯誤清單，整體請求仍成功

#### Scenario: 錯誤原因可區分

- **WHEN** 批次中一筆 id 不存在、另一筆檔案已自磁碟移除
- **THEN** 兩者的錯誤原因不同，且後者指示重建索引

#### Scenario: 全部失敗

- **WHEN** 批次中所有 id 皆不存在
- **THEN** 回傳空的內容清單與完整的錯誤清單，整體請求仍成功
