"""雙軌遙測。

完整日誌  — JSONL，含查詢原文與結果 id。寫入 gitignored 目錄，**不可外流**。
去識別化報告 — 只有數值與分佈，零語料內容。**這份才是設計來分享的**。

真實語料為公司機密，若報告洩漏任何內容，這次資料收集對外部討論就等於沒發生。
因此「報告不含內容」由測試強制守住，而非靠慣例。
"""

from __future__ import annotations

import json
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from .config import DEFAULT_INDEX_NAME, Config
from .entities import UNKNOWN_TYPE
from .index import Index
from .search import MODES, SearchOutcome

if TYPE_CHECKING:  # pragma: no cover - 只為型別，避免 layers → telemetry 的循環匯入
    from .layers import LayeredOutcome
    from .taxonomy import Taxonomy

QUERY_LOG = "queries.jsonl"
FEEDBACK_LOG = "feedback.jsonl"

#: 一次檢索的回傳形態。分層與融合的排名分佈**不可**混在同一組統計裡：
#: 融合後的名次是跨層競爭的結果，分層的名次是層內競爭的結果，兩者不可比。
SHAPE_LAYERED = "layered"
SHAPE_FUSED = "fused"
SHAPE_COMPARE = "compare"
SHAPES: tuple[str, ...] = (SHAPE_LAYERED, SHAPE_FUSED, SHAPE_COMPARE)


def _hit_record(h: Any) -> dict[str, Any]:
    return {
        "rank": h.rank,
        "concept_id": h.concept_id,
        "bundle_id": h.bundle_id,
        "type": h.type,
        "score": h.score,
        "lexical_score": h.lexical_score,
        "entity_score": h.entity_score,
    }


def _type_coverage(etype: str, counts: dict[str, int], measurable: set[str]) -> float | None:
    """只有分母可測的類型才給比例，其餘給 `null`。

    分母可測的條件：該類型的每一次出現都必然被宣告了該類型的樣式圈到。
    不成立時（機台、批號可以裸寫，缺陷名只有字典認得），未覆蓋的部分根本沒被算進分母，
    算出來的比例會恆為 1.0——那等於宣稱「字典已完整覆蓋」。偏誤的方向是「不必維護字典」，
    正好是最不該誤導使用者的方向。`null` 是誠實的答案：我們不知道。
    """
    if etype not in measurable or not counts.get("total"):
        return None
    return round(counts["dict"] / counts["total"], 4)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TelemetryStore:
    log_dir: Path

    @classmethod
    def create(cls, config: Config) -> TelemetryStore:
        d = Path(config.log_dir)
        d.mkdir(parents=True, exist_ok=True)
        return cls(log_dir=d)

    # ---- 寫入 ----------------------------------------------------------

    @property
    def query_path(self) -> Path:
        return self.log_dir / QUERY_LOG

    @property
    def feedback_path(self) -> Path:
        return self.log_dir / FEEDBACK_LOG

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_query(
        self,
        outcome: SearchOutcome,
        requested_mode: str,
        index: str = DEFAULT_INDEX_NAME,
    ) -> str:
        """單一索引內的多模式並排（`compare`）。回傳 query_id，供後續回饋事件關聯。"""
        query_id = uuid.uuid4().hex[:16]
        record = {
            "query_id": query_id,
            "ts": _now(),
            "query": outcome.query,  # 原文只存在本機
            "shape": SHAPE_COMPARE,
            "index": index,
            "requested_mode": requested_mode,
            "k": outcome.k,
            "display_order": outcome.display_order,
            "entities": [
                {"type": e.type, "canonical": e.canonical, "source": e.source} for e in outcome.entities
            ],
            "results": {
                mode: [_hit_record(h) for h in res.hits] for mode, res in outcome.results.items()
            },
            "candidates": {mode: res.candidates for mode, res in outcome.results.items()},
            "overlaps": [
                {"pair": o.pair, "jaccard": o.jaccard, "kendall_tau": o.kendall_tau, "common": o.common}
                for o in outcome.overlaps
            ],
        }
        self._append(self.query_path, record)
        return query_id

    def log_layered(self, outcome: "LayeredOutcome", requested_index: str | None = None) -> str:
        """分層檢索。每層各自的結果與**前處理後**的查詢詞都要記。

        沒有 `prepared_query`，就無法還原「這一層實際上拿到了什麼」——而各層的
        前處理不同，只記原始查詢等於記了一個沒有任何一層真的用過的字串。
        """
        query_id = uuid.uuid4().hex[:16]
        record: dict[str, Any] = {
            "query_id": query_id,
            "ts": _now(),
            "query": outcome.query,
            "shape": outcome.shape,
            "requested_index": requested_index,
            "indexes": [lr.index for lr in outcome.layers],
            "layers": [
                {
                    "index": lr.index,
                    "mode": lr.mode,
                    "prepared_query": lr.prepared_query,
                    "candidates": lr.candidates,
                    "hits": [_hit_record(h) for h in lr.hits],
                }
                for lr in outcome.layers
            ],
        }
        if outcome.fused is not None:
            record["fused"] = [
                {
                    "rank": fh.rank,
                    "index": fh.index,
                    "source_rank": fh.source_rank,
                    "score": fh.score,
                    "concept_id": fh.hit.concept_id,
                }
                for fh in outcome.fused
            ]
        self._append(self.query_path, record)
        return query_id

    def has_query(self, query_id: str) -> bool:
        return any(rec.get("query_id") == query_id for rec in self.read_queries())

    def log_feedback(
        self,
        query_id: str,
        concept_id: str,
        rank: int,
        mode: str,
        action: str = "click",
        index: str = DEFAULT_INDEX_NAME,
    ) -> None:
        """`rank` 是該項目在**它自己那一層內**的名次。

        用跨層合併後的位置會讓排名分佈失去意義：同一個第 1 名，在四層合併之後
        可能落在任何位置，而那個位置反映的是層的順序，不是它有多相關。
        """
        if not self.has_query(query_id):
            raise KeyError(f"unknown query_id: {query_id}")
        self._append(
            self.feedback_path,
            {
                "ts": _now(),
                "query_id": query_id,
                "index": index,
                "concept_id": concept_id,
                "rank": rank,
                "mode": mode,
                "action": action,
            },
        )

    # ---- 讀取 ----------------------------------------------------------

    def read_queries(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.query_path)

    def read_feedback(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.feedback_path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------------------
# 去識別化報告
# ---------------------------------------------------------------------------


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(round(q * (len(sorted_vals) - 1)))
    return sorted_vals[min(len(sorted_vals) - 1, max(0, idx))]


def _dist(values: Iterable[float]) -> dict[str, float]:
    vals = sorted(float(v) for v in values)
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "min": round(vals[0], 6),
        "p25": round(_quantile(vals, 0.25), 6),
        "median": round(statistics.median(vals), 6),
        "p75": round(_quantile(vals, 0.75), 6),
        "max": round(vals[-1], 6),
        "mean": round(statistics.fmean(vals), 6),
    }


def _corpus_block(stats) -> dict[str, Any]:
    """單一索引的語料統計（純數量，type 只留分佈形狀不留名稱）。"""
    return {
        "bundles": stats.bundles,
        "concepts": stats.concepts,
        "avg_concept_chars": round(stats.avg_concept_chars, 1),
        "avg_figures_per_concept": round(stats.avg_figures, 2),
        "vocab_naive": stats.vocab_naive,
        "vocab_protected": stats.vocab_protected,
        "vocab_ratio_protected_over_naive": (
            round(stats.vocab_protected / stats.vocab_naive, 4) if stats.vocab_naive else None
        ),
        "distinct_types": len(stats.types),
        "type_size_distribution": _dist(stats.types.values()),
        "parse_skipped": stats.parse_skipped,
        "parse_warnings": stats.parse_warnings,
    }


def _entity_block(stats) -> dict[str, Any]:
    """單一索引的實體覆蓋率（只有數量與比例，沒有任何實體名稱）。"""
    total_ent = stats.entities_total
    measurable = set(stats.shape_complete_types or ())
    return {
        "distinct_entities": total_ent,
        "from_dictionary": stats.entities_dict,
        "from_regex_fallback": stats.entities_regex,
        "dictionary_coverage": round(stats.entities_dict / total_ent, 4) if total_ent else None,
        # 全域比例把兩種相反的作用平均掉了，只有這層拆解能解讀。
        # 鍵是類型名稱（schema），不是正規名稱（語料內容）。
        "by_type": {
            etype: {**counts, "dictionary_coverage": _type_coverage(etype, counts, measurable)}
            for etype, counts in (stats.entities_by_type or {}).items()
        },
        #: 哪些類型的比例算得出來，一併寫進報告——否則讀報告的人無從判斷
        #: 一個 `null` 是「沒有這種實體」還是「分母不可測」。
        "coverage_measurable_types": sorted(measurable),
    }


def _corpus_total(indexes: dict[str, Index]) -> dict[str, Any]:
    """跨索引彙總。**只加得起來的才加。**

    詞彙量與實體數刻意不彙總：兩個索引的詞彙有多少重疊，索引本身不知道，
    相加會系統性高估。給一個高估的數字比不給更糟——它看起來跟真的一樣。
    平均字元數以 concept 數加權，這個是加得起來的。
    """
    concepts = sum(i.stats.concepts for i in indexes.values())
    weighted_chars = sum(i.stats.avg_concept_chars * i.stats.concepts for i in indexes.values())
    return {
        "indexes": len(indexes),
        "bundles": sum(i.stats.bundles for i in indexes.values()),
        "concepts": concepts,
        "avg_concept_chars": round(weighted_chars / concepts, 1) if concepts else 0.0,
        "parse_skipped": sum(i.stats.parse_skipped for i in indexes.values()),
        "parse_warnings": sum(i.stats.parse_warnings for i in indexes.values()),
        "note": (
            "詞彙量與實體數不做跨索引彙總：重疊程度未知，相加會系統性高估。"
            "請看 by_index。"
        ),
    }


def _mode_rows(rec: dict[str, Any]) -> list[tuple[str, str, list]]:
    """把兩種日誌形狀正規化成 `(索引名稱, 模式, hits)`。

    `compare` 記錄是 `results: {mode: hits}` 加一個索引名；分層記錄是
    `layers: [{index, mode, hits}]`。報告端只該認得一種形狀。
    """
    if rec.get("layers"):
        return [
            (str(lr.get("index") or DEFAULT_INDEX_NAME), str(lr.get("mode") or ""), lr.get("hits") or [])
            for lr in rec["layers"]
        ]
    index = str(rec.get("index") or DEFAULT_INDEX_NAME)
    return [(index, mode, hits) for mode, hits in (rec.get("results") or {}).items()]


def _mode_block(rows: list[tuple[str, list]]) -> dict[str, Any]:
    """`rows` 是 `(模式, hits)`。回傳依模式拆解的命中數與分數分佈。"""
    per_mode: dict[str, Any] = {}
    by_mode: dict[str, list[list]] = {}
    for mode, hits in rows:
        by_mode.setdefault(mode, []).append(hits)
    for mode in [m for m in MODES if m in by_mode] + sorted(set(by_mode) - set(MODES)):
        hit_counts, top_scores, zero = [], [], 0
        for hits in by_mode[mode]:
            hit_counts.append(len(hits))
            if hits:
                top_scores.append(hits[0].get("score", 0.0))
            else:
                zero += 1
        n = len(hit_counts)
        per_mode[mode] = {
            "queries": n,
            "zero_result_rate": round(zero / n, 4) if n else None,
            "hit_count_distribution": _dist(hit_counts),
            "top_score_distribution": _dist(top_scores),
        }
    return per_mode


def build_report(
    indexes: dict[str, Index] | Index,
    store: TelemetryStore,
    config: Config,
    evaluation: dict[str, Any] | None = None,
    taxonomy: "Taxonomy | None" = None,
    id_overlap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """產出可外流的統計報告。

    嚴格規則：任何來自語料或查詢的**文字內容**都不得進入回傳值——
    不含查詢原文、concept 標題/描述/路徑、實體名稱、bundle 名稱、type 名稱、
    defect 名稱、module 名稱、taxonomy 條目文字。
    只允許數量、比例、分佈與設定參數。

    索引名稱是例外，而且必須是例外：它來自設定宣告（schema 層級的識別），
    不是語料內容。沒有它就無法依層拆解，而不同層的規模可能相差數個數量級——
    彙總會把它們平均掉，那正是分層要避免的事。
    """
    if isinstance(indexes, Index):
        indexes = {indexes.name: indexes}
    queries = store.read_queries()
    feedback = store.read_feedback()

    by_index: dict[str, Any] = {}
    for name in sorted(indexes):
        stats = indexes[name].stats
        rows = [
            (mode, hits)
            for rec in queries
            for idx_name, mode, hits in _mode_rows(rec)
            if idx_name == name
        ]
        by_index[name] = {
            "corpus": _corpus_block(stats),
            "entities": _entity_block(stats),
            "modes": _mode_block(rows),
        }

    # --- 查詢 ---
    q_lengths = [len(q.get("query", "")) for q in queries]
    q_entity_counts = [len(q.get("entities") or []) for q in queries]
    with_entity = sum(1 for c in q_entity_counts if c > 0)
    ent_sources = [e.get("source") for q in queries for e in (q.get("entities") or [])]
    # 查詢端也要拆解：語料的覆蓋率高、但使用者實際打的那些類型覆蓋率低，是完全可能的，
    # 而那才是真正影響檢索效果的缺口。只看語料端會漏掉它。
    q_by_type: dict[str, dict[str, int]] = {}
    for q in queries:
        for e in q.get("entities") or []:
            bucket = q_by_type.setdefault(str(e.get("type") or UNKNOWN_TYPE), {"dict": 0, "regex": 0})
            src = e.get("source")
            if src in ("dict", "regex"):
                bucket[src] += 1

    per_mode = _mode_block([(mode, hits) for rec in queries for _, mode, hits in _mode_rows(rec)])

    # 配對清單必須從日誌裡實際出現的配對推出，不能寫死。寫死成 A-B/A-C/B-C 會讓
    # C-D、C-E 這些含稠密腿的配對從報告裡整個消失——而報告是唯一可外流的產出，
    # 讀者看到的會是「稠密腿沒有產生重疊資料」，而不是「這份報告漏了它」。
    seen_pairs = {
        str(o.get("pair")) for q in queries for o in (q.get("overlaps") or []) if o.get("pair")
    }
    ordered = [f"{a}-{b}" for i, a in enumerate(MODES) for b in MODES[i + 1 :]]
    overlaps: dict[str, Any] = {}
    for pair in [p for p in ordered if p in seen_pairs] + sorted(seen_pairs - set(ordered)):
        jac = [o["jaccard"] for q in queries for o in (q.get("overlaps") or []) if o.get("pair") == pair]
        tau = [
            o["kendall_tau"]
            for q in queries
            for o in (q.get("overlaps") or [])
            if o.get("pair") == pair and o.get("kendall_tau") is not None
        ]
        overlaps[pair] = {"jaccard": _dist(jac), "kendall_tau": _dist(tau)}

    query_block = {
        "total_queries": len(queries),
        "query_length_distribution": _dist(q_lengths),
        "queries_with_entity": with_entity,
        "queries_with_entity_rate": round(with_entity / len(queries), 4) if queries else None,
        "entities_per_query_distribution": _dist(q_entity_counts),
        "query_entity_from_dictionary": sum(1 for s in ent_sources if s == "dict"),
        "query_entity_from_regex_fallback": sum(1 for s in ent_sources if s == "regex"),
        "query_entity_by_type": dict(sorted(q_by_type.items())),
    }

    fb_ranks = [f.get("rank") for f in feedback if isinstance(f.get("rank"), int)]
    fb_modes: dict[str, int] = {}
    fb_indexes: dict[str, int] = {}
    for f in feedback:
        mode = str(f.get("mode", ""))
        if mode in MODES:
            fb_modes[mode] = fb_modes.get(mode, 0) + 1
        fb_indexes[str(f.get("index") or DEFAULT_INDEX_NAME)] = (
            fb_indexes.get(str(f.get("index") or DEFAULT_INDEX_NAME), 0) + 1
        )

    return {
        "report_version": 2,
        "generated_at": _now(),
        "note": "去識別化統計報告：不含任何查詢原文或語料內容，可安全分享。",
        # 依索引拆解是主要視角。彙總保留但不是唯一視角——不同層的規模可能相差
        # 數個數量級，只看彙總會把它們平均掉。
        "by_index": by_index,
        "corpus": _corpus_total(indexes),
        "queries": query_block,
        "modes": per_mode,
        "mode_overlap": overlaps,
        "retrieval_shape": _shape_block(queries),
        "taxonomy": (taxonomy.coverage() if taxonomy is not None else None),
        # 各層語料應互斥。非零代表上游重複收錄或 id 沒有跨語料唯一，而它造成的
        # 錯誤全部是靜默的（取全文取到第一層、融合對同一份文件重複加權）。
        # 只留層名與數量——id 屬語料內容。
        "id_overlap": id_overlap,
        # 評估結果只含數字與模式名稱。查詢原文是語料衍生物、帶真實識別碼，
        # 而報告是唯一設計為可外流的產出——這條界線不因方便而放寬。
        "evaluation": evaluation,
        "feedback": {
            "total": len(feedback),
            "clicked_rank_distribution": _dist(fb_ranks),
            "clicks_per_mode": fb_modes,
            # 層內名次而非跨層合併名次——後者反映的是層的順序，不是相關性。
            "clicks_per_index": dict(sorted(fb_indexes.items())),
        },
        "experiment_params": config.experiment_params(),
    }


def _shape_block(queries: list[dict[str, Any]]) -> dict[str, Any]:
    """分層與融合的統計分開。

    融合後的名次是跨層競爭的結果，分層的名次是層內競爭的結果。混在一組分佈裡，
    得到的數字兩者都不代表，而且沒有任何跡象顯示它壞了。
    """
    out: dict[str, Any] = {}
    for shape in SHAPES:
        recs = [q for q in queries if str(q.get("shape") or SHAPE_COMPARE) == shape]
        block: dict[str, Any] = {"queries": len(recs)}
        if shape == SHAPE_LAYERED or shape == SHAPE_FUSED:
            empty_layers: dict[str, int] = {}
            seen_layers: dict[str, int] = {}
            for rec in recs:
                for lr in rec.get("layers") or []:
                    name = str(lr.get("index") or DEFAULT_INDEX_NAME)
                    seen_layers[name] = seen_layers.get(name, 0) + 1
                    if not (lr.get("hits") or []):
                        empty_layers[name] = empty_layers.get(name, 0) + 1
            # 某一層是空的，本身就是訊號——它要能從報告裡讀出來。
            block["empty_layer_rate_by_index"] = {
                name: round(empty_layers.get(name, 0) / count, 4)
                for name, count in sorted(seen_layers.items())
            }
        if shape == SHAPE_FUSED:
            block["fused_rank_distribution"] = _dist(
                [f["rank"] for rec in recs for f in (rec.get("fused") or [])]
            )
            block["source_rank_distribution"] = _dist(
                [f["source_rank"] for rec in recs for f in (rec.get("fused") or [])]
            )
            contributions: dict[str, int] = {}
            for rec in recs:
                for f in rec.get("fused") or []:
                    name = str(f.get("index") or DEFAULT_INDEX_NAME)
                    contributions[name] = contributions.get(name, 0) + 1
            # 四層大小相差數個數量級時，平權 RRF 的實際出席比例是關鍵數字——
            # 「每類知識都派代表出席」是不是真的發生了，只有這裡看得出來。
            block["fused_contributions_by_index"] = dict(sorted(contributions.items()))
        out[shape] = block
    return out
