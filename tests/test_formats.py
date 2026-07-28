"""識別碼格式樣本驗證。

這個機制存在的理由：模式 B/C 的全部效果建立在「識別碼被當成一個整體」之上，
但真實識別碼不能進版控，所以樣式從來沒有被真實形狀驗證過——
合成語料剛好符合樣式，測試全綠，而樣式一條也沒對上真實形狀。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from yedai.cli import app
from yedai.formats import (
    FULL,
    INTACT,
    NONE,
    PARTIAL,
    check_coverage,
    check_sample,
    load_samples,
)
from yedai.tokenizer import Tokenizer

EXAMPLE = Path(__file__).resolve().parents[1] / "identifier-samples.example.yaml"


@pytest.fixture
def tok() -> Tokenizer:
    return Tokenizer()


# --- 四種判定 ---


def test_full_when_captured_whole(tok: Tokenizer) -> None:
    assert check_sample(tok, "aepol1#pm1").verdict == FULL


def test_partial_when_split_into_two(tok: Tokenizer) -> None:
    """被切成兩段看起來「有抓到」，但那正是模式 B 失效的形式，必須算失敗。"""
    r = check_sample(tok, "XTR-05 PM1 particle")
    assert r.verdict == PARTIAL
    assert not r.ok


def test_partial_when_only_part_of_sample_matched(tok: Tokenizer) -> None:
    # 前面多了無法辨識的前綴，命中範圍蓋不滿整個樣本
    r = check_sample(tok, "＠aepol1#pm1")
    assert r.verdict == PARTIAL


def test_none_when_nothing_matches_and_token_shatters(tok: Tokenizer) -> None:
    assert check_sample(tok, "完全沒有識別碼").verdict == NONE


def test_intact_when_not_an_identifier_but_single_token(tok: Tokenizer) -> None:
    """`A16` 沒被圈成識別碼，但仍是完整詞元——模式 A 會切成 `a` + `16`，模式 B 不會。

    這與「被切碎」的後果差很多。混為一談會讓工具喊太多狼，真正該修的就被淹掉。
    """
    r = check_sample(tok, "A16")
    assert r.verdict == INTACT
    assert r.ok


def test_partial_is_worse_than_none(tok: Tokenizer) -> None:
    """正則從中間咬進去會憑空產生一個錯的識別碼——比完全沒抓到更糟。"""
    patterns = [r"\d{3,4}\.\d{3}\b"]  # 缺前置 \b 的舊樣式
    broken = Tokenizer(patterns)
    assert broken.protected("10234.000") == ["1", "ID:0234.000"]
    assert check_sample(broken, "10234.000").verdict == PARTIAL


# --- 樣本檔載入 ---


def test_missing_path_returns_empty() -> None:
    assert load_samples(None) == {}


def test_declared_but_absent_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_samples(tmp_path / "nope.yaml")


def test_non_mapping_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "s.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_samples(p)


def test_type_without_samples_is_reported_not_passed(tok: Tokenizer, tmp_path: Path) -> None:
    """缺口要看得見。「沒有樣本」不等於「通過」。"""
    p = tmp_path / "s.yaml"
    p.write_text("tool_id:\n  - aepol1\nlayer: []\n", encoding="utf-8")
    report = check_coverage(tok, load_samples(p))
    assert report.types_without_samples == ["layer"]
    assert report.ok  # 有樣本的都過了，但上面那行仍顯示缺口


# --- 範例檔本身 ---


def test_example_samples_all_covered(tok: Tokenizer) -> None:
    """讓機制本身在 CI 有涵蓋——否則它壞掉也不會有人知道。"""
    report = check_coverage(tok, load_samples(EXAMPLE))
    assert report.ok, [(r.type, r.sample, r.tokens) for r in report.failures]


# --- 新增的樣式 ---


def test_op_no_survives_the_decimal_point(tok: Tokenizer) -> None:
    assert tok.protected("1234.000") == ["ID:1234.000"]
    assert tok.protected("234.000") == ["ID:234.000"]


def test_op_no_longer_than_spec_still_captured(tok: Tokenizer) -> None:
    """規格寫 3~4 碼，真實樣本有 5 碼——樣式照規格寫就會咬錯。"""
    assert tok.protected("10234.000") == ["ID:10234.000"]


def test_op_no_is_not_expanded(tok: Tokenizer) -> None:
    """小數點在作業序號裡分隔的是序號本身的組成，展開只會產生會碰撞的裸數字。"""
    assert tok.protected("1234.000") == ["ID:1234.000"]


def test_wafer_expands_to_lot(tok: Tokenizer) -> None:
    assert tok.protected("AB1234.01") == ["ID:AB1234.01", "ID:AB1234"]


def test_control_wafer_length_also_captured(tok: Tokenizer) -> None:
    """舊樣式只抓得到 6 碼的量產批，剛好在語義分界線上表現不一致。"""
    assert tok.protected("AB12345.00")[0] == "ID:AB12345.00"


def test_same_wafer_number_on_different_lots_stays_distinct(tok: Tokenizer) -> None:
    a = set(tok.protected("AB1234.01"))
    b = set(tok.protected("AB9999.01"))
    assert not (a & b)


def test_tech_has_no_pattern_but_survives_intact(tok: Tokenizer) -> None:
    """tech 刻意沒有樣式：真實形狀是 `A16` / `n5` / `n3`，前綴與位數都不固定。

    能涵蓋它們的正則會連 `p5`、`Q3` 一起圈進來；而只涵蓋一部分（抓 `n02` 卻漏 `n5`）
    比完全不涵蓋更糟——同類型內部行為不一致不會報錯，只會讓數據悄悄偏掉。
    """
    for sample in ("A16", "n02", "n5", "n3"):
        assert len(tok.protected(sample)) == 1, sample
        assert not tok.find_identifier_spans(sample), sample


def test_tech_still_differentiates_mode_b_from_mode_a(tok: Tokenizer) -> None:
    """沒有樣式不代表模式 B 沒有優勢——A 會切碎，B 不會。"""
    assert Tokenizer.naive("A16") == ["a", "16"]
    assert tok.protected("A16") == ["a16"]


def test_hyphenated_tool_keeps_its_chamber(tok: Tokenizer) -> None:
    """`XTR-05#PM1` 曾經被咬成 ID:XTR05 + ID:PM1，後者跨機台共用。"""
    assert tok.protected("XTR-05#PM1") == ["ID:XTR05#PM1", "ID:XTR05"]


# --- CLI ---


def test_cli_exits_nonzero_when_a_sample_is_uncovered(tmp_path: Path) -> None:
    samples = tmp_path / "s.yaml"
    samples.write_text("mystery:\n  - 完全沒有識別碼\n", encoding="utf-8")
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"identifier_samples_path: {samples}\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["check-formats", "-c", str(cfg)])
    assert result.exit_code == 1


def test_cli_exits_nonzero_when_no_samples_configured(tmp_path: Path) -> None:
    """沒有樣本不是通過——是我們不知道樣式有沒有效。"""
    cfg = tmp_path / "c.yaml"
    cfg.write_text("top_k: 10\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["check-formats", "-c", str(cfg)])
    assert result.exit_code == 2


def test_cli_passes_on_example_file(tmp_path: Path) -> None:
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"identifier_samples_path: {EXAMPLE}\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["check-formats", "-c", str(cfg)])
    assert result.exit_code == 0
