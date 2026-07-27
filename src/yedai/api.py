"""FastAPI 介面。互動式文件頁在 /docs。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import __version__
from .assets import AssetForbidden, AssetNotFound, guess_media_type, resolve_asset
from .config import Config
from .fulltext import (
    MAX_BATCH,
    ConceptFileMissing,
    ConceptNotFound,
    ConceptPathEscape,
    load_concept,
    load_concepts,
)
from .graph import DIRECTIONS, MAX_DEPTH, neighbors as expand_neighbors
from .grep import DEFAULT_MAX_RESULTS, InvalidPattern, ScopeRequired, UnknownScope, grep as run_grep
from .index import INDEX_FORMAT_VERSION, Index
from .runtime import Runtime
from .search import MODES, SearchOutcome, Searcher
from .telemetry import TelemetryStore, build_report

#: API 版本。功能端點全部掛在這個前綴之下；/healthz 與 /version 不版本化，
#: 因為它們描述的是服務本身而非 API 契約——監控不該因 API 改版而失效。
API_VERSION = "v1"

ModeParam = Literal["A", "B", "C", "compare"]
DirectionParam = Literal["out", "in", "both"]

#: 分類依 agent 的工作流切分，所以分組本身就是使用指引。
TAGS_METADATA = [
    {
        "name": "retrieval",
        "description": (
            "**找到 concept。** 只回摘要清單，不含內容——由你決定讀哪幾份完整文件。"
            "`grep` 必須先有範圍，範圍取自 `search` 結果的 `bundle_id`。"
        ),
    },
    {
        "name": "content",
        "description": (
            "**取得內容與資產。** 從 `retrieval` 拿到 `concept_id` 之後用這一組。"
            "一次要讀多份請用批次端點，不要逐筆呼叫。"
        ),
    },
    {
        "name": "graph",
        "description": (
            "**沿 `related` 導航。** `direction=in` 回傳「誰指向這個 concept」，"
            "那是排查復發問題時最需要、卻無法自己拼出來的資訊。"
        ),
    },
    {
        "name": "telemetry",
        "description": (
            "**量測與回饋。** 服務的是 A/B/C 消融實驗，不是日常檢索——"
            "agent 不需要呼叫這一組。`/report` 的輸出不含任何語料內容，可安全分享。"
        ),
    },
    {
        "name": "ops",
        "description": (
            "**服務與語料狀態。** `/healthz` 與 `/version` 不帶版本前綴，"
            "因為監控與部署不該因 API 改版而失效。"
        ),
    },
]


class ConceptsIn(BaseModel):
    concept_ids: list[str] = Field(
        ..., min_length=1, max_length=MAX_BATCH, description=f"concept id 陣列，最多 {MAX_BATCH} 筆"
    )
    include_raw: bool = Field(True, description="是否包含原始 markdown 全文")


class FeedbackIn(BaseModel):
    query_id: str = Field(..., description="來自 /search 回應的查詢識別碼")
    concept_id: str = Field(..., description="被點選的 concept id")
    rank: int = Field(..., ge=1, description="被點選項目在該模式結果中的排名")
    mode: Literal["A", "B", "C"] = Field(..., description="該結果來自哪個模式")
    action: str = Field("click", description="動作類型")


class _State:
    config: Config
    index: Index
    searcher: Searcher
    store: TelemetryStore
    loaded: bool = False
    error: str | None = None


state = _State()


def _load_state() -> None:
    state.loaded = False
    state.error = None
    try:
        # 與 MCP server 共用同一條載入路徑——複製一份必然分歧
        rt = Runtime.load()
        state.config = rt.config
        state.index = rt.index
        state.searcher = rt.searcher
        state.store = rt.store
        state.loaded = True
    except Exception as exc:  # 啟動失敗不應讓服務無法回應 /healthz
        state.error = f"{type(exc).__name__}: {exc}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_state()
    yield


app = FastAPI(
    title="yedai — OKF 關鍵字檢索 baseline",
    description=(
        "A/B/C 三組消融的關鍵字檢索水位線。\n\n"
        "- **A** 天真 BM25F（識別碼被切碎）\n"
        "- **B** BM25F + 識別碼保護斷詞\n"
        "- **C** B + 實體字典匹配加權\n\n"
        "`/report` 產出的統計報告不含任何語料內容，可安全分享。"
    ),
    version=__version__,
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

#: 功能端點統一掛前綴——不逐一改寫十個裝飾器；日後開 /v2 只是再掛一個 router。
router = APIRouter(prefix=f"/{API_VERSION}")


def _require_index() -> None:
    if not state.loaded:
        raise HTTPException(status_code=503, detail=f"索引未載入：{state.error or '未知原因'}")


def _outcome_payload(outcome: SearchOutcome, query_id: str, requested: str) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "query": outcome.query,
        "requested_mode": requested,
        "k": outcome.k,
        "display_order": outcome.display_order or None,
        "entities": [
            {"type": e.type, "canonical": e.canonical, "raw": e.raw, "source": e.source}
            for e in outcome.entities
        ],
        "results": {
            mode: {
                "mode": res.mode,
                "candidates": res.candidates,
                "hits": [h.to_dict() for h in res.hits],
            }
            for mode, res in outcome.results.items()
        },
        "overlaps": [
            {"pair": o.pair, "jaccard": o.jaccard, "kendall_tau": o.kendall_tau, "common": o.common}
            for o in outcome.overlaps
        ],
    }


@app.get("/healthz", summary="健康檢查（不版本化）", tags=["ops"])
def healthz() -> dict[str, Any]:
    return {"status": "ok", "index_loaded": state.loaded, "error": state.error}


@app.get("/version", summary="版本資訊（不版本化）", tags=["ops"])
def version() -> dict[str, Any]:
    """索引未載入時仍須可回應——這個端點的用途之一就是診斷載入失敗。"""
    loaded = state.index if state.loaded else None
    return {
        "package": __version__,
        "api": API_VERSION,
        # 本程式支援的索引格式 vs 目前載入索引的格式：兩者無對應關係，
        # 而「支援 v3、載入的是 v2」正是最需要一眼看出的除錯情境。
        "index_format": INDEX_FORMAT_VERSION,
        "index": None
        if loaded is None
        else {"format_version": loaded.format_version, "signature": loaded.signature},
    }


@router.get("/stats", summary="語料統計與索引狀態", tags=["ops"])
def stats() -> dict[str, Any]:
    _require_index()
    s = state.index.stats
    return {
        "bundles": s.bundles,
        "concepts": s.concepts,
        "avg_concept_chars": round(s.avg_concept_chars, 1),
        "avg_figures_per_concept": round(s.avg_figures, 2),
        "vocab_naive": s.vocab_naive,
        "vocab_protected": s.vocab_protected,
        "entities_total": s.entities_total,
        "entities_from_dictionary": s.entities_dict,
        "entities_from_regex_fallback": s.entities_regex,
        "dangling_related": s.dangling_related,
        "parse_skipped": s.parse_skipped,
        "parse_warnings": s.parse_warnings,
        "types": s.types,
        "index_signature": state.index.signature,
    }


@router.get("/search", summary="查詢（單模式或三模式並排）", tags=["retrieval"])
def search(
    q: str = Query(..., min_length=1, description="查詢字串"),
    mode: ModeParam = Query("compare", description="A / B / C，或 compare 三模式並排"),
    k: Optional[int] = Query(None, ge=1, le=100, description="回傳筆數"),
) -> dict[str, Any]:
    _require_index()
    searcher = state.searcher

    if mode == "compare":
        outcome = searcher.compare(q, k)
    else:
        result = searcher.search(q, mode, k)
        outcome = SearchOutcome(
            query=q,
            k=k or state.config.top_k,
            results={result.mode: result},
            entities=searcher.extract_query_entities(q),
        )

    query_id = state.store.log_query(outcome, requested_mode=mode)
    return _outcome_payload(outcome, query_id, mode)


@router.post(
    "/concepts",
    summary="批次取回 concept 全文",
    description=(
        f"一次取回多個 concept 的完整內容，最多 {MAX_BATCH} 筆。\n\n"
        "**部分成功**：單一 id 失敗不影響其餘，失敗者列於 `errors`，"
        "`reason` 區分 `not_found`（id 打錯）與 `file_missing`（索引過期）。\n\n"
        "`include_raw=false` 時只回結構化欄位，省去原始全文的體積。"
    ),
    tags=["content"],
)
def concepts(payload: ConceptsIn = Body(...)) -> dict[str, Any]:
    _require_index()
    found, errors = load_concepts(state.index, payload.concept_ids, include_raw=payload.include_raw)
    return {
        "requested": len(payload.concept_ids),
        "returned": len(found),
        "concepts": found,
        "errors": errors,
    }


# 這兩條路由必須宣告在 /concept/{concept_id:path} 之前——path 轉換器會吃掉整個
# 尾段，先宣告的規則先比對，順序反了會讓 concept_id 變成 "xxx/neighbors"。
@router.get(
    "/concept/{concept_id:path}/asset",
    summary="下載 concept 引用的資產",
    description=(
        "取回 concept 引用的資產檔案（`_assets/slide_xxx.png` 等）。\n\n"
        "`path` 直接使用 `/concept/{id}` 回傳的 `assets` 陣列中的值——"
        "它以**該 concept 檔案所在目錄**為基準解析，與 markdown 相對連結、"
        "`## Citations` 的寫法完全一致，不需要任何轉換。\n\n"
        "預設以 `inline` 回傳，瀏覽器可直接顯示（看 wafer map 用）；"
        "`download=true` 改為附件下載。\n\n"
        "路徑受三道約束：不接受絕對路徑與 `..`、必須位於該 bundle 根目錄之下、"
        "且必須位於設定允許的資產目錄（預設 `_assets`）之下。違反者回 403。"
    ),
    response_class=FileResponse,
    tags=["content"],
)
def asset(
    concept_id: str,
    path: str = Query(..., min_length=1, description="相對於 concept 檔案的資產路徑"),
    download: bool = Query(False, description="true 則以附件下載，否則內嵌顯示"),
) -> FileResponse:
    _require_index()
    try:
        resolved = resolve_asset(state.index, concept_id, path, state.config.asset_dirs)
    except ConceptNotFound:
        raise HTTPException(status_code=404, detail=f"unknown concept_id: {concept_id}") from None
    except AssetForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except (AssetNotFound, ConceptFileMissing) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    # filename* 用 RFC 5987 編碼，中文檔名才不會破壞標頭
    quoted = quote(resolved.name)
    disposition = "attachment" if download else "inline"
    return FileResponse(
        resolved,
        media_type=guess_media_type(resolved),
        headers={"content-disposition": f"{disposition}; filename*=UTF-8''{quoted}"},
    )


@router.get(
    "/concept/{concept_id:path}/neighbors",
    summary="展開 concept 關聯",
    description=(
        "沿 `related` 展開關聯，重現 agent 在小規模語料上手動跳轉的行為。\n\n"
        "`direction=in` 回傳**誰指向這個 concept**——那是 agent 自己拼不出來、"
        "但排查時最想知道的資訊。\n\n"
        f"`depth` 上限 {MAX_DEPTH}。指向語料中不存在 id 的懸空引用列於 `dangling`。"
    ),
    tags=["graph"],
)
def neighbors(
    concept_id: str,
    depth: int = Query(1, ge=1, le=MAX_DEPTH, description="展開跳數"),
    direction: DirectionParam = Query("both", description="out=我指向誰 / in=誰指向我 / both"),
) -> dict[str, Any]:
    _require_index()
    try:
        return expand_neighbors(state.index, concept_id, depth=depth, direction=direction)
    except ConceptNotFound:
        raise HTTPException(status_code=404, detail=f"unknown concept_id: {concept_id}") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get(
    "/grep",
    summary="限定範圍的字面／正則搜尋",
    description=(
        "**必須指定範圍**（`bundle_id` 或 `concept_id` 至少其一）。\n\n"
        "這不是效能保護，是設計意圖：先用 `/search` 把語料縮到 2~3 個 bundle，"
        "再在那個範圍裡做字面搜尋——那正是小規模 agentic file search 有效的條件。\n\n"
        "預設字面比對；`regex=true` 才啟用正則（使用者正則可能觸發災難性回溯）。"
    ),
    tags=["retrieval"],
)
def grep(
    pattern: str = Query(..., min_length=1, description="搜尋樣式"),
    bundle_id: list[str] = Query(default=[], description="限定 bundle，可重複"),
    concept_id: list[str] = Query(default=[], description="限定 concept，可重複"),
    regex: bool = Query(False, description="是否以正則比對"),
    ignore_case: bool = Query(False, description="是否忽略大小寫"),
    max_results: int = Query(DEFAULT_MAX_RESULTS, ge=1, le=1000, description="結果筆數上限"),
) -> dict[str, Any]:
    _require_index()
    try:
        return run_grep(
            state.index,
            pattern,
            bundle_ids=bundle_id,
            concept_ids=concept_id,
            regex=regex,
            ignore_case=ignore_case,
            max_results=max_results,
        )
    except UnknownScope as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0] if exc.args else exc)) from None
    except (ScopeRequired, InvalidPattern) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get(
    "/concept/{concept_id:path}",
    summary="取回 concept 全文",
    description=(
        "以 `/search` 結果中的 `concept_id` 取回該 concept 的完整內容。\n\n"
        "同時回傳 `raw`（原始 markdown 全文，可直接餵進 LLM context）與解析後的 "
        "`frontmatter` / `sections` / `figures`。\n\n"
        "全文於請求時從磁碟讀取，因此檔案變更會立即反映，無須重建索引。"
    ),
    tags=["content"],
)
def concept(concept_id: str) -> dict[str, Any]:
    _require_index()
    try:
        return load_concept(state.index, concept_id)
    except ConceptNotFound:
        raise HTTPException(status_code=404, detail=f"unknown concept_id: {concept_id}") from None
    except ConceptPathEscape as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    except ConceptFileMissing as exc:
        # 410 而非 404：這個 concept 曾經存在，是語料變動了，處置方式是重建索引
        raise HTTPException(status_code=410, detail=str(exc)) from None


@router.post("/feedback", summary="記錄點選回饋", tags=["telemetry"])
def feedback(payload: FeedbackIn = Body(...)) -> dict[str, Any]:
    _require_index()
    try:
        state.store.log_feedback(
            query_id=payload.query_id,
            concept_id=payload.concept_id,
            rank=payload.rank,
            mode=payload.mode,
            action=payload.action,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown query_id: {payload.query_id}") from exc
    return {"status": "recorded", "query_id": payload.query_id}


@router.get("/report", summary="去識別化統計報告（可安全分享）", tags=["telemetry"])
def report() -> dict[str, Any]:
    _require_index()
    return build_report(state.index, state.store, state.config)


app.include_router(router)
