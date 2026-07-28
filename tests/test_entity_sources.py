"""CSV 實體來源與父子層級展開。

這兩件事是同一個變更的兩半：真實語料把機台與腔體寫在同一張表、以 `#` 區分，
而在此之前 `#` 會讓識別碼斷成兩截、`ID:PM1` 在所有機台之間共用——
模式 B 在腔體層等同於失效。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yedai.config import Config
from yedai.entities import (
    DEFAULT_CHILD_TYPE,
    EntityDictionary,
    EntityExtractor,
    EntitySourceError,
)
from yedai.tokenizer import Tokenizer, expand_hierarchy, language_segments, normalise_identifier


# --- 斷詞層：`#` 與層級展開 ---


def test_hierarchical_identifier_captured_whole() -> None:
    tok = Tokenizer()
    ids = [t for t in tok.protected("aepol1#pm1") if t.startswith("ID:")]
    assert "ID:AEPOL1#PM1" in ids


def test_hash_survives_normalisation() -> None:
    # `#` 是層級分界。移除後無法還原——父層與子層都是變長的。
    assert normalise_identifier("aepol1#pm1") == "AEPOL1#PM1"


def test_hierarchy_expansion_emits_parent() -> None:
    assert expand_hierarchy("AEPOL1#PM1") == ["AEPOL1#PM1", "AEPOL1"]
    assert expand_hierarchy("AEPOL1") == ["AEPOL1"]


def test_parent_query_matches_child_only_document() -> None:
    tok = Tokenizer()
    doc = set(tok.protected("腔體 aepol1#pm1 出現異常"))
    query = [t for t in tok.protected("aepol1") if t.startswith("ID:")]
    assert query and set(query) <= doc


def test_same_chamber_on_different_tools_stays_distinct() -> None:
    tok = Tokenizer()
    a = {t for t in tok.protected("aepol1#pm1") if t.startswith("ID:")}
    b = {t for t in tok.protected("aepol6#pm1") if t.startswith("ID:")}
    # 父層當然不同；關鍵是子層也不能相同，否則等於回到 ID:PM1 共用的老問題
    assert "ID:AEPOL1#PM1" in a and "ID:AEPOL6#PM1" in b
    assert not ({"ID:AEPOL1#PM1"} & b)


def test_find_identifiers_expands_in_step_with_protected() -> None:
    # 只改一邊會讓詞彙腿認得父層、實體腿不認得，而那種分歧會被誤讀成「實體腿沒有用」
    tok = Tokenizer()
    from_protected = {t[3:] for t in tok.protected("aepol1#pm1") if t.startswith("ID:")}
    from_idents = {norm for _raw, norm, _s, _e in tok.find_identifiers("aepol1#pm1")}
    assert from_protected == from_idents == {"AEPOL1#PM1", "AEPOL1"}


def test_expansion_works_without_any_dictionary() -> None:
    # 展開只依字串結構。拿字典覆蓋率當前提會讓兩個機制的效果無法區分。
    ex = EntityExtractor(EntityDictionary.load(None), Tokenizer())
    canon = {h.canonical for h in ex.extract("aepol1#pm1")}
    assert canon == {"AEPOL1#PM1", "AEPOL1"}


def test_plain_identifier_produces_no_extra_token() -> None:
    tok = Tokenizer()
    ids = [t for t in tok.protected("aepol1") if t.startswith("ID:")]
    assert ids == ["ID:AEPOL1"]


# --- 語言分段 ---


def test_language_segments_splits_mixed() -> None:
    assert set(language_segments("Particle 微粒")) == {"Particle", "微粒"}


def test_language_segments_keeps_multiword_phrase_intact() -> None:
    # 拆成 Pattern / Collapse 的話，任何提到 "pattern" 的文件都會被判定含該缺陷
    assert set(language_segments("Pattern Collapse 圖案倒塌")) == {
        "Pattern Collapse",
        "圖案倒塌",
    }


def test_language_segments_strips_edge_punctuation() -> None:
    assert set(language_segments("微粒 (particle)")) == {"微粒", "particle"}


# --- CSV：id_only ---


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_id_only_loads_and_classifies_child_rows(tmp_path: Path) -> None:
    src = _write(tmp_path / "tools.csv", "tool_id\naepol1\naepol1#pm1\n")
    d = EntityDictionary.load(None, [{"type": "tool_id", "path": str(src), "schema": "id_only"}])
    assert d.lookup_normalised("AEPOL1") == ("tool_id", "AEPOL1")
    assert d.lookup_normalised("AEPOL1#PM1") == (DEFAULT_CHILD_TYPE, "AEPOL1#PM1")


def test_id_only_child_type_overridable(tmp_path: Path) -> None:
    src = _write(tmp_path / "t.csv", "aepol1#pm1\n")
    d = EntityDictionary.load(
        None,
        [{"type": "tool_id", "path": str(src), "schema": "id_only", "child_type": "cell"}],
    )
    assert d.lookup_normalised("AEPOL1#PM1") == ("cell", "AEPOL1#PM1")


def test_id_only_rejects_multi_column(tmp_path: Path) -> None:
    src = _write(tmp_path / "t.csv", "aepol1,extra\n")
    with pytest.raises(EntitySourceError) as exc:
        EntityDictionary.load(None, [{"type": "tool_id", "path": str(src), "schema": "id_only"}])
    assert "t.csv:1" in str(exc.value)


# --- CSV：module_code_name ---


def test_module_code_name_registers_name_as_alias(tmp_path: Path) -> None:
    src = _write(tmp_path / "d.csv", "Module,defect code,defect name\nETCH,PARTICLE,微粒\n")
    d = EntityDictionary.load(
        None, [{"type": "defect_code", "path": str(src), "schema": "module_code_name"}]
    )
    assert d.lookup_normalised("PARTICLE") == ("defect_code", "PARTICLE")
    assert d.literal_scan("出現微粒") == [("微粒", "defect_code", "PARTICLE")]


def test_module_is_metadata_not_identity(tmp_path: Path) -> None:
    # code 全域唯一。把 Module 併進識別會讓同一個缺陷分裂成多個實體。
    src = _write(
        tmp_path / "d.csv",
        "Module,defect code,defect name\nETCH,PARTICLE,微粒\nCMP,PARTICLE,微粒\n",
    )
    d = EntityDictionary.load(
        None, [{"type": "defect_code", "path": str(src), "schema": "module_code_name"}]
    )
    assert len(d) == 1


def test_mixed_language_name_matchable_by_either_language(tmp_path: Path) -> None:
    src = _write(
        tmp_path / "d.csv",
        "Module,defect code,defect name\nPHOTO,COLLAPSE,Pattern Collapse 圖案倒塌\n",
    )
    d = EntityDictionary.load(
        None, [{"type": "defect_code", "path": str(src), "schema": "module_code_name"}]
    )
    for probe in ("Pattern Collapse 圖案倒塌", "圖案倒塌"):
        assert d.literal_scan(probe)[0][2] == "COLLAPSE"
    assert d.lookup_normalised(normalise_identifier("PatternCollapse")) == (
        "defect_code",
        "COLLAPSE",
    )


def test_module_code_name_rejects_wrong_column_count(tmp_path: Path) -> None:
    src = _write(tmp_path / "d.csv", "ETCH,PARTICLE\n")
    with pytest.raises(EntitySourceError) as exc:
        EntityDictionary.load(
            None, [{"type": "defect_code", "path": str(src), "schema": "module_code_name"}]
        )
    assert "d.csv:1" in str(exc.value)


# --- 來源宣告的驗證 ---


def test_unknown_schema_fails_loudly(tmp_path: Path) -> None:
    src = _write(tmp_path / "x.csv", "a\n")
    with pytest.raises(EntitySourceError) as exc:
        EntityDictionary.load(None, [{"type": "t", "path": str(src), "schema": "nope"}])
    assert "id_only" in str(exc.value)


def test_missing_source_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        EntityDictionary.load(
            None, [{"type": "tool_id", "path": str(tmp_path / "nope.csv"), "schema": "id_only"}]
        )


def test_config_rejects_incomplete_source_declaration() -> None:
    with pytest.raises(ValueError, match="缺少必要欄位"):
        Config().merged({"entity_sources": [{"type": "tool_id"}]})


def test_config_rejects_unknown_schema() -> None:
    with pytest.raises(ValueError, match="不支援"):
        Config().merged(
            {"entity_sources": [{"type": "t", "path": "x.csv", "schema": "whatever"}]}
        )


# --- YAML 與 CSV 並存 ---


def test_yaml_and_csv_coexist(tmp_path: Path, dictionary_path: Path) -> None:
    src = _write(tmp_path / "tools.csv", "aepol1\n")
    d = EntityDictionary.load(
        dictionary_path, [{"type": "tool_id", "path": str(src), "schema": "id_only"}]
    )
    assert d.lookup_normalised("AEPOL1") is not None
    assert d.lookup_normalised("XTR05") is not None


def test_fingerprint_covers_csv_entries(tmp_path: Path) -> None:
    # 換字典必須讓索引快取失效，不論字典來自 YAML 還是 CSV
    a = _write(tmp_path / "a.csv", "aepol1\n")
    b = _write(tmp_path / "b.csv", "aepol1\naepol6\n")
    fa = EntityDictionary.load(None, [{"type": "tool_id", "path": str(a), "schema": "id_only"}])
    fb = EntityDictionary.load(None, [{"type": "tool_id", "path": str(b), "schema": "id_only"}])
    assert fa.fingerprint() != fb.fingerprint()
