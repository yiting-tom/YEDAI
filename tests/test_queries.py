"""查詢清單產生。

自己產查詢的失敗方式是憑空編——那等於自己選了決定答案的那個變因。
這裡的測試釘住的是「素材全部來自真實語料」與「各組真的在測它該測的東西」。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from yedai.config import Config
from yedai.entities import EntityDictionary, EntityExtractor
from yedai.index import build_index
from yedai.queries import DEFAULT_MIX, generate, load, render
from yedai.tokenizer import Tokenizer

from .conftest import INDEX_NAME


@pytest.fixture
def built(corpus: Path, config: Config):
    dictionary = EntityDictionary.load(config.dictionary_path)
    index = build_index(corpus, config, dictionary, name=INDEX_NAME)
    tok = Tokenizer(config.identifier_specs())
    return index, dictionary, tok


# --- 素材必須來自語料 ---


def test_identifiers_come_from_the_corpus(built) -> None:
    """編造的識別碼分佈會直接決定結論，而那個分佈沒有任何根據。"""
    index, dictionary, tok = built
    qs = generate(index, dictionary, n=30, tokenizer=tok, seed=1)
    known = {k.split(":", 1)[1] for k in index.entities.postings if ":" in k}
    ex = EntityExtractor(dictionary, tok)
    for q in qs.queries:
        for hit in ex.extract(q):
            assert hit.canonical in known or hit.canonical.upper() in {k.upper() for k in known}, q


def test_same_seed_gives_the_same_list(built) -> None:
    """不可重現的清單會讓兩次報告無法比較，而「這次和上次差在哪」正是要看的東西。"""
    index, dictionary, tok = built
    a = generate(index, dictionary, n=25, tokenizer=tok, seed=3).queries
    b = generate(index, dictionary, n=25, tokenizer=tok, seed=3).queries
    assert a == b


def test_different_seed_gives_a_different_list(built) -> None:
    index, dictionary, tok = built
    a = generate(index, dictionary, n=25, tokenizer=tok, seed=3).queries
    b = generate(index, dictionary, n=25, tokenizer=tok, seed=4).queries
    assert a != b


def test_frequent_identifiers_are_sampled_more(built) -> None:
    """常見的識別碼比罕見的更常被查；均勻取樣會系統性高估罕見識別碼的影響。"""
    index, dictionary, tok = built
    qs = generate(index, dictionary, n=400, tokenizer=tok, seed=5, mix={"bare_identifier": 1.0})
    counts: dict[str, int] = {}
    for q in qs.queries:
        counts[q] = counts.get(q, 0) + 1

    df = {k.split(":", 1)[1]: v for k, v in index.entities.df.items() if ":" in k}
    seen = [(counts.get(name, 0), df.get(name, 0)) for name in df]
    hi = [c for c, d in seen if d >= max(df.values())]
    lo = [c for c, d in seen if d == min(df.values())]
    assert sum(hi) / max(len(hi), 1) > sum(lo) / max(len(lo), 1)


# --- 各組要真的在測它該測的東西 ---


def test_descriptive_queries_carry_no_entities(built) -> None:
    """該組存在的理由是「關鍵字腿會落空」。夾帶一個識別碼就會命中；
    夾帶一個字典認得的缺陷名，模式 C 更會靠實體腿直接贏。"""
    index, dictionary, tok = built
    qs = generate(index, dictionary, n=60, tokenizer=tok, seed=2, mix={"descriptive": 1.0})
    ex = EntityExtractor(dictionary, tok)
    for q in qs.queries:
        assert not ex.extract(q), f"描述性查詢仍夾帶實體：{q!r}"


def test_alias_group_uses_non_canonical_forms(built) -> None:
    """用正規名稱造查詢問不出字典的價值——它本來就是識別碼形狀，模式 B 自己就抓得到。"""
    index, dictionary, tok = built
    qs = generate(index, dictionary, n=40, tokenizer=tok, seed=2, mix={"alias": 1.0})
    canonicals = {k.split(":", 1)[1].lower() for k in index.entities.postings if ":" in k}
    assert qs.queries
    for q in qs.queries:
        assert q.lower() not in canonicals, q


def test_bare_identifier_group_is_all_identifiers(built) -> None:
    index, dictionary, tok = built
    qs = generate(index, dictionary, n=20, tokenizer=tok, seed=2, mix={"bare_identifier": 1.0})
    ex = EntityExtractor(dictionary, tok)
    assert all(ex.extract(q) for q in qs.queries)


def test_requested_count_is_honoured(built) -> None:
    index, dictionary, tok = built
    # two_identifiers 會丟掉自己配到自己的那些，所以只檢查上界
    assert len(generate(index, dictionary, n=40, tokenizer=tok, seed=1).queries) <= 40
    assert len(generate(index, dictionary, n=40, tokenizer=tok, seed=1).queries) >= 35


# --- 缺口要看得見 ---


def test_missing_dictionary_reports_a_shortfall_instead_of_crashing(built) -> None:
    """沒有別名就測不了字典那條腿。靜靜產出別的東西會讓「模式 C 沒有用」
    這個結論建立在「根本沒測到模式 C」之上。"""
    index, _dictionary, tok = built
    qs = generate(index, None, n=20, tokenizer=tok, seed=1)
    assert qs.composition["alias"] == 0
    assert "alias" in qs.shortfalls


def test_small_material_pool_is_reported(built) -> None:
    """素材種類少於產出筆數時該組必然重複抽樣——那組的重疊度會變成
    少數幾條查詢的性質，而不是一個分佈。"""
    index, dictionary, tok = built
    qs = generate(index, dictionary, n=200, tokenizer=tok, seed=1, mix={"alias": 1.0})
    assert qs.pool_sizes["alias"] < 200
    assert "alias" in qs.shortfalls


def test_header_records_the_assumptions(built) -> None:
    """比例是一個沒有根據的假設。記錄下來，才能被檢查、被換掉。"""
    index, dictionary, tok = built
    qs = generate(index, dictionary, n=10, tokenizer=tok, seed=9)
    text = render(qs, seed=9, mix=DEFAULT_MIX, index_path=".index/x.pkl")
    assert "seed=9" in text
    assert "不要進版控" in text
    for name in DEFAULT_MIX:
        assert name in text


def test_load_skips_the_header(built, tmp_path: Path) -> None:
    index, dictionary, tok = built
    qs = generate(index, dictionary, n=10, tokenizer=tok, seed=9)
    p = tmp_path / "q.txt"
    p.write_text(render(qs, 9, DEFAULT_MIX, "x"), encoding="utf-8")
    assert load(p) == qs.queries


# --- CLI ---


def test_compare_file_ignores_the_header(built, tmp_path: Path, config: Config, monkeypatch) -> None:
    """檔頭記錄了組成與種子。把它當成查詢會讓一整批註解文字混進統計裡。"""
    from typer.testing import CliRunner

    from yedai.cli import app

    index, dictionary, tok = built
    qs = generate(index, dictionary, n=3, tokenizer=tok, seed=1)
    qfile = tmp_path / "q.txt"
    qfile.write_text(render(qs, 1, DEFAULT_MIX, "x"), encoding="utf-8")

    spec = config.index_spec(INDEX_NAME)
    index.save(spec.path)
    cfgfile = tmp_path / "c.yaml"
    cfgfile.write_text(
        yaml.safe_dump(
            {
                "indexes": {INDEX_NAME: {"source": spec.source, "path": spec.path}},
                "dictionary_path": config.dictionary_path,
                "log_dir": config.log_dir,
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["compare", "-f", str(qfile), "-c", str(cfgfile)])
    assert result.exit_code == 0, result.output
    assert f"批次彙總（{len(qs.queries)} 個查詢）" in result.output
