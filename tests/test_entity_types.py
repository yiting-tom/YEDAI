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


# --- 設定自行宣告類型（敏感的組成規則得以住在本機設定）---


#: 一條**編造**的樣式，形狀模仿「單寫與帶子層必須一致」的那類識別碼。
FAKE_TOOL = r"\b[wxyz][a-z](?:aa|bb)[mn][1-9a-z]\b"


def test_config_can_declare_a_type_for_a_custom_pattern() -> None:
    """敏感的組成規則不該進公開 repo，但寫進本機設定後仍必須帶得動類型宣告——
    否則使用者得在「斷詞正確」與「統計正確」之間二選一。"""
    cfg = Config(
        identifier_patterns=[
            {"pattern": FAKE_TOOL, "type": "widget_id", "shape_complete": True},
            *DEFAULT_IDENTIFIER_PATTERNS,
        ]
    )
    tok = Tokenizer(cfg.identifier_specs())
    ex = EntityExtractor(EntityDictionary.load(None), tok)
    assert {h.canonical: h.type for h in ex.extract("機台 wxaam5 異常")} == {"WXAAM5": "widget_id"}
    assert "widget_id" in tok.shape_complete_types


def test_declared_parent_type_is_used_in_expansion() -> None:
    cfg = Config(
        identifier_patterns=[
            {"pattern": r"\bQQ\d#\d\b", "type": "widget_part", "parent_type": "widget_id"},
            *DEFAULT_IDENTIFIER_PATTERNS,
        ]
    )
    ex = EntityExtractor(EntityDictionary.load(None), Tokenizer(cfg.identifier_specs()))
    assert {h.canonical: h.type for h in ex.extract("QQ1#2")} == {
        "QQ1#2": "widget_part",
        "QQ1": "widget_id",
    }


def test_letter_suffix_gap_is_closable_from_local_config() -> None:
    """這是本次的動機：形狀末位允許字母時，單寫與帶子層的行為必須一致。

    未宣告樣式時 `wxaama` 不是識別碼，但 `wxaama#1` 是——同一個實體因為寫法不同
    而時而進、時而不進實體空間，那種不一致不會報錯，只會讓模式 B/C 悄悄失效。
    """
    plain = Tokenizer()
    assert not plain.find_identifier_spans("wxaama")
    assert plain.find_identifier_spans("wxaama#1")  # 不一致

    cfg = Config(identifier_patterns=[{"pattern": FAKE_TOOL, "type": "widget_id"}, *DEFAULT_IDENTIFIER_PATTERNS])
    fixed = Tokenizer(cfg.identifier_specs())
    assert fixed.find_identifier_spans("wxaama")
    assert fixed.protected("wxaama") == ["ID:WXAAMA"]


def test_shape_complete_without_a_type_is_a_config_error() -> None:
    """沒有類型的完整性宣稱對不到任何分母——它會被靜默忽略，
    而使用者會以為自己開了一個其實沒開的東西。"""
    with pytest.raises(ValueError, match="shape_complete"):
        Config().merged({"identifier_patterns": [{"pattern": r"x\d", "shape_complete": True}]})


def test_mapping_without_pattern_is_rejected() -> None:
    with pytest.raises(ValueError, match="pattern"):
        Config().merged({"identifier_patterns": [{"type": "widget_id"}]})


def test_unknown_key_in_mapping_is_rejected() -> None:
    """打錯欄位名不該被靜默忽略——那會讓宣告看起來生效了但其實沒有。"""
    with pytest.raises(ValueError, match="不認得"):
        Config().merged({"identifier_patterns": [{"pattern": r"x\d", "typo": "widget_id"}]})


def test_invalid_regex_fails_at_config_time() -> None:
    """等到建索引才炸，錯誤會出現在離設定很遠的地方。"""
    with pytest.raises(ValueError, match="正則"):
        Config().merged({"identifier_patterns": ["[unclosed"]})


def test_string_form_still_behaves_the_same() -> None:
    assert Config().identifier_specs() == list(resolve_specs(DEFAULT_IDENTIFIER_PATTERNS))


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
