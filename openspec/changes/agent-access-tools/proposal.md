## Why

`/concept/{id}` 補上了「取全文」，但 agent 要真的取代目前的 glob/grep 工作流，還缺四塊。缺口的共同性質是：**現在的介面只服務「一次查一筆」，而 agent 的實際行為是批次讀、沿關聯跳、在縮小範圍後回頭做字面搜尋。**

- **批次取全文**：agent 一輪要讀 3~7 份 concept，目前得逐筆 round trip
- **關聯展開**：agent 目前靠 `related` 跳轉，但索引根本沒保存這些邊，無法重現
- **限定範圍字面搜尋**：整個設計的收斂點是「把 N 個 bundle 縮到 2~3 個，然後在那個縮小的範圍裡跑原本就有效的 agentic file search」——縮完之後沒有工具可以做那件事
- **MCP server**：claude-agent-sdk 目前得自行包 HTTP 工具定義，且沒有任何機制引導 agent 走「先菜單、再取全文」的正確用法

## What Changes

- 新增批次取全文 `POST /concepts`，**部分成功**語意：單一 id 失敗不影響其餘，失敗原因逐筆回報
- 新增 `GET /concept/{id}/neighbors`，沿 `related` 展開 1~2 跳，同時回傳**出向**（我指向誰）與**入向**（誰指向我）；指向不存在 concept 的懸空引用單獨列出
- 索引新增 concept 關聯邊（出向與入向）。**BREAKING**：索引格式版本 2 → 3，既有快取需重建
- 新增 `GET /grep`，**強制限定範圍**：未指定 bundle 或 concept 範圍時拒絕執行。預設字面比對，正則需明確開啟
- 新增 MCP server（stdio）與 `yedai mcp` 指令，提供 `search` / `get_concept` / `get_concepts` / `neighbors` / `grep` / `stats` 六個工具
- 新增 `runtime.py`：設定、索引、字典、檢索器、遙測的共用載入路徑，供 HTTP 與 MCP 兩個介面重用，避免兩套載入邏輯行為分歧

## Capabilities

### New Capabilities
- `concept-graph`: 依 `related` 展開 concept 關聯，含出向、入向與懸空引用
- `scoped-grep`: 限定範圍內的字面／正則搜尋，拒絕全域搜尋
- `agent-tooling`: MCP server 與其工具集，含引導 agent 正確用法的說明

### Modified Capabilities
- `concept-retrieval`: 新增批次取全文，具部分成功語意與筆數上限
- `keyword-retrieval`: 索引須額外保存 concept 關聯邊，並提升索引格式版本
- `search-interfaces`: HTTP 介面新增批次、關聯展開與限定範圍搜尋端點

## Impact

- **新增**：`src/yedai/graph.py`、`src/yedai/grep.py`、`src/yedai/runtime.py`、`src/yedai/mcp_server.py`
- **修改**：`src/yedai/index.py`（關聯邊、格式版本）、`src/yedai/fulltext.py`（批次）、`src/yedai/api.py`（新端點、改用 runtime）、`src/yedai/cli.py`（`mcp` 指令）
- **新增相依**：`mcp>=1.2`
- **不影響**：檢索計分、三模式消融、遙測與報告——本變更不觸碰任何量測邏輯
- **資料安全**：新端點皆回傳語料內容，與 `/search`、`/concept` 同屬本機使用範疇；去識別化報告不受影響
- **安全邊界**：`grep` 的正則由使用者提供，需限制執行範圍、結果數與正則開關，避免全域掃描與病態回溯
