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
from typing import Any, Iterable

from .config import Config
from .entities import UNKNOWN_TYPE
from .index import Index
from .search import MODES, SearchOutcome

QUERY_LOG = "queries.jsonl"
FEEDBACK_LOG = "feedback.jsonl"


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

    def log_query(self, outcome: SearchOutcome, requested_mode: str) -> str:
        """回傳 query_id，供後續回饋事件關聯。"""
        query_id = uuid.uuid4().hex[:16]
        record = {
            "query_id": query_id,
            "ts": _now(),
            "query": outcome.query,  # 原文只存在本機
            "requested_mode": requested_mode,
            "k": outcome.k,
            "display_order": outcome.display_order,
            "entities": [
                {"type": e.type, "canonical": e.canonical, "source": e.source} for e in outcome.entities
            ],
            "results": {
                mode: [
                    {
                        "rank": h.rank,
                        "concept_id": h.concept_id,
                        "bundle_id": h.bundle_id,
                        "type": h.type,
                        "score": h.score,
                        "lexical_score": h.lexical_score,
                        "entity_score": h.entity_score,
                    }
                    for h in res.hits
                ]
                for mode, res in outcome.results.items()
            },
            "candidates": {mode: res.candidates for mode, res in outcome.results.items()},
            "overlaps": [
                {"pair": o.pair, "jaccard": o.jaccard, "kendall_tau": o.kendall_tau, "common": o.common}
                for o in outcome.overlaps
            ],
        }
        self._append(self.query_path, record)
        return query_id

    def has_query(self, query_id: str) -> bool:
        return any(rec.get("query_id") == query_id for rec in self.read_queries())

    def log_feedback(
        self, query_id: str, concept_id: str, rank: int, mode: str, action: str = "click"
    ) -> None:
        if not self.has_query(query_id):
            raise KeyError(f"unknown query_id: {query_id}")
        self._append(
            self.feedback_path,
            {
                "ts": _now(),
                "query_id": query_id,
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


def build_report(index: Index, store: TelemetryStore, config: Config) -> dict[str, Any]:
    """產出可外流的統計報告。

    嚴格規則：任何來自語料或查詢的**文字內容**都不得進入回傳值——
    不含查詢原文、concept 標題/描述/路徑、實體名稱、bundle 名稱、type 名稱。
    只允許數量、比例、分佈與設定參數。
    """
    queries = store.read_queries()
    feedback = store.read_feedback()
    stats = index.stats

    # --- 語料（純數量，type 只留分佈形狀不留名稱）---
    corpus = {
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

    # --- 實體覆蓋率（只有數量與比例，沒有任何實體名稱）---
    total_ent = stats.entities_total
    entity_corpus = {
        "distinct_entities": total_ent,
        "from_dictionary": stats.entities_dict,
        "from_regex_fallback": stats.entities_regex,
        "dictionary_coverage": round(stats.entities_dict / total_ent, 4) if total_ent else None,
        # 全域比例把兩種相反的作用平均掉了，只有這層拆解能解讀。
        # 鍵是類型名稱（schema），不是正規名稱（語料內容）。
        "by_type": {
            etype: {
                **counts,
                "dictionary_coverage": (
                    round(counts["dict"] / counts["total"], 4) if counts["total"] else None
                ),
            }
            for etype, counts in (stats.entities_by_type or {}).items()
        },
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

    per_mode: dict[str, Any] = {}
    for mode in MODES:
        hit_counts, top_scores, zero = [], [], 0
        for q in queries:
            hits = (q.get("results") or {}).get(mode)
            if hits is None:
                continue
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

    overlaps: dict[str, Any] = {}
    for pair in ("A-B", "A-C", "B-C"):
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
    for f in feedback:
        mode = str(f.get("mode", ""))
        if mode in MODES:
            fb_modes[mode] = fb_modes.get(mode, 0) + 1

    return {
        "report_version": 1,
        "generated_at": _now(),
        "note": "去識別化統計報告：不含任何查詢原文或語料內容，可安全分享。",
        "corpus": corpus,
        "entities": entity_corpus,
        "queries": query_block,
        "modes": per_mode,
        "mode_overlap": overlaps,
        "feedback": {
            "total": len(feedback),
            "clicked_rank_distribution": _dist(fb_ranks),
            "clicks_per_mode": fb_modes,
        },
        "experiment_params": config.experiment_params(),
    }
