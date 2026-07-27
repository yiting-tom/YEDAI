from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from yedai.entities import UNKNOWN_TYPE, EntityDictionary, EntityExtractor
from yedai.tokenizer import Tokenizer


@pytest.fixture
def extractor(dictionary_path: Path) -> EntityExtractor:
    return EntityExtractor(EntityDictionary.load(dictionary_path), Tokenizer())


def test_dictionary_hit(extractor: EntityExtractor) -> None:
    hits = {h.canonical: h for h in extractor.extract("XTR-05 出現異常")}
    assert hits["XTR-05"].type == "tool_id"
    assert hits["XTR-05"].source == "dict"


def test_alias_variants_resolve_to_canonical(extractor: EntityExtractor) -> None:
    for form in ["XTR-05", "XTR05", "xtr 05"]:
        canonicals = {h.canonical for h in extractor.extract(form)}
        assert "XTR-05" in canonicals


def test_regex_fallback_for_unknown_identifier(extractor: EntityExtractor) -> None:
    hits = [h for h in extractor.extract("機台 ZZZ-77 異常") if h.canonical == "ZZZ77"]
    assert hits and hits[0].source == "regex"
    assert hits[0].type == UNKNOWN_TYPE


def test_chinese_alias_longest_match_wins(tmp_path: Path) -> None:
    path = tmp_path / "d.yaml"
    path.write_text(
        yaml.safe_dump(
            {"tool_id": [{"canonical": "XTR-05", "aliases": ["五號機"]}, {"canonical": "X5", "aliases": ["五號"]}]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    ex = EntityExtractor(EntityDictionary.load(path), Tokenizer())
    canonicals = {h.canonical for h in ex.extract("請查五號機的狀況")}
    assert "XTR-05" in canonicals
    assert "X5" not in canonicals


def test_duplicate_entities_collapse(extractor: EntityExtractor) -> None:
    hits = extractor.extract("XTR-05 與 XTR-05 又是 XTR-05")
    assert sum(1 for h in hits if h.canonical == "XTR-05") == 1


def test_missing_dictionary_is_optional() -> None:
    d = EntityDictionary.load(None)
    assert len(d) == 0
    ex = EntityExtractor(d, Tokenizer())
    hits = ex.extract("XTR-05")
    assert hits and hits[0].source == "regex"


def test_missing_dictionary_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        EntityDictionary.load(tmp_path / "nope.yaml")


def test_string_entry_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "d.yaml"
    path.write_text(yaml.safe_dump({"flow_id": ["FL-A100"]}), encoding="utf-8")
    ex = EntityExtractor(EntityDictionary.load(path), Tokenizer())
    hits = {h.canonical: h for h in ex.extract("走 FL-A100 流程")}
    assert hits["FL-A100"].type == "flow_id"


def test_fingerprint_changes_with_content(tmp_path: Path, dictionary_path: Path) -> None:
    a = EntityDictionary.load(dictionary_path).fingerprint()
    other = tmp_path / "d2.yaml"
    other.write_text(yaml.safe_dump({"tool_id": [{"canonical": "LMB-01"}]}), encoding="utf-8")
    assert a != EntityDictionary.load(other).fingerprint()


# --- 實體腿計分 ---------------------------------------------------------


def test_full_coverage_in_top_field_scores_one(searcher) -> None:
    """所有查詢實體都出現在最高權重欄位（title）時，實體腿為 1.0。"""
    result = searcher.search("XTR-05 PARTICLE", mode="C", k=5)
    top = result.hits[0]
    assert top.concept_id == "cpt_title-hit"
    assert top.entity_score == pytest.approx(1.0)


def test_partial_coverage_scores_lower(searcher) -> None:
    full = searcher.search("XTR-05 PARTICLE", mode="C", k=10).hits
    by_id = {h.concept_id: h for h in full}
    # sibling 只涵蓋 PARTICLE，未涵蓋 XTR-05
    assert by_id["cpt_sibling"].entity_score < by_id["cpt_title-hit"].entity_score


def test_no_entity_overlap_scores_zero(searcher) -> None:
    hits = searcher.search("QDN-01 VOID", mode="C", k=10).hits
    unrelated = [h for h in hits if h.concept_id == "cpt_unrelated"]
    assert all(h.entity_score == 0.0 for h in unrelated)


def test_rare_entity_outranks_common(searcher) -> None:
    """PARTICLE 出現在多份、VOID 只在一份 → 命中 VOID 的涵蓋率權重較高。"""
    rare = searcher.search("VOID", mode="C", k=5).hits[0]
    common = searcher.search("PARTICLE", mode="C", k=5).hits[0]
    assert rare.entity_score >= common.entity_score


def test_title_hit_beats_body_hit_on_entity_leg(searcher) -> None:
    hits = {h.concept_id: h for h in searcher.search("XTR-05", mode="C", k=10).hits}
    assert hits["cpt_title-hit"].entity_score > hits["cpt_body-hit"].entity_score


def test_hard_filter_restricts_results(corpus, config) -> None:
    from yedai.entities import EntityDictionary as ED
    from yedai.index import build_index
    from yedai.search import Searcher

    strict = config.merged({"require_entities": True})
    d = ED.load(strict.dictionary_path)
    s = Searcher(build_index(corpus, strict, d), strict, d)

    hits = s.search("XTR-05 VOID", mode="C", k=10).hits
    assert hits == [], "沒有 concept 同時含 XTR-05 與 VOID"

    loose = Searcher(build_index(corpus, config, d), config, d)
    assert loose.search("XTR-05 VOID", mode="C", k=10).hits, "預設不過濾時應仍有結果"
