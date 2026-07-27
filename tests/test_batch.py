from __future__ import annotations

from pathlib import Path

import pytest

from yedai.entities import EntityDictionary
from yedai.fulltext import MAX_BATCH, load_concepts
from yedai.index import build_index


@pytest.fixture
def index(corpus: Path, config):
    return build_index(corpus, config, EntityDictionary.load(config.dictionary_path))


def test_order_matches_request(index) -> None:
    ids = ["cpt_rare", "cpt_title-hit", "cpt_body-hit"]
    found, errors = load_concepts(index, ids)
    assert [c["concept_id"] for c in found] == ids
    assert errors == []


def test_partial_success(index) -> None:
    found, errors = load_concepts(index, ["cpt_title-hit", "cpt_nope", "cpt_body-hit"])
    assert [c["concept_id"] for c in found] == ["cpt_title-hit", "cpt_body-hit"]
    assert [e["concept_id"] for e in errors] == ["cpt_nope"]
    assert errors[0]["reason"] == "not_found"


def test_error_reasons_are_distinguishable(index, corpus: Path) -> None:
    (corpus / "b1" / index.doc_of("cpt_rare").path).unlink()
    _found, errors = load_concepts(index, ["cpt_nope", "cpt_rare"])
    reasons = {e["concept_id"]: e for e in errors}
    assert reasons["cpt_nope"]["reason"] == "not_found"
    assert reasons["cpt_rare"]["reason"] == "file_missing"
    assert "重建索引" in reasons["cpt_rare"]["detail"]


def test_all_failing_still_returns(index) -> None:
    found, errors = load_concepts(index, ["cpt_x", "cpt_y"])
    assert found == []
    assert len(errors) == 2


def test_include_raw_false_omits_full_text(index) -> None:
    found, _ = load_concepts(index, ["cpt_title-hit"], include_raw=False)
    assert "raw" not in found[0]
    # 結構化欄位仍在
    assert found[0]["sections"]
    assert found[0]["frontmatter"]


def test_include_raw_true_by_default(index) -> None:
    found, _ = load_concepts(index, ["cpt_title-hit"])
    assert found[0]["raw"].startswith("---")


def test_batch_limit_constant_is_sane() -> None:
    assert 1 < MAX_BATCH <= 100
