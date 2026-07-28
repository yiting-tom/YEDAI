# 建立索引

索引是**衍生物**，隨時可以砍掉重建。原始 OKF 檔案才是真相。

---

## 1. 語料目錄長什麼樣

`yedai index` 接受的是**bundle 根目錄**——內含多個 bundle 子目錄的那一層：

```
/path/to/bundles/            ← 指這裡
├── yed-deck-001/
│   ├── manifest.json
│   └── okf/
│       ├── _assets/slide_001.png     ← 不解析
│       ├── summary.md                ← 解析為 bundle 摘要，不算 concept
│       ├── log.md                    ← 略過
│       ├── index.md                  ← 略過
│       ├── concept-a.md              ← concept
│       └── concept-b.md
├── yed-deck-002/
└── …
```

解析行為刻意寬鬆，因為真實語料一定有不合格的檔案：

| 情況 | 行為 |
|---|---|
| 沒有 `manifest.json` | 用目錄名稱當 `bundle_id`，繼續 |
| `manifest.json` 不是合法 JSON | 記一則 warning，繼續解析 concept |
| frontmatter 沒有 `---` 分隔線 | 支援（`summary.md` 的格式） |
| 完全沒有 frontmatter | 全文當 body，繼續 |
| frontmatter 缺 `id` | 用 `path:<相對路徑>` 當 `concept_id` |
| frontmatter 有未定義欄位 | 保留在 `extra`，不丟棄 |
| 單一檔案解析爆炸 | 進 `skipped` 清單，**不中斷整批** |
| 沒有 `okf/` 這層、md 直接放在 bundle 根 | 支援 |
| 根目錄本身就是單一 bundle | 支援 |

若根目錄下有多個 bundle 用了同一個 `concept_id`，**保留先出現者**並記入 warnings。
靜默覆蓋會讓 `/concept/{id}` 拿到另一份文件。

---

## 2. 設定

```bash
cp config.example.yaml config.local.yaml     # 已被 gitignore
```

需要改的通常只有三行：

```yaml
dictionary_path: dictionary.local.yaml   # 你的機台 / 製程 / 缺陷字典
index_path: .index/yedai.pkl
log_dir: logs
```

其餘參數的意義見 `config.example.yaml` 的註解，或 [data-flow.md](./data-flow.md#計分)。

### 實體字典（選填但強烈建議）

```yaml
tool_id:
  - canonical: TEL-05
    aliases: [五號機]          # 只有「拼法不同」的別名要寫
  - canonical: TEL-06
defect_code:
  - canonical: PARTICLE
    aliases: [particle, 微粒, 顆粒]
flow_id:
  - FL-A100                    # 條目也可以直接是字串
```

比對前所有別名都會被正規化（移除 `-` `_` 空白、轉大寫），所以
`TEL-05` / `TEL05` / `TEL_05` **不必**各自列出。需要列進 `aliases` 的只有
縮寫、中文俗稱、以及空白分隔的寫法。

沒有字典也能跑——模式 C 會退化成純 regex 抽取，報告裡的
`entities.by_type` 會直接告訴你每一類的覆蓋率缺口有多大。

### 直接吃 MES 匯出的 CSV

真實字典多半是 CSV 而不是 YAML。要求維護者手工轉檔的結果就是字典會過期，
所以 CSV 可以直接宣告為來源，與 YAML 並存：

```yaml
entity_sources:
  - type: tool_id
    path: tools.local.csv
    schema: id_only
    child_type: chamber_id      # 選填，預設就是 chamber_id
  - type: defect_code
    path: defects.local.csv
    schema: module_code_name
```

| schema | 欄位 | 說明 |
|---|---|---|
| `id_only` | 單欄 | 值本身即正規名稱。含 `#` 的列自動歸入 `child_type`——機台與腔體同表，以 `#` 區分 |
| `module_code_name` | `Module, defect code, defect name` | `code` 全域唯一為正規名稱，`name` 是別名，`Module` 只是中繼資料不進識別 |

標頭列可有可無，會依已知欄名自動略過。欄位數不符會**當場報錯並指出檔名與列號**——
靜默略過畸形列會產出一份看起來正常、實則有洞的字典，而那種洞在報告上看不出來。

`defect name` 若同格中英並存（`Pattern Collapse 圖案倒塌`），兩種語言都會被註冊成別名，
所以使用者只打其中一種也命中。多詞英文名稱不會被拆散——否則任何提到 `pattern`
的文件都會被判定含有該缺陷。

> ⚠️ 真實的機台與缺陷清單本身就是敏感資料。請命名為 `*.local.csv`，
> 那個樣式已被 gitignore，而本 repo 是公開的。

---

## 3. 建索引

```bash
uv run yedai index /path/to/bundles -c config.local.yaml
```

輸出：

```
            語料統計
┌────────────────────────┬──────┐
│ bundles                │   30 │
│ concepts               │  729 │
│ 平均 concept 字元數    │ 1616 │
│ 平均 figures / concept │ 6.46 │
│ 詞彙量（naive）        │  517 │
│ 詞彙量（protected）    │ 1310 │
│ 不重複實體             │  858 │
│   來自字典             │   81 │
│   來自 regex fallback  │  777 │
│ 懸空關聯               │    0 │
│ 解析失敗               │    0 │
│ 解析警告               │    0 │
└────────────────────────┴──────┘
```

### 這些數字怎麼看

| 數字 | 該注意什麼 |
|---|---|
| **解析失敗** | 應該是 0。不是 0 就去看下面列出的清單——那是語料品質的訊號 |
| **詞彙量 protected / naive** | 比值明顯 > 1 代表識別碼保護確實把大量識別碼從碎片還原成獨立詞元。接近 1 代表你的語料沒什麼識別碼，模式 B 大概不會有效果 |
| **來自字典 vs regex fallback** | fallback 佔比高 = 字典覆蓋率缺口大。但也可能是正則誤圈（見下方） |
| **懸空關聯** | `related` 指向語料中不存在的 concept 的筆數。以模型產出的 concept 來說，這個數字是語料品質的直接訊號——偏高代表生成階段的 id 對齊有問題。這些 id 不會被靜默丟棄，會出現在 `neighbors` 回應的 `dangling` |
| **平均 concept 字元數** | 遠低於預期表示解析可能吃掉了內容 |
| **type 分佈** | 若出現 `metric` / `Metric` / `量測項目` 這類同義不同寫，代表 type 詞彙需要受控 |

### 誤圈識別碼

預設正則刻意偏向 recall（含空白分隔形式如 `TEL 05`），因此會誤圈
`slide 005`、`page 12`、`figure 3` 這類詞組。

**漏抓比誤抓危險**：真實文件若寫成 `TEL 05` 而正則漏掉，模式 B/C 會被低估，
反而讓你導出「識別碼不重要」的錯誤結論。

誤圈量會顯示在 `from_regex_fallback`。若確認是噪音，覆寫整份清單：

```yaml
identifier_patterns:
  - 'cpt_[0-9A-Za-z]+'
  - '[A-Za-z]{2,6}[-_]\d{1,5}'
  # 只列你要的，這份清單會**完全取代**預設值
```

改了樣式必須重建索引（見下一節）。

### 驗證樣式涵蓋得了真實形狀

這是這支工具最容易靜默失效的地方，值得單獨一節。

模式 B 與 C 的全部效果都建立在「識別碼被當成一個整體」之上。但真實識別碼屬敏感資料、
不能進版控，所以樣式一直**沒有被真實形狀驗證過**——而合成語料產出的 id 剛好符合樣式，
於是測試全綠，程式在跟自己對答案。

作法是把樣本留在本機，只讓「涵蓋與否」這個判定進到把關流程：

```bash
cp identifier-samples.example.yaml identifier-samples.local.yaml
# 填入真實形狀（每個類型三到五筆，涵蓋形狀的變體即可，不必窮舉）
uv run yedai check-formats -c config.local.yaml
```

判定分四種，而不是三種——「沒被圈成識別碼」和「被切碎」的後果差很多：

| 判定 | 意義 | 是否通過 |
|---|---|---|
| 識別碼 | 整段被圈成單一識別碼 | ✅ |
| **完整詞元** | 沒被圈成識別碼，但斷詞後仍是單一完整詞元 | ✅ 通過但提示 |
| **咬錯** | 正則從中間比對進去，憑空產生一個錯的識別碼 | ❌ |
| 碎裂 | 沒被圈起來，斷詞後也碎了 | ❌ |

**「完整詞元」是通過的**。`A16` 沒有對應樣式，但模式 A 會把它切成 `a` + `16`、
模式 B 不會——鑑別力的差異仍在，檢索不受損。唯一的差別是它不會進入實體空間，
所以模式 C 看不到它；若該類型有字典，字典的字面掃描會補上這一塊。

**「咬錯」是最危險的一種**，比完全沒抓到更糟。舊的作業序號樣式缺了前置 `\b`，
於是 `10234.000` 從第二個字元咬進去，產出 `1` + `ID:0234.000`——一個語料裡
根本不存在的識別碼。它不會報錯，只會安靜地污染詞空間。

把「完整詞元」和「咬錯」混為一談會讓這個工具喊太多狼，真正該修的那個就被淹掉了。

有未涵蓋樣本時指令以非零狀態碼結束，可以直接接進 CI。

> ⚠️ 樣本就是真實識別碼。`*-samples.local.yaml` 已被 gitignore，而這個 repo 是公開的。

### 還沒有樣本的類型

`part6` / `part7`、`route`、`stage`、`subroute`、`layer`、`recipe`、`drbl`
目前**只有名稱與意義，沒有字元組成**，因此沒有對應的樣式，也沒有樣本。

這些類型在 `check-formats` 裡會列為「無樣本」。那不是通過——是我們不知道現有樣式
對它們是否有效。憑猜測的形狀寫樣式，正是這一整套驗證機制要根除的失效模式。

---

## 4. 何時必須重建索引

索引簽章 = `hash(欄位清單 + identifier_patterns + entity_field_weights + 字典指紋)`
（`Config.index_signature`，`config.py`）。簽章不符時載入會直接報錯並要你重建。

### 必須重建

| 變更 | 為什麼 |
|---|---|
| 新增 / 刪除 / 搬移 concept 或 bundle | 索引不知道它存在 |
| **編輯 concept 內容** | ⚠️ 見下方說明 |
| `identifier_patterns` | 斷詞結果改變 |
| `entity_field_weights` | 實體權重在建索引時就寫死了 |
| 修改 `related` 欄位 | 關聯邊在建索引時算好，`neighbors` 會拿到舊的圖 |
| 換字典 / 改字典內容 | 實體倒排索引改變 |
| **改 `entity_sources` 指向的 CSV 內容** | 同上——字典指紋涵蓋 CSV 條目 |
| 升級 `INDEX_FORMAT_VERSION` | 索引結構改變，舊檔會被拒絕 |

目前的索引格式版本是 **6**（v2 加入 `by_id` / `bundle_roots`，v3 加入關聯邊，
v4 讓 `#` 成為識別碼的一部分並加入父子層級展開，v5 加入 op no / lot / wafer 樣式
並讓 `#` 的父層可含 `-`，v6 修正作業序號的邊界與位數、移除 tech 樣式）。
從舊版升上來時載入會被拒絕並提示重建，直接重跑 `yedai index` 即可。

`entity_sources` 的**路徑**本身不進簽章——字典指紋是由實際載入的條目算出來的，
已經涵蓋 CSV 內容。換個檔名但內容相同不該白白失效一次索引。

### 不必重建（查詢期才套用）

`k1`、`b`、`field_weights`、`fusion_lexical` / `fusion_entity`、`require_entities`、
`top_k`、`seed`、`asset_dirs`。後者是**服務期政策**（資產端點的安全白名單），
改一個安全設定不該迫使整份語料重建索引。**所以調權重做敏感度測試不需要重建索引**，改 config 直接重跑查詢即可。

### ⚠️ 編輯內容的不同步陷阱

`/concept/{id}` 的全文是請求時從磁碟讀的，但**詞頻統計留在索引裡**。所以編輯一個
`.md` 之後：

```
/concept/{id} 的內容  →  ✅ 立即反映
/search 的排名        →  ❌ 仍是舊內容算出來的
```

這在 debug 時特別容易誤導——你改了文件、`/concept` 看起來對了，但排名沒動。
**編輯內容後請重建索引。**

---

## 5. 疑難排解

| 訊息 | 原因與處置 |
|---|---|
| `index not found: … 請先執行 yedai index` | 還沒建索引，或 `index_path` 指錯 |
| `索引快取與目前設定不相容（斷詞樣式或字典已變更）` | 簽章不符 → 重建 |
| `index format mismatch at … 請重建索引` | 索引格式版本升級 → 重建 |
| `entity dictionary not found: …` | `dictionary_path` 路徑錯。留空可完全不用字典 |
| `找不到 bundle 根目錄` | 路徑錯，或指到了單一 bundle 的 `okf/` 而非其上層 |
| HTTP 503 | 服務啟動時索引載入失敗。看 `/healthz` 的 `error` 欄位 |
| HTTP 410（取全文時） | id 在索引裡但檔案已不在 → 語料變動過，重建索引 |

---

## 6. 規模

目前設計點是 30–100 個 bundle，全部放在記憶體。實測值：

| 語料 | concepts | 建索引 | 索引檔 |
|---|---|---|---|
| 合成 30 bundle | 729 | 數秒 | 數 MB |

預期成長到 10 萬個 bundle（約 220 萬 concept、30–40 GB markdown）時，
**這套記憶體索引不會是最終方案**——但那時架構本來就會換（向量庫 + 實體 SQL 索引）。
本工具的任務是在換架構之前，先量出純關鍵字檢索的水位線。

有一件事已經為那個規模做對了：**全文不進索引**。否則 pickle 會膨脹到無法載入。
見 [data-flow.md](./data-flow.md#索引裡有什麼沒有什麼)。

---

## 7. 沒有真實語料時

```bash
uv run yedai gen-synthetic .synthetic -n 30 -s 42
uv run yedai index .synthetic -c config.local.yaml   # dictionary_path 指向 .synthetic/dictionary.yaml
```

> ⚠️ 合成語料**僅供驗證程式跑得通**。詞頻分佈、識別碼密度、模板多樣性全是編造的，
> **不得用於調整任何參數，也不得用於推論任何檢索效果數字。**
