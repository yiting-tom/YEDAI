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

需要改的通常是字典路徑與**索引宣告**：

```yaml
dictionary_path: dictionary.local.yaml   # 你的機台 / 製程 / 缺陷字典
log_dir: logs

indexes:
  library:
    source: ./corpus/library
    path: .index/library.pkl
  heuristics:
    source: ./corpus/heuristics
    path: .index/heuristics.pkl
    depends_on: [library]     # library 是實體字典來源
    keep_identifiers: false   # 這一層的查詢裡識別碼是雜訊
    default_mode: D
    top_k: 5
  cases:
    source: ./corpus/cases
    path: .index/cases.pkl
    depends_on: [library]
```

其餘參數的意義見 `config.example.yaml` 的註解，或 [data-flow.md](./data-flow.md#計分)。

### 為什麼是多個索引，而不是一個索引加過濾條件

每個索引持有**完全獨立**的詞彙與實體統計：`df`、`avg_field_len`、實體 idf 都不共用。

混在一起時這些統計是全域的。持續累積的那一層（已結案）每長大一次，其他層的排名就
漂移一次——**沒有任何變更、沒有任何測試會紅，檢索品質卻退化了**。查詢時加 `--bundle`
之類的過濾解不了這件事：過濾只影響誰參與排序，碰不到 idf。

實測的量級：同一份文件、同樣的查詢，在另一層灌入 60 篇之後，BM25 分數從 0.50
掉到 0.027。文件本身一個字都沒改。

這條性質有回歸測試釘著：`tests/test_layers.py::test_growing_one_index_does_not_move_another`。

### 層要自己說明自己

`description` 與 `when_to_use` 不是註解，是**執行期資料**：它們會出現在 `/v1/stats`，
並且被組進 MCP `search` 工具的說明裡。工具說明是 agent 唯一的手冊——寫死一組例子
在別人的部署上就是錯的提示，所以那段文字從設定生成。

沒寫也能跑，但 agent 只能從索引名稱猜這層是什麼，而那是它最沒有把握的一種判斷。
`/v1/stats` 的 `indexes_without_description` 會列出漏寫的層。

`type` 幫不上忙：它是**每份文件**的類型（`case_investigation` / `meeting_minutes` /
`spec_definition` …），與「這層是什麼」是兩個正交的軸——同一層裡通常什麼型都有。

### 每層可以有自己的檢索設定

| 鍵 | 用途 |
|---|---|
| `source` / `path` | 語料來源與索引檔輸出（必填） |
| `description` | **這一層裝什麼。** 索引名稱是任意鍵，agent 只看得到那個字串 |
| `when_to_use` | **什麼情況下該查這一層。** 與 description 分開：前者說「這是什麼」，後者說「你什麼時候需要它」 |
| `collection` | 這一層的 qdrant collection。不宣告就沒有稠密腿，`D`/`E` 明確不可用 |
| `depends_on` | 這一層的實體字典來自哪一層。決定重建順序 |
| `keep_identifiers` | query 前處理。識別碼在案件層是主訊號，在敘述性語料是雜訊 |
| `default_mode` / `top_k` | 這一層的預設模式與深度 |
| `field_weights` / `entity_field_weights` | 覆寫全域欄位權重；未列出的欄位仍用全域值 |
| `fusion_lexical` / `fusion_entity` / `require_entities` | 覆寫模式 C 的融合設定 |

`keep_identifiers: false` 的差別在**計分之前**：查詢 `XTR-05 overlay` 進入該層時
會變成 `overlay`。帶著機台編號去查「這類問題怎麼追」，比對到的是一個跟問題無關的
字串。這也是為什麼分層不能退化成「同一個檢索器加過濾條件」——差異發生在過濾之前。

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
`entities.by_type` 會告訴你每一類的覆蓋率缺口有多大。

### 哪些類型的覆蓋率算得出來

實體類型多半只有字典能給。但有三種形狀本身就唯一決定了類型，字典外的實體也認得出來：

| 形狀 | 類型 | 父層 |
|---|---|---|
| `機台#腔體` | `chamber_id` | `tool_id` |
| `xxxxxx.00` | `lot` | `lot`（批底） |
| `xxxxxx.NN` | `wafer` | `lot`（批底） |
| `ddd.ddd` | `op_no` | 無（純數字不展開） |

其餘樣式（`XTR-05` 這類）的形狀被機台、製程、流程、料號共用，**刻意不宣告類型**——
猜一個填上去會讓覆蓋率拿到一個自信而錯誤的分母，那比沒有分母更難察覺。

因此 `dictionary_coverage` 只在**分母可測**時給值，否則為 `null`：

- **`chamber_id` / `wafer` / `op_no`** —— 每一次出現都必然被樣式圈到，比例是真的
- **`tool_id` / `lot`** —— 可以裸寫（`AEPOL1`、`AB1234`），分母只是下界，給 `null`
- **`defect_code` 等一般詞** —— 只有字典認得，分母恆等於分子，給 `null`

報告的 `entities.coverage_measurable_types` 會列出當次實際可測的類型。它由**當時那組
樣式**導出而非寫死——換掉 `identifier_patterns` 時，能不能算比例也跟著變。

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
uv run yedai index -c config.local.yaml                 # 全部，依 depends_on 順序
uv run yedai index -i cases -c config.local.yaml        # 只重建這一層
```

**順序不是裝飾。** 上游是下游的實體字典來源，反過來建會讓下游用到舊字典——
而那不會報錯，只會讓下游的實體腿對不上。

每層各自輸出一份統計：

```
       語料統計 — 索引 cases
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

### 為自訂樣式宣告類型

上面那種字串形式只換得到斷詞行為——命中會歸入 `unknown`，該類型的覆蓋率因此
沒有分母（見「哪些類型的覆蓋率算得出來」）。要連統計一起正確，改用 mapping：

```yaml
identifier_patterns:
  # ⚠️ 編造的例子。你的真實組成規則請寫進 config.local.yaml。
  - pattern: '\b[wxyz][a-z](?:aa|bb)[mn][1-9a-z]\b'
    type: widget_id
    shape_complete: true      # 該類型的每一次出現都被這條樣式圈到
  - pattern: '\bQQ\d#\d\b'
    type: widget_part
    parent_type: widget_id    # 層級展開後的父層是機台而不是腔體
  - 'cpt_[0-9A-Za-z]+'        # 字串形式仍然可用
```

| 欄位 | 意義 |
|---|---|
| `pattern` | 必填 |
| `type` | 形狀**唯一決定**的類型。形狀不決定類型時請留空，猜一個會產出自信而錯誤的分母 |
| `parent_type` | 層級展開後父層詞元的類型。不填則父層歸 `unknown` |
| `shape_complete` | 宣告該類型的每一次出現都被這條樣式圈到，其覆蓋率比例因此可算。不確定就別填 |

**敏感的組成規則請放進 `config.local.yaml`（已 gitignore）。** 這個 repo 是公開的，
而識別碼的完整字元集是廠內分類法，與 `0000.000` 這種形狀的敏感度不同。

這個機制的動機是一個真實的缺陷：某類識別碼的末位允許字母，而通用樣式只抓得到
數字結尾那種，於是**同一個實體單寫時不是識別碼、帶子層寫時是**。這種不一致不會報錯，
只會讓模式 B/C 在一部分實體上悄悄失效。

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

## 3b. taxonomy：一份刻意不進索引的資源

```yaml
taxonomy_path: taxonomy.local.yaml                    # defect → 判斷方法
defect_catalogue_path: defects.catalogue.local.yaml   # defect 全集，覆蓋率的分母
```

`taxonomy` 是每個 defect 一條的**判斷方法**：看到這種形貌，該往哪些 module 查、
依據什麼判準。取用方式是以 defect 為鍵取回那一條——`GET /v1/taxonomy/{defect}`，
或 MCP 的 `taxonomy` 工具。

### 為什麼它不是第四個索引

因為存取模式不同。其他三層是「文件集合，回傳 top-k」；這個是「一張對照表，
給我那一條」。

放進倒排索引會有兩個後果。第一，呼叫端拿到的是「最像的幾列」而不是「那一條」，
而且沒有任何訊號告訴它拿到的不是要的。第二，模型會拿著另一個 defect 的判斷方法
去解讀影像——**那比沒有方法更糟**，因為錯誤的方法看起來跟正確的一樣有條理。

所以查無條目一律回「無此條目」，不做任何近似比對。上游必須自己處理
「這個 defect 還沒有整理過方法」，而那是它該知道的事實。

### 條目是方法，不是答案

```yaml
DEFECT_ALPHA:
  category: pattern
  description: 這個 defect 在影像上長什麼樣（給看圖的模型當判斷依據）
  method: 怎麼從影像推出候選 module。寫成判準與排除法，不要寫成結論
  modules: [MODULE_ONE]   # 選填。多數條目只給方法不給清單
  notes: 只在方法本身有例外或前提時才寫
```

`modules` 一旦寫死，模型就不再看圖了。多數條目應該只給 `method`。

**方法的正確性無法靜態檢查**——一段判準寫得對不對，看它本身看不出來，只有用了
才知道。驗證要靠歷史結案回放：拿已結案的前半跑一遍，看產出的候選有沒有命中結案裡
工程師確認的 module。那是後續變更的範圍。

### 覆蓋率是第一級指標

taxonomy 是**部分填充**的：有些 defect 還沒整理過方法。`defect_catalogue_path`
提供分母，覆蓋率因此看得見：

```
taxonomy: {covered: 42, total: 118, unknown_keys: 3, by_category: {...}}
```

沒有分母時 `total` 為 `null`——那時 `covered` 只說明整理了幾條，不說明還缺幾條。
拿條目數當分母會讓覆蓋率恆為 1.0，也就是永遠看不見缺口。

`unknown_keys` 是「條目指向清單裡沒有的 defect」。這種條目會被保留並發出警告，
不會丟棄——它可能表示**清單缺漏**，而那本身是要處理的訊號。

### 各層語料必須互斥

同一個 `concept_id` 出現在兩層，不是「這份文件屬於兩類知識」，而是語料重複收錄了，
或 id 產生方式沒有跨語料唯一。它造成的問題**全部是靜默的**：

| 症狀 | 現在的行為 |
|---|---|
| 取全文取到哪一層 | 宣告順序的第一層。答案可能是錯的，但至少是穩定的 |
| 批次取回 | 先歸屬再逐層取，不會回傳重複條目 |
| 跨層融合 | 每個 concept 只以最好的名次計一次分，不因重複而加倍 |

系統把行為壓成確定的，但**根因要修在語料端**。重複量在 `/v1/stats` 與 `yedai report`
的 `id_overlap` 看得到；CLI 的 `search` 在載入時也會印警告。

### 邊界

defect shape → module 的對照就是 fab taxonomy，比識別碼樣式更敏感——樣式只洩漏形狀，
這裡洩漏的是製程知識本身。repo 內只有 schema 與明顯是佔位符的範例；實際內容走
`*.local.yaml`（已 gitignore）。

---

## 4. 何時必須重建索引

索引簽章 = `hash(欄位清單 + identifier_patterns + entity_field_weights + 字典指紋 + 索引名稱)`
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

| **上游索引的內容變更** | 它是下游的字典來源；下游的實體抽取結果因此改變 |

目前的索引格式版本是 **8**（v2 加入 `by_id` / `bundle_roots`，v3 加入關聯邊，
v4 讓 `#` 成為識別碼的一部分並加入父子層級展開，v5 加入 op no / lot / wafer 樣式
並讓 `#` 的父層可含 `-`，v6 修正作業序號的邊界與位數、移除 tech 樣式，
v7 讓 regex fallback 的實體帶形狀決定的類型，v8 讓索引攜帶所屬的具名索引、
統計改為分層獨立）。從舊版升上來時載入會被拒絕並提示重建，直接重跑 `yedai index` 即可。

**簽章納入索引名稱。** 索引檔被放到另一個索引宣告的路徑下時，載入會報錯而不是靜默
採用——兩份統計互換之後檢索仍會回傳結果，只是分數全錯。

**重建有依賴順序。** 上游（實體字典來源）重建後，下游會因簽章不符而過期。錯誤訊息
會指名該重建哪些索引，而不是只說「請重建索引」——後者會讓你反覆重建同一個並困惑於
它為什麼還是紅的。`yedai index` 不指定 `-i` 時自動依拓撲順序處理。

`entity_sources` 的**路徑**本身不進簽章——字典指紋是由實際載入的條目算出來的，
已經涵蓋 CSV 內容。換個檔名但內容相同不該白白失效一次索引。

### 不必重建（查詢期才套用）

`k1`、`b`、`field_weights`、`fusion_lexical` / `fusion_entity`、`rrf_k`、
`require_entities`、`top_k`、`seed`、`asset_dirs`。最後一項是**服務期政策**
（資產端點的安全白名單），改一個安全設定不該迫使整份語料重建索引。
**所以調權重做敏感度測試不需要重建索引**，改 config 直接重跑查詢即可。

`embedding` / `vector` / `llm` 三個區塊也不進簽章——它們不影響倒排索引的內容。

### 重建索引之後，向量庫可能就對不上了

向量庫是獨立的一份資料，`yedai index` 不會動它。所以：

| 語料變動 | 索引 | 向量庫 |
|---|---|---|
| 只編輯 concept 內容 | 重建後正確 | ⚠️ 仍是舊內容的向量，**要重跑 `yedai embed`** |
| 新增 concept | 重建後正確 | ⚠️ 新 concept 沒有向量，在模式 D/E 裡等於不存在 |
| 刪除 concept | 重建後正確 | 孤兒向量仍會被檢索到，但 `by_id` 查不到而被跳過——所以模式 D 可能回傳**少於 k 筆**，讀 `hit_count_distribution` 時要記得這件事 |

**這個不同步不會報錯。** 索引簽章擋得住「設定變了」，擋不住「語料變了而向量沒跟上」——
`embed` 只檢查索引簽章，不比對內容雜湊。語料變動後重跑 `index` 再重跑 `embed`
是唯一安全的順序；embedding 快取會讓沒變的 concept 不重複付費。

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
| `index not found: … 請先執行 yedai index -i <名稱>` | 還沒建這一層，或 `indexes.<名稱>.path` 指錯 |
| `… 的索引名稱是 'X'，但設定在這個路徑宣告的是 'Y'` | 兩層的 `path` 寫到同一個檔，或改名後沒重建 |
| `索引 'X' 的快取與目前設定不相容` | 簽章不符 → 依訊息指名的順序重建（含下游） |
| `設定未宣告任何索引` | `indexes` 是必填。不回退到預設路徑是刻意的——回退會讓你以為索引建好了 |
| `設定鍵 index_path 已移除` | 舊設定。改成 `indexes` 宣告，不做自動轉換（舊設定沒有層的概念） |
| `設定中有重複的鍵 'X'` | YAML 的重複鍵預設靜默保留最後一個，其中一個索引會無聲消失 |
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
uv run yedai index -c config.local.yaml   # indexes.synthetic.source 指向 .synthetic/
```

> ⚠️ 合成語料**僅供驗證程式跑得通**。詞頻分佈、識別碼密度、模板多樣性全是編造的，
> **不得用於調整任何參數，也不得用於推論任何檢索效果數字。**
