from __future__ import annotations

from pathlib import Path

import pytest

from yedai.entities import EntityDictionary
from yedai.grep import InvalidPattern, ScopeRequired, UnknownScope, grep
from yedai.index import build_index


@pytest.fixture
def index(corpus: Path, config):
    return build_index(corpus, config, EntityDictionary.load(config.dictionary_path))


# --- 範圍是必填，不是選填 -------------------------------------------------


def test_no_scope_is_rejected(index) -> None:
    with pytest.raises(ScopeRequired) as exc:
        grep(index, "PARTICLE")
    # 錯誤訊息必須指引正確用法，否則 agent 只會重試一次一樣的呼叫
    assert "search" in str(exc.value)


def test_scope_by_bundle(index) -> None:
    result = grep(index, "PARTICLE", bundle_ids=["bdl_b1"])
    assert result["results"]
    assert {r["bundle_id"] for r in result["results"]} == {"bdl_b1"}


def test_scope_by_concept(index) -> None:
    result = grep(index, "PARTICLE", concept_ids=["cpt_title-hit"])
    assert {r["concept_id"] for r in result["results"]} == {"cpt_title-hit"}


def test_unknown_bundle_rejected(index) -> None:
    with pytest.raises(UnknownScope):
        grep(index, "x", bundle_ids=["bdl_nope"])


def test_unknown_concept_rejected(index) -> None:
    with pytest.raises(UnknownScope):
        grep(index, "x", concept_ids=["cpt_nope"])


# --- 比對模式 -----------------------------------------------------------


def test_literal_by_default(index) -> None:
    """正則特殊字元在預設模式下應被當作字面內容。"""
    result = grep(index, "XTR-05 PARTICLE", bundle_ids=["bdl_b1"])
    assert result["results"]
    assert result["regex"] is False


def test_literal_does_not_interpret_regex(index) -> None:
    # `.*` 當字面看待時，語料裡沒有這個字串
    assert grep(index, "XTR.*PARTICLE", bundle_ids=["bdl_b1"])["results"] == []
    # 開啟正則後就找得到
    assert grep(index, "XTR.*PARTICLE", bundle_ids=["bdl_b1"], regex=True)["results"]


def test_invalid_regex_raises(index) -> None:
    with pytest.raises(InvalidPattern):
        grep(index, "XTR-0(5", bundle_ids=["bdl_b1"], regex=True)


def test_ignore_case(index) -> None:
    assert grep(index, "particle", bundle_ids=["bdl_b1"])["results"] == []
    assert grep(index, "particle", bundle_ids=["bdl_b1"], ignore_case=True)["results"]


def test_ignore_case_with_regex(index) -> None:
    assert grep(index, "particle", bundle_ids=["bdl_b1"], regex=True, ignore_case=True)["results"]


def test_empty_pattern_rejected(index) -> None:
    with pytest.raises(ValueError):
        grep(index, "", bundle_ids=["bdl_b1"])


# --- 結果 ---------------------------------------------------------------


def test_result_fields(index) -> None:
    hit = grep(index, "PARTICLE", bundle_ids=["bdl_b1"])["results"][0]
    for key in ("concept_id", "bundle_id", "type", "title", "path", "line", "text"):
        assert key in hit
    assert hit["line"] >= 1
    assert "PARTICLE" in hit["text"]


def test_no_match_returns_empty(index) -> None:
    result = grep(index, "ZZZZZZ_NOT_PRESENT", bundle_ids=["bdl_b1"])
    assert result["results"] == []
    assert result["truncated"] is False


def test_truncation_flagged(index) -> None:
    result = grep(index, "PARTICLE", bundle_ids=["bdl_b1"], max_results=1)
    assert len(result["results"]) == 1
    assert result["truncated"] is True


def test_missing_file_is_skipped_not_fatal(index, corpus: Path) -> None:
    (corpus / "b1" / index.doc_of("cpt_rare").path).unlink()
    result = grep(index, "PARTICLE", bundle_ids=["bdl_b1"])
    assert result["files_skipped"] == 1
    assert result["results"], "其餘檔案仍應被搜尋"


def test_scope_is_echoed(index) -> None:
    result = grep(index, "PARTICLE", bundle_ids=["bdl_b1"], concept_ids=["cpt_rare"])
    assert result["scope"] == {"bundle_ids": ["bdl_b1"], "concept_ids": ["cpt_rare"]}
