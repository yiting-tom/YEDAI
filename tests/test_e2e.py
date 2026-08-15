"""端到端：合成語料 → 索引 → 三模式查詢 → 回饋 → 報告。

語料是分層的，這裡取識別碼密集的那一層——三模式的分野幾乎完全由識別碼決定，
拿剝除識別碼的那一層來跑，A/B/C 會看起來沒有差別。"""

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
    assert result["layers"]["cases"]["bundles"] == 3
    assert result["concepts"] > 0
    corpus = Path(result["layers"]["cases"]["source"])

    index_path = tmp_path / ".index" / "e2e.pkl"
    config = Config(
        dictionary_path=result["dictionary"],
        indexes={"e2e": {"source": str(corpus), "path": str(index_path)}},
        log_dir=str(tmp_path / "logs"),
        seed=3,
    )
    dictionary = EntityDictionary.load(config.dictionary_path)

    index = build_index(corpus, config, dictionary, name="e2e")
    assert index.stats.parse_skipped == 0, f"合成語料不應有解析失敗：{index.skipped}"
    assert index.stats.concepts == result["layers"]["cases"]["concepts"]

    # 快取往返
    saved = index.save(index_path)
    reloaded = Index.load(saved, expect_name="e2e")
    reloaded.check_signature(config.index_signature(dictionary.fingerprint(), "e2e"))
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


def test_synthetic_chamber_gap_is_visible_in_the_coverage_metric(tmp_path: Path) -> None:
    """合成語料刻意只把一半的機台腔體放進字典，就是為了讓覆蓋率缺口有東西可看。

    這條測試是本次修正的迴歸點。在修正之前，`chamber_id` 的覆蓋率恆為 1.0——
    因為類型只有字典能給，regex fallback 一律標成 `unknown`，於是缺口整整掉進
    另一個桶裡。一個被設計來暴露缺口的量測看不見刻意為它準備的缺口，
    與「合成語料剛好符合樣式、測試全綠」是同一種病：量測只能確認自己。
    """
    out = tmp_path / "s"
    result = generate(out, n_bundles=6, seed=42)
    corpus = Path(result["layers"]["cases"]["source"])
    config = Config(
        dictionary_path=result["dictionary"],
        indexes={"gap": {"source": str(corpus), "path": str(tmp_path / ".index" / "gap.pkl")}},
        log_dir=str(tmp_path / "logs"),
    )
    index = build_index(corpus, config, EntityDictionary.load(config.dictionary_path), name="gap")
    report = build_report({"gap": index}, TelemetryStore.create(config), config)

    chamber = report["by_index"]["gap"]["entities"]["by_type"]["chamber_id"]
    assert chamber["regex"] > 0, "字典外的腔體必須計入 chamber_id，而不是掉進 unknown"
    assert chamber["dictionary_coverage"] == 0.5


def test_synthetic_output_is_reproducible(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    generate(a, n_bundles=2, seed=7)
    generate(b, n_bundles=2, seed=7)

    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert files_a == files_b
    for rel in files_a:
        # 產出的設定寫的是絕對路徑（載入器把相對路徑接到工作目錄，不是設定檔所在目錄），
        # 所以比對前要把各自的輸出根目錄正規化掉——差在根目錄不算不可重現。
        left = (a / rel).read_bytes().replace(str(a).encode(), b"<ROOT>")
        right = (b / rel).read_bytes().replace(str(b).encode(), b"<ROOT>")
        assert left == right, f"{rel} 不可重現"


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
    result = generate(out, n_bundles=2, seed=5)
    from yedai.parser import load_bundles

    bundles, _ = load_bundles(Path(result["layers"]["cases"]["source"]))
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


def test_different_seeds_produce_disjoint_concept_ids(tmp_path: Path) -> None:
    """不同種子的合成語料，concept_id 不得相撞。

    端對端跑出來的迴歸點：id 原本由 `bundle_slug + 序號` 完全決定，與種子無關，
    於是兩份獨立產生的語料大量共用 id（實測 8-deck 與 12-deck 之間 156 個相同）。

    單一語料時代看不出來。分層之後兩份語料會同時載入，相撞的後果是取全文取到
    錯的那一層、批次取回出現重複、跨層融合對同一份文件重複加權——全部靜默。
    """
    import re

    def ids(root: Path) -> set[str]:
        return {
            m.group(1)
            for f in root.rglob("*.md")
            for m in re.finditer(r"^id: ((?:cpt|sum|bdl)_\w+)", f.read_text(encoding="utf-8"), re.M)
        }

    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, n_bundles=4, seed=11)
    generate(b, n_bundles=6, seed=22)

    ia, ib = ids(a), ids(b)
    assert ia and ib, "前提不成立：沒有抓到任何 id"
    assert not (ia & ib), f"不同種子的語料共用了 {len(ia & ib)} 個 id"
