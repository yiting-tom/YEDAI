"""形狀決定的實體類型，與「分母可測才給比例」。

這個機制存在的理由：類型原本只有字典能給，regex fallback 一律標成 `unknown`。
於是每個具名類型的 regex 計數恆為 0、覆蓋率恆為 1.0——一個被設計來暴露字典缺口的
量測，結構上不可能暴露任何缺口。合成語料刻意只把一半的腔體放進字典，就是為了讓
缺口有東西可看，而那個缺口整整看不見。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yedai.config import Config
from yedai.entities import UNKNOWN_TYPE, EntityDictionary, EntityExtractor
from yedai.telemetry import build_report
from yedai.tokenizer import DEFAULT_IDENTIFIER_PATTERNS, IdentifierPattern, Tokenizer, resolve_specs


@pytest.fixture
def tok() -> Tokenizer:
    return Tokenizer()


@pytest.fixture
def bare(tok: Tokenizer) -> EntityExtractor:
    """完全沒有字典——類型只能由形狀決定，這正是要測的路徑。"""
    return EntityExtractor(EntityDictionary.load(None), tok)


# --- 形狀決定類型 ---


def test_chamber_gets_its_type_without_any_dictionary(bare: EntityExtractor) -> None:
    hits = {h.canonical: h for h in bare.extract("機台 TSK-04#PM3 異常")}
    assert hits["TSK04#PM3"].type == "chamber_id"
    assert hits["TSK04#PM3"].source == "regex"


def test_parent_gets_its_own_type_not_the_childs(bare: EntityExtractor) -> None:
    """`AEPOL1#PM1` 是腔體，`AEPOL1` 是機台。父層沿用子層類型會讓腔體的分母混進機台。"""
    hits = {h.canonical: h.type for h in bare.extract("aepol1#pm1")}
    assert hits == {"AEPOL1#PM1": "chamber_id", "AEPOL1": "tool_id"}


def test_ambiguous_shape_stays_unknown(bare: EntityExtractor) -> None:
    """`XTR-05` 可能是機台、製程、流程——猜一個會產出自信而錯誤的分母。"""
    assert all(h.type == UNKNOWN_TYPE for h in bare.extract("XTR-05 出現異常"))


def test_lot_and_wafer_split_on_the_suffix(bare: EntityExtractor) -> None:
    assert {h.canonical: h.type for h in bare.extract("AB1234.00")} == {
        "AB1234.00": "lot",
        "AB1234": "lot",
    }
    assert {h.canonical: h.type for h in bare.extract("AB1234.01")} == {
        "AB1234.01": "wafer",
        "AB1234": "lot",
    }


def test_lot_base_type_does_not_depend_on_which_sibling_was_seen(bare: EntityExtractor) -> None:
    """同一個字串必須永遠拿到同一個類型，否則查詢端與文件端會產出不同的實體鍵而比對不到。"""
    from_lot = {h.canonical: h.type for h in bare.extract("AB1234.00")}["AB1234"]
    from_wafer = {h.canonical: h.type for h in bare.extract("AB1234.01")}["AB1234"]
    assert from_lot == from_wafer == "lot"


def test_op_no_is_typed_and_not_expanded(bare: EntityExtractor) -> None:
    hits = {h.canonical: h.type for h in bare.extract("站點 1234.000")}
    assert hits == {"1234.000": "op_no"}


def test_dictionary_wins_over_shape(tok: Tokenizer, tmp_path: Path) -> None:
    """字典是人維護的，形狀是從樣式推的。衝突時以人為準。"""
    d = tmp_path / "d.yaml"
    d.write_text("some_other_type:\n  - canonical: TSK04#PM3\n", encoding="utf-8")
    ex = EntityExtractor(EntityDictionary.load(d), tok)
    hit = next(h for h in ex.extract("TSK-04#PM3") if h.canonical == "TSK04#PM3")
    assert hit.type == "some_other_type"
    assert hit.source == "dict"


# --- 宣告不能在「設定 → Tokenizer」之間掉光 ---


def test_config_default_keeps_the_type_declarations() -> None:
    """設定檔只能給字串。直接把字串丟給 Tokenizer 會讓宣告靜靜消失，覆蓋率退回恆為 1.0。

    這正是本次修的病，而它第一次出現就是在這條路徑上。
    """
    assert Config().identifier_specs() == list(resolve_specs(DEFAULT_IDENTIFIER_PATTERNS))
    assert "chamber_id" in Tokenizer(Config().identifier_specs()).shape_complete_types


def test_user_added_pattern_does_not_void_the_others() -> None:
    """加一條自訂樣式，不該讓其他樣式的宣告一起失效。"""
    cfg = Config(identifier_patterns=[*DEFAULT_IDENTIFIER_PATTERNS, r"ZZ\d{4}"])
    specs = cfg.identifier_specs()
    assert any(s.type == "chamber_id" for s in specs)
    assert specs[-1] == IdentifierPattern(r"ZZ\d{4}")  # 自訂的沒有宣告 → unknown


def test_measurable_types_follow_the_patterns_actually_used() -> None:
    """換掉樣式清單時，能不能算比例也要跟著變——寫死會讓宣稱在改過的樣式上繼續成立。"""
    only_op_no = Tokenizer([r"\b\d{3,6}\.\d{3}\b"])
    assert only_op_no.shape_complete_types == {"op_no"}


# --- 覆蓋率比例 ---


def _report(config: Config, corpus: Path):
    from yedai.index import build_index
    from yedai.telemetry import TelemetryStore

    index = build_index(corpus, config, EntityDictionary.load(config.dictionary_path))
    return build_report(index, TelemetryStore.create(config), config)


def test_ratio_is_null_when_the_denominator_is_not_measurable(config, corpus: Path) -> None:
    """機台可以裸寫，裸寫的形狀與其他類型無法區分——分母只會是下界，比例必然偏高。

    偏高的方向正好是「字典夠用、不必維護」，是最不該誤導使用者的方向。
    """
    by_type = _report(config, corpus)["entities"]["by_type"]
    assert by_type["tool_id"]["dictionary_coverage"] is None
    assert by_type["tool_id"]["dict"] > 0  # 有計數，只是沒有比例


def test_typing_does_not_change_what_matches_what(bare: EntityExtractor) -> None:
    """實體鍵從 `unknown:X` 變成 `chamber_id:X`，但查詢端與文件端**同步**改變。

    只改一邊會讓字典外的腔體在模式 C 徹底找不到，而那會被誤讀成「實體腿沒有用」。
    """
    doc = {h.key for h in bare.extract("## 現象\n\nTSK-04#PM3 出現異常")}
    query = {h.key for h in bare.extract("TSK04#PM3")}
    assert query <= doc
    assert "chamber_id:TSK04#PM3" in query


def test_lexical_tokens_are_untouched(tok: Tokenizer) -> None:
    """類型只影響實體空間的統計。模式 B 的詞元一字不改——包含 lot/wafer 的分流判斷
    若判錯，代價也僅止於統計桶的標籤。"""
    assert tok.protected("TSK-04#PM3") == ["ID:TSK04#PM3", "ID:TSK04"]
    assert tok.protected("AB1234.00") == ["ID:AB1234.00", "ID:AB1234"]
    assert tok.protected("AB1234.01") == ["ID:AB1234.01", "ID:AB1234"]


def test_report_says_which_types_have_a_measurable_denominator(config, corpus: Path) -> None:
    """否則讀報告的人無從判斷一個 null 是「沒有這種實體」還是「分母不可測」。"""
    entities = _report(config, corpus)["entities"]
    assert "chamber_id" in entities["coverage_measurable_types"]
    assert "tool_id" not in entities["coverage_measurable_types"]
