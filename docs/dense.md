# 稠密腿與 RRF 融合（模式 D / E）

A/B/C 只能回答「識別碼斷詞與實體字典有沒有用」。它答不出**關鍵字檢索本身夠不夠**。

現場查詢有兩種形狀，失效模式相反：

| 查詢 | 關鍵字腿 | 稠密腿 |
|---|---|---|
| `AEPOL1#PM1 微粒` | 強——識別碼精確 | 弱，**分不出兄弟機台** |
| 「蝕刻後圖案倒塌要看哪些參數」 | 常常直接落空 | 這是它存在的理由 |

第二列是實測的：合成語料上以模式 D 查 `XTR-05 PARTICLE`，第 2 名回的是 `XTR-06`。稠密向量看不出末碼差一碼是兩台不同的機器。

**所以要的是融合而不是取代。**

## RRF 為什麼只用排名

BM25 分數與餘弦相似度沒有共同尺度。要把它們相加就得先湊一個正規化與一組權重，而那組權重無法從原理推導，只能靠猜——最後變成一個沒人敢動也沒人解釋得了的魔術數字。

RRF 不碰分數：

```
score(doc) = Σ  1 / (k + rank_leg(doc))
```

唯一的常數 `k` 只控制「前幾名比後幾名重要多少」，而且對它不敏感。預設 60（慣例值），設定鍵是 `rrf_k`——但在有真實查詢與人工判斷之前調它，調的是雜訊。

各腿先各自取到 `max(k · 5, k)` 的深度再融合。只取 top-k 就融合，會讓「在 C 排第 12、在 D 排第 3」這種文件——也就是融合唯一能救回來的那種——根本進不了候選集。

## 換供應商只改設定

Embedding 走 **OpenAI 相容的 `/embeddings`**。程式不認得任何一家供應商。

```yaml
embedding:
  base_url: https://openrouter.ai/api/v1     # 開發期
  model: qwen/qwen3-embedding-8b
  dim: 4096
  api_key_env: OPENROUTER_API_KEY            # 環境變數**名稱**，不是金鑰
  trusted_endpoint: false
```

production 換成自架的 LiteLLM → vLLM：

```yaml
embedding:
  base_url: http://litellm.internal/v1
  model: qwen3-embedding-8b                  # 自架端的模型名可能不同
  api_key_env: LITELLM_API_KEY
  trusted_endpoint: true
```

其餘一字不改。把供應商寫進程式的代價不是重寫成本，是「開發跟 production 跑的不是同一條路」，於是開發期驗過的東西在 production 不算數。

**金鑰只從環境變數讀**（`.env`，已 gitignore）。`api_key_env` 若填進 `sk-` 開頭的字串會被設定驗證擋下——設定檔會進版控，而這個 repo 是公開的。

## 語料外流閘門

`yedai embed` 會把 concept 全文送到 `base_url`。語料是最高機密，而開發期的預設端點是第三方。

所以：**非合成語料 + 未宣告 `trusted_endpoint` → 拒絕執行**，訊息裡直接印出那個 base_url。

```
拒絕執行：這會把 ./bundles 的 concept 全文送到
    https://openrouter.ai/api/v1
而該語料不是合成的。語料一旦送出就收不回來。
```

合成語料不受限——它本來就是編造的，而每次都要解閘的閘門會被找方法繞過，那等於沒有閘門。

這道閘擋的不是惡意，是「拿開發設定跑了真語料」這種**一次就無法挽回**的意外。

## 向量庫

```yaml
vector:
  path: .index/qdrant     # 本機檔案模式，不必架服務
  url: null               # 指定則連 server
  collection: yedai
```

要求先架一套服務，實際效果是這個實驗不會被跑——架設成本會直接變成「之後再說」的理由。

集合維度與設定不符時會**重建**而非沿用。沿用會留下一份「部分舊模型、部分新模型」的向量庫，那種混合不會報錯，只會讓相似度在不同文件之間不可比。

## 跑起來

```bash
cp .env.example .env          # 填入金鑰
uv run yedai index   -c config.local.yaml
uv run yedai embed   -c config.local.yaml           # 每層寫進自己的 collection
uv run yedai search "蝕刻後圖案倒塌" -m E -c config.local.yaml
```

查詢向量會落地快取（鍵含模型與維度），同一份 `queries.txt` 重跑不重複付費。換模型後快取自動失效——沿用舊向量會產出無聲的錯誤結果。

**每個索引一個 collection。** collection 名稱寫在該索引的宣告裡；沒宣告 `collection` 的索引就沒有稠密腿，它的 `available_modes` 不含 D/E。分開的理由跟分層一樣，另加一個：不同層的稠密腿價值不同（敘述性語料預期 D 是主力，同格式的結構化文件預期不是），分開才能分開決定要不要付這筆成本。

**全部 collection 共用一個 qdrant client。** collection 在 qdrant 是查詢參數，不是 client 參數。本機檔案模式對儲存資料夾持有**獨佔鎖**——每層各開一個 client 的話，第二個有向量的層會讓整個載入直接炸掉：

```
RuntimeError: Storage folder .index/qdrant is already accessed by another instance
```

症狀是「跑過 `embed` 的層一旦超過一個，`serve` 與 `mcp` 就起不來」，而錯誤訊息指向 qdrant、不指向設定。`VectorBackend` 持有那個唯一的 client，`backend.store(dim, collection)` 取得各 collection 的操作介面。回歸測試在 `tests/test_layers_interfaces.py::test_several_layers_share_one_client_on_the_same_storage`。

**跨程序併發仍然不行。** 那是本機檔案模式的固有限制：`serve` 與 `mcp` 不能同時對同一個 `vector.path` 開著。要併發就得改指 `vector.url`，起一套 qdrant 服務。

HTTP 與 MCP 現在也載入向量庫——`Runtime.load()` 會為每個宣告了 collection 的索引建立向量檢索器，並在該 collection 尚無向量時把 D/E 標為不可用。

## 沒有向量時，D/E 是「不可用」而不是退化成 C

這一點是刻意的。靜默退化會讓報告顯示「稠密腿沒有帶來差異」，而真相是它根本沒有執行——那個假象會被當成結論，而且沒有任何地方會露出破綻。

`compare` 只跑可用的模式，重疊度也只在可用模式的兩兩配對上計算。

## 怎麼讀 D / E 的數字

- **`C-D` jaccard 低** → 兩腿看到的東西不同，融合有料可混
- **`C-D` jaccard 接近 1** → 稠密腿只是換一種方式講同一件事，不必留
- **`C-E` jaccard 接近 1** → 融合沒有改變結果，模式 E 不值得那筆 embedding 費用
- **`D-E` jaccard 接近 1** → RRF 幾乎被稠密腿主導，該檢查關鍵字腿的深度夠不夠

## 刻意不做的事

- **不分塊**。一個 concept 一個向量（超過 `max_chars` 截斷）。分塊會同時改變召回粒度與融合行為，兩個變因一起動就分不出是誰的功勞。等 D 與 E 的數字出來再決定。
- **不調 `rrf_k`**。理由同上。
