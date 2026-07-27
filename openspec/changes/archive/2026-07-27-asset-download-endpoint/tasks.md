## 1. 設定

- [x] 1.1 `Config` 新增 `asset_dirs: list[str]`，預設 `["_assets"]`
- [x] 1.2 確認 `asset_dirs` **不**進 `index_signature`（服務期政策，不改變索引內容）
- [x] 1.3 `config.example.yaml` 補上 `asset_dirs` 與說明

## 2. 資產解析模組

- [x] 2.1 新增 `src/yedai/assets.py`，只依賴 `Index` 與 `fulltext.resolve_path`，不依賴 FastAPI
- [x] 2.2 定義 `AssetNotFound` 與 `AssetForbidden` 兩種例外，對應「檔案不存在」與「路徑違規」
- [x] 2.3 早期拒絕：空路徑、絕對路徑、含 `..` 片段（在接觸檔案系統之前）
- [x] 2.4 以 concept 檔案所在目錄為基準解析相對路徑
- [x] 2.5 容器檢查：解析後絕對路徑必須位於該 concept 所屬 bundle 根目錄之下
- [x] 2.6 白名單檢查：解析後路徑必須位於 `asset_dirs` 所列名稱的目錄之下，錯誤訊息指出是此規則
- [x] 2.7 實作 `resolve_asset(index, concept_id, path, asset_dirs)` 回傳已驗證的絕對路徑
- [x] 2.8 實作 `guess_media_type(path)`：以 `mimetypes` 判定，未知退回 `application/octet-stream`

## 3. HTTP 端點

- [x] 3.1 `GET /concept/{concept_id}/asset?path=`，宣告於 `/concept/{concept_id:path}` **之前**
- [x] 3.2 以串流方式回傳檔案，不整份讀進記憶體
- [x] 3.3 `ConceptNotFound` / `AssetNotFound` → 404；`AssetForbidden` → 403；缺 `path` → 422
- [x] 3.4 預設 `Content-Disposition: inline`；`download=true` 時為 `attachment`
- [x] 3.5 檔名以 URL 編碼放入 `filename*`，避免中文檔名破壞標頭
- [x] 3.6 端點加上 summary/description，確認出現在互動式 API 文件

## 4. 測試

- [x] 4.1 取回資產：位元組與磁碟一致、media type 正確
- [x] 4.2 巢狀 concept：路徑以 concept 所在目錄為基準解析
- [x] 4.3 未知副檔名退回 `application/octet-stream`
- [x] 4.4 路徑穿越：`../`、URL 編碼的 `..`、絕對路徑、空路徑皆被拒
- [x] 4.5 symlink 指向 bundle 之外被拒
- [x] 4.6 bundle 內但不在 `asset_dirs` 之下的檔案被拒，且訊息指出資產目錄限制
- [x] 4.7 覆寫 `asset_dirs` 後行為隨之改變
- [x] 4.8 失敗可區分：concept 不存在 vs 資產不存在 vs 路徑違規
- [x] 4.9 HTTP：200 / 403 / 404 / 422 各情境；`download=true` 的處置標頭；端點出現在 openapi.json
- [x] 4.10 串接：`/concept/{id}` 取 `assets` → 逐項取資產皆 200

## 5. 端到端驗證

- [x] 5.1 以合成語料實測：取回 PNG、位元組數與檔案相符
- [x] 5.2 以瀏覽器自動化在文件頁測試該端點，確認 200 與圖片型別
- [x] 5.3 實測攻擊路徑（`../` 與絕對路徑）確實回 403

## 6. 文件

- [x] 6.1 README 端點表新增資產端點
- [x] 6.2 `docs/agent-tools.md` 說明如何從 `assets` / `figures` 取得圖片，並註明 MCP 尚無對應工具
- [x] 6.3 `docs/data-flow.md` 補上資產取用的資料流與三道防線
- [x] 6.4 `docs/indexing.md` 說明 `asset_dirs` 為服務期政策、變更不需重建索引
