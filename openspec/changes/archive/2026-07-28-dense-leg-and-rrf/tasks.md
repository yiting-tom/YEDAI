## 1. Embedding 客戶端

- [x] 1.1 `EmbeddingClient` 協定：`embed(texts) -> list[list[float]]`，讓測試能離線替換
- [x] 1.2 `HttpEmbeddingClient`：OpenAI 相容 `/embeddings`，base_url／model／dim 由設定決定
- [x] 1.3 金鑰只從環境變數讀；缺漏時指名該變數
- [x] 1.4 依 `index` 欄位還原順序——不假設回應順序等於輸入順序
- [x] 1.5 維度核對，不符即失敗且不寫入
- [x] 1.6 分批與重試（含 429／5xx 退避）

## 2. 語料外流閘門

- [x] 2.1 合成語料的判定（產生器寫下的免責檔）
- [x] 2.2 非合成語料 + 未宣告可信 → 拒絕，訊息含 base_url
- [x] 2.3 測試涵蓋三種組合

## 3. 向量儲存

- [x] 3.1 `VectorStore`：未給 url 時走本機檔案模式
- [x] 3.2 集合維度與設定不符時重建
- [x] 3.3 payload 帶 concept_id，可還原到 `DocMeta`
- [x] 3.4 `yedai embed`：組出待嵌文字、分批、寫入、可重跑

## 4. 模式 D / E

- [x] 4.1 `rrf()`：只吃排名，不吃分數
- [x] 4.2 模式 D：查詢向量 → Qdrant → `ModeResult`
- [x] 4.3 模式 E：RRF(C, D)
- [x] 4.4 `Searcher.available_modes`；向量不可用時 D/E 不可用而非退化為 C
- [x] 4.5 `compare()` 在可用模式的兩兩配對上算重疊度

## 5. 查詢向量快取

- [x] 5.1 落地快取，鍵含模型與維度
- [x] 5.2 換模型後不沿用

## 6. 設定與介面

- [x] 6.1 `embedding` / `vector` / `rrf_k` 設定區塊與驗證
- [x] 6.2 `.env` 載入；`.env` 與 `.env.*` 進 gitignore，附 `.env.example`
- [x] 6.3 `schemas.py` / `api.py`：模式列舉改為動態，`/v1/version` 揭露可用模式

## 7. 測試（全部離線）

- [x] 7.1 假的 embedding 客戶端，測試 MUST NOT 觸網
- [x] 7.2 維度不符、金鑰缺漏、順序還原
- [x] 7.3 閘門三種組合
- [x] 7.4 RRF 的算式與「只用排名」的性質
- [x] 7.5 向量不可用時 D/E 不可用，且 A/B/C 不受影響

## 8. 文件

- [x] 8.1 `docs/` 說明開發（OpenRouter）與 production（LiteLLM→vLLM）只差設定
- [x] 8.2 外流閘門的理由與解除方式
- [x] 8.3 README 的模式表補上 D／E 與判讀方式
