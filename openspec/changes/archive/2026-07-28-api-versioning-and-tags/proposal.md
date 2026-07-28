## Why

HTTP 介面已經長到 10 個端點，但只有兩個分類標籤：`ops` 與 `search`。`search` 這一組現在同時裝著檢索、取全文、批次、關聯展開、字面搜尋、資產下載與點選回饋——**七個用途完全不同的端點擠在同一個標籤下**，文件頁失去導航價值，agent 也無從判斷該用哪一組。

同時，所有端點都掛在根路徑上，**沒有任何版本標示**。目前唯一的消費者是使用者自己，但一旦 agent 開始依賴這組介面，任何破壞性變更都無路可退——沒有版本前綴就沒有並行提供新舊契約的可能。現在改成本最低。

此外，服務目前無法回答「我跑的是哪一版、索引格式相容嗎」。`INDEX_FORMAT_VERSION` 已經因為結構變更升過兩次（1→2→3），每次都需要重建索引，但除錯時無從得知服務端與索引檔各自是什麼版本。

## What Changes

- **BREAKING**：所有功能端點移至 `/v1` 前綴。`/search` → `/v1/search`，其餘同理
- `/healthz` 與新增的 `/version` 維持在**未版本化的根路徑**——它們描述的是服務本身，不是 API 契約，監控與部署不該因 API 改版而失效
- 端點依用途重新分為五類，取代原本的兩類：

  | 標籤 | 端點 | 用途 |
  |---|---|---|
  | `retrieval` | `/v1/search`、`/v1/grep` | 找到 concept |
  | `content` | `/v1/concept/{id}`、`/v1/concepts`、`/v1/concept/{id}/asset` | 取得內容與資產 |
  | `graph` | `/v1/concept/{id}/neighbors` | 沿關聯導航 |
  | `telemetry` | `/v1/feedback`、`/v1/report` | 量測與回饋 |
  | `ops` | `/healthz`、`/version`、`/v1/stats` | 服務與語料狀態 |

- 每個標籤附帶說明，於互動式文件頁顯示，讓分組本身就是使用指引
- 新增 `GET /version`，一次回報四個版本號：套件版本、API 版本、索引格式版本，以及目前載入索引的簽章與格式版本
- OpenAPI 文件的 `version` 欄位改為套件版本

## Capabilities

### New Capabilities
- `api-versioning`: API 版本前綴、未版本化的服務層端點，以及版本資訊查詢

### Modified Capabilities
- `search-interfaces`: 所有端點路徑加上版本前綴，並重新分類標籤

## Impact

- **BREAKING**：既有的 `/search`、`/concept/...`、`/grep`、`/feedback`、`/report`、`/stats` 全部失效，需改用 `/v1` 前綴。`/healthz` 不受影響
- **不影響 MCP**：MCP server 直接呼叫 Python 函式，不經 HTTP
- **不影響索引**：純介面變更，既有索引無須重建
- **修改**：`src/yedai/api.py`（改用 `APIRouter` 統一掛前綴，標籤重分類，新增 `/version`）
- **文件**：README 端點表、`docs/agent-tools.md` 的 HTTP 對照表、`docs/data-flow.md` 的端點引用皆須更新
