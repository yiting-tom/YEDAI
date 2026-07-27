"""FastAPI 介面。互動式文件頁在 /docs。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .config import Config
from .entities import EntityDictionary
from .fulltext import ConceptFileMissing, ConceptNotFound, ConceptPathEscape, load_concept
from .index import Index
from .search import MODES, SearchOutcome, Searcher
from .telemetry import TelemetryStore, build_report

ModeParam = Literal["A", "B", "C", "compare"]


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
        cfg = Config.load(os.environ.get("YEDAI_CONFIG") or None)
        dictionary = EntityDictionary.load(cfg.dictionary_path)
        idx = Index.load(os.environ.get("YEDAI_INDEX") or cfg.index_path)
        idx.check_signature(cfg.index_signature(dictionary.fingerprint()))
        state.config = cfg
        state.index = idx
        state.searcher = Searcher(idx, cfg, dictionary)
        state.store = TelemetryStore.create(cfg)
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
    version="0.1.0",
    lifespan=lifespan,
)


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


@app.get("/healthz", summary="健康檢查", tags=["ops"])
def healthz() -> dict[str, Any]:
    return {"status": "ok", "index_loaded": state.loaded, "error": state.error}


@app.get("/stats", summary="語料統計與索引狀態", tags=["ops"])
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
        "parse_skipped": s.parse_skipped,
        "parse_warnings": s.parse_warnings,
        "types": s.types,
        "index_signature": state.index.signature,
    }


@app.get("/search", summary="查詢（單模式或三模式並排）", tags=["search"])
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


@app.get(
    "/concept/{concept_id:path}",
    summary="取回 concept 全文",
    description=(
        "以 `/search` 結果中的 `concept_id` 取回該 concept 的完整內容。\n\n"
        "同時回傳 `raw`（原始 markdown 全文，可直接餵進 LLM context）與解析後的 "
        "`frontmatter` / `sections` / `figures`。\n\n"
        "全文於請求時從磁碟讀取，因此檔案變更會立即反映，無須重建索引。"
    ),
    tags=["search"],
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


@app.post("/feedback", summary="記錄點選回饋", tags=["search"])
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


@app.get("/report", summary="去識別化統計報告（可安全分享）", tags=["ops"])
def report() -> dict[str, Any]:
    _require_index()
    return build_report(state.index, state.store, state.config)
