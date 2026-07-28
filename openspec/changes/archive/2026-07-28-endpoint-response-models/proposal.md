## Why

`/docs` 與 `/redoc` 上，每個端點的 200 回應都是空的——沒有欄位、沒有型別、沒有範例。

原因是所有端點的回傳型別都寫成 `dict[str, Any]`，FastAPI 據此產出的 schema 就是一個空物件。目前 OpenAPI 只描述了參數、錯誤碼與標籤分類，**回應結構完全缺席**，而回應結構才是呼叫端真正需要的部分。

這造成三個具體後果：

1. **文件頁無法作為使用依據。** 想知道 `/v1/search` 回什麼，只能去讀 `_outcome_payload()` 的原始碼，或者實際打一次看結果。
2. **`docs/api.md` 得手寫回應結構。** 那是一份會過期的副本——OpenAPI 沒有可比對的來源，`test_docs_sync.py` 目前只能檢查路徑、參數、狀態碼與標籤四項。
3. **agent 拿不到契約。** MCP 工具的輸出結構同樣來自這些函式，而 schema 是唯一能讓呼叫端在寫程式前知道欄位長相的東西。

## What Changes

- 新增 `schemas.py`，集中所有回應模型，不散在 `api.py` 裡
- 為每個回傳 JSON 的端點宣告 `response_model`
- `/v1/search` 的巢狀結構拆成數個模型：`Hit` / `ModeResult` / `Overlap` / `EntityRef`
- `Distribution`（`n / min / p25 / median / p75 / max / mean`）獨立成一個模型——它在報告中出現十餘次
- `test_docs_sync.py` 擴充：`docs/api.md` 必須涵蓋每個回應模型的頂層欄位
- `docs/api.md` 的回應結構改為與 schema 對齊

## Capabilities

### Modified Capabilities
- `search-interfaces`: HTTP 介面的回應結構納入 OpenAPI schema

## Impact

- **新增**：`src/yedai/schemas.py`
- **修改**：`src/yedai/api.py`（掛上 `response_model`）、`tests/test_docs_sync.py`、`docs/api.md`
- **不影響行為**：回應內容一個位元組都不變。模型只是描述既有輸出——若兩者不符，那是模型寫錯，不是輸出該改
- **不影響索引**：純介面層變更，不需重建索引
- **`/v1/concept/{id}/asset` 不適用**：它回傳二進位檔案，已宣告 `response_class=FileResponse`

## 設計取捨：`/v1/report` 不做完整建模

報告是一份統計文件，含大量**動態鍵**的映射（`by_type` 的鍵是實體類型、`mode_overlap` 的鍵是模式組合、`clicks_per_mode` 的鍵是模式）與隨指標增減而變動的區塊。

把每個指標都寫成欄位，會讓「新增一個統計數字」變成必須同步修改模型、測試與文件三處——而報告的指標本來就會隨實驗進展調整。所以報告只建模**穩定的頂層區塊**與 `Distribution`，區塊內部維持開放結構並在模型上註明。

這是刻意的：schema 的價值在於描述**契約**，而報告的內部指標不是契約，是實驗產物。
