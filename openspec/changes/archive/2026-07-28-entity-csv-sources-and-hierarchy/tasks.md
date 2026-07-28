## 1. 斷詞器：`#` 與層級展開

- [x] 1.1 `DEFAULT_IDENTIFIER_PATTERNS` 新增含 `#` 的樣式，使 `aepol1#pm1` 整段被圈出
- [x] 1.2 `normalise_identifier` 確認保留 `#`（現行只移除 `- _ 空白`，須加測試鎖住此行為）
- [x] 1.3 新增 `expand_hierarchy(normalised)`：含 `#` 者回傳 `[子層, 父層]`，否則回傳 `[原值]`
- [x] 1.4 `Tokenizer.protected()` 對含 `#` 的識別碼輸出子層與父層兩個詞元
- [x] 1.5 `Tokenizer.find_identifiers()` 同步展開，父層沿用子層的位置區間
- [x] 1.6 確認長樣式優先仍成立：`aepol1#pm1` 不被短樣式先咬掉 `aepol1`

## 2. 實體字典：CSV 來源

- [x] 2.1 `entities.py` 新增 `load_csv_id_only(path, etype)`：單欄，含 `#` 者歸入子層類型
- [x] 2.2 `entities.py` 新增 `load_csv_module_code_name(path, etype)`：三欄，`code` 為 canonical、`name` 為別名、`Module` 為中繼資料
- [x] 2.3 兩者共用標頭偵測與列驗證，欄位數不符時拋出含檔名與列號的錯誤
- [x] 2.4 未知 schema 名稱時失敗並列出支援清單
- [x] 2.5 `EntityDictionary.load` 擴充為可同時吃 YAML 與多個 CSV 來源
- [x] 2.6 別名語言分段：`add()` 對同時含 CJK 與拉丁的別名，額外註冊各連續區塊
- [x] 2.7 確認 `fingerprint()` 涵蓋 CSV 條目（由 `_alias` 導出，應自動成立，加測試鎖住）

## 3. 設定

- [x] 3.1 `config.py` 新增 `entity_sources: list[dict]`（`type` / `path` / `schema`）
- [x] 3.2 `validate()` 檢查每筆宣告的必要欄位與 schema 名稱合法性
- [x] 3.3 `index_signature` 不需改動（字典指紋已涵蓋內容），加註說明避免日後誤加

## 4. 統計與報告

- [x] 4.1 `index.py` 的實體統計聚合改為 per-type（保留既有全域數字）
- [x] 4.2 `telemetry.py` 報告新增 `entities.by_type`，鍵為類型名稱
- [x] 4.3 查詢端實體來源統計同步拆解
- [x] 4.4 確認 `unknown` 類型不展開其正規名稱

## 5. 索引格式版本

- [x] 5.1 `INDEX_FORMAT_VERSION` 3 → 4
- [x] 5.2 確認載入舊格式時拒絕並提示重建指令（既有機制，加測試涵蓋 v3→v4）

## 6. 資料安全與範例檔

- [x] 6.1 `.gitignore` 加入 `*.local.csv`
- [x] 6.2 新增 `tools.example.csv`（編造值，含機台與含 `#` 的腔體各數列）
- [x] 6.3 新增 `defects.example.csv`（編造值，含純中文、純英文、同格中英混合各數列）
- [x] 6.4 `config.example.yaml` 補上 `entity_sources` 範例與註解

## 6b. 合成語料

- [x] 6b.1 `synthetic.py` 的腔體改為綁在機台上（`XTR-05#PM2`），而非獨立的 `PM2`
- [x] 6b.2 產生的字典只收一半機台的腔體，讓 by_type 拆解看得到覆蓋率缺口

> 這一節不在原本的計畫裡。`#` 的缺陷之所以存在了這麼久，正是因為合成語料
> 從來沒有產生過含 `#` 的識別碼——不補這裡，就是把同一個錯誤留給下一個缺陷。

## 7. 測試

- [x] 7.1 `#` 整段圈出、正規化保留 `#`
- [x] 7.2 層級展開：父層詞元產生、查父層命中子層、不同機台同名腔體不混淆
- [x] 7.3 實體抽取與詞彙腿的展開一致（同一文本兩條路徑都看得到父層）
- [x] 7.4 字典為空時展開仍成立
- [x] 7.5 CSV 兩種 schema 的正常載入與畸形輸入（欄位數不符、檔案不存在、未知 schema）
- [x] 7.6 `Module` 不同但 code 相同時歸為同一實體
- [x] 7.7 別名語言分段：同格中英混合可用任一語言命中
- [x] 7.8 per-type 統計數字正確
- [x] 7.9 擴充 `test_report_leaks_no_corpus_content` 涵蓋 `by_type` 結構
- [x] 7.10 舊格式索引被拒絕

## 8. 文件

- [x] 8.1 `README.md` 的「已知的調參旋鈕」補上層級展開的代價（父層詞元鑑別力下降）
- [x] 8.2 `docs/indexing.md` 補上 CSV 來源設定與何時需重建
- [x] 8.3 `docs/data-flow.md` 的實體抽取段落補上展開步驟
- [x] 8.4 `docs/api.md`：端點沒變，但 `/v1/report` 與 `/v1/stats` 的**回應多了 `by_type`**，補上並說明它是解讀 `B-C` 的前提

## 9. 驗證

- [x] 9.1 `uv run pytest` 全綠
- [x] 9.2 以合成語料重建索引並跑 `compare`，確認不因展開而崩潰
- [x] 9.3 啟動 `serve`，以 Playwright 走過 `/docs` 與一次實際查詢
