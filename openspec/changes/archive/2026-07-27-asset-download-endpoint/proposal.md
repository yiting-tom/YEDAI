## Why

`/concept/{id}` 回傳的 `assets` 陣列與 `figures[].file_id` 指向 `_assets/slide_xxx.png`，但**沒有任何端點能把那些檔案取出來**。目前這些欄位是死路：agent 知道有圖、知道圖的路徑、也拿得到模型寫的圖說，就是拿不到圖。

對 YED 語料而言這個缺口特別大——wafer map、缺陷影像、趨勢圖是**證據本身**，文字圖說只是包裝。平均每個 concept 有 7 張圖，佔語料的資訊量比重極高。

## What Changes

- 新增 `GET /concept/{concept_id}/asset?path=<相對路徑>`，回傳該 concept 引用的資產檔案（二進位），並帶正確的 media type
- 路徑**相對於該 concept 檔案所在目錄**解析，與 markdown 相對連結、`assets` frontmatter 及 `## Citations` 的寫法一致
- 新增設定 `asset_dirs`（預設 `["_assets"]`）：資產必須位於這些名稱的目錄之下，否則拒絕。此為安全預設，可覆寫
- 支援 `download=true` 以附件方式下載（預設 `inline`，讓瀏覽器直接顯示）

## Capabilities

### New Capabilities
- `asset-delivery`: 依 concept 與相對路徑取回其引用的資產檔案，含路徑約束與 media type 判定

### Modified Capabilities
- `search-interfaces`: HTTP 介面新增資產下載端點

## Impact

- **新增**：`src/yedai/assets.py`（解析與驗證，不依賴 FastAPI，供後續 MCP 圖片工具重用）
- **修改**：`src/yedai/config.py`（新增 `asset_dirs`）、`src/yedai/api.py`（新端點）
- **不影響索引**：`asset_dirs` 是服務期政策，不進索引簽章，**不需要重建索引**
- **安全**：`path` 直接來自呼叫端（不像 `concept_id` 有索引可查），因此路徑穿越是本變更的主要風險。以三道防線處理：早期拒絕絕對路徑與 `..`、解析後驗證位於 bundle 根目錄之下、驗證位於 `asset_dirs` 允許的目錄之下
- **資料安全**：資產屬語料內容，與 `/concept` 同為本機使用範疇；去識別化報告不受影響
