# yedai — OKF 關鍵字檢索 baseline harness

在投入混合檢索、實體向量、issue family 之前，先量出**純關鍵字檢索的水位線**。

這支工具的存在只為了回答一個問題：

> 你的 OKF 語料裡，文字主體是機台 id、製程 id、flow 等專有字詞。
> 一般斷詞會把 `TEL-05` 切成 `tel` + `05`，讓它與 `TEL-06` 幾乎無法區分。
> **識別碼到底需不需要特別處理？需要的話，停在斷詞層就夠，還是必須維護實體字典？**

---

## 三組消融

| 模式 | 內容 | 隔離出的變因 |
|---|---|---|
| **A** | 天真 BM25F，識別碼被一般斷詞切碎 | 水位線：什麼都不做 |
| **B** | BM25F + 識別碼保護斷詞（`TEL-05` 為單一詞元） | **斷詞層**的貢獻 |
| **C** | B + 實體字典正規化與精確匹配加權 | **字典**的額外貢獻 |

只做兩組（A vs C）只能回答「合起來有沒有效」。三組能回答「哪一個干預有效」——
如果 A→B 就補完大部分差距，字典那筆長期人力成本就不必付。

---

## 文件

| | |
|---|---|
| [docs/api.md](docs/api.md) | API 參考：逐端點的參數、運作步驟、回應結構與錯誤碼 |
| [docs/data-flow.md](docs/data-flow.md) | 資料流圖（DFD）+ 計分公式 + 資料存放位置 |
| [docs/indexing.md](docs/indexing.md) | 如何建立索引、統計數字怎麼看、何時必須重建 |
| [docs/agent-tools.md](docs/agent-tools.md) | 六個 agent 工具、建議流程、MCP 接法、常見誤用 |
| [openspec/specs/](openspec/specs/) | 規格（需求與情境） |

## 安裝

```bash
uv sync
```

## 指向你的真實語料

```bash
# 1. 準備設定
cp config.example.yaml config.local.yaml     # config.local.yaml 已被 gitignore
cp dictionary.example.yaml dictionary.local.yaml   # 填入你的機台/製程/缺陷字典

# 字典也可以直接吃 MES 匯出的 CSV（不必手工轉成 YAML，兩者可並存）：
#   tool_id      單欄；含 `#` 的列自動歸為腔體（aepol1 / aepol1#pm1 同表）
#   defect_code  三欄 Module, defect code, defect name；name 就是別名欄
# 在 config.local.yaml 的 entity_sources 宣告。真實清單請命名為 *.local.csv——
# 那個樣式已被 gitignore，而本 repo 是公開的。

# 2. 建索引（bundle 根目錄 = 內含多個 bundle 子目錄的那一層）
#    索引格式版本變更時舊快取會被拒絕載入並提示重建，直接重跑這行即可
uv run yedai index /path/to/your/bundles -c config.local.yaml

# 3. 查詢
uv run yedai search "XTR-05 的 particle 問題" -c config.local.yaml -m C

# 4. 三模式並排 + 重疊度
uv run yedai compare "XTR-05 的 particle 問題" -c config.local.yaml

# 5. 批次跑一整份查詢清單
uv run yedai compare -f queries.txt -c config.local.yaml

# 6. 產出可分享的去識別化報告
uv run yedai report -o report.json -c config.local.yaml
```

## HTTP API

```bash
uv run yedai serve -c config.local.yaml
# Swagger： http://127.0.0.1:8000/docs
# ReDoc：   http://127.0.0.1:8000/redoc
```

每個端點的**參數、回應欄位與錯誤碼都在 OpenAPI schema 裡**，兩個文件頁都讀得到，
不必翻原始碼。

功能端點都在 **`/v1`** 之下，依用途分成五類；`/healthz` 與 `/version` 不帶版本前綴，
因為它們描述的是服務本身而非 API 契約——監控與部署不該因 API 改版而失效。

| 分類 | 端點 | 用途 |
|---|---|---|
| **retrieval**<br>找到 concept | `GET /v1/search?q=&mode=&k=` | `mode` 為 `A`/`B`/`C` 或 `compare`。**只回菜單，不回內容** |
| | `GET /v1/grep` | **限定範圍**的字面／正則搜尋；未給範圍會被拒絕 |
| **content**<br>取得內容 | `GET /v1/concept/{concept_id}` | 單一 concept 全文（`raw` + `frontmatter` + `sections` + `figures`） |
| | `POST /v1/concepts` | 批次取全文（最多 50 筆，部分成功語意） |
| | `GET /v1/concept/{concept_id}/asset?path=` | 下載該 concept 引用的資產，預設 inline |
| **graph**<br>沿關聯導航 | `GET /v1/concept/{concept_id}/neighbors` | 展開 1~2 跳；`direction=in` 回傳「誰指向我」 |
| **telemetry**<br>量測與回饋 | `POST /v1/feedback` | 記錄點選；`query_id` 來自 `/v1/search` 回應 |
| | `GET /v1/report` | 去識別化統計報告 |
| **ops**<br>服務與語料狀態 | `GET /v1/stats` | 語料統計與索引狀態 |
| | `GET /healthz` | 健康檢查（不版本化） |
| | `GET /version` | 套件／API／索引格式版本（不版本化） |

前三類正好對應建議流程（search → get → neighbors），所以分組本身就是流程說明。
`telemetry` 刻意獨立——那兩個端點服務的是 A/B/C 消融實驗，不是日常檢索，agent 不需要呼叫。

**逐端點的參數、運作步驟、回應結構與錯誤碼見 [docs/api.md](docs/api.md)。**

`GET /version` 會同時回報「本程式支援的索引格式」與「目前載入索引的格式」，
兩者無對應關係；「支援 v3、載入的是 v2」正是最需要一眼看出的除錯情境。

## 給 Agent 用（MCP）

```bash
uv run yedai mcp -c config.local.yaml
```

claude-agent-sdk / Claude Code 的設定：

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

六個工具：`search`、`get_concept`、`get_concepts`、`neighbors`、`grep`、`stats`。
細節與常見誤用見 [docs/agent-tools.md](docs/agent-tools.md)。

### 建議流程

```
search（縮範圍、取菜單）
  └─ 挑 3~7 筆
       └─ get_concepts（批次取全文）
            ├─ neighbors（沿 related 展開，尤其 direction=in）
            └─ grep（在 search 給的 bundle_id 範圍內做字面搜尋）
```

### 兩個刻意的限制

**`search` 不回內容，只回菜單。** 讓 agent 自己決定讀哪幾份全文，才保得住
「agent 當 reranker、讀完整文件」這個讓小規模 agentic file search 效果好的性質。
直接把 chunk 塞給 agent 就退化成一般 RAG 了。

**`grep` 必須先有範圍。** 允許無範圍搜尋等於留一條繞過檢索層的退路——agent 會用它，
然後我們回到「掃三十 GB、拿回三百條命中、無從分流」的原點。範圍取自 `search` 結果的 `bundle_id`。

### 圖怎麼拿

`/concept/{id}` 回傳的 `assets` 陣列可以直接餵給資產端點：

```bash
curl "$B/v1/concept/$CID" | jq -r '.assets[]' \
  | while read p; do curl -sO "$B/v1/concept/$CID/asset?path=$(jq -rn --arg x "$p" '$x|@uri')"; done
```

路徑以**該 concept 檔案所在目錄**為基準解析，和 markdown 相對連結、`## Citations`
的寫法完全一致，不用轉換。對 YED 語料這很重要——wafer map 與缺陷影像是證據本身，
文字圖說只是包裝。

安全上有三道約束：不接受絕對路徑與 `..`、必須在該 bundle 根目錄之下、
且必須在 `asset_dirs`（預設 `_assets`）之下。違反者一律 403。

### 全文的兩個性質

`raw` 是完整檔案內容，可直接餵進 LLM context；`sections` 是切好的
`{heading, text}`，適合「只讀根因段落」這類針對性取用。

全文是**請求時從磁碟讀**，不存在索引裡——所以改一個 `.md` 內容立即反映。
但**新增/刪除 concept 或改 `related` 仍要重建索引**，否則檢索排名與關聯圖還是舊的。

---

## 資料安全

這是本工具的設計前提，不是附註：

- **真實語料永不進版控** — `data/`、`bundles/`、`corpus/` 已被 gitignore
- **完整查詢日誌不可外流** — 含查詢原文與 concept id，寫在 `logs/`（gitignore）
- **只有 `yedai report` 的輸出設計為可分享** — 零語料內容，只有數值、分佈與設定參數

最後一點由測試強制守住，不靠慣例：`tests/test_telemetry.py::test_report_leaks_no_corpus_content`
會斷言報告序列化後不含任何查詢原文、concept 標題、描述或實體名稱。

如果報告洩漏了內容，你就不能把它帶出公司，這次資料收集對外部討論等於沒發生。

---

## 怎麼讀報告

最關鍵的單一指標是 **`mode_overlap`**：

```json
"mode_overlap": {
  "A-B": { "jaccard": { "median": 0.11 } },
  "B-C": { "jaccard": { "median": 0.67 } }
}
```

- `A-B` 的 jaccard **低** → 斷詞層有實際作用，識別碼必須保護
- `A-B` 的 jaccard **接近 1** → 天真斷詞已經夠好，後面所有機制都是過度設計
- `B-C` 的 jaccard **低** → 字典帶來額外資訊，值得投資維護
- `B-C` 的 jaccard **接近 1** → 停在斷詞層就好，別維護字典

其次看 `entities.by_type`——**不要只看全域的 `dictionary_coverage`**。

字典對不同類型的作用是相反的：對缺陷名（`微粒`、`刮傷`）它是**唯一來源**，
因為一般詞沒有結構可讓正則辨識，沒有字典那條腿就歸零；對機台識別碼它只是
**擋掉 regex 誤圈的白名單**，沒有字典只是精確度差一點。

全域比例把這兩者平均成一個中間值，於是「fallback 佔 60%」推不出任何結論——
拆開之後才分得出那 60% 是集中在無所謂的類型，還是集中在字典本該覆蓋的類型。

`experiment_params` 記錄了該次使用的所有參數——沒有它，任何數字都不可重現。

---

## 已知的調參旋鈕

- **識別碼正則過寬**：預設樣式包含空白分隔形式（`TEL 05`），會誤圈 `slide 005`、`page 12`
  這類詞組。漏抓比誤抓危險（會讓模式 B/C 被低估、導出錯誤結論），所以預設偏向recall。
  誤圈量會顯示在報告的 `from_regex_fallback`，整份清單可用 `identifier_patterns` 覆寫。
- **父子層級展開有代價**：`aepol1#pm1` 會同時產生腔體層與機台層詞元，讓「查機台」
  命中只寫到腔體的文件。代價是機台層詞元變高頻、鑑別力下降——這部分由 BM25 的 idf
  自動吸收，不需調參，但若日後發現機台層查詢過於發散，這裡是第一個該看的地方。
- **BM25F 欄位權重是猜的**（title 3.0 / description 2.0 / body 1.0），首批真實數據回來後應調整。
- **融合權重**預設 `lexical 0.4 / entity 0.6`，偏向實體腿。
- **中文用 unigram + bigram**，不依賴 jieba——領域專有詞不在通用詞典裡，jieba 會切錯且錯法不可預測。

---

## 合成語料

開發者無法取得真實語料（公司機密），因此附一份格式相符的合成產生器供程式驗證：

```bash
uv run yedai gen-synthetic .synthetic -n 30 -s 42
```

> ⚠️ **合成資料僅供驗證程式正確性。**
> 它的詞頻分佈、識別碼密度、模板多樣性都是編造的，
> **不得用於調整任何參數，也不得用於推論任何檢索效果數字。**
> 所有效果結論必須來自你在真實語料上跑出的報告。

## 測試

```bash
uv run pytest
```

---

## 這不做什麼

刻意不做，因為它是對照組：向量檢索、embedding、reranker、issue family、
多層導航、graph DB。這些要不要做，由這支工具產出的數據決定。
