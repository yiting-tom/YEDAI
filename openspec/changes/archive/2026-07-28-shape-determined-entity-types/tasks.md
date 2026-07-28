## 1. 樣式帶類型宣告

- [x] 1.1 `IdentifierPattern`：`pattern` / `type` / `parent_type` / `shape_complete`
- [x] 1.2 `DEFAULT_IDENTIFIER_PATTERNS` 保持 `list[str]`（設定檔介面不變），由 spec 清單導出
- [x] 1.3 `Tokenizer` 接受字串或 spec
- [x] 1.4 `#` 樣式 → `chamber_id`，父層 `tool_id`
- [x] 1.5 `xxxxxx.00` → `lot`（獨立樣式，排在晶圓之前）
- [x] 1.6 `xxxxxx.NN` → `wafer`，父層 `lot`
- [x] 1.7 `\b\d{3,6}\.\d{3}\b` → `op_no`（純數字不展開，無父層）
- [x] 1.8 `find_identifiers` 回傳 `IdentifierHit`，帶每個詞元的類型

## 2. 抽取時採用

- [x] 2.1 字典未命中時採用樣式宣告的類型，無宣告才用 `unknown`
- [x] 2.2 字典命中優先於形狀——字典是人維護的，形狀是猜的

## 3. 覆蓋率比例

- [x] 3.1 「分母可測」改為 spec 上的 `shape_complete`，由 `Tokenizer.shape_complete_types`
      從**實際使用的樣式**導出，不是寫死的常數
- [x] 3.2 `CorpusStats.shape_complete_types` 隨索引保存——數字要追溯得回它成立的前提
- [x] 3.3 `dictionary_coverage` 型別改為 `float | None`；報告加 `coverage_measurable_types`
- [x] 3.4 `schemas.py` 的 `entities_by_type` 說明更新
- [x] 3.5 `INDEX_FORMAT_VERSION` 6 → 7

## 4. 宣告不得在設定路徑上遺失

實作時撞到的第一個 bug，而且它**沒有讓任何測試變紅**：設定檔預設就帶著樣式字串清單，
於是宣告在 `Config → Tokenizer` 之間被靜靜丟掉，覆蓋率照樣回報 1.0。
本能力要修的正是這種失效形式，不能在修它的路上重現一次。

- [x] 4.1 `resolve_specs()` 逐條把字串對回內建樣式，沿用其宣告
- [x] 4.2 `Config.identifier_specs()`；三處 `Tokenizer(...)` 全部改走這裡
- [x] 4.3 測試釘住預設設定保留宣告、以及新增自訂樣式不影響其他宣告

## 5. 測試

- [x] 5.1 `TSK04#PM3` 未入字典時類型為 `chamber_id`、父層為 `tool_id`
- [x] 5.2 通用樣式命中者仍為 `unknown`
- [x] 5.3 合成語料的 `chamber_id` 覆蓋率為 0.5——**本次的迴歸點**
- [x] 5.4 `tool_id` 的 `dictionary_coverage` 為 `null` 而非 1.0
- [x] 5.5 批底的類型不因先看到 lot 還是 wafer 而不同（否則兩端產出不同的鍵）
- [x] 5.6 實體鍵改變但查詢端／文件端同步；`ID:` 詞元一字不改
- [x] 5.7 可測類型隨樣式清單改變

## 6. 文件

- [x] 6.1 `docs/api.md`：`dictionary_coverage` 可為 null，及 `null` 不等於 0
- [x] 6.2 `docs/indexing.md`：形狀決定類型的樣式表、三段式判讀、索引版本沿革
- [x] 6.3 `README.md`：讀 `by_type` 時 `null` 代表什麼
