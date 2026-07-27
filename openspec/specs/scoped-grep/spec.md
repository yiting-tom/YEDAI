# scoped-grep Specification

## Purpose
TBD - created by archiving change agent-access-tools. Update Purpose after archive.
## Requirements
### Requirement: 強制限定搜尋範圍

系統 SHALL 要求字面搜尋必須指定 bundle 或 concept 範圍至少其一。未指定任何範圍時 MUST 拒絕執行，且錯誤訊息 MUST 指引使用者先以檢索縮小範圍再行搜尋。

#### Scenario: 未指定範圍

- **WHEN** 呼叫搜尋但未提供任何 bundle 或 concept 範圍
- **THEN** 系統拒絕執行，並在訊息中說明應先以檢索取得 bundle 範圍

#### Scenario: 以 bundle 限定範圍

- **WHEN** 指定一個 bundle 進行搜尋
- **THEN** 只搜尋該 bundle 內的 concept 檔案

#### Scenario: 以 concept 限定範圍

- **WHEN** 指定若干 concept id 進行搜尋
- **THEN** 只搜尋這些 concept 的檔案

#### Scenario: 範圍指向不存在的 bundle

- **WHEN** 指定的 bundle 不存在於索引
- **THEN** 系統回報該範圍無效

### Requirement: 預設字面比對，正則須明確開啟

搜尋 SHALL 預設以字面子字串比對。正則比對 MUST 由呼叫端明確開啟。無效的正則 MUST 回報為請求錯誤，不得造成未處理的例外。

#### Scenario: 預設字面比對

- **WHEN** 以含正則特殊字元的字串搜尋且未開啟正則
- **THEN** 該字串被當作字面內容比對

#### Scenario: 開啟正則

- **WHEN** 開啟正則並提供合法樣式
- **THEN** 以正則進行比對

#### Scenario: 無效正則

- **WHEN** 開啟正則但樣式無法編譯
- **THEN** 系統回報請求錯誤並說明原因

#### Scenario: 大小寫不敏感

- **WHEN** 指定忽略大小寫
- **THEN** 比對不區分大小寫

### Requirement: 搜尋結果內容與上限

搜尋結果 SHALL 逐筆回報所屬 concept id、bundle id、行號與該行內容。系統 MUST 支援結果筆數上限，並在結果被截斷時明確標示。

#### Scenario: 結果含定位資訊

- **WHEN** 搜尋命中某行
- **THEN** 該筆結果含 concept id、bundle id、行號與行內容

#### Scenario: 結果被截斷

- **WHEN** 命中數超過指定上限
- **THEN** 回傳至上限筆數，並標示結果已被截斷

#### Scenario: 無命中

- **WHEN** 範圍內沒有任何命中
- **THEN** 回傳空結果而非錯誤

#### Scenario: 檔案已不存在

- **WHEN** 範圍內某 concept 的檔案已自磁碟移除
- **THEN** 系統略過該檔案並繼續搜尋其餘檔案

