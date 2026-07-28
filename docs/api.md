# API 參考

逐端點說明：參數、內部如何運作、回應結構、錯誤碼。

資料流的全貌見 [data-flow.md](./data-flow.md)；agent 該怎麼用見 [agent-tools.md](./agent-tools.md)。

```bash
uv run yedai serve -c config.local.yaml
# 互動式文件： http://127.0.0.1:8000/docs
```

---

## 總覽

功能端點都在 **`/v1`** 之下。`/healthz` 與 `/version` 不帶版本前綴——它們描述的是
服務本身而非 API 契約，監控與部署不該因 API 改版而失效。

| 分類 | 端點 | |
|---|---|---|
| **retrieval** | [`GET /v1/search`](#get-v1search) | 三模式檢索，只回菜單 |
| | [`GET /v1/grep`](#get-v1grep) | 限定範圍的字面／正則搜尋 |
| **content** | [`GET /v1/concept/{concept_id}`](#get-v1conceptconcept_id) | 單一 concept 全文 |
| | [`POST /v1/concepts`](#post-v1concepts) | 批次取全文 |
| | [`GET /v1/concept/{concept_id}/asset`](#get-v1conceptconcept_idasset) | 下載資產 |
| **graph** | [`GET /v1/concept/{concept_id}/neighbors`](#get-v1conceptconcept_idneighbors) | 沿 `related` 展開 |
| **telemetry** | [`POST /v1/feedback`](#post-v1feedback) | 記錄點選 |
| | [`GET /v1/report`](#get-v1report) | 去識別化統計報告 |
| **ops** | [`GET /v1/stats`](#get-v1stats) | 語料統計 |
| | [`GET /healthz`](#get-healthz) | 健康檢查 |
| | [`GET /version`](#get-version) | 版本資訊 |

---

## 通用約定

### 錯誤格式

所有錯誤回應都是 `{"detail": "<可讀訊息>"}`。訊息刻意寫成可操作的形式——
例如無範圍的 `grep` 會直接告訴你「先用 search 取得 bundle_id」。

### 狀態碼語意

| 碼 | 意義 | 何時出現 |
|---|---|---|
| `403` | 路徑違反約束 | 只有資產端點會回：逸出 bundle，或不在允許的資產目錄之下 |
| `404` | 查無此資源 | id 不存在、bundle 不存在 |
| `410` | **曾經存在，語料已變動** | concept 在索引裡但檔案已不在磁碟上 → 重建索引 |
| `422` | 參數驗證失敗 | 缺必填、超出範圍、列舉值不合法、無效正則、grep 未給範圍 |
| `500` | 索引中的路徑異常 | 索引被竄改或人工編輯出錯 |
| `503` | 索引未載入 | 啟動時載入失敗；看 `/healthz` 的 `error` 欄位 |

**`404` 與 `410` 刻意分開**：前者是 id 打錯，後者是索引過期。兩者需要的處置完全不同，
混為一談會讓你無從判斷該不該重建索引。

### 索引未載入時

除 `/healthz` 與 `/version` 外，所有端點回 `503`。那兩個端點刻意仍可運作——
它們的用途之一就是診斷載入失敗。

---

## retrieval

### `GET /v1/search`

三種消融模式的檢索。**只回摘要清單，不含內容**——由呼叫端決定讀哪幾份完整文件，
這保住了「agent 當 reranker、讀完整文件」的性質。

| 參數 | 位置 | 必填 | 預設 | 約束 |
|---|---|---|---|---|
| `q` | query | ✅ | — | 至少 1 字 |
| `mode` | query | | `compare` | `A` / `B` / `C` / `compare` |
| `k` | query | | 設定的 `top_k`（10） | 1–100 |

**運作**

1. pydantic 驗證參數（不合 → `422`）
2. `mode=compare` 時對同一查詢跑三次檢索；否則只跑指定模式
3. 各模式的斷詞與計分：
   - **A** 天真斷詞 → `XTR-05` 碎成 `xtr` + `05` → naive 空間 BM25F
   - **B** 識別碼保護斷詞 → `ID:XTR05` 單一詞元 → protected 空間 BM25F
   - **C** = B 的詞彙腿 + 實體字典匹配的實體腿，兩腿正規化後線性融合（預設 0.4 / 0.6）
4. 各自 `sort(-score)` 取 top-k，用 doc 位置取回 metadata
5. compare 模式另計 A-B / A-C / B-C 的 Jaccard 與 Kendall tau
6. `display_order` 以 seeded RNG 洗牌，降低並排呈現時的位置偏差
7. 整筆寫入 `logs/queries.jsonl`，回傳 `query_id`

計分公式見 [data-flow.md](./data-flow.md#計分)。

**回應**

```
query_id            供 /v1/feedback 關聯
query, requested_mode, k
display_order       ["C","A","B"]  compare 模式才有
entities[]          {type, canonical, raw, source}   source ∈ dict|regex
results{A|B|C}      {mode, candidates, hits[]}
  hits[]            {rank, concept_id, bundle_id, type, title, description,
                     path, score, lexical_score, entity_score, index_line}
overlaps[]          {pair, jaccard, kendall_tau, common}
```

`lexical_score` / `entity_score` 分開回傳，才看得出模式 C 的兩條腿各自貢獻多少——
那正是這套工具存在的目的。`kendall_tau` 在共同項目少於兩個時為 `null`。

`index_line` 的格式與 bundle 內 `index.md` 的行格式相同，agent 的既有讀法可直接沿用。

**狀態碼** `200` · `422` · `503`

```bash
curl -s "$B/v1/search?q=XTR-05%20PARTICLE&mode=compare&k=10"
```

---

### `GET /v1/grep`

在**已限定的範圍內**做字面或正則搜尋。

| 參數 | 位置 | 必填 | 預設 | 約束 |
|---|---|---|---|---|
| `pattern` | query | ✅ | — | 至少 1 字 |
| `bundle_id` | query | ⚠️ | `[]` | 可重複 |
| `concept_id` | query | ⚠️ | `[]` | 可重複 |
| `regex` | query | | `false` | |
| `ignore_case` | query | | `false` | |
| `max_results` | query | | 100 | 1–1000 |

⚠️ **`bundle_id` 與 `concept_id` 至少提供其一**，否則 `422`。

這不是效能保護，是設計意圖的強制執行：允許無範圍 grep 等於留一條繞過檢索層的退路，
呼叫端會用它，然後回到「掃三十 GB、拿回三百條命中、無從分流」的原點。
錯誤訊息直接指引「先用 search 取得 bundle_id」。

**運作**

1. 範圍為空 → `422`；範圍指向不存在的 bundle/concept → `404`
2. 編譯比對器：預設字面子字串；`regex=true` 才編譯正則（無法編譯 → `422`）
3. 展開範圍為 concept 清單（bundle 展開為其所有 concept），去重保序
4. 逐檔解析路徑並讀磁碟；檔案已移除則計入 `files_skipped` 並繼續，不中斷整批
5. 逐行比對，達到 `max_results` 即停並標記 `truncated`

正則預設關閉：呼叫端提供的正則可能觸發災難性回溯，而 Python 的 `re` 沒有執行時間上限。

**注意**：搜尋的是**整份原始檔案**，包含 frontmatter。所以 `figures[].title` 這類
frontmatter 內容也會命中。

**回應**

```
pattern, regex, ignore_case
scope               {bundle_ids[], concept_ids[]}   回聲，確認範圍被正確解讀
files_searched      實際讀取的檔案數
files_skipped       檔案已移除而略過的數量
max_results, truncated
results[]           {concept_id, bundle_id, type, title, path, line, text}
```

`line` 為 1-based 行號。

**狀態碼** `200` · `404`（未知範圍）· `422`（無範圍／無效正則）· `503`

```bash
curl -s "$B/v1/grep?pattern=PARTICLE&bundle_id=$BID&max_results=20"
```

---

## content

### `GET /v1/concept/{concept_id}`

取回單一 concept 的完整內容。

| 參數 | 位置 | 必填 |
|---|---|---|
| `concept_id` | path | ✅ |

**運作**

1. `index.by_id` 查找（不存在 → `404`）
2. 以 `bundle_roots[bundle_id]` 接上 `DocMeta.path` 組出絕對路徑
3. 驗證解析後的路徑位於該 bundle 根目錄之下（不符 → `500`）
4. 檔案不存在 → `410`（**曾經存在、語料已變動**，訊息指示重建索引）
5. 讀磁碟，呼叫**與建索引時相同的解析路徑**，確保結構一致
6. 另解析一次 frontmatter，回傳完整的原始字典

**全文於請求時從磁碟讀，不存在索引裡。** 220 萬 concept × 300 行約 30–40 GB，
塞進 pickle 會讓索引無法載入；而且檔案是唯一真相，改一個 `.md` 內容立即反映。

⚠️ 但**檢索排名不會**——詞頻統計留在索引裡。詳見 [indexing.md](./indexing.md#4-何時必須重建索引)。

**回應**

```
concept_id, bundle_id, type, title, slug, description, path, index_line
confidence, timestamp, resource, provenance, subpath, content_hash, model, generated
tags[], related[], assets[]
figures[]           {file_id, type, title, description, key_points[]}
sections[]          {index, heading, text}      依 `## ` 切分
frontmatter{}       解析後的完整 frontmatter
raw                 原始 markdown 全文（含 frontmatter），可直接餵進 LLM context
```

`raw` 與 `sections` 內容重疊是刻意的：兩者服務不同消費者，在單一 concept
（約 3k tokens）的尺度上，重複一份遠比逼每個呼叫端各自實作解析便宜。

**狀態碼** `200` · `404` · `410` · `422` · `500` · `503`

---

### `POST /v1/concepts`

批次取全文，**部分成功**語意。

```json
{"concept_ids": ["cpt_a", "cpt_b"], "include_raw": true}
```

| 欄位 | 必填 | 預設 | 約束 |
|---|---|---|---|
| `concept_ids` | ✅ | — | 1–50 筆 |
| `include_raw` | | `true` | |

**運作**

逐筆走與單筆相同的流程，**單一 id 失敗不影響其餘**。失敗者收進 `errors`：

| `reason` | 意義 | 處置 |
|---|---|---|
| `not_found` | id 不在索引中 | id 打錯，或屬於另一份語料 |
| `file_missing` | 索引裡有、磁碟上沒有 | 語料變動過，重建索引 |
| `path_escape` | 路徑異常 | 索引被竄改 |

單一 id 失敗就讓整批失敗，會逼呼叫端退回逐筆呼叫，等於白做這個介面。
上限 50 筆——超過的話應該先縮範圍，而不是把整個 bundle 拉進 context。

`include_raw=false` 時不回 `raw`，只保留結構化欄位。只需要標題與章節結構時用它，
可省下大量 context。

**回應**

```
requested           請求筆數
returned            成功筆數
concepts[]          與單筆端點相同的結構，順序與請求一致
errors[]            {concept_id, reason, detail}
```

**部分失敗仍回 `200`** —— 這是設計，不是疏漏。

**狀態碼** `200` · `422`（空清單／超過 50 筆）· `503`

---

### `GET /v1/concept/{concept_id}/asset`

下載該 concept 引用的資產（`_assets/slide_xxx.png` 等）。

| 參數 | 位置 | 必填 | 預設 |
|---|---|---|---|
| `concept_id` | path | ✅ | — |
| `path` | query | ✅ | — |
| `download` | query | | `false` |

`path` 直接使用 `/v1/concept/{concept_id}` 回傳的 **`assets` 陣列中的值**——它以該 concept
檔案所在目錄為基準解析，與 markdown 相對連結、`## Citations` 的寫法完全一致，
不需要任何轉換。

**運作 —— 三道防線**

這是整個 API 裡**唯一路徑直接來自呼叫端**的地方（`concept_id` 有索引可查，
路徑是系統自己組的），所以路徑穿越在這裡是實際風險。

| 防線 | 擋什麼 | 性質 |
|---|---|---|
| 1 早期拒絕 | 空路徑、絕對路徑、`..` 片段、`C:/` 前綴 | 便宜，不碰檔案系統 |
| 2 容器檢查 | 解析後路徑逸出 bundle 根目錄（`resolve()` 已展開 symlink） | **安全邊界** |
| 3 目錄白名單 | 不在 `asset_dirs`（預設 `_assets`）之下的檔案 | 縱深防禦 |

沒有第 3 道，這個端點會退化成「讀取 bundle 內任意檔案」的泛用介面。
`asset_dirs` 可由設定覆寫，且**不進索引簽章**——改一個安全設定不該迫使重建索引。

通過後：以副檔名判定 media type（不做內容嗅探，未知退回 `application/octet-stream`），
串流回傳。

**回應**

二進位檔案內容。標頭：

```
content-type:        依副檔名判定
content-disposition: inline（預設）或 attachment（download=true）
                     檔名以 RFC 5987 的 filename* 編碼，中文檔名不會破壞標頭
accept-ranges, etag, last-modified   由檔案回應自動附帶
```

**狀態碼** `200` · `403`（違反約束）· `404`（concept 或檔案不存在）· `422`（缺 `path`）· `503`

```bash
curl -s "$B/v1/concept/$CID" | jq -r '.assets[]' \
  | while read p; do curl -sO "$B/v1/concept/$CID/asset?path=$(jq -rn --arg x "$p" '$x|@uri')"; done
```

---

## graph

### `GET /v1/concept/{concept_id}/neighbors`

沿 `related` 展開關聯。

| 參數 | 位置 | 必填 | 預設 | 約束 |
|---|---|---|---|---|
| `concept_id` | path | ✅ | — | |
| `depth` | query | | `1` | 1–2 |
| `direction` | query | | `both` | `out` / `in` / `both` |

**`direction=in` 是這個端點最有價值的部分**——「還有哪些文件引用了這個概念」
是呼叫端自己拼不出來的資訊，而排查復發問題時正好需要它。

**運作**

1. 起點不存在 → `404`；`depth` 或 `direction` 不合 → `422`
2. 自起點 BFS 逐跳擴散，走 `related_out` / `related_in`（依 `direction`）
3. 排除起點自身與已訪節點，每筆記錄 `depth` 與 `via`（從誰跳過來）
4. 該起點的懸空引用單獨列在 `dangling`

**關聯邊在建索引時就算好。** 出向直接來自 frontmatter 的 `related`；入向需要等
全部 concept 掃完才能算——否則前向引用會被誤判成懸空。

深度上限 2：再深就是圖查詢，且高連通度語料上回應會爆掉。

**回應**

```
concept_id, depth, direction        回聲
neighbors[]   {concept_id, bundle_id, type, title, description, path,
               index_line, depth, direction, via}
dangling[]    `related` 指向但語料中不存在的 id
```

`dangling` 單獨列出而非靜默丟棄——以模型產出的 concept 來說，這是語料品質的直接訊號。
語料層級的總數在 `/v1/stats` 的 `dangling_related`。

回傳同樣是**摘要清單**，要內容請再呼叫 `/v1/concepts`。

**狀態碼** `200` · `404` · `422` · `503`

---

## telemetry

這一組服務的是 **A/B/C 消融實驗**，不是日常檢索——agent 不需要呼叫。

### `POST /v1/feedback`

記錄點選，作為隱性相關性標註。

```json
{"query_id": "…", "concept_id": "cpt_…", "rank": 1, "mode": "C", "action": "click"}
```

| 欄位 | 必填 | 預設 | 約束 |
|---|---|---|---|
| `query_id` | ✅ | — | 來自 `/v1/search` 回應 |
| `concept_id` | ✅ | — | |
| `rank` | ✅ | — | ≥ 1 |
| `mode` | ✅ | — | `A` / `B` / `C` |
| `action` | | `click` | |

**運作**：掃 `logs/queries.jsonl` 驗證 `query_id` 存在（不存在 → `404`，
因為無法關聯的回饋沒有分析價值），再追加一行到 `logs/feedback.jsonl`。

**狀態碼** `200` · `404` · `422` · `503`

---

### `GET /v1/report`

去識別化統計報告。**無參數。**

**運作**：讀 `logs/queries.jsonl` + `logs/feedback.jsonl` + 索引統計，聚合成純數值報告。

> **這份輸出設計為可外流。** 不含任何查詢原文、concept 標題、描述、路徑或實體名稱——
> 只有數量、比例、分佈與設定參數。由測試強制守住：
> `tests/test_telemetry.py::test_report_leaks_no_corpus_content` 會斷言報告序列化後
> 不含任何語料內容。

**回應**

```
report_version, generated_at, note
corpus{}            bundles / concepts / 平均長度 / 兩套詞彙量 / 詞彙量比值
                    / distinct_types / type_size_distribution / parse_skipped
entities{}          distinct_entities / from_dictionary / from_regex_fallback
                    / dictionary_coverage
queries{}           總數 / 長度分佈 / 含實體比例 / 每查詢實體數分佈
                    / 查詢實體的 dict vs regex 來源
modes{A|B|C}        queries / zero_result_rate / hit_count_distribution
                    / top_score_distribution
mode_overlap{}      A-B / A-C / B-C 各自的 jaccard 與 kendall_tau 分佈
feedback{}          總數 / 點選排名分佈 / 各模式點選數
experiment_params{} 該次使用的全部參數——沒有它任何數字都不可重現
```

所有分佈都是 `{n, min, p25, median, p75, max, mean}`。

**最關鍵的欄位是 `mode_overlap`**：A-B 的 jaccard 接近 1 代表斷詞層沒有作用、
B-C 接近 1 代表字典不值得維護。判讀方式見 [README](../README.md#怎麼讀報告)。

無任何查詢紀錄時仍可產出，查詢相關指標為零或空。

**狀態碼** `200` · `503`

---

## ops

### `GET /v1/stats`

語料統計與索引狀態。**無參數。**

直接讀建索引時算好的 `CorpusStats`，不重新計算。

```
bundles, concepts, avg_concept_chars, avg_figures_per_concept
vocab_naive, vocab_protected                  兩套詞彙空間各自的詞彙量
entities_total / from_dictionary / from_regex_fallback
dangling_related                              懸空關聯總數
parse_skipped, parse_warnings
types{}                                       type → concept 數
index_signature
```

數字怎麼判讀見 [indexing.md](./indexing.md#這些數字怎麼看)。

**狀態碼** `200` · `503`

---

### `GET /healthz`

健康檢查。**不帶版本前綴**——監控探針不該因 API 從 v1 升到 v2 就失效。

```json
{"status": "ok", "index_loaded": true, "error": null}
```

索引載入失敗時 `index_loaded` 為 `false`，`error` 含例外型別與訊息。
**此端點本身永遠回 `200`**，即使索引未載入——否則就無從得知失敗原因。

---

### `GET /version`

版本資訊。**不帶版本前綴。**

```json
{
  "package": "0.1.0",
  "api": "v1",
  "index_format": 3,
  "index": {"format_version": 3, "signature": "3c0adccf2b4b9565"}
}
```

| 欄位 | 意義 |
|---|---|
| `package` | 套件版本 |
| `api` | API 版本（URL 前綴） |
| `index_format` | **本程式支援**的索引格式版本 |
| `index.format_version` | **目前載入索引**的格式版本 |
| `index.signature` | 索引簽章（斷詞樣式 + 欄位 + 字典指紋的雜湊） |

後兩者與 `index_format` 刻意分開——兩者無對應關係，而「服務支援 v3、載入的索引是 v2」
正是最需要一眼看出的除錯情境。

索引未載入時 `index` 為 `null`，但仍回 `200`——診斷載入失敗正是這個端點的用途之一。
