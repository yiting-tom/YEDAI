"""taxonomy 查表資源。

這份資源的核心約束是**查無條目不做近似比對**。拿另一個 defect 的判斷方法去解讀
影像，比沒有方法更糟——錯的方法看起來跟對的一樣有條理，而呼叫端沒有任何訊號
可以分辨。所以「沒有」必須是一個明確的答案，不是一個最接近的答案。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from yedai.taxonomy import (
    Taxonomy,
    TaxonomyNotFound,
    load_defect_catalogue,
)


def _write(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


@pytest.fixture
def resource(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "taxonomy.yaml",
        {
            "DEFECT_ALPHA": {
                "category": "pattern",
                "description": "形貌描述",
                "method": "判斷方法",
                "modules": ["MODULE_ONE"],
            },
            "DEFECT_BETA": {"category": "particle", "description": "另一種形貌"},
        },
    )


@pytest.fixture
def catalogue(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "defects.yaml",
        {
            "DEFECT_ALPHA": "pattern",
            "DEFECT_BETA": "particle",
            "DEFECT_GAMMA": "pattern",  # 尚未整理方法
        },
    )


# --- 以鍵取回，不做近似 -------------------------------------------------


def test_get_returns_the_entry(resource: Path) -> None:
    tx = Taxonomy.load(resource)
    assert tx.get("DEFECT_ALPHA").method == "判斷方法"
    assert tx.get("DEFECT_ALPHA").modules == ("MODULE_ONE",)


def test_missing_entry_raises_instead_of_approximating(resource: Path) -> None:
    """回最接近的一筆，會讓模型拿著錯的判準去看圖而且完全察覺不到。"""
    tx = Taxonomy.load(resource)
    with pytest.raises(TaxonomyNotFound):
        tx.get("DEFECT_ALPH")  # 只差一個字元


def test_missing_entry_leaks_no_other_entry(resource: Path) -> None:
    tx = Taxonomy.load(resource)
    try:
        tx.get("DEFECT_NOPE")
    except TaxonomyNotFound as exc:
        blob = json.dumps(exc.args, ensure_ascii=False)
        assert "DEFECT_ALPHA" not in blob
        assert "判斷方法" not in blob


def test_has_does_not_mutate_or_approximate(resource: Path) -> None:
    tx = Taxonomy.load(resource)
    assert tx.has("DEFECT_ALPHA")
    assert not tx.has("defect_alpha"), "鍵比對必須是精確的，大小寫不同就是不同的 defect"


# --- 載入與驗證 ---------------------------------------------------------


def test_no_resource_still_starts(tmp_path: Path) -> None:
    tx = Taxonomy.load(None)
    assert len(tx) == 0
    with pytest.raises(TaxonomyNotFound):
        tx.get("anything")


def test_malformed_yaml_raises_instead_of_starting_empty(tmp_path: Path) -> None:
    """以空資源靜默啟動，症狀會是「所有 defect 都查不到方法」——
    那看起來跟「還沒整理」一模一樣。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text("indexes:\n  - [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        Taxonomy.load(bad)
    assert str(bad) in str(exc.value)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Taxonomy.load(tmp_path / "nope.yaml")


def test_unknown_entry_key_is_refused(tmp_path: Path) -> None:
    p = _write(tmp_path / "t.yaml", {"D": {"methd": "拼錯了"}})
    with pytest.raises(ValueError, match="unknown keys"):
        Taxonomy.load(p)


def test_entry_outside_the_catalogue_is_warned_not_dropped(resource: Path, catalogue: Path) -> None:
    """條目指向清單外的 defect，可能表示清單缺漏——那本身是要處理的訊號。"""
    defects = load_defect_catalogue(catalogue)
    defects.pop("DEFECT_BETA")
    tx = Taxonomy.load(resource, defects)
    assert tx.unknown_keys == ["DEFECT_BETA"]
    assert tx.has("DEFECT_BETA"), "警告但保留——丟棄會讓缺漏無聲消失"
    assert tx.warnings


# --- 覆蓋率 -------------------------------------------------------------


def test_coverage_uses_the_catalogue_as_denominator(resource: Path, catalogue: Path) -> None:
    tx = Taxonomy.load(resource, load_defect_catalogue(catalogue))
    cov = tx.coverage()
    assert cov["total"] == 3
    assert cov["covered"] == 2
    assert cov["by_category"]["pattern"] == {"covered": 1, "total": 2}
    assert cov["by_category"]["particle"] == {"covered": 1, "total": 1}


def test_coverage_without_catalogue_reports_null_total(resource: Path) -> None:
    """拿條目數當分母會讓覆蓋率恆為 1.0，也就是永遠看不見缺口。"""
    cov = Taxonomy.load(resource).coverage()
    assert cov["total"] is None
    assert cov["covered"] == 2


def test_coverage_leaks_no_defect_names_or_entry_text(resource: Path, catalogue: Path) -> None:
    """類別名屬 schema，defect 名與條目文字屬語料內容——報告要能外流。"""
    tx = Taxonomy.load(resource, load_defect_catalogue(catalogue))
    blob = json.dumps(tx.coverage(), ensure_ascii=False)
    for secret in ("DEFECT_ALPHA", "DEFECT_BETA", "DEFECT_GAMMA", "判斷方法", "形貌描述", "MODULE_ONE"):
        assert secret not in blob, f"覆蓋率統計洩漏了 {secret!r}"
    assert "pattern" in blob, "類別名必須留著，否則拆解沒有意義"


# --- repo 邊界 ----------------------------------------------------------


def test_example_files_carry_no_real_content() -> None:
    """repo 是公開的：範例檔只能有結構示意。"""
    root = Path(__file__).resolve().parents[1]
    for name in ("taxonomy.example.yaml", "defects.catalogue.example.yaml"):
        text = (root / name).read_text(encoding="utf-8")
        assert "DEFECT_ALPHA" in text, "範例應使用明顯是佔位符的名稱"
        # 佔位符以外的 defect 名不該出現在範例中
        assert "local.yaml" in text, "範例必須指向 .local 檔，說明真實內容該放哪"


def test_local_taxonomy_paths_are_gitignored() -> None:
    root = Path(__file__).resolve().parents[1]
    ignored = (root / ".gitignore").read_text(encoding="utf-8")
    assert "*.local.yaml" in ignored, "taxonomy 與 defect/module 清單屬 fab 專有知識"
