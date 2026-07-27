from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from yedai.entities import EntityDictionary
from yedai.fulltext import (
    ConceptFileMissing,
    ConceptNotFound,
    ConceptPathEscape,
    load_concept,
    resolve_path,
)
from yedai.index import INDEX_FORMAT_VERSION, Index, build_index

from .conftest import make_bundle, write_concept

MARKER = "獨一無二的內文標記_ZQXJ7"


@pytest.fixture
def index(corpus: Path, config):
    return build_index(corpus, config, EntityDictionary.load(config.dictionary_path))


def test_returns_raw_identical_to_disk(index, corpus: Path) -> None:
    data = load_concept(index, "cpt_title-hit")
    on_disk = (corpus / "b1" / data["path"]).read_text(encoding="utf-8")
    assert data["raw"] == on_disk
    assert data["raw"].startswith("---")


def test_returns_parsed_frontmatter_and_sections(index) -> None:
    data = load_concept(index, "cpt_title-hit")
    assert data["frontmatter"]["id"] == "cpt_title-hit"
    assert data["frontmatter"]["title"] == "XTR-05 PARTICLE 調查"
    assert [s["heading"] for s in data["sections"]] == ["現象"]
    assert data["tags"] == ["yield"]


def test_identity_fields_match_search_results(index, searcher) -> None:
    hit = next(
        h for h in searcher.search("PARTICLE", mode="B", k=10).hits if h.concept_id == "cpt_title-hit"
    )
    data = load_concept(index, hit.concept_id)

    for key in ("concept_id", "bundle_id", "type", "title", "description", "path"):
        assert data[key] == getattr(hit, key), f"{key} 在檢索結果與全文之間不一致"
    assert data["index_line"] == hit.index_line()


def test_undelimited_frontmatter_parses_same_as_indexing(tmp_path: Path, config) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    write_concept(
        okf,
        "nodelim",
        frontmatter={"id": "cpt_nodelim", "title": "無分隔線", "custom_key": 99},
        body="## 甲\n\n內容甲\n\n## 乙\n\n內容乙\n",
        delimited=False,
    )
    idx = build_index(root, config, EntityDictionary.load(config.dictionary_path))
    data = load_concept(idx, "cpt_nodelim")

    assert data["title"] == "無分隔線"
    assert [s["heading"] for s in data["sections"]] == ["甲", "乙"]
    assert data["frontmatter"]["custom_key"] == 99  # 未知欄位保留


def test_index_does_not_contain_body(corpus: Path, config) -> None:
    """全文若被塞進索引，2.2M concept 時 pickle 會膨脹到無法載入。"""
    okf = corpus / "b1" / "okf"
    write_concept(okf, "marked", frontmatter={"id": "cpt_marked"}, body=f"## 現象\n\n{MARKER}\n")
    idx = build_index(corpus, config, EntityDictionary.load(config.dictionary_path))

    blob = pickle.dumps(idx)
    assert MARKER.encode("utf-8") not in blob, "索引不得含 concept body"
    # 但仍取得回全文
    assert MARKER in load_concept(idx, "cpt_marked")["raw"]


def test_file_edit_reflected_without_reindex(index, corpus: Path) -> None:
    path = corpus / "b1" / index.doc_of("cpt_body-hit").path
    path.write_text(path.read_text(encoding="utf-8") + f"\n## 追加\n\n{MARKER}\n", encoding="utf-8")

    data = load_concept(index, "cpt_body-hit")
    assert MARKER in data["raw"]
    assert "追加" in [s["heading"] for s in data["sections"]]


def test_by_id_lookup_and_bundle_roots(index, corpus: Path) -> None:
    assert index.doc_of("cpt_title-hit") is not None
    assert index.doc_of("cpt_does_not_exist") is None
    assert set(index.bundle_roots) == {"bdl_b1"}

    _meta, path = resolve_path(index, "cpt_title-hit")
    assert path.is_file()
    assert path.is_relative_to(Path(index.bundle_roots["bdl_b1"]))


def test_unknown_concept_id_raises_not_found(index) -> None:
    with pytest.raises(ConceptNotFound):
        load_concept(index, "cpt_nope")


def test_missing_file_raises_distinct_error(index, corpus: Path) -> None:
    (corpus / "b1" / index.doc_of("cpt_rare").path).unlink()
    with pytest.raises(ConceptFileMissing):
        load_concept(index, "cpt_rare")


def test_path_escape_is_rejected(index) -> None:
    index.docs[index.by_id["cpt_unrelated"]].path = "../../../../etc/passwd"
    with pytest.raises(ConceptPathEscape):
        load_concept(index, "cpt_unrelated")


def test_duplicate_concept_id_keeps_first_and_warns(tmp_path: Path, config) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    write_concept(okf, "aaa", frontmatter={"id": "cpt_dup"}, body="## x\n\n第一份\n")
    write_concept(okf, "zzz", frontmatter={"id": "cpt_dup"}, body="## x\n\n第二份\n")

    idx = build_index(root, config, EntityDictionary.load(config.dictionary_path))
    assert any("重複的 concept_id" in w for w in idx.warnings)
    assert "第一份" in load_concept(idx, "cpt_dup")["raw"]


def test_old_format_index_is_rejected(tmp_path: Path) -> None:
    stale = Index(signature="x")
    stale.format_version = INDEX_FORMAT_VERSION - 1
    path = tmp_path / "stale.pkl"
    stale.save(path)

    with pytest.raises(ValueError, match="重建索引"):
        Index.load(path)
