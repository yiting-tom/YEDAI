## Why

分層索引已經實作完成，但**沒有任何一組資料能把它跑起來**。`gen-synthetic` 產的是一份扁平語料加一份字典，`config.local.yaml` 也還是單一索引 `synthetic:`。三層的行為目前只活在單元測試的雙索引 fixture 裡。

這件事的代價不是「少一個 demo」。分層存在的理由是**三層的文本性質不同**——library 是每個 defect 一條的登錄、heuristics 是無固定格式的自由文字、cases 是識別碼密集的固定格式報告。統計隔離、每層各自的 `keep_identifiers` 與 `default_mode`，全都是為了這個差異而存在。用同一個產生器產三堆一模一樣的文件再分到三個目錄，跑得起來，但**證明不了任何事**：`df` 分佈相同時看不出隔離有沒有用，識別碼密度相同時看不出前處理有沒有生效。

同樣的缺口也在查表資源上：taxonomy、defect 全集、兩份 CSV 實體來源目前只有手寫的 `*.example.*` 佔位檔，彼此的鍵對不起來，也對不上任何語料。覆蓋率統計因此沒有可跑的輸入。

## What Changes

- `gen-synthetic` 改為產出**分層**資料集，每層有自己的文本性質：
  - `library` — 每個 defect 一條，短、結構固定、識別碼稀少
  - `heuristics` — 自由文字、段落長、識別碼稀少（該層本來就剝除識別碼）
  - `cases` — 固定模板、識別碼密集（機台／腔體／製程／流程／批號／晶圓）
- **defect 全集為單一事實來源**：由它同時產生 `dictionary.yaml`、`defects.csv`、`taxonomy.yaml`、`defects.catalogue.yaml` 與 library 層的語料。四份檔互相對得上，不是各寫各的
- taxonomy **刻意留缺口**：部分 defect 無條目、部分有描述無 method。覆蓋率恆為 100% 的資料集無法暴露覆蓋率統計本身的錯誤
- 一併產出 `tools.csv`（`id_only`，含 `#` 的腔體列）、`identifier-samples.yaml`（取自實際產生的識別碼），以及一份**可直接使用的 `config.yaml`**
- `concept_id` 的命名空間納入層名——三層會同時載入，相撞的後果是取全文取到錯的那一層、跨層融合對同一份文件重複加權，而兩者都不報錯

## Capabilities

### Modified Capabilities
- `synthetic-fixtures`: 由單一扁平語料改為分層資料集，並涵蓋全部輸入種類

## Impact

- **修改**：`synthetic.py`、`yedai gen-synthetic`（`--bundles` 改為每層的 bundle 數）
- **不影響**：解析、索引、檢索、報告——產出的仍是既有格式的 OKF bundle
- **相容性**：輸出目錄結構改變（語料移到 `corpus/<layer>/`）。舊的產出目錄需重產，不做轉換

## 這份資料集能回答什麼、不能回答什麼

**能**：分層機制**會不會照宣告運作**。三層的識別碼密度與文本長度不同，所以「heuristics 剝除識別碼之後查詢詞真的變了」「cases 長大之後 library 的排名沒有漂移」是真的量測。

**不能**：任何檢索效果數字。詞頻分佈、識別碼密度、模板多樣性全是編造的，既有的使用限制說明繼續適用，且必須跟著分層資料集一起輸出。
