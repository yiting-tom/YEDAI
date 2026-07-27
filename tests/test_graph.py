from __future__ import annotations

import pytest

from yedai.fulltext import ConceptNotFound
from yedai.graph import MAX_DEPTH, neighbors


# --- 索引層的邊 ---------------------------------------------------------


def test_out_edges_recorded(graph_index) -> None:
    assert set(graph_index.related_out["cpt_a"]) == {"cpt_b", "cpt_c"}


def test_in_edges_computed(graph_index) -> None:
    assert graph_index.related_in["cpt_b"] == ["cpt_a"]
    assert graph_index.related_in["cpt_d"] == ["cpt_b"]
    assert "cpt_a" not in graph_index.related_in


def test_dangling_kept_out_of_edges(graph_index) -> None:
    assert graph_index.dangling["cpt_a"] == ["cpt_ghost"]
    assert "cpt_ghost" not in graph_index.related_out["cpt_a"]


def test_dangling_counted_in_stats(graph_index) -> None:
    assert graph_index.stats.dangling_related == 1


# --- 展開 ---------------------------------------------------------------


def test_depth_one_out(graph_index) -> None:
    result = neighbors(graph_index, "cpt_a", depth=1, direction="out")
    assert {n["concept_id"] for n in result["neighbors"]} == {"cpt_b", "cpt_c"}
    assert all(n["depth"] == 1 for n in result["neighbors"])
    assert all(n["direction"] == "out" for n in result["neighbors"])


def test_depth_two_marks_hops(graph_index) -> None:
    result = neighbors(graph_index, "cpt_a", depth=2, direction="out")
    by_id = {n["concept_id"]: n for n in result["neighbors"]}
    assert set(by_id) == {"cpt_b", "cpt_c", "cpt_d"}
    assert by_id["cpt_b"]["depth"] == 1
    assert by_id["cpt_d"]["depth"] == 2
    assert by_id["cpt_d"]["via"] == "cpt_b"


def test_start_node_excluded(graph_index) -> None:
    result = neighbors(graph_index, "cpt_a", depth=2, direction="both")
    assert "cpt_a" not in {n["concept_id"] for n in result["neighbors"]}


def test_direction_in_only(graph_index) -> None:
    result = neighbors(graph_index, "cpt_b", depth=1, direction="in")
    assert [n["concept_id"] for n in result["neighbors"]] == ["cpt_a"]


def test_direction_both(graph_index) -> None:
    result = neighbors(graph_index, "cpt_b", depth=1, direction="both")
    assert {n["concept_id"] for n in result["neighbors"]} == {"cpt_a", "cpt_d"}


def test_isolated_concept_returns_empty(graph_index) -> None:
    result = neighbors(graph_index, "cpt_e", depth=2, direction="both")
    assert result["neighbors"] == []
    assert result["dangling"] == []


def test_dangling_reported_separately(graph_index) -> None:
    result = neighbors(graph_index, "cpt_a", depth=1, direction="out")
    assert result["dangling"] == ["cpt_ghost"]
    assert "cpt_ghost" not in {n["concept_id"] for n in result["neighbors"]}


def test_neighbors_carry_summary_fields(graph_index) -> None:
    n = neighbors(graph_index, "cpt_a", depth=1, direction="out")["neighbors"][0]
    for key in ("concept_id", "bundle_id", "type", "title", "description", "path", "index_line"):
        assert key in n
    assert n["index_line"].startswith("cpt_")


def test_unknown_start_raises(graph_index) -> None:
    with pytest.raises(ConceptNotFound):
        neighbors(graph_index, "cpt_nope")


def test_depth_above_limit_rejected(graph_index) -> None:
    with pytest.raises(ValueError, match="depth"):
        neighbors(graph_index, "cpt_a", depth=MAX_DEPTH + 1)


def test_depth_zero_rejected(graph_index) -> None:
    with pytest.raises(ValueError):
        neighbors(graph_index, "cpt_a", depth=0)


def test_unknown_direction_rejected(graph_index) -> None:
    with pytest.raises(ValueError, match="direction"):
        neighbors(graph_index, "cpt_a", direction="sideways")
