## 1. 索引結構

- [x] 1.1 `Index` 新增 `by_id: dict[str, int]`（concept id → docs 位置）與 `bundle_roots: dict[str, str]`（bundle id → 絕對根目錄）
- [x] 1.2 `build_index()` 填入上述兩份對照；bundle 根目錄以絕對路徑登錄，且以 bundle 為單位不逐筆重複
- [x] 1.3 `INDEX_FORMAT_VERSION` 由 1 提升至 2，確認 `Index.load()` 對舊版索引明確報錯並指示重建
- [x] 1.4 處理同一 `concept_id` 在不同 bundle 重複出現的情況（後者不覆蓋前者，並記入 warnings）

## 2. 全文讀取模組

- [x] 2.1 新增 `src/yedai/fulltext.py`，只依賴 `Index` 與 `parser`，不依賴 FastAPI
- [x] 2.2 定義 `ConceptNotFound` 與 `ConceptFileMissing` 兩種例外，對應「不存在」與「索引過期」
- [x] 2.3 實作路徑組合：`bundle_roots[bundle_id] / DocMeta.path`，並驗證解析後絕對路徑位於該 bundle 根目錄之下
- [x] 2.4 實作 `load_concept(index, concept_id)`：讀原始檔案內容 → 呼叫既有 `parse_concept()` → 組裝回傳結構
- [x] 2.5 回傳結構含 `raw`（原始全文）、`frontmatter`、`sections`、`figures`、`related`、`tags`、`assets`、`resource`、`provenance`、`index_line` 與識別資訊

## 3. HTTP 端點

- [x] 3.1 `api.py` 新增 `GET /concept/{concept_id}`，索引未載入回 503
- [x] 3.2 `ConceptNotFound` → 404；`ConceptFileMissing` → 410 且訊息指示重建索引
- [x] 3.3 端點加上 summary/description，確認出現在互動式 API 文件

## 4. 測試

- [x] 4.1 取回既有 concept：raw 與磁碟檔案完全一致、frontmatter 欄位正確、section 依 `## ` 切分
- [x] 4.2 無分隔線 frontmatter 與未知欄位保留，行為與建索引時一致
- [x] 4.3 索引不含任何 body 內容（序列化後斷言）
- [x] 4.4 檔案在建索引後被修改，取回的是最新內容
- [x] 4.5 `by_id` 查找不需線性掃描；`bundle_roots` 可還原絕對路徑
- [x] 4.6 舊格式版本索引載入時報錯
- [x] 4.7 路徑逸出 bundle 根目錄時拒絕讀取
- [x] 4.8 API：200 / 404 / 410 三種情況；與 `/search` 結果的識別欄位一致；端點出現在 openapi.json

## 5. 端到端驗證

- [x] 5.1 重建合成語料索引（格式版本已變更），確認零解析失敗
- [x] 5.2 啟動服務，以瀏覽器自動化在文件頁測試 `/concept/{concept_id}`，確認回 200 且含全文
- [x] 5.3 驗證 `/search` → 取 `concept_id` → `/concept/{id}` 的完整串接

## 6. 文件

- [x] 6.1 README 端點表新增 `/concept/{concept_id}`
- [x] 6.2 README 說明索引格式版本變更需重建索引
- [x] 6.3 README 補上「search 回菜單、agent 自行取全文」的使用流程
