"""端到端：合成語料 → 索引 → 三模式查詢 → 回饋 → 報告。"""

from __future__ import annotations

import json
from pathlib import Path

from yedai.config import Config
from yedai.entities import EntityDictionary
from yedai.index import Index, build_index
from yedai.search import Searcher
from yedai.synthetic import generate
from yedai.telemetry import TelemetryStore, build_report


def test_full_pipeline_over_synthetic_corpus(tmp_path: Path) -> None:
    out = tmp_path / "synthetic"
    result = generate(out, n_bundles=3, seed=42)
    assert result["bundles"] == 3
    assert result["concepts"] > 0

    config = Config(
        dictionary_path=result["dictionary"],
        index_path=str(tmp_path / ".index" / "e2e.pkl"),
        log_dir=str(tmp_path / "logs"),
        seed=3,
    )
    dictionary = EntityDictionary.load(config.dictionary_path)

    index = build_index(out, config, dictionary)
    assert index.stats.parse_skipped == 0, f"合成語料不應有解析失敗：{index.skipped}"
    assert index.stats.concepts == result["concepts"]

    # 快取往返
    saved = index.save(config.index_path)
    reloaded = Index.load(saved)
    reloaded.check_signature(config.index_signature(dictionary.fingerprint()))
    assert reloaded.stats.concepts == index.stats.concepts

    searcher = Searcher(reloaded, config, dictionary)
    store = TelemetryStore.create(config)

    outcome = searcher.compare("XTR-05 PARTICLE", k=10)
    qid = store.log_query(outcome, requested_mode="compare")
    assert all(outcome.results[m].hits for m in ("A", "B", "C"))

    top_c = outcome.results["C"].hits[0]
    store.log_feedback(qid, top_c.concept_id, top_c.rank, "C")

    report = build_report(reloaded, store, config)
    blob = json.dumps(report, ensure_ascii=False)
    assert "XTR-05" not in blob and "PARTICLE" not in blob
    assert report["queries"]["total_queries"] == 1
    assert report["feedback"]["total"] == 1


def test_synthetic_output_is_reproducible(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    generate(a, n_bundles=2, seed=7)
    generate(b, n_bundles=2, seed=7)

    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert files_a == files_b
    for rel in files_a:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), f"{rel} 不可重現"


def test_synthetic_summary_uses_undelimited_frontmatter(tmp_path: Path) -> None:
    out = tmp_path / "s"
    generate(out, n_bundles=1, seed=1)
    summary = next(out.rglob("summary.md"))
    assert not summary.read_text(encoding="utf-8").startswith("---")


def test_synthetic_has_sibling_identifiers(tmp_path: Path) -> None:
    out = tmp_path / "s"
    generate(out, n_bundles=5, seed=1)
    text = "\n".join(p.read_text(encoding="utf-8") for p in out.rglob("*.md"))
    assert "XTR-05" in text and "XTR-06" in text


def test_synthetic_ships_disclaimer(tmp_path: Path) -> None:
    out = tmp_path / "s"
    generate(out, n_bundles=1, seed=1)
    note = (out / "README.txt").read_text(encoding="utf-8")
    assert "僅供驗證程式正確性" in note
    assert "不得用於調整參數" in note


def test_same_type_concepts_share_section_structure(tmp_path: Path) -> None:
    out = tmp_path / "s"
    generate(out, n_bundles=2, seed=5)
    from yedai.parser import load_bundles

    bundles, _ = load_bundles(out)
    by_type: dict[str, list[list[str]]] = {}
    for bundle in bundles:
        for concept in bundle.concepts:
            headings = [s.heading for s in concept.sections if s.heading and s.heading not in
                        ("Related Concepts", "Citations")]
            by_type.setdefault(concept.type, []).append(headings)

    for ctype, groups in by_type.items():
        if len(groups) < 2:
            continue
        assert groups[0] == groups[1], f"{ctype} 的區段結構應在同類型間重複"
