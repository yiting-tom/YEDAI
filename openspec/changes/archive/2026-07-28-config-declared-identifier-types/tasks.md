## 1. 樣式可帶宣告

- [x] 1.1 `resolve_specs` 接受 mapping：`{pattern, type, parent_type, shape_complete}`
- [x] 1.2 字串維持原行為（逐條對回內建宣告）
- [x] 1.3 `index_signature` 對 mapping 形式仍然穩定——樣式改變必須讓索引失效

## 2. 設定驗證

- [x] 2.1 mapping 缺 `pattern` → 設定錯誤
- [x] 2.2 `shape_complete` 為真但無 `type` → 設定錯誤（沒有類型的完整性宣稱對不到分母）
- [x] 2.3 樣式無法編譯 → 當場失敗，不要等到建索引才炸

## 3. 測試

- [x] 3.1 自訂樣式宣告的類型會出現在抽取結果
- [x] 3.2 宣告的 `parent_type` 用於層級展開
- [x] 3.3 `shape_complete` 宣告使該類型可測
- [x] 3.4 字串形式行為不變
- [x] 3.5 錯誤宣告被擋下

## 4. 文件

- [x] 4.1 `docs/indexing.md`：mapping 形式與**編造**的範例
- [x] 4.2 寫明敏感的組成規則應住在 `config.local.yaml`，理由是這個 repo 公開
