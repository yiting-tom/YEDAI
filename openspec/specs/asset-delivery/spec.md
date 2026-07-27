# asset-delivery Specification

## Purpose
TBD - created by archiving change asset-download-endpoint. Update Purpose after archive.
## Requirements
### Requirement: 依 concept 與相對路徑取回資產

系統 SHALL 提供依 `concept_id` 與相對路徑取回資產檔案的能力。相對路徑 MUST 以該 concept 檔案所在目錄為基準解析，使 `assets` frontmatter、`figures` 與 `## Citations` 中的寫法可直接使用而無須轉換。

#### Scenario: 取回 concept 引用的資產

- **WHEN** 以某 concept 的 `assets` 陣列中的路徑請求資產
- **THEN** 回傳該檔案的完整內容

#### Scenario: 內容與磁碟一致

- **WHEN** 取回資產
- **THEN** 回傳的位元組與磁碟上的檔案完全相同

#### Scenario: 路徑相對於 concept 而非 bundle

- **WHEN** concept 位於 bundle 的子目錄中，且引用同層的資產
- **THEN** 該相對路徑以 concept 所在目錄為基準解析成功

### Requirement: media type 判定

系統 SHALL 依副檔名判定回傳的 media type，判定不出時 MUST 使用通用二進位型別。系統 MUST NOT 依檔案內容嗅探型別。

#### Scenario: 已知副檔名

- **WHEN** 取回 `.png` 資產
- **THEN** 回應的 media type 為對應的圖片型別

#### Scenario: 未知副檔名

- **WHEN** 取回副檔名無法對應型別的資產
- **THEN** 回應的 media type 為通用二進位型別

### Requirement: 拒絕逸出語料的路徑

系統 SHALL 拒絕任何會讀取到 bundle 根目錄之外的資產請求。絕對路徑與含上層目錄片段的路徑 MUST 在接觸檔案系統前即被拒絕。解析後的絕對路徑 MUST 位於該 concept 所屬 bundle 的根目錄之下。

#### Scenario: 含上層目錄片段

- **WHEN** 請求的路徑含 `..` 片段
- **THEN** 系統拒絕該請求

#### Scenario: 絕對路徑

- **WHEN** 請求的路徑為絕對路徑
- **THEN** 系統拒絕該請求

#### Scenario: 空路徑

- **WHEN** 請求的路徑為空
- **THEN** 系統拒絕該請求

#### Scenario: 符號連結指向語料之外

- **WHEN** 資產目錄中的符號連結指向 bundle 根目錄之外的檔案
- **THEN** 系統拒絕該請求

### Requirement: 資產目錄白名單

系統 SHALL 僅允許讀取位於設定所列資產目錄名稱之下的檔案，預設為 `_assets`。此清單 MUST 可由設定覆寫。不符者 MUST 被拒絕，且錯誤訊息 MUST 指出是此規則所擋。

#### Scenario: 位於資產目錄之內

- **WHEN** 請求的資產位於 `_assets` 目錄之下
- **THEN** 允許讀取

#### Scenario: 位於資產目錄之外但仍在 bundle 內

- **WHEN** 請求 bundle 內但不在任何資產目錄之下的檔案
- **THEN** 系統拒絕，且訊息指出資產目錄限制

#### Scenario: 覆寫資產目錄清單

- **WHEN** 設定將資產目錄改為其他名稱
- **THEN** 該名稱之下的檔案可被讀取，`_assets` 之下的則否

### Requirement: 區分各類失敗

系統 SHALL 對下列情況給出可區分的回應：concept 不存在、資產檔案不存在、路徑違反約束。

#### Scenario: concept 不存在

- **WHEN** 以不存在的 `concept_id` 請求資產
- **THEN** 回應指出查無此 concept

#### Scenario: 資產檔案不存在

- **WHEN** `concept_id` 存在但指定的資產檔案不在磁碟上
- **THEN** 回應指出查無此資產，且與「concept 不存在」可區分

#### Scenario: 路徑違反約束

- **WHEN** 路徑違反上層目錄或資產目錄的約束
- **THEN** 回應與「檔案不存在」可區分

### Requirement: 下載與內嵌兩種處置

系統 SHALL 預設以內嵌方式回傳資產，使瀏覽器可直接顯示；並 SHALL 支援以附件方式下載。檔名 MUST 以不破壞標頭的方式編碼。

#### Scenario: 預設內嵌

- **WHEN** 未指定下載
- **THEN** 回應的處置方式為內嵌

#### Scenario: 指定下載

- **WHEN** 指定以附件下載
- **THEN** 回應的處置方式為附件，並含檔名

### Requirement: 資產讀取邏輯不依賴傳輸層

資產路徑解析與驗證 SHALL 位於獨立模組，只依賴索引與設定，不依賴 HTTP 框架。

#### Scenario: 不經 HTTP 直接解析

- **WHEN** 程式直接以索引、`concept_id` 與相對路徑呼叫解析函式
- **THEN** 回傳已驗證的絕對路徑，無須啟動 HTTP 服務

