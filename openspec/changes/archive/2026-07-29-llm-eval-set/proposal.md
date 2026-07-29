## Why

`mode_overlap` 只能告訴你五個模式的結果**不一樣**。它永遠答不出**哪一個比較對**——因為沒有標準答案。這是整個實驗最根本的天花板，先前所有的努力都撞在這面牆上。

公司內部有可用的 LLM，且語料可以送進去。這使得一件先前做不到的事變得可行：讓 LLM 讀一篇 concept，產出「**這篇文件是哪個問題的答案**」。拿到的不只是查詢，是 **(查詢 → 已知相關文件)** 的配對——一組評估標籤。

有了標籤就能算 recall@k 與 MRR，而不只是 jaccard。

## What Changes

- 新增 `llm` 設定區塊：OpenAI 相容的 chat 端點，與 embedding 同一個 LiteLLM，只差 model 名稱
- 新增 `yedai gen-evalset`：取樣 concept → LLM 產查詢 → 寫出 `(query, gold_concept_id, kind)`
- 新增 `yedai evaluate`：對每個可用模式算 recall@k、MRR，並**依查詢種類拆解**
- 評估結果併入 `yedai report`——它只含數字與 concept id，沒有語料內容
- LLM 回應落地快取，重跑不重複付費

## 標籤的偏誤，以及為什麼它仍然可用

來源 concept 只是「**一篇**相關文件」，不是「唯一相關的文件」。同一個查詢很可能有別的 concept 答得一樣好甚至更好，而那些會被算成未命中。

所以 recall@k 是**下界**、MRR 偏低。絕對值不可外推。

但這不影響它的用途：**五個模式面對的是同一組標籤、同一組偏誤**。要下的結論是「B 比 A 好多少」，而不是「B 的絕對 recall 是多少」。偏誤在模式之間是共同的，因此互相比較仍然成立。

指標的命名與報告 MUST 帶著這個限制，否則絕對值遲早會被引用到不該被引用的地方。

## 另一個必須標明的偏誤

LLM 看著文件寫查詢，容易照抄文件裡的罕見詞——那會讓 BM25 系（A/B/C）虛胖，稠密腿（D）被低估。

提示詞用「假設你沒讀過這份文件」壓一部分，並要求同時產出**症狀式**（不含識別碼）的查詢。但壓不掉全部，所以查詢種類要記錄下來、指標要依種類拆解：識別碼式查詢上 A/B/C 佔優是預期內的，症狀式查詢上若 A/B/C 仍佔優才是有訊息量的結果。

## Capabilities

### Added Capabilities
- `evaluation`: LLM 產生的評估集，與依模式、依查詢種類拆解的檢索指標

## Impact

- **新增**：`llm.py`、`evalset.py`、`yedai gen-evalset`、`yedai evaluate`
- **修改**：`config.py`（`llm` 區塊）、`telemetry.py`（報告納入評估結果）
- **不影響**：檢索模式本身、索引格式、既有的 `mode_overlap`

## 語料外流閘門同樣適用

`gen-evalset` 會把 concept 全文送到 chat 端點，風險與 `embed` 相同。沿用同一道閘：非合成語料 + 未宣告端點可信 → 拒絕執行。

`llm` 的可信宣告與 `embedding` 的**各自獨立**。兩者現在指向同一個 LiteLLM，但把信任從一個端點自動延伸到另一個，正是這道閘門要防的那種事。
