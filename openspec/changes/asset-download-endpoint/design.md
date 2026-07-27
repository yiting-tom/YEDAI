## Context

合成語料裡一個 concept 長這樣：

```yaml
assets: [_assets/slide_005.png, _assets/slide_012.png]
figures:
  - {file_id: slide_001, type: wafer_map, description: …}
```

```markdown
## Citations
[5] [slide 5](_assets/slide_005.png)
```

檔案實際位於 `<bundle>/okf/_assets/slide_005.png`，而 concept 位於 `<bundle>/okf/`。
三處引用（frontmatter、figures、Citations）都是**相對於 concept 檔案所在目錄**的寫法。

這是本變更唯一真正的設計問題：**`path` 直接來自呼叫端**。`concept_id` 有索引可查，
路徑是系統自己組出來的；資產路徑不是。路徑穿越在這裡是實際風險，不是理論風險。

## Goals / Non-Goals

**Goals:**

- 讓 `assets` 與 `figures` 從死路變成可取用
- 路徑解析語意與 markdown 相對連結完全一致，不需要呼叫端做任何轉換
- 在不破壞真實語料相容性的前提下，把路徑穿越的攻擊面壓到最小

**Non-Goals:**

- 不做縮圖、轉檔、壓縮
- 不做 MCP 的圖片工具（回傳 base64 `ImageContent`）——那是另一個變更
- 不做資產列表端點：`/concept/{id}` 已回傳 `assets` 與 `figures`，那就是清單
- 不做 Range 請求與快取控制以外的效能處理

## Decisions

### D1. 以 concept 為錨點，不是以 bundle

| | `/bundle/{bid}/asset/{path}` | **`/concept/{cid}/asset?path=`（採用）** |
|---|---|---|
| 路徑基準 | bundle 根目錄或 `okf/`，**有歧義** | concept 檔案所在目錄，**無歧義** |
| 與檔案裡的寫法 | 需要呼叫端自行轉換 | 直接照抄 `assets` 的值即可 |
| 巢狀 concept（`subpath`） | 基準不明 | 自動正確 |

真實語料有 `subpath` 欄位，代表 concept 可能不在 `okf/` 根層。以 bundle 為錨點時，
`_assets/x.png` 到底相對於誰就變成猜測。以 concept 為錨點沒有這個問題——
markdown 相對連結本來就是相對於檔案自己。

### D2. 資產路徑用 query 參數，不用路徑片段

`/concept/{concept_id:path}/asset/{asset_path:path}` 需要在同一條路由裡放兩個
path 轉換器，兩個都編譯成 `.*`，靠回溯決定切點——路徑本身含 `/asset/` 時會誤切。

改成 `/concept/{concept_id:path}/asset?path=…`：與已驗證可行的 `neighbors` 同形，
且資產路徑經 URL 編碼傳遞，含空白、中文、特殊字元都不會出問題。

路由必須宣告在 `/concept/{concept_id:path}` **之前**，否則 path 轉換器會把
`/asset` 吃進 `concept_id`。

### D3. 三道防線，順序由便宜到昂貴

1. **早期拒絕**：`path` 為絕對路徑、含 `..` 片段、或為空 → 直接拒絕，不碰檔案系統
2. **容器檢查**：解析後的絕對路徑必須位於該 concept 所屬 bundle 的根目錄之下
3. **目錄白名單**：解析後的路徑必須位於名稱屬於 `asset_dirs`（預設 `["_assets"]`）的目錄之下

第 2 道是安全邊界——沒有它就能讀到語料以外的任何檔案。
第 3 道是縱深防禦：即使容器檢查有疏漏，能讀到的也只有資產目錄。

`resolve()` 會展開 symlink，所以指向外部的 symlink 會在第 2 道被擋下。

**為什麼要有第 3 道**：沒有它，這個端點就變成「讀取 bundle 內任意檔案」。
雖然 `/concept` 本來就給得出所有 `.md` 的內容，但把一個泛用的檔案讀取端點開在
語料目錄上，攻擊面遠大於必要。`asset_dirs` 可覆寫，真實語料若用別的目錄名改設定即可。

### D4. media type 由副檔名判定，不做內容嗅探

用標準函式庫的 `mimetypes`。判不出來時退回 `application/octet-stream`——
不猜測、不嗅探內容，避免把一個偽裝的檔案標成可執行或可內嵌的型別。

### D5. 預設 `inline`，`download=true` 才是附件

預設 `Content-Disposition: inline`，讓瀏覽器與文件頁直接顯示圖片（這是主要用途：
人在看 wafer map）。需要存檔時加 `download=true`。

檔名以 URL 編碼形式放進 `filename*`，避免中文檔名破壞標頭。

### D6. `asset_dirs` 不進索引簽章

它是**服務期政策**，不改變索引內容。放進簽章會讓改一個安全設定就得重建整份索引，
在 220 萬 concept 的規模下是明顯不合理的代價。

## Risks / Trade-offs

- **路徑穿越** → D3 的三道防線；測試涵蓋 `../`、絕對路徑、symlink 逸出、URL 編碼過的 `..`
- **`asset_dirs` 白名單擋掉真實語料的合法資產** → 可由設定覆寫；錯誤訊息明確指出是哪一道規則擋的，而不是含糊的 404
- **大檔案佔記憶體** → 以串流方式回傳（`FileResponse`），不整份讀進記憶體
- **資產不存在但 frontmatter 有列** → 回 404 並區分於「concept 不存在」；這也是語料品質訊號
- **未做 MCP 圖片工具** → agent 目前只能拿到 URL 與圖說，看不到圖。列為後續變更

## Open Questions

- 是否需要 MCP 的 `get_asset` 工具回傳 base64 `ImageContent`，讓 agent 真的「看見」wafer map——
  這對 YED 場景價值很高，但會大量消耗 context，需要先量測
- 是否需要縮圖端點（`?w=`）以降低傳輸量——待實際使用後決定
