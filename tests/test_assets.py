from __future__ import annotations

from pathlib import Path

import pytest

from yedai.assets import AssetForbidden, AssetNotFound, guess_media_type, resolve_asset
from yedai.entities import EntityDictionary
from yedai.fulltext import ConceptNotFound, load_concept
from yedai.index import build_index

from .conftest import PNG


@pytest.fixture
def index(corpus: Path, config):
    return build_index(corpus, config, EntityDictionary.load(config.dictionary_path))


# --- 正常路徑 -----------------------------------------------------------


def test_resolves_asset_from_frontmatter(index, corpus: Path) -> None:
    """`assets` 陣列裡的值可以直接使用，不需要任何轉換——這是端點存在的理由。"""
    path = resolve_asset(index, "cpt_title-hit", "_assets/slide_001.png")
    assert path.read_bytes() == PNG
    assert path == (corpus / "b1" / "okf" / "_assets" / "slide_001.png").resolve()


def test_every_declared_asset_resolves(index) -> None:
    declared = load_concept(index, "cpt_title-hit")["assets"]
    assert declared
    for rel in declared:
        assert resolve_asset(index, "cpt_title-hit", rel).is_file()


def test_citation_style_path_resolves(index) -> None:
    """`## Citations` 用的也是同一種相對寫法。"""
    assert resolve_asset(index, "cpt_title-hit", "_assets/slide_001.png").is_file()


def test_dot_slash_prefix_accepted(index) -> None:
    assert resolve_asset(index, "cpt_title-hit", "./_assets/slide_001.png").is_file()


def test_media_types() -> None:
    assert guess_media_type("x/slide_001.png") == "image/png"
    assert guess_media_type("x/a.jpg") in ("image/jpeg", "image/jpg")
    # 未知副檔名不猜測、不嗅探內容
    assert guess_media_type("x/notes.bin") == "application/octet-stream"
    assert guess_media_type("x/noext") == "application/octet-stream"


# --- 防線 1：早期拒絕 ----------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../../../../etc/passwd",
        "_assets/../../../../etc/passwd",
        "..",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "..\\..\\windows",
        "",
        "   ",
    ],
)
def test_traversal_and_absolute_paths_rejected(index, bad: str) -> None:
    with pytest.raises(AssetForbidden):
        resolve_asset(index, "cpt_title-hit", bad)


def test_traversal_rejected_before_touching_disk(index, corpus: Path) -> None:
    """含 `..` 的路徑即使指向真實存在的檔案也必須被擋。"""
    with pytest.raises(AssetForbidden):
        resolve_asset(index, "cpt_title-hit", "_assets/../not-an-asset.txt")


# --- 防線 2：容器檢查（安全邊界）----------------------------------------


def test_symlink_escaping_bundle_rejected(index, corpus: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("不該被讀到", encoding="utf-8")
    link = corpus / "b1" / "okf" / "_assets" / "escape.txt"
    link.symlink_to(outside)

    with pytest.raises(AssetForbidden, match="逸出"):
        resolve_asset(index, "cpt_title-hit", "_assets/escape.txt")


def test_symlink_within_bundle_allowed(index, corpus: Path) -> None:
    assets = corpus / "b1" / "okf" / "_assets"
    (assets / "alias.png").symlink_to(assets / "slide_001.png")
    assert resolve_asset(index, "cpt_title-hit", "_assets/alias.png").read_bytes() == PNG


# --- 防線 3：資產目錄白名單 ---------------------------------------------


def test_file_in_bundle_but_outside_asset_dirs_rejected(index) -> None:
    """誘餌檔在 bundle 內、路徑合法，但不在 _assets 之下——白名單必須擋住。"""
    with pytest.raises(AssetForbidden, match="_assets"):
        resolve_asset(index, "cpt_title-hit", "not-an-asset.txt")


def test_sibling_concept_file_not_readable_as_asset(index) -> None:
    with pytest.raises(AssetForbidden):
        resolve_asset(index, "cpt_title-hit", "body-hit.md")


def test_asset_dirs_override(index, corpus: Path) -> None:
    media = corpus / "b1" / "okf" / "media"
    media.mkdir()
    (media / "x.png").write_bytes(PNG)

    with pytest.raises(AssetForbidden):
        resolve_asset(index, "cpt_title-hit", "media/x.png")
    assert resolve_asset(index, "cpt_title-hit", "media/x.png", asset_dirs=["media"]).is_file()
    # 覆寫之後 _assets 就不再被允許
    with pytest.raises(AssetForbidden):
        resolve_asset(index, "cpt_title-hit", "_assets/slide_001.png", asset_dirs=["media"])


def test_nested_asset_dir_allowed(index, corpus: Path) -> None:
    nested = corpus / "b1" / "okf" / "_assets" / "figs"
    nested.mkdir()
    (nested / "deep.png").write_bytes(PNG)
    assert resolve_asset(index, "cpt_title-hit", "_assets/figs/deep.png").is_file()


# --- 失敗語意可區分 ------------------------------------------------------


def test_unknown_concept_raises_concept_not_found(index) -> None:
    with pytest.raises(ConceptNotFound):
        resolve_asset(index, "cpt_nope", "_assets/slide_001.png")


def test_missing_asset_raises_asset_not_found(index) -> None:
    with pytest.raises(AssetNotFound):
        resolve_asset(index, "cpt_title-hit", "_assets/does_not_exist.png")


def test_three_failure_modes_are_distinct(index) -> None:
    """三種失敗必須是三種例外——混在一起使用者無從判斷該修什麼。"""
    with pytest.raises(ConceptNotFound):
        resolve_asset(index, "cpt_nope", "_assets/slide_001.png")
    with pytest.raises(AssetNotFound):
        resolve_asset(index, "cpt_title-hit", "_assets/missing.png")
    with pytest.raises(AssetForbidden):
        resolve_asset(index, "cpt_title-hit", "../escape.png")


# --- 設定 ---------------------------------------------------------------


def test_config_rejects_empty_asset_dirs(config) -> None:
    with pytest.raises(ValueError, match="asset_dirs"):
        config.merged({"asset_dirs": []})


def test_config_rejects_path_separators_in_asset_dirs(config) -> None:
    with pytest.raises(ValueError, match="asset_dirs"):
        config.merged({"asset_dirs": ["a/b"]})


def test_asset_dirs_not_in_index_signature(config) -> None:
    """服務期政策改動不該迫使 220 萬 concept 重建索引。"""
    before = config.index_signature("fp")
    after = config.merged({"asset_dirs": ["media"]}).index_signature("fp")
    assert before == after
