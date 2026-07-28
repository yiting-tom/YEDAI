## 1. 版本常數與分類定義

- [x] 1.1 `api.py` 定義 `API_VERSION = "v1"`，並自套件取得 `__version__`
- [x] 1.2 定義五個標籤常數與其說明文字（`retrieval` / `content` / `graph` / `telemetry` / `ops`）
- [x] 1.3 `FastAPI(...)` 帶入 `openapi_tags`（標籤說明）與 `version=__version__`

## 2. 路由重組

- [x] 2.1 建立 `APIRouter(prefix=f"/{API_VERSION}")`，將全部功能端點改掛其上
- [x] 2.2 保持路由宣告順序：`/concept/{id}/asset` 與 `/concept/{id}/neighbors` 仍在 `/concept/{id}` 之前
- [x] 2.3 依新分類為每個端點指定標籤
- [x] 2.4 `/healthz` 留在未版本化根路徑
- [x] 2.5 `app.include_router(router)`；確認未版本化的舊路徑不再存在

## 3. 版本查詢端點

- [x] 3.1 新增未版本化的 `GET /version`
- [x] 3.2 回報 `package` / `api` / `index_format`（本程式支援）
- [x] 3.3 回報 `index`：目前載入索引的 `format_version` 與 `signature`；未載入時為 `null`
- [x] 3.4 索引未載入時仍回 200，不呼叫 `_require_index()`

## 4. 測試

- [x] 4.1 `/v1/*` 全部端點可用，行為與變更前一致
- [x] 4.2 未版本化的舊路徑（`/search`、`/stats`、`/concept/...`、`/grep`、`/feedback`、`/report`）皆回 404
- [x] 4.3 `/healthz` 與 `/version` 在根路徑可用
- [x] 4.4 `/version` 的四個版本欄位正確；「支援的索引格式」與「已載入索引的格式」為獨立欄位
- [x] 4.5 索引未載入時 `/version` 仍回 200 且索引欄位為 null
- [x] 4.6 openapi.json 的 `version` 等於套件版本
- [x] 4.7 每個端點恰好屬於五個標籤之一；每個標籤有非空說明
- [x] 4.8 `/v1/concept/{id}/neighbors` 與 `/asset` 路由順序正確，`concept_id` 未吞入尾段
- [x] 4.9 更新既有 API 測試的路徑

## 5. 端到端驗證

- [x] 5.1 啟動服務，以瀏覽器自動化確認文件頁出現五個分組且各有說明
- [x] 5.2 於文件頁實測 `/version` 與一個 `/v1` 端點
- [x] 5.3 確認舊路徑回 404

## 6. 文件

- [x] 6.1 README 端點表全面改為 `/v1`，並標示 BREAKING 與 `/healthz`、`/version` 不版本化
- [x] 6.2 README 的範例指令（curl 片段）更新路徑
- [x] 6.3 `docs/agent-tools.md` 的 HTTP 對照表更新路徑
- [x] 6.4 `docs/data-flow.md` 中的端點引用更新路徑
- [x] 6.5 於 README 或 docs 說明五個分類的意義
