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

## 安裝

```bash
uv sync
```

## 指向你的真實語料

```bash
# 1. 準備設定
cp config.example.yaml config.local.yaml     # config.local.yaml 已被 gitignore
cp dictionary.example.yaml dictionary.local.yaml   # 填入你的機台/製程/缺陷字典

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
# 互動式文件： http://127.0.0.1:8000/docs
```

| 端點 | 用途 |
|---|---|
| `GET /search?q=&mode=&k=` | `mode` 為 `A`/`B`/`C` 或 `compare`（三模式並排）。**只回 header 菜單，不回內容** |
| `GET /concept/{concept_id}` | 取回單一 concept 全文（`raw` + `frontmatter` + `sections` + `figures`） |
| `POST /feedback` | 記錄點選；`query_id` 來自 `/search` 回應 |
| `GET /stats` | 語料統計與索引狀態 |
| `GET /report` | 去識別化統計報告 |
| `GET /healthz` | 健康檢查 |

### Agent 的使用流程

```
query → /search  → header 菜單（index.md 行格式）
                 → agent 自行挑 3~7 筆
                 → /concept/{id} 逐一取全文
                 → 作答
```

**`/search` 刻意不回傳內容片段。** 回一份菜單、讓 agent 自己決定讀哪幾份全文，
才保得住「agent 當 reranker、讀完整文件」這個讓小規模 agentic file search 效果好的性質。
直接把 chunk 塞給 agent 就退化成一般 RAG 了。

`/concept/{id}` 的全文是**請求時從磁碟讀**，不存在索引裡——所以改一個 `.md`
內容立即反映，不必重建索引（但新增/刪除 concept 仍要重建，索引才知道它存在）。

`raw` 是完整檔案內容，可直接餵進 LLM context；`sections` 是切好的
`{heading, text}`，適合「只讀根因段落」這類針對性取用。

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

其次看 `entities.dictionary_coverage`：字典命中 vs regex fallback 的比例，
直接告訴你字典的覆蓋率缺口有多大。

`experiment_params` 記錄了該次使用的所有參數——沒有它，任何數字都不可重現。

---

## 已知的調參旋鈕

- **識別碼正則過寬**：預設樣式包含空白分隔形式（`TEL 05`），會誤圈 `slide 005`、`page 12`
  這類詞組。漏抓比誤抓危險（會讓模式 B/C 被低估、導出錯誤結論），所以預設偏向recall。
  誤圈量會顯示在報告的 `from_regex_fallback`，整份清單可用 `identifier_patterns` 覆寫。
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
