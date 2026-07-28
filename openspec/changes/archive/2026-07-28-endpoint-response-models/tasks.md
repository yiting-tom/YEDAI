## 1. 回應模型

- [x] 1.1 新增 `src/yedai/schemas.py`
- [x] 1.2 共用模型：`Distribution`、`EntityRef`（`ConceptSummary` 未建立——摘要欄位在
      `HitOut` 與 `NeighborOut` 中的語義不同，硬抽共用型別只會製造假的一致性）
- [x] 1.3 檢索：`HitOut` / `ModeResultOut` / `OverlapOut` / `SearchOut`
- [x] 1.4 內容：`FigureOut` / `SectionOut` / `ConceptOut` / `ConceptErrorOut` / `ConceptsOut`
- [x] 1.5 關聯：`NeighborOut` / `NeighborsOut`
- [x] 1.6 檢索（grep）：`GrepMatchOut` / `GrepScopeOut` / `GrepOut`
- [x] 1.7 遙測：`FeedbackOut` / `ReportOut`（頂層區塊 + Distribution，內部開放）
- [x] 1.8 ops：`HealthOut` / `VersionOut` / `StatsOut`

## 2. 掛上端點

- [x] 2.1 每個回傳 JSON 的端點加 `response_model`
- [x] 2.2 `/v1/concept/{id}/asset` 維持 `response_class=FileResponse`，不加模型
- [x] 2.3 確認 `response_model` 不會裁掉既有欄位（回應內容必須逐位元組不變）

## 3. 測試

- [x] 3.1 逐端點比對建模前後的回應內容一致（一次性遷移檢查：以暫時測試擷取前後
      回應並 diff，確認完全相同後移除。發現兩處差異並修正，見下）
- [x] 3.2 OpenAPI 中每個端點的 200 回應都有非空 schema
- [x] 3.3 `test_docs_sync.py` 擴充：回應模型的頂層欄位必須出現在 `docs/api.md`

## 4. 文件

- [x] 4.1 `docs/api.md` 的回應結構與模型對齊
- [x] 4.2 `README.md` / `docs/agent-tools.md` 指向 `/docs` 作為回應結構的來源

## 5. 驗證

- [x] 5.1 `uv run pytest` 全綠
- [x] 5.2 Playwright 走過 `/docs` 與 `/redoc`，確認回應欄位顯示出來
