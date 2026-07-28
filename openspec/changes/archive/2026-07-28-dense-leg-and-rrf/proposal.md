## Why

A/B/C 只能回答「識別碼斷詞與實體字典有沒有用」。它答不出另一個問題：**關鍵字檢索本身夠不夠**。

現場查詢有兩種形狀。一種是「`AEPOL1#PM1` 微粒」——識別碼精確，BM25F 本來就強。另一種是「蝕刻後圖案倒塌要看哪些參數」——沒有識別碼、用詞與文件不一定重疊，關鍵字腿在這種查詢上會直接落空（報告的 `zero_result_rate` 會看得到）。稠密向量正是為後者存在的。

兩者的失效模式相反，所以要的是**融合而不是取代**。RRF 只用排名不用分數，因此不需要在 BM25 分數與餘弦相似度之間硬湊一個可比的尺度——那種湊出來的權重會變成一個沒人敢動的魔術數字。

## What Changes

- 新增 **模式 D**（純稠密）與 **模式 E**（RRF 融合 C 與 D），沿用既有的 `mode_overlap` 量測
- Embedding 走 **OpenAI 相容的 `/embeddings`**，端點由設定決定：開發期指向 OpenRouter，production 指向 LiteLLM → self-host vLLM。程式不認得任何一家供應商
- 向量存 Qdrant。未指定 `url` 時用本機檔案模式，不需要架 server
- `yedai embed` 建立／更新向量；查詢向量落地快取，同一組 queries.txt 重跑不重複付費
- 模式 D/E 在未設定向量時**不可用**，而不是靜默退化成 C——靜默退化會讓報告顯示「稠密腿沒有作用」，而真相是它根本沒跑

## 語料外流的閘門

`yedai embed` 會把 concept 全文送到 `base_url`。語料是最高機密，而開發期的預設端點是第三方。

所以：**非合成語料 + 未宣告端點可信 → 拒絕執行**，錯誤訊息裡直接印出那個 base_url。合成語料不受限，因為它本來就是編造的。

這個閘門擋的不是惡意，是「拿開發設定跑了真語料」這種一次就無法挽回的意外。

## Capabilities

### Added Capabilities
- `dense-retrieval`: 稠密檢索腿、RRF 融合、供應商無關的 embedding 客戶端、語料外流閘門

## Impact

- **新增**：`embedding.py`、`vectors.py`、`yedai embed`、`.env` 支援
- **修改**：`search.py`（模式 D/E 與 RRF）、`config.py`、`cli.py`、`schemas.py`、`api.py`
- **相依**：`qdrant-client`、`httpx`
- **不影響**：A/B/C 三個模式的行為、索引格式、實體字典

## 刻意不做的事

- **不做分塊**。一個 concept 一個向量。分塊會同時改變召回粒度與融合行為，兩個變因一起動就分不出是誰的功勞。等 D 與 E 的數字出來再決定值不值得。
- **不調 RRF 的 k**。固定 60（慣例值）。在沒有真實查詢與人工判斷之前調它，調的是雜訊。
