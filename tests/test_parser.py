from __future__ import annotations

from pathlib import Path

import pytest

from yedai.parser import load_bundles, parse_sections, split_frontmatter

from .conftest import make_bundle, write_concept


def test_full_frontmatter_is_parsed(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    write_concept(
        okf,
        "full",
        frontmatter={
            "type": "spec_definition",
            "title": "標題",
            "slug": "s",
            "description": "描述",
            "generated": True,
            "content_hash": "abc",
            "confidence": "high",
            "resource": "file://x.pptx#slide=1,2",
            "provenance": "file://x.pptx#slide=1,2",
            "tags": ["a", "b"],
            "related": ["cpt_other"],
            "model": "m",
            "timestamp": "2026-06-01T00:00:00+00:00",
            "assets": ["_assets/slide_001.png"],
            "subpath": "spec/s",
            "figures": [
                {"file_id": "f1", "type": "chart", "title": "圖", "description": "說明", "key_points": ["p1"]}
            ],
        },
    )
    bundles, report = load_bundles(root)
    concept = bundles[0].concepts[0]

    assert report.concepts == 1
    assert concept.type == "spec_definition"
    assert concept.tags == ["a", "b"]
    assert concept.related == ["cpt_other"]
    assert concept.figures[0].key_points == ["p1"]
    assert concept.figures[0].file_id == "f1"


def test_missing_id_falls_back_to_path(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    path = okf / "noid.md"
    path.write_text("---\ntype: training\ntitle: T\n---\n\n## A\n\nx\n", encoding="utf-8")

    bundles, _ = load_bundles(root)
    assert bundles[0].concepts[0].concept_id.startswith("path:")


def test_unknown_fields_preserved_in_extra(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    write_concept(okf, "x", frontmatter={"custom_field": 42})

    bundles, _ = load_bundles(root)
    assert bundles[0].concepts[0].extra["custom_field"] == 42


def test_frontmatter_without_delimiters(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    write_concept(okf, "nodelim", frontmatter={"title": "無分隔線"}, delimited=False)

    bundles, _ = load_bundles(root)
    concept = bundles[0].concepts[0]
    assert concept.title == "無分隔線"
    assert "## 內容" in concept.body


def test_no_frontmatter_at_all(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    (okf / "plain.md").write_text("## 只有內容\n\n沒有 frontmatter。\n", encoding="utf-8")

    bundles, report = load_bundles(root)
    assert report.concepts == 1
    assert bundles[0].concepts[0].body.startswith("## 只有內容")


def test_broken_file_does_not_stop_batch(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    write_concept(okf, "good")
    # frontmatter 宣稱是 mapping 但實際是 scalar → parse_concept 會拿到非 dict
    (okf / "broken.md").write_text("---\n\t- [unclosed\n---\n\n## x\n", encoding="utf-8")

    bundles, report = load_bundles(root)
    assert report.concepts >= 1
    assert any(c.concept_id == "cpt_good" for c in bundles[0].concepts)


def test_assets_directory_excluded(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    write_concept(okf, "real")
    (okf / "_assets" / "note.md").write_text("---\nid: cpt_asset\ntype: x\n---\n\n## a\n", encoding="utf-8")

    bundles, report = load_bundles(root)
    assert report.concepts == 1
    assert bundles[0].concepts[0].concept_id == "cpt_real"


def test_reserved_filenames_are_routed(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    write_concept(okf, "real")
    (okf / "summary.md").write_text("id: sum_1\ntype: bundle_summary\ntitle: 摘要\n\n## 摘要\n\nx\n", encoding="utf-8")
    (okf / "log.md").write_text("# log\n", encoding="utf-8")
    (okf / "index.md").write_text("[摘要](summary.md)\n", encoding="utf-8")

    bundles, report = load_bundles(root)
    assert report.concepts == 1
    assert bundles[0].summary is not None
    assert bundles[0].summary.title == "摘要"


def test_missing_manifest_is_tolerated(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    (root / "b1" / "manifest.json").unlink()
    write_concept(okf, "x")

    bundles, _ = load_bundles(root)
    assert bundles[0].bundle_id == "b1"


def test_broken_manifest_records_warning(tmp_path: Path) -> None:
    root = tmp_path / "b"
    okf = make_bundle(root, "b1")
    (root / "b1" / "manifest.json").write_text("{not json", encoding="utf-8")
    write_concept(okf, "x")

    _, report = load_bundles(root)
    assert report.warnings
    assert report.concepts == 1


def test_parse_sections_keeps_preamble() -> None:
    sections = parse_sections("前言文字\n\n## 現象\n\n內容\n")
    assert sections[0].heading == ""
    assert "前言文字" in sections[0].text
    assert sections[1].heading == "現象"


def test_parse_sections_without_headings() -> None:
    sections = parse_sections("只有一段文字")
    assert len(sections) == 1
    assert sections[0].heading == ""


def test_split_frontmatter_variants() -> None:
    fm, body = split_frontmatter("---\na: 1\n---\n\n## x\n")
    assert fm == {"a": 1} and body.strip() == "## x"

    fm, body = split_frontmatter("a: 1\nb: 2\n\n## x\n")
    assert fm == {"a": 1, "b": 2} and body.strip().startswith("## x")

    fm, body = split_frontmatter("## 只有標題\n")
    assert fm == {}


def test_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        load_bundles(tmp_path / "does-not-exist")
