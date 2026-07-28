from __future__ import annotations

import pytest

from yedai.search import LEXICAL_MODES, MODES, ModeUnavailable, jaccard, kendall_tau


def test_all_modes_available(searcher) -> None:
    for mode in searcher.available_modes:
        assert searcher.search("PARTICLE", mode=mode, k=3).mode == mode


def test_dense_modes_are_unavailable_without_vectors(searcher) -> None:
    """沒有向量時 D/E 必須不可用，而不是退化成 C。

    退化會讓報告顯示「稠密腿沒有帶來差異」，而真相是它根本沒有執行——
    那個假象會被當成結論，而且沒有任何地方會露出破綻。
    """
    assert searcher.available_modes == LEXICAL_MODES
    for mode in ("D", "E"):
        with pytest.raises(ModeUnavailable):
            searcher.search("PARTICLE", mode=mode, k=3)


def test_unknown_mode_rejected(searcher) -> None:
    with pytest.raises(ValueError):
        searcher.search("x", mode="Z")


def test_title_hit_outranks_body_hit(searcher) -> None:
    hits = searcher.search("PARTICLE", mode="B", k=10).hits
    order = [h.concept_id for h in hits]
    assert order.index("cpt_title-hit") < order.index("cpt_body-hit")


def test_naive_mode_confuses_sibling_tools(searcher) -> None:
    """模式 A 應把 XTR-06 也拉進來（前綴被切成共用詞元）；模式 B 不該。"""
    a_ids = searcher.search("XTR-05", mode="A", k=3).ids
    b_ids = searcher.search("XTR-05", mode="B", k=3).ids
    assert "cpt_sibling" in a_ids
    assert "cpt_sibling" not in b_ids


def test_zero_results_returns_empty_not_error(searcher) -> None:
    # 中文查詢幾乎不可能零命中（unigram 保召回），所以用純拉丁的無意義字串
    result = searcher.search("zzzzzz qqqqqq wwwwww", mode="B", k=5)
    assert result.hits == []


def test_k_limit_respected(searcher) -> None:
    assert len(searcher.search("PARTICLE", mode="B", k=2).hits) <= 2


def test_invalid_k_rejected(searcher) -> None:
    with pytest.raises(ValueError):
        searcher.search("x", mode="B", k=0)


def test_mode_c_exposes_both_legs(searcher) -> None:
    for hit in searcher.search("XTR-05 PARTICLE", mode="C", k=5).hits:
        assert hit.lexical_score >= 0.0
        assert 0.0 <= hit.entity_score <= 1.0


def test_index_line_format(searcher) -> None:
    line = searcher.search("PARTICLE", mode="B", k=1).hits[0].index_line()
    parts = [p.strip() for p in line.split(" . ")]
    assert parts[0].startswith("cpt_")
    assert parts[2].startswith("[") and "](" in parts[2]


def test_compare_returns_all_modes_and_overlaps(searcher) -> None:
    outcome = searcher.compare("XTR-05 PARTICLE", k=5)
    assert set(outcome.results) == set(searcher.available_modes)
    assert {o.pair for o in outcome.overlaps} == {"A-B", "A-C", "B-C"}
    assert sorted(outcome.display_order) == sorted(searcher.available_modes)


def test_compare_records_query_entities(searcher) -> None:
    outcome = searcher.compare("XTR-05 PARTICLE", k=5)
    assert {e.canonical for e in outcome.entities} >= {"XTR-05", "PARTICLE"}


# --- 重疊度指標 ---------------------------------------------------------


def test_jaccard_identical_and_disjoint() -> None:
    assert jaccard(["a", "b"], ["a", "b"]) == 1.0
    assert jaccard(["a", "b"], ["c", "d"]) == 0.0
    assert jaccard([], []) == 1.0


def test_kendall_tau_identical_order() -> None:
    assert kendall_tau(["a", "b", "c"], ["a", "b", "c"]) == 1.0


def test_kendall_tau_reversed_order() -> None:
    assert kendall_tau(["a", "b", "c"], ["c", "b", "a"]) == -1.0


def test_kendall_tau_undefined_with_fewer_than_two_common() -> None:
    assert kendall_tau(["a"], ["a"]) is None
    assert kendall_tau(["a", "b"], ["c", "d"]) is None
