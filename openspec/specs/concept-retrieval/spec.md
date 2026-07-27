# concept-retrieval Specification

## Purpose
TBD - created by archiving change concept-fulltext-endpoint. Update Purpose after archive.
## Requirements
### Requirement: 依 concept id 取回完整內容

系統 SHALL 提供依 `concept_id` 取回單一 concept 完整內容的能力。回傳內容 MUST 包含該 concept 的原始 markdown 全文（含 frontmatter）、解析後的 frontmatter 字典、依 `## ` 切分的 section 清單、figures 清單，以及 `related`、`tags`、`assets`、`resource`、`provenance` 等欄位。

#### Scenario: 取回既有 concept

- **WHEN** 以索引中存在的 `concept_id` 請求全文
- **THEN** 回傳該 concept 的原始 markdown 全文、frontmatter、section 清單與 figures

#### Scenario: 原始全文可直接閱讀

- **WHEN** 檢視回傳的原始 markdown 欄位
- **THEN** 其內容與磁碟上的檔案完全一致，包含 frontmatter 分隔線與 body

#### Scenario: section 依二級標題切分

- **WHEN** concept 的 body 含多個 `## ` 標題
- **THEN** 回傳的 section 清單依序含各標題與其內容

#### Scenario: 回傳與檢索結果一致的識別資訊

- **WHEN** 取回 concept 全文
- **THEN** 其 `concept_id`、`bundle_id`、`type`、`title`、`description`、路徑與 `index_line` 與該 concept 在檢索結果中的對應欄位一致

### Requirement: 全文於請求時自磁碟讀取

系統 SHALL 於請求時從磁碟讀取 concept 檔案，而非將全文儲存於索引中。檔案位置 MUST 由索引中的 bundle 根目錄登錄與相對路徑組合而得。

#### Scenario: 檔案內容變更立即反映

- **WHEN** concept 檔案在建立索引之後被修改，且未重建索引
- **THEN** 取回的全文為磁碟上的最新內容

#### Scenario: 索引不含全文

- **WHEN** 檢視序列化後的索引
- **THEN** 索引不含任何 concept 的 body 內容

### Requirement: 解析行為與檢索管線一致

取回全文時的解析 SHALL 重用既有的 concept 解析路徑，使 frontmatter 變體、未知欄位保留與 section 切分等行為與建索引時完全一致。

#### Scenario: 無分隔線 frontmatter

- **WHEN** 取回一個 frontmatter 未使用 `---` 分隔線的 concept
- **THEN** frontmatter 與 body 被正確切分，行為與建索引時相同

#### Scenario: 未知欄位保留

- **WHEN** concept 的 frontmatter 含規格未定義的欄位
- **THEN** 該欄位出現在回傳的 frontmatter 中

### Requirement: 區分「不存在」與「索引過期」

系統 SHALL 對兩種失敗情況給出可區分的回應：`concept_id` 不存在於索引中，與 `concept_id` 存在於索引但對應檔案已不在磁碟上。後者的訊息 MUST 指示重建索引。

#### Scenario: concept id 不存在

- **WHEN** 以索引中不存在的 `concept_id` 請求全文
- **THEN** 回應表示查無此 concept

#### Scenario: 檔案已被移除

- **WHEN** `concept_id` 存在於索引，但其對應檔案在建索引後已被刪除或移動
- **THEN** 回應與「不存在」不同，且訊息指示需要重建索引

### Requirement: 路徑必須位於 bundle 根目錄之下

系統 SHALL 在讀取檔案前驗證解析後的絕對路徑位於該 concept 所屬 bundle 的根目錄之下，不符者 MUST 拒絕讀取。

#### Scenario: 路徑逸出 bundle 根目錄

- **WHEN** 索引中某筆記錄的相對路徑會使解析結果落在 bundle 根目錄之外
- **THEN** 系統拒絕讀取該檔案並回報錯誤

### Requirement: 讀取邏輯不依賴傳輸層

取回全文的實作 SHALL 位於獨立模組，只依賴索引與解析器，不依賴 HTTP 框架，使其可被其他介面直接重用。

#### Scenario: 不經 HTTP 直接取用

- **WHEN** 程式直接以索引與 `concept_id` 呼叫取全文函式
- **THEN** 回傳完整內容，無須啟動 HTTP 服務

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

