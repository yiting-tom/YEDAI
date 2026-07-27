# Data Flow

資料從 OKF bundle 進入系統，到查詢結果與全文回到呼叫端的完整路徑。

系統有**兩個時間上分離的階段**：離線建索引（`yedai index`）與線上查詢（HTTP / CLI）。
兩者唯一的介面是磁碟上的索引檔與原始 OKF 檔案。

---

## Level 0 — 情境圖

```mermaid
flowchart LR
  ENG(["工程師 / Agent"])
  OKF[("OKF bundle<br/>manifest.json + okf/*.md")]
  DICT[("實體字典<br/>YAML")]
  SYS["yedai"]
  IDX[("索引快取<br/>.index/*.pkl")]
  LOG[("查詢日誌<br/>logs/*.jsonl")]
  RPT(["去識別化報告<br/>可外流"])

  OKF -->|解析| SYS
  DICT -->|實體正規化| SYS
  SYS <-->|"建立 / 載入"| IDX
  ENG -->|"query / concept_id"| SYS
  SYS -->|"排序結果 + 全文"| ENG
  SYS -->|追加| LOG
  LOG --> SYS
  SYS -->|聚合| RPT
```

**信任邊界**：`OKF bundle`、`索引快取`、`查詢日誌` 全部含機密內容，只存在本機。
只有 `去識別化報告` 設計為可外流——它不含任何查詢原文或語料內容。

---

## Level 1 — 階段一：離線建索引

指令：`yedai index <bundles-dir> -c config.yaml`

```mermaid
flowchart TB
  subgraph IN[輸入]
    ROOT[("bundle 根目錄")]
    CFG[("config.yaml")]
    DIC[("dictionary.yaml")]
  end

  ROOT --> P1["1. load_bundles()<br/><i>parser.py:186</i>"]
  P1 --> P2["2. parse_bundle()<br/>排除 _assets/<br/>分流 summary/log/index.md<br/><i>parser.py:155</i>"]
  P2 --> P3["3. parse_concept()<br/>split_frontmatter + parse_sections<br/>未知欄位 → extra<br/><i>parser.py:102</i>"]
  P3 -->|失敗| SKIP[["skipped 清單<br/>不中斷整批"]]
  P3 --> P4["4. field_texts()<br/>切成 6 個欄位<br/><i>models.py</i>"]

  CFG --> TOK
  P4 --> TOK["5. 斷詞"]
  TOK --> TA["Tokenizer.naive()<br/>XTR-05 → 'xtr','05'"]
  TOK --> TB["tokenizer.protected()<br/>XTR-05 → 'ID:XTR05'"]

  DIC --> EX
  P4 --> EX["6. _concept_entities()<br/>字典命中 / regex fallback<br/><i>index.py:338</i>"]

  TA --> SA[("naive TermSpace<br/>倒排 + 欄位長度")]
  TB --> SB[("protected TermSpace")]
  EX --> SE[("EntitySpace<br/>倒排 + 位置權重")]

  P3 --> META[("docs（DocMeta 清單）<br/>by_id / bundle_roots")]

  SA --> FIN["7. finalise()<br/>各欄位平均長度"]
  SB --> FIN
  FIN --> SAVE[("8. pickle → .index/*.pkl<br/>含 signature 與 format_version")]
  SE --> SAVE
  META --> SAVE
```

### 每個 concept 被切成 6 個欄位

`Concept.field_texts()` → `title` / `description` / `tags` / `headings` / `figures` / `body`
（`FIELDS`，`config.py:16`）。BM25F 對每個欄位獨立做長度正規化後加權合併。

### 同一份語料建了三套索引

| 空間 | 內容 | 服務哪個模式 |
|---|---|---|
| `naive` TermSpace | 天真斷詞的倒排索引 | **A** |
| `protected` TermSpace | 識別碼保護斷詞的倒排索引 | **B**、**C** 的詞彙腿 |
| `EntitySpace` | 實體倒排索引 + 位置權重 | **C** 的實體腿 |

三者建在**完全相同的 concept 集合**上，所以 A/B/C 的差異只來自索引方式，不來自語料。

### 索引裡有什麼、沒有什麼

**有**：`DocMeta`（id / bundle / type / title / description / path / tags / timestamp）、
詞頻與欄位長度統計、實體權重、`by_id`、`bundle_roots`、`CorpusStats`。

**沒有**：**任何 concept 的 body 內容**。全文於請求時從磁碟讀（見下方階段三）。
這由測試強制守住：`tests/test_fulltext.py::test_index_does_not_contain_body`
會把索引 pickle 成位元組並斷言 body 標記不在其中。

---

## Level 1 — 階段二：線上查詢

`GET /search?q=…&mode=compare&k=10`（`api.py:137`）

```mermaid
flowchart TB
  Q(["query"]) --> V{"pydantic 驗證<br/>q≥1字 / mode∈A,B,C,compare / 1≤k≤100"}
  V -->|不合| E422(["422"])
  V --> R{"_require_index()<br/><i>api.py:79</i>"}
  R -->|索引未載入| E503(["503"])
  R --> CMP["Searcher.compare()<br/><i>search.py</i>"]

  CMP --> MA["模式 A"]
  CMP --> MB["模式 B"]
  CMP --> MC["模式 C"]

  MA --> A1["Tokenizer.naive(query)"] --> A2["naive.score()<br/>BM25F"]
  MB --> B1["tokenizer.protected(query)"] --> B2["protected.score()<br/>BM25F"]

  MC --> C1["protected 斷詞"] --> C3["詞彙腿"]
  MC --> C2["EntityExtractor.extract()<br/>regex + 字典最長優先"] --> C4["實體腿"]
  C2 -.->|"require_entities=true"| HF["docs_with_all()<br/>硬過濾"]
  HF -.-> C3
  HF -.-> C4
  C3 --> FUSE["max 正規化 + 線性融合<br/>0.4·lex + 0.6·ent"]
  C4 --> FUSE

  A2 --> RANK["sort by -score → top-k<br/>doc_idx → docs 第 i 筆取 metadata"]
  B2 --> RANK
  FUSE --> RANK

  RANK --> OV["jaccard + kendall_tau<br/>A-B / A-C / B-C"]
  OV --> SH["display_order 洗牌<br/>（seeded，降低位置偏差）"]
  SH --> LG[("log_query()<br/>→ queries.jsonl<br/>回傳 query_id")]
  LG --> OUT(["JSON：header 菜單<br/>不含內容"])
```

### 計分

**BM25F**（`TermSpace.score`，`index.py:46` 起）：

```
idf(t)   = log(1 + (N − df + 0.5) / (df + 0.5))

tf̃(t,d)  = Σ_f  w_f · tf_f / (1 − b + b · len_f / avglen_f)      各欄位獨立長度正規化

score   += qn(t) · idf(t) · tf̃ / (k1 + tf̃)
```

預設 `w` = title 3.0 / description 2.0 / tags 2.0 / headings 1.5 / figures 1.5 / body 1.0；
`k1` = 1.2、`b` = 0.75。全部可由設定檔覆寫，且會被記進報告的 `experiment_params`。

**實體腿**（`EntitySpace.score`，`index.py:117` 起）：

```
num(d) = Σ_{e ∈ q∩d}  idf(e) · boost(e,d)        boost = 該實體在 d 中出現過的最高欄位權重
den    = Σ_{e ∈ q}    idf(e) · max_field_weight  分母含「語料裡不存在的查詢實體」
score  = num / den  ∈ [0,1]
```

分母刻意包含語料中不存在的查詢實體——語料涵蓋不了的查詢本來就不該拿滿分。

**融合**（`Searcher._hybrid`）：

```
lex_n = lex / max(lex over candidates)     詞彙腿在結果集內做 max 正規化
final = 0.4 · lex_n + 0.6 · ent            實體腿本身已是 [0,1] 的涵蓋率，不再正規化
```

不用 RRF：RRF 只吃排名、會抹掉分數資訊，那樣就無法回答「哪一條腿貢獻了多少」——
而那正是這套工具存在的目的。

### 回應內容

每筆只有 `concept_id` / `bundle_id` / `type` / `title` / `description` / `path` /
`score` / `lexical_score` / `entity_score` / `index_line`。

**刻意不回傳內容片段。** 回一份菜單、讓 agent 自己決定讀哪幾份全文，才保得住
「agent 讀完整文件並自行判斷」這個讓小規模 agentic file search 效果好的性質。

---

## Level 1 — 階段三：取回全文

`GET /concept/{concept_id}`（`api.py:171` → `fulltext.load_concept`，`fulltext.py:55`）

```mermaid
flowchart TB
  CID(["concept_id"]) --> L1{"index.by_id 查找"}
  L1 -->|不存在| E404(["404<br/>ConceptNotFound"])
  L1 --> L2["取 DocMeta"]
  L2 --> L3["以 bundle_roots 取根目錄<br/>再接上 DocMeta.path"]
  L3 --> L4{"解析後絕對路徑<br/>是否在 bundle 根目錄之下？"}
  L4 -->|否| E500(["500<br/>ConceptPathEscape"])
  L4 --> L5{"檔案存在？"}
  L5 -->|否| E410(["410<br/>ConceptFileMissing<br/>訊息指示重建索引"])
  L5 --> L6[("read_text()<br/>磁碟")]
  L6 --> L7["parse_concept(text=raw)<br/>重用建索引時的同一條解析路徑"]
  L7 --> OUT2(["raw + frontmatter<br/>+ sections + figures"])
```

**404 與 410 刻意分開**：前者是 id 打錯，後者是語料在建索引後變動了。
兩者需要的處置完全不同，混為一談會讓使用者無從判斷該不該重建索引。

**路徑防線**：`concept_id` 只用於查 `by_id`，實際路徑來自索引而非使用者輸入；
仍額外驗證解析結果落在 bundle 根目錄之下，以防索引被竄改或人工編輯出錯。

### ⚠️ 內容編輯與檢索排名的不同步

全文從磁碟讀，但**詞頻統計仍留在索引裡**。因此改一個 `.md` 之後：

| | 是否立即反映 |
|---|---|
| `/concept/{id}` 的內容 | ✅ 立即 |
| `/search` 的排名 | ❌ 要重建索引 |

詳見 [indexing.md](./indexing.md#4-何時必須重建索引)。

---

## 完整迴路

```mermaid
sequenceDiagram
  participant A as Agent
  participant S as /search
  participant C as GET /concept
  participant F as OKF 檔案
  participant L as logs/*.jsonl

  A->>S: query
  S->>S: A / B / C 三模式計分 + 重疊度
  S->>L: log_query() → query_id
  S-->>A: header 菜單（index.md 行格式）+ query_id
  A->>A: 挑 3~7 筆
  loop 每一筆
    A->>C: concept_id
    C->>F: read_text()
    F-->>C: raw markdown
    C-->>A: raw + frontmatter + sections + figures
  end
  A->>A: 作答
  A->>S: POST /feedback（query_id, concept_id, rank, mode）
  S->>L: 追加 feedback.jsonl
```

---

## 遙測：兩條獨立路徑

```mermaid
flowchart LR
  SR["/search"] -->|"log_query()"| QJ[("queries.jsonl<br/>含查詢原文<br/>❌ 不外流")]
  FB["POST /feedback"] -->|"has_query() 驗證<br/>不存在 → 404"| FJ[("feedback.jsonl")]
  QJ --> BR["build_report()<br/><i>telemetry.py:164</i>"]
  FJ --> BR
  IDX[("index.stats")] --> BR
  BR --> RP(["/report<br/>✅ 零內容，可分享"])
```

`build_report()` 只輸出數量、比例、分佈與設定參數。
`tests/test_telemetry.py::test_report_leaks_no_corpus_content` 斷言報告序列化後
不含任何查詢原文、concept 標題、描述或實體名稱——由測試強制，不靠慣例。

報告中最關鍵的欄位是 `mode_overlap`：A-B 的 jaccard 接近 1 代表斷詞層沒有作用、
B-C 接近 1 代表字典不值得維護。判讀方式見 [README](../README.md#怎麼讀報告)。

---

## 資料存放位置

| 資料 | 位置 | 機密 | 版控 |
|---|---|---|---|
| OKF bundle 原檔 | 使用者指定路徑 | ✅ | ❌ gitignore |
| 索引快取 | `.index/*.pkl` | ✅（含 title/description） | ❌ gitignore |
| 完整查詢日誌 | `logs/queries.jsonl` | ✅（含查詢原文） | ❌ gitignore |
| 點選回饋 | `logs/feedback.jsonl` | ⚠️（含 concept_id） | ❌ gitignore |
| 去識別化報告 | `yedai report -o` 指定路徑 | ❌ | 可分享 |
| 合成語料 | `.synthetic/` | ❌ | ❌ gitignore |

---

## 目前流程的缺口

已補：`/concept/{id}` 讓 agent 拿得到全文。

尚未實作（後續變更）：

| 缺口 | 影響 |
|---|---|
| 批次取全文 | agent 一次要讀 3~7 份，目前得逐筆 round trip |
| `neighbors`（沿 `related` 展開） | 無法重現 agent 目前用 `related` 跳轉的行為 |
| 限定範圍 `grep` | 範圍縮小後無法恢復原本有效的 agentic file search |
| MCP server | claude-agent-sdk 目前得自行包 HTTP 工具定義 |
| 三欄並排 Web UI | Swagger 無法收集點選資料，`/feedback` 實際上沒人會用 |
