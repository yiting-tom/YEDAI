"""HTTP 回應模型。

集中在這裡而不是散在 `api.py`——端點函式應該讀起來是「這個端點做什麼」，
不是「這個端點回什麼欄位」。

**這些模型只描述既有輸出，不改變它。** 若模型與實際回應不符，那是模型寫錯了。
每個模型都設 `extra="allow"`：回應由手寫的 dict 組出，漏列一個欄位不該讓它被靜默裁掉——
少一個欄位的回應比缺一份 schema 危險得多。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

#: 範例用的層名。它們是**設定宣告的 schema 識別**，不是語料內容——
#: 範例裡出現的每一個值都必須是這種等級，否則 /docs 就成了洩漏管道。
#: 識別碼與缺陷名沿用 `dictionary.example.yaml` 的編造值。
_L_HEUR, _L_CASES = "heuristics", "cases"


def _out(example: dict) -> ConfigDict:
    """帶範例的回應模型設定。

    範例不是裝飾：`/docs` 是呼叫端唯一會讀的東西，一個「Example Value」比三段
    散文更快講清楚 `layers[]` 長什麼樣、空層為什麼還在裡面。
    `extra="allow"` 必須一起帶——漏掉它，回應多出來的欄位會被靜默裁掉。
    """
    return ConfigDict(extra="allow", json_schema_extra={"example": example})


_HIT_EXAMPLE = {
    "rank": 1,
    "concept_id": "cpt_6ba20e237aea",
    "bundle_id": "bdl_922a0c8479f1",
    "type": "case_investigation",
    "title": "XTR-05 PARTICLE 調查",
    "description": "XTR-05 於 CVD 出現 PARTICLE，依 A-flow 流程檢討。",
    "path": "okf/yed-deck-003-02.md",
    "score": 0.8421,
    "lexical_score": 0.7310,
    "entity_score": 0.9155,
    "index_line": "cpt_6ba20e237aea . case_investigation . [yed-deck-003-02.md](okf/yed-deck-003-02.md) . XTR-05 於 CVD 出現 PARTICLE，依 A-flow 流程檢討。",
}


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


# --- 共用 ---


class Distribution(_Out):
    """分佈統計。無資料時只有 `n=0`，其餘欄位不存在。"""

    n: int
    min: Optional[float] = None
    p25: Optional[float] = None
    median: Optional[float] = None
    p75: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None


class EntityRef(_Out):
    type: str = Field(description="實體類型；未命中字典者為 unknown")
    canonical: str = Field(description="正規名稱")
    raw: str = Field(description="原文中的實際寫法")
    source: str = Field(description="dict=命中字典 / regex=僅符合識別碼樣式")


# --- retrieval：search ---


class HitOut(_Out):
    model_config = _out(_HIT_EXAMPLE)

    rank: int
    concept_id: str
    bundle_id: str
    type: str
    title: str
    description: str
    path: str
    score: float = Field(description="最終分數；模式 C 為兩腿融合後的結果")
    lexical_score: float = Field(description="詞彙腿分數")
    entity_score: float = Field(description="實體腿分數；僅模式 C 非零")
    index_line: str = Field(description="可直接貼進 context 的單行摘要")


class ModeResultOut(_Out):
    mode: str
    candidates: int = Field(description="進入計分的候選數，非回傳筆數")
    hits: list[HitOut]


class OverlapOut(_Out):
    pair: str = Field(description="模式組合，如 A-B")
    jaccard: float
    kendall_tau: Optional[float] = Field(default=None, description="交集少於兩筆時為 null")
    common: int


class LayerOut(_Out):
    """一層的結果。`hits` 為空時這一層仍然出現在回應中——**層的缺席本身是訊號**，
    省略它會讓「這一層沒有相關知識」與「排在回傳筆數之外」不可區分。"""

    model_config = _out(
        {
            "index": _L_CASES,
            "mode": "C",
            "candidates": 137,
            "prepared_query": "XTR-05 的 PARTICLE 問題",
            "hits": [_HIT_EXAMPLE],
        }
    )

    index: str = Field(description="這一層的索引名稱")
    mode: str
    candidates: int = Field(description="進入計分的候選數，非回傳筆數")
    prepared_query: str = Field(
        description="這一層實際收到的查詢（前處理後）。與 query 不同時，"
        "表示該層宣告了剝除識別碼之類的前處理"
    )
    hits: list[HitOut]


class FusedHitOut(HitOut):
    """跨索引融合的一筆。融合分數看不出來源深淺，`source_rank` 看得出來。"""

    model_config = _out(
        {
            **_HIT_EXAMPLE,
            # `rank` 與 `score` 是**融合後**的值，覆蓋 hit 自己的層內值。
            # score = 1/(rrf_k + source_rank) = 1/(60+1)
            "rank": 1,
            "index": _L_CASES,
            "source_rank": 1,
            "score": 0.01639344,
        }
    )

    index: str = Field(description="這一筆來自哪一層")
    source_rank: int = Field(description="它在自己那一層內的名次")


class LayeredSearchOut(_Out):
    """分層檢索回應。預設不跨層排序——RRF 融合的前提是兩份排名在回答同一個問題，
    跨模式滿足，跨索引不滿足。"""

    model_config = _out(
        {
            "query_id": "709fac89a8074523",
            "query": "XTR-05 的 PARTICLE 問題",
            "shape": "layered",
            "requested_index": None,
            "layers": [
                {
                    "index": _L_HEUR,
                    "mode": "D",
                    "candidates": 0,
                    # 這一層宣告了剝除識別碼：帶著機台編號去查「這類問題怎麼追」，
                    # 比對到的是一個跟問題無關的字串。
                    "prepared_query": "的 PARTICLE 問題",
                    # 空層仍然回傳。這代表「心法裡沒有對應的查法」，
                    # 與「排在 k 之外」是兩件事——省略它就分不出來了。
                    "hits": [],
                },
                {
                    "index": _L_CASES,
                    "mode": "C",
                    "candidates": 137,
                    "prepared_query": "XTR-05 的 PARTICLE 問題",
                    "hits": [_HIT_EXAMPLE],
                },
            ],
            "fused": None,
        }
    )

    query_id: str = Field(description="送 /v1/feedback 時要帶回這個值")
    query: str
    shape: str = Field(description="layered 或 fused；遙測據此分開統計，兩者的名次不可比")
    requested_index: Optional[str] = Field(
        default=None, description="呼叫端指定的索引；未指定時為 null（分層全查）"
    )
    layers: list[LayerOut] = Field(description="每個索引一筆，含無命中的層")
    fused: Optional[list[FusedHitOut]] = Field(
        default=None,
        description=(
            "跨層平權 RRF 融合清單，每筆帶來源索引與層內名次。\n\n"
            "**未要求融合時是 `null`，不是 `[]`**——空清單會讓「沒要求融合」與"
            "「融合後沒有結果」不可區分。\n\n"
            "（OpenAPI 會把 `null` 從範例中剔除，所以預設那個範例裡看不到這個欄位。"
            "要看它長什麼樣，切到「跨層融合」那個範例。）"
        ),
    )


#: `/v1/search` 的兩個具名範例。Swagger 會渲染成下拉選單——兩種形態並排看，
#: 比一段散文更快講清楚「預設不融合」與「融合長什麼樣」的差別。
SEARCH_EXAMPLES: dict[str, dict[str, Any]] = {
    "layered": {
        "summary": "分層（預設）——含一個空層",
        "description": (
            "心法層沒有命中，但**它仍然出現在 `layers` 裡**。那代表「這類問題沒有"
            "既定查法」，跟「排在 k 之外」是兩件事。\n\n"
            "注意 `prepared_query`：心法層宣告了剝除識別碼，所以它實際查的不是原字串。"
        ),
        "value": LayeredSearchOut.model_config["json_schema_extra"]["example"],
    },
    "fused": {
        "summary": "跨層融合（fuse=true）——分層結構仍然保留",
        "description": (
            "融合之後就看不出某一層是不是整個沒東西了，所以 `layers` 不會被取代。\n\n"
            "`score` 是 RRF 值 `1/(60 + source_rank)`，只由層內名次決定；"
            "`source_rank` 讓你看得出這一筆在自己那層排多前面。"
        ),
        "value": {
            **LayeredSearchOut.model_config["json_schema_extra"]["example"],
            "shape": "fused",
            "fused": [
                {
                    **_HIT_EXAMPLE,
                    "rank": 1,
                    "index": _L_CASES,
                    "source_rank": 1,
                    "score": 0.01639344,
                },
                {
                    **_HIT_EXAMPLE,
                    "concept_id": "cpt_e14ff646b176",
                    "title": "overlay 偏移的查法",
                    "type": "heuristic",
                    "rank": 2,
                    "index": _L_HEUR,
                    # 兩層各自的第 1 名分數相同——平權的意思就是每類知識都派代表出席
                    "source_rank": 1,
                    "score": 0.01639344,
                },
            ],
        },
    },
}


class SearchOut(_Out):
    """單一索引內的多模式並排（消融實驗）。日常檢索請用 `LayeredSearchOut`。"""

    model_config = _out(
        {
            "query_id": "3c0adccf2b4b9565",
            "query": "XTR-05 PARTICLE",
            "index": _L_CASES,
            "requested_mode": "compare",
            "k": 10,
            # 呈現順序隨機化，降低並排時的位置偏差；日誌會記下實際順序
            "display_order": ["C", "A", "B"],
            "entities": [
                {"type": "tool_id", "canonical": "XTR-05", "raw": "XTR-05", "source": "dict"},
                {"type": "defect_code", "canonical": "PARTICLE", "raw": "PARTICLE", "source": "dict"},
            ],
            "results": {
                "C": {"mode": "C", "candidates": 137, "hits": [_HIT_EXAMPLE]},
            },
            "overlaps": [
                # jaccard 接近 1 代表該干預沒有實際作用。
                # kendall_tau 在共同項目少於兩個時為 null。
                {"pair": "A-B", "jaccard": 0.428, "kendall_tau": 0.667, "common": 3},
                {"pair": "B-C", "jaccard": 0.818, "kendall_tau": 0.900, "common": 9},
            ],
        }
    )

    query_id: str = Field(description="送 /v1/feedback 時要帶回這個值")
    query: str
    index: Optional[str] = Field(default=None, description="這次消融所在的索引")
    requested_mode: str
    k: int
    display_order: Optional[list[str]] = Field(
        default=None, description="三模式並排時的隨機呈現順序，用於降低位置偏差"
    )
    entities: list[EntityRef]
    results: dict[str, ModeResultOut] = Field(description="模式代號 → 該模式的結果")
    overlaps: list[OverlapOut] = Field(description="僅 compare 模式非空")


# --- content ---


class FigureOut(_Out):
    file_id: str
    type: str
    title: str
    description: str
    key_points: list[str]


class SectionOut(_Out):
    index: int
    heading: str
    text: str


class ConceptOut(_Out):
    model_config = _out(
        {
            "concept_id": "cpt_6ba20e237aea",
            "bundle_id": "bdl_922a0c8479f1",
            "type": "case_investigation",
            "title": "XTR-05 PARTICLE 調查",
            "slug": "yed-deck-003-02",
            "description": "XTR-05 於 CVD 出現 PARTICLE，依 A-flow 流程檢討。",
            "path": "okf/yed-deck-003-02.md",
            "index_line": "cpt_6ba20e237aea . case_investigation . [yed-deck-003-02.md](okf/yed-deck-003-02.md) . XTR-05 於 CVD 出現 PARTICLE，依 A-flow 流程檢討。",
            "confidence": "high",
            "timestamp": "2026-03-14T00:00:00+00:00",
            "resource": "file://yed-deck-003.pptx#slide=2,5",
            "provenance": "file://yed-deck-003.pptx#slide=2,5",
            "subpath": "case_investigation/yed-deck-003-02",
            "content_hash": "9bb54f092a135bb5",
            "model": "synthetic-generator-0.1",
            # 布林，不是字串。這裡曾誤宣告成 str，導致所有內容端點對
            # `generated: true` 的語料回 500。
            "generated": True,
            "tags": ["particle", "yield", "review"],
            # 只在同一層之內解析；指向其他層的 id 會列在 neighbors 的 dangling
            "related": ["cpt_16cccf646981"],
            # 直接餵給 /v1/concept/{id}/asset 的 path 參數，不需要任何轉換
            "assets": ["_assets/slide_002.png", "_assets/slide_005.png"],
            "figures": [
                {
                    "file_id": "slide_002",
                    "type": "wafer_map",
                    "title": "缺陷分佈",
                    "description": "邊緣環狀集中。",
                    "key_points": ["邊緣集中", "右下象限較密"],
                }
            ],
            "sections": [
                {"index": 0, "heading": "背景", "text": "量測結果顯示 PARTICLE 密度上升。"}
            ],
            "frontmatter": {"id": "cpt_6ba20e237aea", "type": "case_investigation"},
            "raw": "---\nid: cpt_6ba20e237aea\n…\n---\n\n## 背景\n\n量測結果顯示 PARTICLE 密度上升。\n",
        }
    )

    concept_id: str
    bundle_id: str
    type: str
    title: str
    slug: str
    description: str
    path: str
    index_line: str
    confidence: Optional[str] = None
    timestamp: Optional[str] = None
    resource: Optional[str] = None
    provenance: Optional[str] = None
    subpath: Optional[str] = None
    content_hash: Optional[str] = None
    model: Optional[str] = None
    #: `Concept.generated` 是 `bool | None`（`parser.py` 只接受布林，其餘轉成 None）。
    #: 這裡曾誤宣告為 str，於是任何 frontmatter 有 `generated: true` 的 concept
    #: 都會讓回應驗證失敗、端點回 500——而合成語料每一篇都有這個欄位。
    generated: Optional[bool] = None
    tags: list[str]
    related: list[str]
    assets: list[str] = Field(description="可直接餵給 /v1/concept/{id}/asset 的相對路徑")
    figures: list[FigureOut]
    sections: list[SectionOut]
    frontmatter: dict[str, Any]
    raw: Optional[str] = Field(default=None, description="原始 markdown；include_raw=false 時不存在")


class ConceptErrorOut(_Out):
    concept_id: str
    reason: str = Field(description="not_found=id 打錯 / file_missing=索引過期 / path_escape")
    detail: str


class ConceptsOut(_Out):
    model_config = _out(
        {
            # 送了 3 個 id：2 個取得到，1 個打錯。部分成功不影響其餘。
            "requested": 3,
            "returned": 2,
            "concepts": [],
            "errors": [
                {
                    "concept_id": "cpt_nope",
                    "reason": "not_found",
                    "detail": "不在任何已載入的索引中",
                }
            ],
        }
    )

    requested: int
    returned: int
    concepts: list[ConceptOut]
    errors: list[ConceptErrorOut] = Field(description="部分成功：單一 id 失敗不影響其餘")


# --- graph ---


class NeighborOut(_Out):
    concept_id: str
    bundle_id: str
    type: str
    title: str
    description: str
    path: str
    index_line: str
    depth: int = Field(description="距離起點的跳數")
    direction: str = Field(description="out=起點指向它 / in=它指向起點")
    via: str = Field(description="從哪個 concept 到達")


class NeighborsOut(_Out):
    model_config = _out(
        {
            "concept_id": "cpt_6ba20e237aea",
            "depth": 1,
            "direction": "both",
            "neighbors": [
                {
                    "concept_id": "cpt_16cccf646981",
                    "bundle_id": "bdl_922a0c8479f1",
                    "type": "meeting_minutes",
                    "title": "XTR-05 RESIDUE 會議紀錄",
                    "description": "後續追蹤。",
                    "path": "okf/yed-deck-003-05.md",
                    "index_line": "cpt_16cccf646981 . meeting_minutes . [yed-deck-003-05.md](okf/yed-deck-003-05.md) . 後續追蹤。",
                    "depth": 1,
                    "direction": "in",
                    "via": "cpt_6ba20e237aea",
                }
            ],
            # 指向其他層、或指向不存在的 id，都落在這裡。
            # 關聯只在同一層之內解析——跨層的邊會讓一層的圖依賴另一層當時的內容。
            "dangling": ["cpt_ghost"],
        }
    )

    concept_id: str
    depth: int
    direction: str
    neighbors: list[NeighborOut]
    dangling: list[str] = Field(description="related 指向但語料中不存在的 id")


# --- retrieval：grep ---


class GrepScopeOut(_Out):
    bundle_ids: list[str]
    concept_ids: list[str]


class GrepMatchOut(_Out):
    concept_id: str
    bundle_id: str
    type: str
    title: str
    path: str
    line: int
    text: str


class GrepOut(_Out):
    model_config = _out(
        {
            "pattern": "PARTICLE",
            "regex": False,
            "ignore_case": False,
            # 範圍必填。先用 search 把語料縮到 2~3 個 bundle，再在那裡搜。
            "scope": {"bundle_ids": ["bdl_922a0c8479f1"], "concept_ids": []},
            "files_searched": 24,
            "files_skipped": 0,
            "max_results": 100,
            "truncated": False,
            "results": [
                {
                    "concept_id": "cpt_6ba20e237aea",
                    "bundle_id": "bdl_922a0c8479f1",
                    "type": "case_investigation",
                    "title": "XTR-05 PARTICLE 調查",
                    "path": "okf/yed-deck-003-02.md",
                    "line": 42,
                    "text": "量測結果顯示 PARTICLE 密度上升。",
                }
            ],
        }
    )

    pattern: str
    regex: bool
    ignore_case: bool
    scope: GrepScopeOut
    files_searched: int
    files_skipped: int
    max_results: int
    truncated: bool = Field(description="達到 max_results 而提前停止")
    results: list[GrepMatchOut]


# --- telemetry ---


class FeedbackOut(_Out):
    model_config = _out({"status": "recorded", "query_id": "709fac89a8074523", "index": _L_CASES})

    status: str
    query_id: str
    index: Optional[str] = Field(default=None, description="這筆點選歸屬的索引")


class ReportFeedbackOut(_Out):
    total: int
    clicked_rank_distribution: Distribution
    clicks_per_mode: dict[str, int]
    clicks_per_index: dict[str, int] = Field(
        default_factory=dict, description="索引名稱 → 點選數；排名為層內名次"
    )


class ReportOverlapOut(_Out):
    jaccard: Distribution
    kendall_tau: Distribution


class ReportOut(_Out):
    """去識別化統計報告。

    只有頂層區塊與 `Distribution` 建模，區塊內部維持開放結構——報告的指標會隨實驗
    進展增減，把每個數字都寫成欄位會讓「加一個統計」變成要同步改模型、測試與文件三處。
    schema 描述的是契約，而報告內部的指標是實驗產物，不是契約。

    內容保證：不含任何查詢原文、concept 標題／描述／路徑、實體名稱或 bundle 名稱。
    """

    report_version: int
    generated_at: str
    note: str
    by_index: dict[str, Any] = Field(
        description="索引名稱 → 該層的 corpus / entities / modes。"
        "**這是主要視角**：不同層的規模可能相差數個數量級，彙總會把它們平均掉"
    )
    corpus: dict[str, Any] = Field(
        description="跨索引彙總，只含加得起來的量。詞彙量與實體數不彙總——"
        "重疊程度未知，相加會系統性高估"
    )
    queries: dict[str, Any]
    modes: dict[str, Any] = Field(description="模式代號 → 該模式的分數與零結果統計（全部索引）")
    mode_overlap: dict[str, ReportOverlapOut] = Field(description="模式組合 → 重疊度分佈")
    retrieval_shape: dict[str, Any] = Field(
        description="分層 / 融合 / 消融各自的統計。三者的名次語意不同，不可混算"
    )
    taxonomy: Optional[dict[str, Any]] = Field(
        default=None,
        description="taxonomy 覆蓋率（有條目的 defect 佔比，依類別拆解）。"
        "只以類別名為鍵，不含 defect 名稱或條目文字",
    )
    id_overlap: Optional[dict[str, Any]] = Field(
        default=None, description="跨層重複的 concept_id 數與配對；只含層名與數量"
    )
    feedback: ReportFeedbackOut
    experiment_params: dict[str, Any] = Field(description="沒有它，任何數字都不可重現")


# --- ops ---


class HealthOut(_Out):
    model_config = _out({"status": "ok", "index_loaded": True, "error": None})

    status: str
    index_loaded: bool
    error: Optional[str] = None


class IndexRefOut(_Out):
    format_version: int
    signature: str


class VersionOut(_Out):
    model_config = _out(
        {
            "package": "0.1.0",
            "api": "v1",
            # 「本程式支援 v8、載入的索引是 v7」正是最需要一眼看出的除錯情境，
            # 所以這兩個數字刻意分開。
            "index_format": 8,
            "indexes": {
                _L_CASES: {"format_version": 8, "signature": "9648ec20b108ba66"},
                _L_HEUR: {"format_version": 8, "signature": "74a02e12884b85ed"},
            },
        }
    )

    package: str
    api: str
    index_format: int = Field(description="**本程式支援的**索引格式")
    indexes: dict[str, IndexRefOut] = Field(
        default_factory=dict, description="**目前載入的**各索引；未載入時為空物件"
    )


class IndexStatsOut(_Out):
    description: str = Field(
        description="這一層裝什麼。空字串表示設定裡沒寫——那時只能從 types 分佈推測"
    )
    when_to_use: str = Field(description="什麼情況下該查這一層")
    bundles: int
    concepts: int
    avg_concept_chars: float
    avg_figures_per_concept: float
    vocab_naive: int
    vocab_protected: int
    entities_total: int
    entities_from_dictionary: int
    entities_from_regex_fallback: int
    entities_by_type: dict[str, dict[str, int]] = Field(
        description="實體類型 → {total, dict, regex}。比例見 /v1/report——"
        "只有分母可測的類型才有 dictionary_coverage"
    )
    dangling_related: int
    parse_skipped: int
    parse_warnings: int
    types: dict[str, int]
    index_signature: str
    available_modes: list[str] = Field(
        description="這一層目前可用的模式。沒有向量時 D/E 不在此列——"
        "呼叫端因此拿得到「不可用」而不是一份看起來正常的錯結果"
    )


class StatsOut(_Out):
    model_config = _out(
        {
            "indexes": [_L_CASES, _L_HEUR],
            "by_index": {
                _L_CASES: {
                    "description": "已結案的 defect report。同格式文件，識別碼是主訊號。",
                    "when_to_use": "想知道「這個現象以前發生過什麼、最後查到哪裡」",
                    "bundles": 8,
                    "concepts": 201,
                    "avg_concept_chars": 1582.0,
                    "avg_figures_per_concept": 6.81,
                    "vocab_naive": 517,
                    "vocab_protected": 1158,
                    "entities_total": 712,
                    "entities_from_dictionary": 261,
                    "entities_from_regex_fallback": 451,
                    "entities_by_type": {"tool_id": {"total": 40, "dict": 40, "regex": 0}},
                    "dangling_related": 0,
                    "parse_skipped": 0,
                    "parse_warnings": 0,
                    "types": {"case_investigation": 137, "spec_definition": 56},
                    "index_signature": "9648ec20b108ba66",
                    "available_modes": ["A", "B", "C", "D", "E"],
                },
                _L_HEUR: {
                    "description": "查案心法。自由文字，量大，無固定格式。",
                    "when_to_use": "想知道「這類問題該從哪裡開始追」",
                    "bundles": 12,
                    "concepts": 274,
                    "avg_concept_chars": 1614.0,
                    "avg_figures_per_concept": 6.42,
                    "vocab_naive": 517,
                    "vocab_protected": 1227,
                    "entities_total": 781,
                    "entities_from_dictionary": 261,
                    "entities_from_regex_fallback": 520,
                    "entities_by_type": {"tool_id": {"total": 40, "dict": 40, "regex": 0}},
                    "dangling_related": 0,
                    "parse_skipped": 0,
                    "parse_warnings": 0,
                    "types": {"training": 220},
                    "index_signature": "74a02e12884b85ed",
                    # 這一層還沒跑過 embed，所以 D/E 不在其中——
                    # 指定它們會失敗，而不是悄悄退化成 C。
                    "available_modes": ["A", "B", "C"],
                },
            },
            "taxonomy": {
                "covered": 3,
                "total": 5,
                "unknown_keys": 0,
                "by_category": {"particle": {"covered": 1, "total": 2}},
            },
            # 各層語料應互斥。非零要當成錯誤看——它造成的問題全部是靜默的。
            "id_overlap": {"total": 0, "pairs": {}},
            "indexes_without_description": [],
        }
    )

    indexes: list[str] = Field(description="已載入的索引名稱")
    by_index: dict[str, IndexStatsOut] = Field(description="索引名稱 → 該層的語料統計")
    taxonomy: dict[str, Any] = Field(
        description="taxonomy 覆蓋率。total 為 null 表示沒有 defect 清單，"
        "亦即分母不可知——那時 covered 只說明整理了幾條，不說明還缺幾條"
    )
    indexes_without_description: list[str] = Field(
        default_factory=list,
        description="沒有在設定裡寫 description 的層。呼叫端對這些層只能從名字猜",
    )
    id_overlap: dict[str, Any] = Field(
        description="跨層重複的 concept_id 數與配對。各層語料應互斥；"
        "非零代表上游重複收錄或 id 沒有跨語料唯一，而它造成的錯誤全部是靜默的"
    )


#: taxonomy 的兩個具名範例：已整理方法 vs 已登錄但方法未整理。
#: 後者是正常狀態——taxonomy 是部分填充的衍生欄位，缺口本來就存在。
TAXONOMY_EXAMPLES: dict[str, dict[str, Any]] = {
    "with_method": {
        "summary": "已整理判斷方法",
        "description": "`method` 是**方法不是答案**：它說明怎麼推，不直接給 module 清單。",
        "value": {
            "defect": "DEFECT_ALPHA",
            "description": "影像上呈現規則性的重複結構。",
            "method": "先排除量測誤差，再依分佈位置縮小到前段或後段模組；邊緣集中時優先看搬運。",
            "modules": [],
            "category": "pattern",
            "notes": "只在方法本身有例外或前提時才寫。",
        },
    },
    "not_yet_written": {
        "summary": "已登錄，但方法尚未整理",
        "description": (
            "`method` 為空字串。這與「查無此 defect」（404）是兩件事：前者是"
            "「這個缺陷存在，但還沒人整理過怎麼查」，後者是「沒有這個缺陷」。"
        ),
        "value": {
            "defect": "DEFECT_GAMMA",
            "description": "另一種形貌的描述。",
            "method": "",
            "modules": [],
            "category": "pattern",
            "notes": "",
        },
    },
}


class TaxonomyOut(_Out):
    """taxonomy 條目。內容是**方法不是答案**：它說明怎麼從影像推出候選 module。"""

    model_config = _out(
        {
            "defect": "DEFECT_ALPHA",
            "description": "影像上呈現規則性的重複結構。",
            # 寫成判準與排除法，不要寫成結論——寫成結論會讓模型跳過觀察直接抄答案。
            "method": "先排除量測誤差，再依分佈位置縮小到前段或後段模組；邊緣集中時優先看搬運。",
            # 多數條目只給方法不給清單。一旦寫死清單，模型就不再看圖了。
            "modules": [],
            "category": "pattern",
            "notes": "只在方法本身有例外或前提時才寫。",
        }
    )

    defect: str
    description: str
    method: str = Field(
        description="怎麼從影像推出候選 module。**空字串代表這個 defect 已登錄但方法尚未整理**——"
        "那是正常狀態，覆蓋率統計要看得見它"
    )
    modules: list[str] = Field(
        description="選填的候選提示。多數條目只給方法不給清單——寫死清單，模型就不再看圖了"
    )
    category: str
    notes: str
