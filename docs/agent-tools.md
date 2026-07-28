# Agent 工具

給 agent 用的六個工具，以 MCP（stdio）或 HTTP 兩種方式提供。兩者共用同一份核心實作
（`runtime.py`），同一個查詢在兩邊的結果排序一定一致。

---

## 設計前提

整套系統的收斂點：

> **不要用 RAG 取代 agentic file search，用檢索把 N 個 bundle 縮到 2~3 個，
> 然後在那個縮小的範圍裡跑原本就有效的 agentic file search。**

工具集是照這句話設計的，所以有兩個看起來「不方便」但刻意為之的限制：

1. **`search` 不回傳內容**，只回菜單。由 agent 決定讀哪幾份完整文件，比讓系統塞片段更準——
   這保住了「agent 當 reranker、讀完整文件」這個讓小規模檔案搜尋有效的性質。
2. **`grep` 必須先有範圍**。允許無範圍 grep 等於留一條繞過檢索層的退路；
   agent 會用它，然後我們回到「掃三十 GB、拿回三百條命中、無從分流」的原點。

---

## 建議流程

```
search（縮範圍、取菜單）
  └─ 挑 3~7 筆
       └─ get_concepts（批次取全文）
            ├─ neighbors（沿 related 展開，尤其 direction=in）
            └─ grep（在 search 給的 bundle_id 範圍內做字面搜尋）
```

---

## 工具

### `search`

在語料中檢索，**只回摘要清單**。每筆含 `concept_id` / `bundle_id` / `type` / `title` /
`description` / `path` / 分數 / `index_line`。

| 參數 | 說明 |
|---|---|
| `query` | 查詢字串 |
| `mode` | `A` 天真斷詞 / `B` 識別碼保護 / `C` 加實體字典。**一般用途用 `C`** |
| `k` | 回傳筆數（1–100，預設 10） |

`mode` 是消融實驗留下的旋鈕。A 會把 `TEL-05` 切成 `tel` + `05`，因此會把 `TEL-06`
的文件也拉進來——除非你在做對照，否則不要用。

### `get_concept`

取單一 concept 全文：`raw`（原始 markdown，可直接進 context）、`frontmatter`、
`sections`（依 `##` 切分）、`figures`、`related`。

要讀多份請用 `get_concepts`，不要連續呼叫這個。

### `get_concepts`

批次取全文，最多 **50 筆**。

**部分成功**：單一 id 失敗不影響其餘，失敗者在 `errors`，`reason` 區分：

| reason | 意義 | 處置 |
|---|---|---|
| `not_found` | id 不存在 | id 打錯，或屬於另一份語料 |
| `file_missing` | 索引裡有、磁碟上沒有 | 語料變動過，需重建索引 |

`include_raw=false` 時只回結構化欄位，省下大量 context——只需要標題與章節結構時用它。

### `neighbors`

沿 `related` 展開關聯。

| 參數 | 說明 |
|---|---|
| `concept_id` | 起點 |
| `depth` | 1 或 2（上限 2） |
| `direction` | `out` 我指向誰 / `in` **誰指向我** / `both` |

**`direction=in` 是這個工具最有價值的部分**——「還有哪些文件引用了這個概念」是你
自己拼不出來的資訊，而排查復發問題時正好需要它。

回傳一樣是摘要清單（要內容再呼叫 `get_concepts`），每筆標有 `depth` 與 `via`。
指向不存在 concept 的懸空引用列在 `dangling`，不會混進正常清單。

### `grep`

在**已限定的範圍內**做字面或正則搜尋。

| 參數 | 說明 |
|---|---|
| `pattern` | 搜尋樣式 |
| `bundle_ids` / `concept_ids` | **至少提供其一**，否則被拒絕 |
| `regex` | 預設 `false`（字面比對） |
| `ignore_case` | 預設 `false` |
| `max_results` | 預設 100，上限 1000 |

範圍請取自 `search` 結果的 `bundle_id`。忘了給範圍會拿到 `scope_required` 錯誤，
訊息裡有正確用法。

正則預設關閉：使用者提供的正則可能觸發災難性回溯，而 Python 的 `re` 沒有執行時間上限。

### 資產（圖片）

**MCP 目前沒有對應工具**——資產是二進位，需要以 `ImageContent` 回傳，那是另一個變更。
目前只能走 HTTP：

```
GET /v1/concept/{concept_id}/asset?path=<assets 陣列中的值>
```

`get_concept` / `get_concepts` 回傳的 `assets` 陣列與 `figures[].description`
已經給了 agent 圖的位置與模型寫的圖說。要真正看到圖，需要人或另一個管道去取這個 URL。

以 YED 語料而言這個限制值得注意：平均每個 concept 有 7 張圖，
而 wafer map、缺陷影像、趨勢圖是**證據本身**，文字圖說只是包裝。

### `stats`

語料統計：bundle 數、concept 數、type 分佈、詞彙量、實體覆蓋率、懸空關聯數、解析失敗數。
用來了解語料的規模與形狀。

---

## 接上 MCP

```bash
uv run yedai mcp -c config.local.yaml
```

claude-agent-sdk / Claude Code 的 MCP 設定：

```json
{
  "mcpServers": {
    "yedai": {
      "command": "uv",
      "args": ["run", "yedai", "mcp", "-c", "config.local.yaml"],
      "cwd": "/path/to/YEDAI"
    }
  }
}
```

索引必須先建好（見 [indexing.md](./indexing.md)），否則 server 啟動即失敗並提示。

工具執行失敗時回傳的是**標示為錯誤的結果**（`{"error": ..., "detail": ...}`），
不會中斷連線——agent 可以讀錯誤訊息自行修正後重試。

---

## 接上 HTTP

```bash
uv run yedai serve -c config.local.yaml     # http://127.0.0.1:8000/docs
```

| 工具 | HTTP |
|---|---|
| MCP 工具 | HTTP | 分類 |
|---|---|---|
| `search` | `GET /v1/search?q=&mode=&k=` | retrieval |
| `grep` | `GET /v1/grep?pattern=&bundle_id=&regex=` | retrieval |
| `get_concept` | `GET /v1/concept/{concept_id}` | content |
| `get_concepts` | `POST /v1/concepts` | content |
| （無對應工具） | `GET /v1/concept/{concept_id}/asset?path=` | content |
| `neighbors` | `GET /v1/concept/{concept_id}/neighbors?depth=&direction=` | graph |
| `stats` | `GET /v1/stats` | ops |

HTTP 額外有 `POST /v1/feedback`（點選回饋）與 `GET /v1/report`（去識別化統計報告），
那兩個屬 `telemetry` 分類，服務的是 A/B/C 消融實驗，不在 agent 工具集裡。

每個端點的完整參數、運作步驟與錯誤碼見 [api.md](./api.md)。

`GET /healthz` 與 `GET /version` 不帶版本前綴。

---

## 常見誤用

| 症狀 | 原因 | 正解 |
|---|---|---|
| 「搜尋結果沒有內容」 | 把 `search` 當唯一入口 | `search` 只回菜單，內容要 `get_concepts` |
| `scope_required` 錯誤 | 直接 `grep` 沒給範圍 | 先 `search` 拿 `bundle_id`，再 `grep` |
| 逐筆呼叫 `get_concept` 很多次 | 沒用批次 | 改用 `get_concepts` 一次拿 |
| context 爆掉 | 一次拉太多全文 | 先 `include_raw=false` 看結構，再挑要讀的 |
| 檢索抓錯機台 | 用了 `mode=A` | 一般用途用 `mode=C` |
| `related` 指向的 concept 取不到 | 那是懸空引用 | 看回應的 `dangling`，那些 id 在語料中不存在 |
| 資產下載回 403 | 路徑違反約束 | 直接用 `assets` 陣列裡的值；別自己拼路徑或用 `..` |
