"""FastAPI 介面。互動式文件頁在 /docs。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query
from fastapi import Path as FPath
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

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
from .graph import MAX_DEPTH, neighbors as expand_neighbors
from .grep import DEFAULT_MAX_RESULTS, InvalidPattern, ScopeRequired, UnknownScope, grep as run_grep
from .index import INDEX_FORMAT_VERSION, Index
from .layers import LayeredOutcome, LayeredSearcher, UnknownIndex
from .runtime import Runtime
from .schemas import (
    SEARCH_EXAMPLES,
    TAXONOMY_EXAMPLES,
    ConceptOut,
    ConceptsOut,
    FeedbackOut,
    GrepOut,
    HealthOut,
    LayeredSearchOut,
    NeighborsOut,
    ReportOut,
    SearchOut,
    StatsOut,
    TaxonomyOut,
    VersionOut,
)
from .search import ModeUnavailable, SearchOutcome
from .taxonomy import TaxonomyNotFound
from .telemetry import TelemetryStore, build_report

#: API 版本。功能端點全部掛在這個前綴之下；/healthz 與 /version 不版本化，
#: 因為它們描述的是服務本身而非 API 契約——監控不該因 API 改版而失效。
API_VERSION = "v1"

#: `compare` 不再是 /search 的模式值——多模式並排是獨立端點（/v1/compare），
#: 因為它固定在單一索引內，而 /search 是跨層的。把兩者塞進同一個參數，
#: 「compare + 分層」會變成一個沒有意義卻仍會回應的組合。
ModeParam = Literal["A", "B", "C", "D", "E"]
DirectionParam = Literal["out", "in", "both"]

#: 分類依 agent 的工作流切分，所以分組本身就是使用指引。
TAGS_METADATA = [
    {
        "name": "retrieval",
        "description": (
            "**找到 concept。** `search` 分層回傳——每一類知識一個索引，各自的結果與分數，"
            "不跨層排序。只回摘要清單，不含內容：由你決定讀哪幾份完整文件。\n\n"
            "`taxonomy` 是查表不是檢索，查無條目就是查無條目。"
            "`grep` 必須先有範圍，範圍取自 `search` 結果的 `bundle_id`。"
        ),
    },
    {
        "name": "content",
        "description": (
            "**取得內容與資產。** 從 `retrieval` 拿到 `concept_id` 之後用這一組。"
            "`concept_id` 會自動解析到它所屬的層——你不必記得它是從哪一層來的。"
            "一次要讀多份請用批次端點，不要逐筆呼叫。"
        ),
    },
    {
        "name": "graph",
        "description": (
            "**沿 `related` 導航。** `direction=in` 回傳「誰指向這個 concept」，"
            "那是排查復發問題時最需要、卻無法自己拼出來的資訊。\n\n"
            "關聯只在**同一層之內**解析：指向其他層的 `related` 會列在 `dangling`。"
        ),
    },
    {
        "name": "telemetry",
        "description": (
            "**量測與回饋。** `compare` 服務的是 A–E 消融實驗，不是日常檢索——"
            "agent 不需要呼叫這一組。`/report` 的輸出不含任何語料內容，可安全分享。"
        ),
    },
    {
        "name": "ops",
        "description": (
            "**服務與語料狀態。** 先打 `/v1/stats` 就知道有哪些層、各層叫什麼、"
            "各層可用哪些模式。`/healthz` 與 `/version` 不帶版本前綴，"
            "因為監控與部署不該因 API 改版而失效。"
        ),
    },
]


class ConceptsIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                # 跨層混著送沒問題：每個 id 會自動解析到它所屬的層。
                # 重複的 id 只回一次，不存在的落在 errors。
                "concept_ids": ["cpt_6ba20e237aea", "cpt_16cccf646981"],
                "include_raw": True,
            }
        }
    )

    concept_ids: list[str] = Field(
        ..., min_length=1, max_length=MAX_BATCH, description=f"concept id 陣列，最多 {MAX_BATCH} 筆"
    )
    include_raw: bool = Field(True, description="是否包含原始 markdown 全文；false 省下大量 context")


class FeedbackIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query_id": "709fac89a8074523",
                "concept_id": "cpt_6ba20e237aea",
                "rank": 1,
                "mode": "C",
                "index": "cases",
                "action": "click",
            }
        }
    )

    query_id: str = Field(..., description="來自 /search 回應的查詢識別碼")
    concept_id: str = Field(..., description="被點選的 concept id")
    rank: int = Field(
        ...,
        ge=1,
        description=(
            "被點選項目在**它自己那一層內**的排名。"
            "用跨層合併後的位置會讓排名分佈反映層的順序，而不是相關性。"
        ),
    )
    mode: Literal["A", "B", "C", "D", "E"] = Field(..., description="該結果來自哪個模式")
    index: Optional[str] = Field(None, description="該結果來自哪個索引；省略則由 concept_id 推定")
    action: str = Field("click", description="動作類型")


class _State:
    config: Config
    runtime: Runtime
    store: TelemetryStore
    loaded: bool = False
    error: str | None = None

    @property
    def layered(self) -> LayeredSearcher:
        return self.runtime.layered

    @property
    def indexes(self) -> dict[str, Index]:
        return {name: s.index for name, s in self.runtime.layered.searchers.items()}


state = _State()


def _load_state() -> None:
    state.loaded = False
    state.error = None
    try:
        # 與 MCP server 共用同一條載入路徑——複製一份必然分歧
        rt = Runtime.load()
        state.config = rt.config
        state.runtime = rt
        state.store = rt.store
        state.loaded = True
    except Exception as exc:  # 啟動失敗不應讓服務無法回應 /healthz
        state.error = f"{type(exc).__name__}: {exc}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_state()
    yield


app = FastAPI(
    title="yedai — 分層檢索",
    description=(
        "查案知識的分層檢索。每一類知識是一個**獨立索引**，各自持有自己的詞彙與實體"
        "統計——`df`、`avg_field_len`、實體 idf 都不跨層共用。\n\n"
        "### 為什麼分層\n\n"
        "混在一份統計裡，持續累積的那一層每長大一次，其他層的排名就漂移一次——"
        "沒有任何變更、沒有任何測試會紅，檢索品質卻退化了。查詢時加過濾條件解不了："
        "過濾只影響誰參與排序，碰不到 idf。\n\n"
        "### `/v1/search` 預設不給你一份混好的排序\n\n"
        "RRF 融合的前提是**兩份排名在回答同一個問題**。跨模式（C 與 D）滿足；"
        "跨索引不滿足——「這篇心法比那筆已結案更相關」不是有意義的命題。\n\n"
        "所以回應是 `layers[]`，每層一筆。**空的層仍會回傳**：某層沒有命中，意思是"
        "「這類知識裡沒有對應的東西」，那本身是資訊，不是「沒找到」。\n\n"
        "`fuse=true` 可取得跨層 RRF 融合清單，供對照；它不是預設。\n\n"
        "### 五個檢索模式\n\n"
        "| 模式 | 內容 | 隔離的變因 |\n"
        "|---|---|---|\n"
        "| **A** | 天真 BM25F（`XTR-05` 被切成 `xtr`+`05`） | 水位線 |\n"
        "| **B** | A + 識別碼保護斷詞 | 斷詞層的貢獻 |\n"
        "| **C** | B + 實體字典匹配加權 | 字典的額外貢獻 |\n"
        "| **D** | 純稠密向量 | 關鍵字腿整個落空的那些查詢 |\n"
        "| **E** | RRF(C, D) | 融合的額外貢獻 |\n\n"
        "沒有向量時 D/E 是**不可用**而非退化成 C——靜默退化會讓報告顯示"
        "「稠密腿沒有帶來差異」，而真相是它根本沒有執行。各層目前可用哪些模式，"
        "見 `/v1/stats` 的 `available_modes`。\n\n"
        "### 建議流程\n\n"
        "```\n"
        "GET /v1/stats                      先知道有哪些層\n"
        "  └─ GET /v1/search?q=…            分層檢索，跨層挑 3~7 筆\n"
        "       └─ POST /v1/concepts        批次取全文\n"
        "            ├─ GET …/neighbors     沿 related 展開\n"
        "            └─ GET /v1/grep        在已縮小的範圍裡字面搜尋\n"
        "```\n\n"
        "`/v1/report` 產出的統計報告不含任何語料內容，可安全分享。"
    ),
    version=__version__,
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

#: 功能端點統一掛前綴——不逐一改寫十個裝飾器；日後開 /v2 只是再掛一個 router。
router = APIRouter(prefix=f"/{API_VERSION}")

_ERROR_DESCRIPTIONS = {
    403: "路徑違反約束（逸出 bundle，或不在允許的資產目錄之下）",
    404: "查無此資源",
    410: "資源曾經存在但語料已變動——需重建索引",
    500: "索引中的路徑異常",
    503: "索引未載入",
}


def _errs(*codes: int) -> dict[int, dict[str, str]]:
    """把實際會回傳的錯誤碼宣告進 OpenAPI。

    不宣告的話文件頁只會顯示 200/422，與實際行為不符——而這份 schema
    正是 agent 與呼叫端唯一的契約來源。
    """
    return {c: {"description": _ERROR_DESCRIPTIONS[c]} for c in codes}


def _require_index() -> None:
    if not state.loaded:
        raise HTTPException(status_code=503, detail=f"索引未載入：{state.error or '未知原因'}")


def _owning_index(concept_id: str) -> Index:
    """哪一個索引持有這個 concept。

    以 concept_id 解析而不是要呼叫端多帶一個 `index` 參數：agent 從分層檢索
    拿到 id 之後，不該還要記得它是從哪一層來的。

    各層語料應該互斥。真的重複時取宣告順序的第一層——結果對不對是一回事，
    每次呼叫給出不同答案是另一回事。重複量由 `/v1/stats` 的 `id_overlap` 揭露。
    """
    owner = state.layered.owner_of(concept_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"unknown concept_id: {concept_id}")
    return state.indexes[owner]


def _scoped_index(bundle_ids: list[str], concept_ids: list[str]) -> Index:
    """grep 的範圍落在哪一個索引。跨索引的範圍是錯誤，不是要合併的東西——
    兩層的 bundle 一起 grep，回傳的行號與路徑會來自兩份不同的語料。"""
    if not bundle_ids and not concept_ids:
        # 完全沒給範圍時不在這裡報錯：交給 grep 自己回 ScopeRequired。
        # 「沒給範圍」與「範圍不存在」是兩種不同的錯誤，處置也不同。
        return next(iter(state.indexes.values()))
    owners: dict[str, Index] = {}
    for name, index in state.indexes.items():
        if any(index.has(cid) for cid in concept_ids) or any(
            b in index.bundle_roots for b in bundle_ids
        ):
            owners[name] = index
    if not owners:
        raise HTTPException(
            status_code=404, detail="範圍不屬於任何已載入的索引（bundle_id / concept_id 都比對不到）"
        )
    if len(owners) > 1:
        raise HTTPException(
            status_code=422,
            detail=f"範圍跨越多個索引（{sorted(owners)}）；請分別查詢，跨索引的結果無法合併解讀",
        )
    return next(iter(owners.values()))


def _layer_payload(outcome: "LayeredOutcome", query_id: str, requested: str | None) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "query": outcome.query,
        "shape": outcome.shape,
        "requested_index": requested,
        "layers": [
            {
                "index": lr.index,
                "mode": lr.mode,
                "candidates": lr.candidates,
                "prepared_query": lr.prepared_query,
                "hits": [h.to_dict() for h in lr.hits],
            }
            for lr in outcome.layers
        ],
        # 序列化一律走 FusedHit.to_dict()——各處自己拼一次，遲早有一處把 hit
        # 展開在融合欄位之後，而那會靜默蓋掉 rank 與 score。
        "fused": (None if outcome.fused is None else [fh.to_dict() for fh in outcome.fused]),
    }


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


@app.get(
    "/healthz",
    summary="健康檢查（不版本化）",
    tags=["ops"],
    response_model=HealthOut,
    response_model_exclude_unset=True,
)
def healthz() -> dict[str, Any]:
    return {"status": "ok", "index_loaded": state.loaded, "error": state.error}


@app.get(
    "/version",
    summary="版本資訊（不版本化）",
    tags=["ops"],
    response_model=VersionOut,
    response_model_exclude_unset=True,
)
def version() -> dict[str, Any]:
    """索引未載入時仍須可回應——這個端點的用途之一就是診斷載入失敗。"""
    loaded = state.indexes if state.loaded else {}
    return {
        "package": __version__,
        "api": API_VERSION,
        # 本程式支援的索引格式 vs 目前載入索引的格式：兩者無對應關係，
        # 而「支援 v8、載入的是 v7」正是最需要一眼看出的除錯情境。
        "index_format": INDEX_FORMAT_VERSION,
        "indexes": {
            name: {"format_version": idx.format_version, "signature": idx.signature}
            for name, idx in sorted(loaded.items())
        },
    }


@router.get(
    "/stats",
    summary="語料統計與索引狀態",
    tags=["ops"],
    response_model=StatsOut,
    response_model_exclude_unset=True,
    responses=_errs(503),
)
def stats() -> dict[str, Any]:
    _require_index()
    per_index: dict[str, Any] = {}
    for name, index in sorted(state.indexes.items()):
        s = index.stats
        spec = state.config.index_spec(name)
        per_index[name] = {
            # 索引名稱是設定檔裡的任意鍵。沒有這兩句，呼叫端只能從名字猜這層是什麼。
            "description": spec.description,
            "when_to_use": spec.when_to_use,
            "bundles": s.bundles,
            "concepts": s.concepts,
            "avg_concept_chars": round(s.avg_concept_chars, 1),
            "avg_figures_per_concept": round(s.avg_figures, 2),
            "vocab_naive": s.vocab_naive,
            "vocab_protected": s.vocab_protected,
            "entities_total": s.entities_total,
            "entities_from_dictionary": s.entities_dict,
            "entities_from_regex_fallback": s.entities_regex,
            # 依類型拆解：全域比例把「字典是唯一來源」的類型（缺陷名）與
            # 「字典只是白名單」的類型（機台）平均在一起，數字因此無法解讀
            "entities_by_type": s.entities_by_type,
            "dangling_related": s.dangling_related,
            "parse_skipped": s.parse_skipped,
            "parse_warnings": s.parse_warnings,
            "types": s.types,
            "index_signature": index.signature,
            "available_modes": list(state.layered.searchers[name].available_modes),
        }
    return {
        "indexes": sorted(state.indexes),
        "by_index": per_index,
        "taxonomy": state.runtime.taxonomy.coverage(),
        # 各層語料應互斥。非零代表上游有重複收錄或 id 沒有跨語料唯一——
        # 它造成的錯誤全部是靜默的，所以要在這裡看得見。
        "id_overlap": state.layered.id_overlap.to_dict(),
        # 沒寫說明的層——呼叫端只能從名字猜，讓它知道自己在猜
        "indexes_without_description": state.config.undescribed_indexes(),
    }


@router.get(
    "/search",
    summary="查詢（分層回傳；可指定單一索引）",
    description=(
        "**預設分層回傳**：每個索引各自的結果、各自的分數，不跨層排序。\n\n"
        "不混成一份排序，是因為 RRF 融合的前提是兩份排名在回答同一個問題——"
        "跨模式滿足，跨索引不滿足。「這篇心法比那筆已結案更相關」不是有意義的命題。\n\n"
        "無命中的層仍會出現在 `layers` 中且 `hits` 為空：**層的缺席本身是訊號**，"
        "省略它會讓「這一層沒有相關知識」與「排在回傳筆數之外」不可區分。\n\n"
        "`index` 指定單一索引；`fuse=true` 額外附上跨索引平權 RRF 融合清單，"
        "每一筆帶來源索引與層內名次。`mode` 與 `k` 省略時各層用自己宣告的預設。"
    ),
    tags=["retrieval"],
    response_model=LayeredSearchOut,
    response_model_exclude_unset=True,
    responses={
        **_errs(503),
        200: {"content": {"application/json": {"examples": SEARCH_EXAMPLES}}},
    },
)
def search(
    q: str = Query(
        ...,
        min_length=1,
        description="查詢字串",
        examples=["XTR-05 的 PARTICLE 問題", "overlay 偏移要怎麼查"],
    ),
    index: Optional[str] = Query(
        None,
        description="索引名稱（見 /v1/stats 的 indexes）；省略則分層檢索全部。"
        "不確定要查哪一層時**不要指定**——分層全查會讓你看見別層也有東西",
        examples=["cases"],
    ),
    mode: Optional[ModeParam] = Query(
        None, description="A / B / C / D / E；省略則用各層宣告的預設", examples=["C"]
    ),
    k: Optional[int] = Query(
        None, ge=1, le=100, description="回傳筆數；省略則用各層宣告的深度", examples=[10]
    ),
    fuse: bool = Query(False, description="是否附上跨索引 RRF 融合清單。分層結構仍然保留"),
) -> dict[str, Any]:
    _require_index()
    try:
        outcome = state.layered.search(q, index=index, mode=mode, k=k, fuse=fuse)
    except UnknownIndex as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except (ModeUnavailable, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    query_id = state.store.log_layered(outcome, requested_index=index)
    return _layer_payload(outcome, query_id, index)


@router.get(
    "/compare",
    summary="單一索引內的多模式並排（消融實驗）",
    description=(
        "對同一查詢並排執行各可用模式，並回傳模式間重疊度。\n\n"
        "**固定在單一索引內**：跨索引比模式是在比兩件不同的事，重疊度會變成"
        "「這兩層語料有多像」而不是「這個干預有沒有作用」。"
    ),
    tags=["telemetry"],
    response_model=SearchOut,
    response_model_exclude_unset=True,
    responses=_errs(503),
)
def compare(
    q: str = Query(..., min_length=1, description="查詢字串", examples=["XTR-05 PARTICLE"]),
    index: Optional[str] = Query(
        None, description="索引名稱；只有一個索引時可省略", examples=["cases"]
    ),
    k: Optional[int] = Query(None, ge=1, le=100, description="回傳筆數", examples=[10]),
) -> dict[str, Any]:
    _require_index()
    try:
        searcher = state.runtime.searcher(index)
    except (UnknownIndex, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    outcome = searcher.compare(q, k)
    query_id = state.store.log_query(outcome, requested_mode="compare", index=searcher.name)
    payload = _outcome_payload(outcome, query_id, "compare")
    payload["index"] = searcher.name
    return payload


@router.get(
    "/taxonomy/{defect}",
    summary="以 defect 為鍵取回 taxonomy 條目",
    description=(
        "**這是查表，不是檢索。** 查無條目回 404，不做近似比對——"
        "拿另一個 defect 的判斷方法去解讀影像，比沒有方法更糟，"
        "因為錯的方法看起來跟對的一樣有條理。\n\n"
        "條目內容是**方法不是答案**：它說明怎麼從影像推出候選 module。"
    ),
    tags=["retrieval"],
    response_model=TaxonomyOut,
    response_model_exclude_unset=True,
    responses={
        **_errs(404, 503),
        200: {"content": {"application/json": {"examples": TAXONOMY_EXAMPLES}}},
    },
)
def taxonomy(
    defect: str = FPath(..., description="defect 識別碼；精確比對", examples=["DEFECT_ALPHA"]),
) -> dict[str, Any]:
    _require_index()
    try:
        return state.runtime.taxonomy.get(defect).to_dict()
    except TaxonomyNotFound:
        raise HTTPException(
            status_code=404, detail=f"taxonomy 沒有 {defect!r} 的條目"
        ) from None


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
    response_model=ConceptsOut,
    response_model_exclude_unset=True,
    responses=_errs(503),
)
def concepts(payload: ConceptsIn = Body(...)) -> dict[str, Any]:
    _require_index()
    # 各層語料不重疊，所以 id 可以直接解析到它所屬的索引；呼叫端不必記得
    # 這批 id 分別來自哪一層——那正是分層之後最容易產生的摩擦。
    # 先決定每個 id 歸屬哪一層，再逐層批次取——不先歸屬的話，跨層重複的 id
    # 會被每一層各取一次，`returned` 因此大於 `requested`。
    by_layer: dict[str, list[str]] = {}
    missing: list[str] = []
    for cid in dict.fromkeys(payload.concept_ids):  # 去重但保序
        owner = state.layered.owner_of(cid)
        if owner is None:
            missing.append(cid)
        else:
            by_layer.setdefault(owner, []).append(cid)

    found: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = [
        {"concept_id": cid, "reason": "not_found", "detail": "不在任何已載入的索引中"}
        for cid in missing
    ]
    for name, ids in by_layer.items():
        got, errs = load_concepts(state.indexes[name], ids, include_raw=payload.include_raw)
        found.extend(got)
        errors.extend(errs)
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
    responses=_errs(403, 404, 503),
)
def asset(
    concept_id: str = FPath(..., examples=["cpt_6ba20e237aea"]),
    path: str = Query(
        ...,
        min_length=1,
        description="相對於 concept 檔案的資產路徑；直接用 /v1/concept/{id} 回傳的 assets 陣列中的值",
        examples=["_assets/slide_001.png"],
    ),
    download: bool = Query(False, description="true 則以附件下載，否則內嵌顯示"),
) -> FileResponse:
    _require_index()
    try:
        resolved = resolve_asset(
            _owning_index(concept_id), concept_id, path, state.config.asset_dirs
        )
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
    response_model=NeighborsOut,
    response_model_exclude_unset=True,
    responses=_errs(404, 503),
)
def neighbors(
    concept_id: str = FPath(..., examples=["cpt_6ba20e237aea"]),
    depth: int = Query(1, ge=1, le=MAX_DEPTH, description="展開跳數", examples=[1]),
    direction: DirectionParam = Query("both", description="out=我指向誰 / in=誰指向我 / both"),
) -> dict[str, Any]:
    _require_index()
    try:
        # 關聯邊不跨索引解析（見 index._build_related_edges），所以展開只在
        # 持有它的那一層之內進行。跨層的 related 會出現在 dangling。
        return expand_neighbors(
            _owning_index(concept_id), concept_id, depth=depth, direction=direction
        )
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
    response_model=GrepOut,
    response_model_exclude_unset=True,
    responses=_errs(404, 503),
)
def grep(
    pattern: str = Query(..., min_length=1, description="搜尋樣式", examples=["PARTICLE"]),
    bundle_id: list[str] = Query(
        default=[], description="限定 bundle，可重複；取自 search 結果的 bundle_id",
        examples=[["bdl_922a0c8479f1"]],
    ),
    concept_id: list[str] = Query(default=[], description="限定 concept，可重複"),
    regex: bool = Query(False, description="是否以正則比對"),
    ignore_case: bool = Query(False, description="是否忽略大小寫"),
    max_results: int = Query(DEFAULT_MAX_RESULTS, ge=1, le=1000, description="結果筆數上限"),
) -> dict[str, Any]:
    _require_index()
    try:
        return run_grep(
            _scoped_index(bundle_id, concept_id),
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
    response_model=ConceptOut,
    response_model_exclude_unset=True,
    responses=_errs(404, 410, 500, 503),
)
def concept(
    concept_id: str = FPath(..., description="來自 search 結果的 concept_id",
                            examples=["cpt_6ba20e237aea"]),
) -> dict[str, Any]:
    _require_index()
    try:
        return load_concept(_owning_index(concept_id), concept_id)
    except ConceptNotFound:
        raise HTTPException(status_code=404, detail=f"unknown concept_id: {concept_id}") from None
    except ConceptPathEscape as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None
    except ConceptFileMissing as exc:
        # 410 而非 404：這個 concept 曾經存在，是語料變動了，處置方式是重建索引
        raise HTTPException(status_code=410, detail=str(exc)) from None


@router.post(
    "/feedback",
    summary="記錄點選回饋",
    tags=["telemetry"],
    response_model=FeedbackOut,
    response_model_exclude_unset=True,
    responses=_errs(404, 503),
)
def feedback(payload: FeedbackIn = Body(...)) -> dict[str, Any]:
    _require_index()
    # 省略 index 時由 concept_id 推定——各層語料不重疊，所以這是明確的，
    # 而要求前端記住來源層只會讓回饋更難收集，那是目前最缺的資料。
    index_name = payload.index
    if index_name is None:
        index_name = state.layered.owner_of(payload.concept_id)
        if index_name is None:
            raise HTTPException(
                status_code=404, detail=f"unknown concept_id: {payload.concept_id}"
            )
    elif index_name not in state.indexes:
        raise HTTPException(
            status_code=422,
            detail=f"未宣告的索引名稱 {index_name!r}；可用的有 {sorted(state.indexes)}",
        )
    try:
        state.store.log_feedback(
            query_id=payload.query_id,
            concept_id=payload.concept_id,
            rank=payload.rank,
            mode=payload.mode,
            action=payload.action,
            index=index_name,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown query_id: {payload.query_id}") from exc
    return {"status": "recorded", "query_id": payload.query_id, "index": index_name}


@router.get(
    "/report",
    summary="去識別化統計報告（可安全分享）",
    tags=["telemetry"],
    response_model=ReportOut,
    response_model_exclude_unset=True,
    responses=_errs(503),
)
def report() -> dict[str, Any]:
    _require_index()
    return build_report(
        state.indexes,
        state.store,
        state.config,
        taxonomy=state.runtime.taxonomy,
        id_overlap=state.layered.id_overlap.to_dict(),
    )


app.include_router(router)
