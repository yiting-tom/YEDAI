# defect-taxonomy-lookup Specification

## Purpose
TBD - created by archiving change layered-indexes. Update Purpose after archive.
## Requirements
### Requirement: taxonomy 以鍵取回而非檢索

taxonomy 條目 SHALL 以 defect 識別碼為鍵取回。系統 MUST NOT 對 taxonomy 執行近似比對、模糊匹配或排名檢索，MUST NOT 將 taxonomy 納入任何檢索索引。

查無條目時 SHALL 回傳明確的「無此條目」，MUST NOT 回傳其他 defect 的條目作為近似結果——以錯誤 defect 的判斷方法解讀影像，比沒有方法更糟。

#### Scenario: 以 defect 鍵取回條目

- **WHEN** 以存在的 defect 識別碼查詢 taxonomy
- **THEN** 回傳該 defect 的條目內容

#### Scenario: 查無條目不做近似

- **WHEN** 以不存在的 defect 識別碼查詢 taxonomy
- **THEN** 回傳明確的「無此條目」，且回應中不含任何其他 defect 的條目

#### Scenario: taxonomy 不出現在檢索結果

- **WHEN** 執行分層檢索
- **THEN** 回應的任何層中都不含 taxonomy 條目

### Requirement: taxonomy 資源的載入與驗證

系統 SHALL 從設定指定的路徑載入 taxonomy 資源。載入時 MUST 驗證每個條目的鍵在 defect 清單中存在；指向未知 defect 的條目 MUST 被回報為警告並保留，不得靜默丟棄——它可能表示 defect 清單缺漏，而那本身是要處理的訊號。

未提供 taxonomy 資源時系統 MUST 正常啟動，所有查詢皆回傳「無此條目」。

#### Scenario: 載入資源

- **WHEN** 設定指定有效的 taxonomy 資源路徑
- **THEN** 條目被載入且可依 defect 鍵取回

#### Scenario: 條目指向未知 defect

- **WHEN** taxonomy 含一個 defect 清單中不存在的鍵
- **THEN** 系統回報該鍵為警告，條目仍可載入

#### Scenario: 未提供資源

- **WHEN** 設定未指定 taxonomy 資源
- **THEN** 系統正常啟動，所有 taxonomy 查詢回傳「無此條目」

#### Scenario: 資源格式錯誤

- **WHEN** taxonomy 資源檔格式無法解析
- **THEN** 系統報錯並指出檔案路徑與失敗原因，不得以空資源靜默啟動

### Requirement: taxonomy 覆蓋率統計

系統 SHALL 統計 taxonomy 的覆蓋率：有條目的 defect 數、defect 總數，以及依 defect 類別拆解的同一組數字。此統計 MUST 可併入去識別化報告。

統計 MUST 僅以類別名稱為鍵。defect 的名稱、識別碼與條目內容 MUST NOT 出現在統計中——類別名屬 schema，其餘屬語料內容。

#### Scenario: 產出覆蓋率

- **WHEN** 請求 taxonomy 覆蓋率統計
- **THEN** 回傳有條目的 defect 數與 defect 總數

#### Scenario: 依類別拆解

- **WHEN** defect 清單含多個類別
- **THEN** 統計可分別讀取各類別的覆蓋數與總數

#### Scenario: 統計不洩漏內容

- **WHEN** 產出覆蓋率統計
- **THEN** 序列化結果中不出現任何 defect 名稱、識別碼或條目文字

### Requirement: 公開邊界

repo 內 SHALL 僅保留 taxonomy 的 schema 與形狀範例。實際條目內容、defect 清單與 module 清單 MUST 位於版控排除的路徑。

#### Scenario: 範例檔不含真實內容

- **WHEN** 檢視版控中的 taxonomy 範例檔
- **THEN** 檔案僅含結構示意，不含任何真實 defect 名稱、module 名稱或判斷方法

#### Scenario: 實際資源被版控排除

- **WHEN** 檢視版控忽略設定
- **THEN** taxonomy 實際資源、defect 清單與 module 清單所在路徑皆被排除

