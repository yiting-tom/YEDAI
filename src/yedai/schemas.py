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


class SearchOut(_Out):
    query_id: str = Field(description="送 /v1/feedback 時要帶回這個值")
    query: str
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
    generated: Optional[str] = None
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
    status: str
    query_id: str


class ReportFeedbackOut(_Out):
    total: int
    clicked_rank_distribution: Distribution
    clicks_per_mode: dict[str, int]


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
    corpus: dict[str, Any]
    entities: dict[str, Any] = Field(
        description="全域覆蓋率與 by_type 拆解；解讀 B-C 差異需要後者"
    )
    queries: dict[str, Any]
    modes: dict[str, Any] = Field(description="模式代號 → 該模式的分數與零結果統計")
    mode_overlap: dict[str, ReportOverlapOut] = Field(description="模式組合 → 重疊度分佈")
    feedback: ReportFeedbackOut
    experiment_params: dict[str, Any] = Field(description="沒有它，任何數字都不可重現")


# --- ops ---


class HealthOut(_Out):
    status: str
    index_loaded: bool
    error: Optional[str] = None


class IndexRefOut(_Out):
    format_version: int
    signature: str


class VersionOut(_Out):
    package: str
    api: str
    index_format: int = Field(description="**本程式支援的**索引格式")
    index: Optional[IndexRefOut] = Field(
        default=None, description="**目前載入的**索引；未載入時為 null"
    )


class StatsOut(_Out):
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
