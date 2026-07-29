# evaluation Specification

## Purpose
TBD - created by archiving change llm-eval-set. Update Purpose after archive.
## Requirements
### Requirement: LLM 產生評估集

系統 SHALL 取樣語料中的 concept，交由 LLM 產生「這篇文件是哪個問題的答案」形式的查詢，並記錄該 concept 為該查詢的標準答案。

每個查詢 MUST 帶有一個**種類**標記，至少區分：含識別碼的查詢、以及不含識別碼的症狀式查詢。指標必須依種類拆解——識別碼式查詢上關鍵字模式佔優是預期內的結果，沒有資訊量；症狀式查詢上的表現才能回答「稠密腿值不值得」。

提示 MUST 要求 LLM 以「未讀過該文件的人」的角度提問。LLM 看著文件寫查詢會照抄罕見詞，使關鍵字模式虛胖、稠密腿被低估。此偏誤 MUST 記錄於產出檔，因為提示只能壓抑而無法消除它。

LLM 回應 SHALL 落地快取，鍵含模型名稱。重跑同一組 concept MUST NOT 重複請求。

產出的評估集含真實語料衍生的查詢，MUST 預設寫入已被 gitignore 的路徑。

#### Scenario: 產出查詢與標準答案

- **WHEN** 對某 concept 產生評估項目
- **THEN** 每一項含查詢文字、該 concept 的 id、以及查詢種類

#### Scenario: 種類涵蓋兩種失效模式

- **WHEN** 產生評估集
- **THEN** 其中同時含有含識別碼與不含識別碼的查詢

#### Scenario: 快取避免重複請求

- **WHEN** 同一個 concept 第二次被要求產生查詢
- **THEN** 系統使用快取，不發出請求

#### Scenario: 回應不是合法 JSON

- **WHEN** LLM 回傳無法解析的內容
- **THEN** 系統跳過該 concept 並計入失敗數，MUST NOT 讓整批中止

### Requirement: 依模式與種類拆解的檢索指標

系統 SHALL 對每個**可用**模式計算 recall@k 與 MRR，並依查詢種類拆解。

指標的命名與輸出 MUST 標明標籤只涵蓋單一相關文件，因此 recall@k 為**下界**、MRR 偏低。絕對值 MUST NOT 被呈現為可外推的檢索品質。

模式之間的比較 SHALL 為主要輸出。標籤的偏誤在各模式之間是共同的，所以相對差距成立，而絕對值不成立。

未命中的查詢 MUST 計入分母。把找不到的查詢排除會讓表現差的模式看起來更好。

#### Scenario: 逐模式指標

- **WHEN** 對評估集執行評估
- **THEN** 每個可用模式各有 recall@k 與 MRR

#### Scenario: 依種類拆解

- **WHEN** 評估集含識別碼式與症狀式兩種查詢
- **THEN** 指標分別依這兩種呈現

#### Scenario: 未命中計入分母

- **WHEN** 某查詢的標準答案不在任何模式的前 k 名
- **THEN** 該查詢仍計入所有模式的分母，其 MRR 貢獻為 0

#### Scenario: 輸出帶著標籤的限制

- **WHEN** 產出評估結果
- **THEN** 結果中載明標籤僅涵蓋單一相關文件，指標為下界

### Requirement: 評估結果併入去識別化報告

評估結果 SHALL 可併入 `report` 的輸出。結果只含數字與模式名稱，MUST NOT 含查詢原文。

查詢原文是語料衍生物，帶有真實識別碼；報告是唯一設計為可外流的產出，這條界線 MUST NOT 因為方便而放寬。

#### Scenario: 報告含評估結果但不含查詢原文

- **WHEN** 產出報告
- **THEN** 報告含逐模式指標，且不含任何查詢文字或實體名稱

### Requirement: LLM 端點的信任宣告獨立於 embedding

`gen-evalset` 會把 concept 全文送出程序，SHALL 沿用語料外流閘門：非合成語料且未宣告該端點可信時拒絕執行。

LLM 端點的信任宣告 MUST 獨立於 embedding 端點的宣告。把信任從一個端點自動延伸到另一個，正是這道閘門要防的事——即使兩者目前指向同一個位址。

#### Scenario: embedding 已宣告可信不代表 LLM 可信

- **WHEN** 設定宣告 embedding 端點可信，但未宣告 LLM 端點可信
- **THEN** 對非合成語料執行 `gen-evalset` 被拒絕

