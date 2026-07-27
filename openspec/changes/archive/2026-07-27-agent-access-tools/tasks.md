## 1. 索引：關聯邊

- [x] 1.1 `Index` 新增 `related_out: dict[str, list[str]]` 與 `related_in: dict[str, list[str]]`
- [x] 1.2 `build_index()` 收集出向邊；全部 concept 掃完後一次算出入向邊（需等所有 id 已知才能判定懸空）
- [x] 1.3 懸空引用（`related` 指向語料中不存在的 id）記入 `Index.dangling: dict[str, list[str]]`，並在 `CorpusStats` 加總
- [x] 1.4 `INDEX_FORMAT_VERSION` 由 2 提升至 3
- [x] 1.5 CLI `index` 指令的統計輸出加上「懸空關聯」一列

## 2. 共用載入路徑

- [x] 2.1 新增 `src/yedai/runtime.py`，`Runtime` 持有 config / dictionary / index / searcher / store
- [x] 2.2 實作 `Runtime.load(config_path, index_path)`，含簽章驗證，錯誤訊息與既有一致
- [x] 2.3 `api.py` 的 `_load_state()` 改用 `Runtime.load()`，保留「載入失敗仍能回應 `/healthz`」的行為

## 3. 批次取全文

- [x] 3.1 `fulltext.py` 新增 `load_concepts(index, ids, include_raw=True)`，回傳 `(concepts, errors)`
- [x] 3.2 部分成功語意：單筆失敗不影響其餘；錯誤逐筆含 `concept_id` 與 `reason`
- [x] 3.3 錯誤原因區分 `not_found` 與 `file_missing`，後者訊息指示重建索引
- [x] 3.4 `include_raw=False` 時不回傳原始全文
- [x] 3.5 定義批次上限常數（50），超過或空清單由呼叫端拒絕

## 4. 關聯展開

- [x] 4.1 新增 `src/yedai/graph.py`，只依賴 `Index`
- [x] 4.2 實作 `neighbors(index, concept_id, depth=1, direction="both")`，BFS 展開並記錄各節點跳數
- [x] 4.3 起點不存在丟出 `ConceptNotFound`；深度 > 2 或方向無效丟出 `ValueError`
- [x] 4.4 結果不含起點自身；每筆含 id、bundle_id、type、title、description、path、`index_line`、`depth`、`direction`
- [x] 4.5 懸空引用單獨列出，不混入正常關聯清單

## 5. 限定範圍搜尋

- [x] 5.1 新增 `src/yedai/grep.py`，只依賴 `Index` 與 `fulltext.resolve_path`
- [x] 5.2 實作 `grep(index, pattern, bundle_ids, concept_ids, regex=False, ignore_case=False, max_results=100)`
- [x] 5.3 範圍為空時丟出 `ScopeRequired`，訊息指引先用 search 取得 bundle_id
- [x] 5.4 範圍指向不存在的 bundle 時丟出 `UnknownScope`
- [x] 5.5 無效正則丟出 `InvalidPattern`，不得逸出為未處理例外
- [x] 5.6 每筆結果含 concept_id、bundle_id、path、行號、行內容；超過上限時標示 `truncated`
- [x] 5.7 檔案已不存在時略過並繼續，不中斷整批

## 6. HTTP 端點

- [x] 6.1 `POST /concepts`：批次取全文，部分成功回 200；超過上限或空清單回 422
- [x] 6.2 `GET /concept/{concept_id}/neighbors`：深度與方向參數，404 / 422 對應
- [x] 6.3 `GET /grep`：範圍必填，未指定回 422、無效正則回 422、未知 bundle 回 404
- [x] 6.4 三個端點加上 summary/description，確認出現在互動式 API 文件

## 7. MCP server

- [x] 7.1 新增 `src/yedai/mcp_server.py`，以 stdio 通訊，啟動時載入 `Runtime`
- [x] 7.2 實作六個工具：`search`、`get_concept`、`get_concepts`、`neighbors`、`grep`、`stats`
- [x] 7.3 每個工具宣告 JSON Schema 輸入結構描述
- [x] 7.4 工具說明寫明：search 只回菜單、取內容需另呼叫、grep 必須先有範圍且範圍取自 search 結果
- [x] 7.5 工具執行失敗回傳標示為錯誤的結果與可讀原因，不中斷連線
- [x] 7.6 索引未建立時啟動失敗並明確指示先建索引
- [x] 7.7 CLI 新增 `yedai mcp` 指令
- [x] 7.8 `pyproject.toml` 加入 `mcp>=1.2` 相依

## 8. 測試

- [x] 8.1 索引：出向與入向邊正確、懸空引用被保留並計入統計、格式版本提升後舊索引被拒
- [x] 8.2 批次：順序一致、部分失敗仍成功、錯誤原因可區分、`include_raw=False`、上限與空清單
- [x] 8.3 關聯：一跳、兩跳與跳數標記、方向過濾、不含起點、無關聯回空、深度超限、起點不存在、懸空分離
- [x] 8.4 搜尋：無範圍被拒、bundle 與 concept 兩種範圍、字面 vs 正則、無效正則、忽略大小寫、上限與截斷標示、檔案缺失時略過
- [x] 8.5 HTTP：三個端點的 200 / 404 / 422 各情境；新端點出現在 openapi.json
- [x] 8.6 MCP：工具列舉含六項且皆有輸入結構描述、呼叫 search 與 get_concept 成功、失敗回錯誤結果
- [x] 8.7 一致性：同一查詢經 HTTP 與 MCP 得到相同的 concept id 排序

## 9. 端到端驗證

- [x] 9.1 重建合成語料索引（格式版本已變更），確認零解析失敗並顯示懸空關聯數
- [x] 9.2 以瀏覽器自動化在文件頁測試 `/concepts`、`/neighbors`、`/grep`，確認狀態碼與內容
- [x] 9.3 實際啟動 MCP server 走一次 stdio 握手與工具列舉
- [x] 9.4 驗證完整鏈路：search → get_concepts → neighbors → grep（範圍取自 search 結果）

## 10. 文件

- [x] 10.1 README 端點表新增三個端點，並補上 MCP 接法與 claude-agent-sdk 設定範例
- [x] 10.2 `docs/data-flow.md` 補上關聯展開與限定範圍搜尋的資料流，並更新「缺口」一節
- [x] 10.3 `docs/indexing.md` 補上懸空關聯統計的判讀，以及格式版本 3 需重建索引
- [x] 10.4 新增 `docs/agent-tools.md`：六個工具的用途、建議流程與常見誤用
