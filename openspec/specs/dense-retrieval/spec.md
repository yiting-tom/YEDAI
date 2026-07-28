# dense-retrieval Specification

## Purpose
TBD - created by archiving change dense-leg-and-rrf. Update Purpose after archive.
## Requirements
### Requirement: 供應商無關的 embedding 客戶端

系統 SHALL 以 OpenAI 相容的 `/embeddings` 介面取得向量，端點、模型名稱、維度與金鑰環境變數名稱皆由設定決定。系統 MUST NOT 在程式中綁定任何特定供應商——開發期指向 OpenRouter、production 指向 LiteLLM 代理的 self-host vLLM，兩者只差設定。

金鑰 MUST 只從環境變數讀取，MUST NOT 出現在設定檔中——設定檔會進版控，而這個 repo 是公開的。

回傳向量的維度 MUST 與設定的維度核對，不符時 MUST 明確失敗。維度不符若被接受，相似度計算仍會產出看似正常的數字，而錯誤不會有任何徵兆。

請求 MUST 依設定的批次大小分批，且回應 MUST 依 `index` 欄位還原輸入順序，MUST NOT 假設回應順序與輸入相同。

#### Scenario: 端點由設定決定

- **WHEN** 設定把 `base_url` 指向 LiteLLM 代理
- **THEN** 請求送往該端點，程式行為與指向 OpenRouter 時相同

#### Scenario: 維度不符時失敗

- **WHEN** 設定宣告維度 4096，但端點回傳 1024 維向量
- **THEN** 系統回報明確錯誤，MUST NOT 寫入向量庫

#### Scenario: 依 index 還原順序

- **WHEN** 端點回傳的資料順序與輸入順序不同
- **THEN** 系統依每筆的 `index` 還原對應關係

#### Scenario: 金鑰缺漏

- **WHEN** 設定指定的環境變數不存在
- **THEN** 系統回報明確錯誤，指出缺少的變數名稱

### Requirement: 語料外流閘門

`yedai embed` 會把 concept 全文送出程序。系統 SHALL 在語料非合成、且設定未宣告端點可信時**拒絕執行**，錯誤訊息 MUST 包含該次會送往的 `base_url`。

合成語料 MUST NOT 受此限制——它本來就是編造的，且用它驗證程式正確性是常態操作。

這個閘門擋的是「拿開發設定跑了真語料」的意外。一旦送出就無法收回，所以預設必須是拒絕。

#### Scenario: 真實語料配未宣告可信的端點

- **WHEN** 對非合成語料執行 embed，而設定未宣告端點可信
- **THEN** 系統拒絕執行並印出該 base_url

#### Scenario: 合成語料不受限

- **WHEN** 對合成語料執行 embed
- **THEN** 即使未宣告端點可信也照常執行

#### Scenario: 明確宣告後放行

- **WHEN** 設定宣告端點可信
- **THEN** 對任何語料都照常執行

### Requirement: 向量儲存

系統 SHALL 以 Qdrant 儲存 concept 向量。未指定伺服器位址時 MUST 使用本機檔案模式，不得要求使用者另外架設服務——架設成本會直接變成實驗不被執行的理由。

集合的向量維度 MUST 與設定一致；已存在但維度不符的集合 MUST 被重建而非沿用。

每個向量 MUST 帶有可還原到 concept 的識別資訊。

#### Scenario: 無伺服器時使用本機模式

- **WHEN** 設定未指定向量庫位址
- **THEN** 系統在本機路徑建立向量庫並正常運作

#### Scenario: 維度變更時重建集合

- **WHEN** 既有集合維度為 1024，設定改為 4096
- **THEN** 系統重建集合，而非寫入維度不符的向量

### Requirement: 稠密檢索與 RRF 融合

系統 SHALL 提供模式 D（純稠密）與模式 E（RRF 融合模式 C 與模式 D 的排名）。

融合 SHALL 使用 Reciprocal Rank Fusion：每個文件的分數為各腿 `1/(k + rank)` 之和，`k` 為設定值。MUST 只使用排名而非原始分數——BM25 分數與餘弦相似度沒有共同尺度，硬湊出來的權重無法解釋也無人敢調整。

模式 D 與 E 在向量庫不可用時 MUST 為**不可用**，MUST NOT 靜默退化為模式 C。靜默退化會讓報告顯示「稠密腿沒有帶來差異」，而真相是它根本沒有執行——那是一個會被當成結論的假象。

模式間重疊度 SHALL 在所有**可用**模式的兩兩配對上計算。

#### Scenario: 純稠密檢索

- **WHEN** 以模式 D 查詢
- **THEN** 結果依查詢向量與 concept 向量的相似度排序

#### Scenario: RRF 只用排名

- **WHEN** 某文件在模式 C 排第 1、在模式 D 排第 10
- **THEN** 其融合分數為 `1/(k+1) + 1/(k+10)`，與兩腿的原始分數無關

#### Scenario: 向量不可用時模式 D 不可用

- **WHEN** 未建立向量庫而請求模式 D
- **THEN** 系統回報該模式不可用，MUST NOT 回傳模式 C 的結果

#### Scenario: 重疊度涵蓋可用模式

- **WHEN** 五個模式皆可用
- **THEN** 報告含全部十組兩兩重疊度

### Requirement: 查詢向量快取

系統 SHALL 快取查詢文字對應的向量。同一組查詢重跑時 MUST NOT 重複向端點請求。

實驗的常態是拿同一份查詢清單反覆重跑；不快取會讓每次重跑都產生費用與網路延遲，而那會直接減少實驗被執行的次數。

快取 MUST 以模型與維度為鍵的一部分——換模型後沿用舊向量會產出無聲的錯誤結果。

#### Scenario: 重複查詢不重複請求

- **WHEN** 同一段查詢文字第二次被檢索
- **THEN** 系統使用快取向量，不發出請求

#### Scenario: 換模型後快取失效

- **WHEN** 設定改用另一個 embedding 模型
- **THEN** 先前的快取不被沿用

