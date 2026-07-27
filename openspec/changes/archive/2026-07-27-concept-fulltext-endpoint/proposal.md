## Why

現有的 data flow 在 metadata 就結束了。`/search` 每筆只回 `concept_id` / `type` / `title` / `description` / `path` / 分數，而索引建構時就把 markdown body 丟掉，只留詞頻統計（`DocMeta` 不含內容）。

結果是：**agent 拿到候選菜單之後無路可走**——沒有任何端點能取回 concept 全文，因此無法閱讀、無法作答、無法沿 `related` 判斷要不要展開。目前這套是完整的「量測迴路」，但不是「取用迴路」。

補上全文端點，檢索流程才能從

```
query → search → header 菜單 → （斷掉）
```

延伸為

```
query → search → header 菜單 → agent 挑數份 → 取全文 → 作答
```

## What Changes

- 新增 `GET /concept/{concept_id}`，回傳單一 concept 的完整內容：原始 markdown、解析後的 frontmatter、切分好的 section 清單、figures、related
- 索引新增 `concept_id → 文件位置` 的對照，以及各 bundle 的根目錄登錄；全文**於請求時從磁碟讀取**，不存進索引
- **BREAKING**：索引格式版本自 1 提升至 2。既有 `.pkl` 快取需重建（`yedai index …`），舊索引載入時會明確報錯而非靜默失敗
- 查無此 `concept_id` 回 404；索引中有登錄但檔案已不存在（語料在建索引後被移動或刪除）回 410，並提示重建索引

## Capabilities

### New Capabilities
- `concept-retrieval`: 依 concept id 取回單一 concept 的完整內容與結構化欄位

### Modified Capabilities
- `keyword-retrieval`: 「索引建構與快取」須額外保存 concept id 對照與 bundle 根目錄登錄，並提升索引格式版本
- `search-interfaces`: HTTP 介面新增全文端點

## Impact

- **修改**：`src/yedai/index.py`（`Index` 新增 `by_id` 與 `bundle_roots`、格式版本 +1）、`src/yedai/api.py`（新端點）
- **新增**：`src/yedai/fulltext.py`（讀取與組裝邏輯，供 HTTP 與後續 MCP 共用）
- **不影響**：檢索計分、三模式消融、遙測與報告——本變更不觸碰任何量測邏輯
- **資料安全**：此端點回傳語料原文，與 `/search` 同屬**本機使用**範疇；去識別化報告不受影響、仍不含任何內容
- **後續銜接**：`/concept/{id}` 是 MCP server 的第一個讀取工具；批次取用、`neighbors`、限定範圍 `grep` 為後續變更
