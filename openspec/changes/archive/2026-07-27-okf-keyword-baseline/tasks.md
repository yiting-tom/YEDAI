## 1. 專案骨架與設定

- [x] 1.1 建立 `pyproject.toml`，宣告相依（pyyaml、fastapi、uvicorn、typer、rich）與 `yedai` CLI 進入點
- [x] 1.2 建立 `.gitignore`，排除 `data/`、`.index/`、`logs/`、`.venv/`、`__pycache__/`、合成語料輸出目錄
- [x] 1.3 實作 `config.py`：設定資料類別（斷詞樣式、BM25 參數 k1/b、欄位權重、融合權重、字典路徑、索引快取路徑、日誌路徑），支援 YAML 覆寫與內建預設值
- [x] 1.4 建立 `config.example.yaml` 與 `dictionary.example.yaml` 兩份範例檔

## 2. OKF 解析

- [x] 2.1 實作 `models.py`：`Figure`、`Section`、`Concept`、`BundleDoc`、`Bundle` 資料類別，含 `field_texts()` 欄位切分與 `index_line()` 摘要行
- [x] 2.2 實作 `parser.py` 的 `split_frontmatter()`，同時支援 `---` 包夾與無分隔線兩種格式
- [x] 2.3 實作 `parse_sections()`，依 `## ` 切分並保留前言為空標題 section
- [x] 2.4 實作 `parse_concept()` 與 `parse_bundle_doc()`，未知 frontmatter 欄位收進 `extra`
- [x] 2.5 實作 `parse_bundle()` 與 `load_bundles()`，排除 `_assets/`、分流保留檔名、單檔失敗進 `skipped` 不中斷
- [x] 2.6 支援根目錄本身即為單一 bundle 的情況

## 3. 斷詞

- [x] 3.1 實作 `tokenizer.py` 的 `normalise_identifier()`，移除連字號/底線/空白並轉大寫
- [x] 3.2 實作 `Tokenizer.naive()`：非字母數字全視為分隔符，英數混合再拆為字母段與數字段
- [x] 3.3 實作 `Tokenizer.protected()`：先圈出識別碼並正規化為單一詞元，其餘走一般斷詞
- [x] 3.4 實作中日韓 unigram + bigram 產生，拉丁字母數字轉小寫
- [x] 3.5 實作 `find_identifiers()` 供實體抽取的 regex fallback 使用
- [x] 3.6 讓識別碼樣式清單可由設定檔完全覆寫

## 4. 實體字典與匹配

- [x] 4.1 實作 `EntityDictionary.load()`：YAML 載入、支援條目為字串或物件、字典為選填、路徑不存在時明確報錯
- [x] 4.2 實作正規化別名索引與含中文/空白別名的最長優先字面掃描
- [x] 4.3 實作 `EntityExtractor.extract()`：字典命中標 `source=dict`，未命中的識別碼標 `source=regex` 且 `type=unknown`，同一實體去重
- [x] 4.4 實作 `extract_weighted()`：對 concept 各欄位抽實體並取位置加權最大值
- [x] 4.5 實作實體逆文件頻率統計與實體腿計分，正規化至 0–1 的查詢實體涵蓋比例
- [x] 4.6 實作選用的實體硬過濾開關，預設關閉
- [x] 4.7 實作字典覆蓋率統計（語料端與查詢端的 dict / regex 比例）

## 5. 索引與檢索

- [x] 5.1 實作 `index.py`：同時建立 naive 與 protected 兩套詞彙空間的倒排索引與欄位長度統計
- [x] 5.2 實作 BM25F 計分，各欄位獨立長度正規化後加權合併詞頻，參數與權重可覆寫
- [x] 5.3 實作實體倒排索引與實體 idf
- [x] 5.4 實作索引序列化與快取載入，並在設定變更時判定快取失效
- [x] 5.5 實作 `search.py` 的模式 A、B、C 三個檢索路徑
- [x] 5.6 實作模式 C 的兩腿正規化線性融合，結果保留詞彙腿與實體腿各自分數
- [x] 5.7 實作結果模型：排名、分數、兩腿分數、concept id、bundle id、type、title、description、路徑、`index_line()`
- [x] 5.8 實作零結果與筆數上限處理
- [x] 5.9 實作模式間 top-k 重疊度計算（Jaccard 與 Kendall tau）

## 6. 遙測

- [x] 6.1 實作 `telemetry.py` 的完整 JSONL 查詢日誌寫入（查詢識別碼、時間戳、查詢原文、模式、實體、各模式結果與分數）
- [x] 6.2 實作點選回饋記錄與查詢識別碼關聯，未知識別碼須報錯
- [x] 6.3 實作三模式並排的呈現順序隨機化與記錄，支援固定種子以利測試
- [x] 6.4 實作去識別化報告產生器，涵蓋語料統計、查詢統計、實體統計、各模式分數分佈、模式間重疊度、點選排名分佈、當次設定參數
- [x] 6.5 確保報告在無任何查詢紀錄時仍可產出且不報錯

## 7. CLI

- [x] 7.1 實作 `cli.py` 骨架（typer + rich），載入設定
- [x] 7.2 實作 `index` 指令：建索引、顯示語料統計與解析失敗清單、目錄不存在時非零退出
- [x] 7.3 實作 `search` 指令：表格輸出，索引不存在時提示並非零退出
- [x] 7.4 實作 `compare` 指令：三模式並排 + 重疊度，支援從檔案批次讀入查詢並輸出彙總
- [x] 7.5 實作 `report` 指令：輸出去識別化報告至終端或檔案
- [x] 7.6 實作 `gen-synthetic` 指令，轉呼叫合成產生器

## 8. HTTP API

- [x] 8.1 實作 `api.py` 骨架與索引載入的生命週期管理
- [x] 8.2 實作 `GET /search`：支援單模式與三模式並排，回傳查詢識別碼，無效模式與缺少查詢字串回 422
- [x] 8.3 實作 `POST /feedback`：記錄點選，未知查詢識別碼回 404
- [x] 8.4 實作 `GET /stats`、`GET /report`、`GET /healthz`
- [x] 8.5 確認互動式 API 文件頁可列出所有端點並可直接送出請求

## 9. 合成語料產生器

- [x] 9.1 實作 `scripts/gen_synthetic.py`，產出與真實格式一致的 bundle 目錄結構（manifest、index/summary/log、_assets、concept 檔）
- [x] 9.2 產生假機台/製程/flow/缺陷識別碼，並刻意包含僅末碼不同的相似識別碼
- [x] 9.3 依類型套用固定區段模板，重現類型重複但內容不同的特性
- [x] 9.4 `summary.md` 採用無分隔線 frontmatter 格式以覆蓋該解析路徑
- [x] 9.5 同時輸出配套的實體字典檔
- [x] 9.6 支援隨機種子，相同種子產生完全相同輸出
- [x] 9.7 在輸出目錄與終端訊息標示「僅供驗證程式正確性，不得用於調參或推論效果」

## 10. 測試

- [x] 10.1 解析測試：完整 frontmatter、缺 id、無分隔線、完全無 frontmatter、壞檔不中斷、`_assets` 排除、保留檔名分流
- [x] 10.2 斷詞測試：識別碼變體正規化一致、`TEL-05` 與 `TEL-06` 不共享詞元、中文 bigram、模式 A 確實切碎識別碼
- [x] 10.3 實體測試：字典命中與 regex fallback、中文別名最長優先、去重、罕見實體權重較高、標題加權較高、硬過濾
- [x] 10.4 檢索測試：標題命中優於內文、零結果、筆數上限、兩腿分數可個別取得、重疊度在相同與無交集情況的邊界值
- [x] 10.5 遙測測試：**斷言去識別化報告序列化結果不含任何查詢原文、concept 標題與實體名稱**
- [x] 10.6 遙測測試：無查詢紀錄時報告仍可產出、未知查詢識別碼的回饋被拒絕
- [x] 10.7 端到端測試：對合成語料建索引 → 三模式查詢 → 回饋 → 產報告，全流程無錯

## 11. 端到端流程驗證

- [x] 11.1 產生 30 個合成 bundle 並建立索引，確認零解析失敗
- [x] 11.2 以 CLI 跑 `search` 與 `compare`，確認三模式在相似識別碼查詢上出現可觀察的差異
- [x] 11.3 啟動 HTTP 服務，以瀏覽器自動化開啟互動式 API 文件頁
- [x] 11.4 於文件頁依序測試 `/healthz`、`/stats`、`/search`（單模式與並排）、`/feedback`、`/report`，確認皆回 200 且內容正確
- [x] 11.5 確認 `/report` 回應中不含任何語料內容

## 12. 文件

- [x] 12.1 撰寫 `README.md`：安裝、指向真實資料的方式、三模式的實驗意義、如何產出並分享去識別化報告
- [x] 12.2 在 README 明確標示真實資料不進版控、完整日誌不外流、僅報告可分享
- [x] 12.3 說明合成資料僅供程式驗證、不得用於調參或推論效果
