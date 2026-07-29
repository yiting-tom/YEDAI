"""LLM 產生的評估集與檢索指標。

`mode_overlap` 只能說五個模式不一樣，說不出哪個比較對——因為沒有標準答案。
這裡補的就是標準答案，而標籤的兩個偏誤必須一路跟著數字走。

測試**一律不觸網**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yedai.config import Config
from yedai.entities import EntityDictionary
from yedai.evalset import (
    EVALSET_CAVEATS,
    IDENTIFIER_KIND,
    SYMPTOM_KIND,
    EvalItem,
    EvalSet,
    dump,
    evaluate,
    generate,
    load,
    sample_concepts,
)
from yedai.index import build_index
from yedai.llm import CachedChat, ChatError, HttpChatClient, parse_json_block
from yedai.search import Searcher
from yedai.vectors import CorpusLeakGuard, guard_corpus_leaves_process


class FakeChat:
    """回傳固定的 JSON。可設定成回傳畸形內容，用來測失敗處理。"""

    def __init__(self, payload: str | None = None) -> None:
        self.model = "fake-kimi"
        self.calls: list[tuple[str, str]] = []
        self.payload = payload or json.dumps(
            [
                {"query": "AEPOL1 微粒偏高", "kind": IDENTIFIER_KIND},
                {"query": "蝕刻後圖案倒塌要看哪些參數", "kind": SYMPTOM_KIND},
            ],
            ensure_ascii=False,
        )

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.payload


@pytest.fixture
def built(corpus: Path, config: Config):
    dictionary = EntityDictionary.load(config.dictionary_path)
    index = build_index(corpus, config, dictionary)
    return index, Searcher(index, config, dictionary)


# --- JSON 解析 ---------------------------------------------------------


def test_parses_plain_json() -> None:
    assert parse_json_block('[{"a": 1}]') == [{"a": 1}]


def test_parses_fenced_json() -> None:
    """模型很常把 JSON 包在圍欄裡。嚴格解析會讓一個純粹的格式習慣變成整批失敗。"""
    assert parse_json_block('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert parse_json_block("```\n[1, 2]\n```") == [1, 2]


def test_parses_json_with_surrounding_prose() -> None:
    assert parse_json_block('以下是結果：\n[{"a": 1}]\n希望有幫助') == [{"a": 1}]


def test_malformed_json_raises_rather_than_being_repaired() -> None:
    """修復畸形 JSON 會把「模型答錯了」變成「我們猜它想說什麼」。"""
    with pytest.raises(ValueError):
        parse_json_block("[{'a': ")


# --- 產生 ---------------------------------------------------------------


def test_generates_query_and_gold_label(built) -> None:
    index, _ = built
    chat = FakeChat()
    es = generate(index, chat, n_concepts=2, text_of=lambda m: m.title, seed=1)
    assert es.items
    known = {m.concept_id for m in index.docs}
    for item in es.items:
        assert item.gold_concept_id in known
        assert item.query


def test_both_kinds_are_present(built) -> None:
    """症狀式那組是回答「稠密腿值不值得」的唯一素材；
    識別碼式查詢上關鍵字模式佔優是預期內的，沒有資訊量。"""
    index, _ = built
    es = generate(index, FakeChat(), n_concepts=2, text_of=lambda m: m.title, seed=1)
    kinds = set(es.by_kind())
    assert kinds == {IDENTIFIER_KIND, SYMPTOM_KIND}


def test_bad_response_skips_the_concept_without_aborting(built) -> None:
    """一批可能是幾百次請求。為了一次格式異常全部重來，代價是這個工具不會被再跑第二次。"""
    index, _ = built
    es = generate(index, FakeChat("這不是 JSON"), n_concepts=3, text_of=lambda m: m.title, seed=1)
    assert es.items == []
    assert es.failed == 3
    assert es.sampled == 3


def test_unknown_kind_is_dropped(built) -> None:
    index, _ = built
    payload = json.dumps([{"query": "x", "kind": "made_up"}, {"query": "y", "kind": SYMPTOM_KIND}])
    es = generate(index, FakeChat(payload), n_concepts=1, text_of=lambda m: m.title, seed=1)
    assert [i.kind for i in es.items] == [SYMPTOM_KIND]


def test_prompt_asks_for_an_unread_perspective(built) -> None:
    """LLM 看著文件寫查詢會照抄罕見詞，使關鍵字模式虛胖、稠密腿被低估。"""
    index, _ = built
    chat = FakeChat()
    generate(index, chat, n_concepts=1, text_of=lambda m: m.title, seed=1)
    _system, user = chat.calls[0]
    assert "沒有讀過" in user
    assert "不含任何識別碼" in user


def test_sampling_spreads_across_types() -> None:
    """全擠在同一類會讓評估集反映的是那一類的性質——不同 type 的文件結構差很多。"""
    from yedai.index import DocMeta, Index

    idx = Index(signature="x")
    # 刻意不平衡：training 佔九成。天真的隨機取樣會幾乎只抽到 training。
    idx.docs = [
        DocMeta(f"cpt_{i}", "b", "training" if i % 10 else "case_investigation", "t", "d", "p")
        for i in range(50)
    ]
    picked = sample_concepts(idx, n=6, seed=1)
    types = {idx.docs[i].type for i in picked}
    assert types == {"training", "case_investigation"}


# --- 快取 ---------------------------------------------------------------


def test_cache_avoids_a_second_request(tmp_path: Path) -> None:
    inner = FakeChat()
    cached = CachedChat(inner, tmp_path / "c")
    cached.complete("sys", "user")
    cached.complete("sys", "user")
    assert len(inner.calls) == 1
    assert cached.hits == 1


def test_cache_is_keyed_by_model(tmp_path: Path) -> None:
    """換模型後沿用舊標籤會讓兩批標籤混在一起，而混合的標籤集對應不到
    任何一個可解釋的產生過程。"""
    a = CachedChat(FakeChat(), tmp_path / "c")
    a.complete("s", "u")
    other = FakeChat()
    other.model = "another"
    b = CachedChat(other, tmp_path / "c")
    b.complete("s", "u")
    assert b.misses == 1


def test_missing_key_names_the_variable(monkeypatch) -> None:
    monkeypatch.delenv("NOPE_ENV", raising=False)
    with pytest.raises(ChatError, match="NOPE_ENV"):
        HttpChatClient("https://x/v1", "m", "NOPE_ENV").complete("s", "u")


# --- 指標 ---------------------------------------------------------------


def _searcher_with_known_answer(built):
    index, searcher = built
    return index, searcher


def test_metrics_are_computed_per_mode(built) -> None:
    index, searcher = built
    gold = index.docs[0].concept_id
    es = EvalSet(items=[EvalItem(index.docs[0].title, gold, IDENTIFIER_KIND)])
    result = evaluate(es, searcher, k=10)
    assert set(result["overall"]) == set(searcher.available_modes)
    for m in result["overall"].values():
        assert m["recall_at_k"] is not None


def test_misses_count_in_the_denominator(built) -> None:
    """把找不到的查詢排除會讓表現差的模式看起來更好——那正好是要分辨的東西。"""
    index, searcher = built
    es = EvalSet(
        items=[
            EvalItem("完全對不上任何東西的查詢字串", index.docs[0].concept_id, SYMPTOM_KIND),
            EvalItem(index.docs[0].title, index.docs[0].concept_id, IDENTIFIER_KIND),
        ]
    )
    result = evaluate(es, searcher, k=10)
    for m in result["overall"].values():
        assert m["n"] == 2
        assert m["recall_at_k"] <= 0.5


def test_metrics_split_by_kind(built) -> None:
    index, searcher = built
    es = EvalSet(
        items=[
            EvalItem(index.docs[0].title, index.docs[0].concept_id, IDENTIFIER_KIND),
            EvalItem(index.docs[1].title, index.docs[1].concept_id, SYMPTOM_KIND),
        ]
    )
    result = evaluate(es, searcher, k=10)
    for kinds in result["by_kind"].values():
        assert kinds[IDENTIFIER_KIND]["n"] == 1
        assert kinds[SYMPTOM_KIND]["n"] == 1


def test_result_carries_the_caveats(built) -> None:
    """限制跟著數字走。分家之後，絕對值遲早會被引用到不該被引用的地方。"""
    index, searcher = built
    es = EvalSet(items=[EvalItem("x", index.docs[0].concept_id, SYMPTOM_KIND)])
    result = evaluate(es, searcher, k=5)
    assert result["caveats"] == list(EVALSET_CAVEATS)
    assert any("下界" in c for c in result["caveats"])


# --- 落地 ---------------------------------------------------------------


def test_roundtrip_preserves_items(tmp_path: Path) -> None:
    es = EvalSet(
        items=[EvalItem("查詢", "cpt_a", IDENTIFIER_KIND)], sampled=3, failed=1, model="fake"
    )
    p = tmp_path / "e.jsonl"
    dump(es, p)
    back = load(p)
    assert back.items == es.items
    assert (back.sampled, back.failed, back.model) == (3, 1, "fake")


def test_file_header_carries_the_caveats(tmp_path: Path) -> None:
    p = tmp_path / "e.jsonl"
    dump(EvalSet(items=[EvalItem("q", "cpt_a", SYMPTOM_KIND)]), p)
    header = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert header["_header"] is True
    assert header["caveats"] == list(EVALSET_CAVEATS)
    assert "不要進版控" in header["note"]


# --- 外流閘門 ---------------------------------------------------------


def test_llm_trust_is_independent_of_embedding_trust(tmp_path: Path) -> None:
    """把信任從一個端點自動延伸到另一個，正是這道閘門要防的事——
    即使兩者目前指向同一個位址。"""
    real = tmp_path / "real"
    real.mkdir()
    cfg = Config().merged({"embedding": {"trusted_endpoint": True}})
    assert cfg.embedding["trusted_endpoint"] is True
    assert cfg.llm["trusted_endpoint"] is False
    with pytest.raises(CorpusLeakGuard):
        guard_corpus_leaves_process(
            real, cfg.llm["base_url"], bool(cfg.llm.get("trusted_endpoint", False))
        )


def test_config_rejects_a_key_pasted_into_llm_api_key_env() -> None:
    with pytest.raises(ValueError, match="環境變數名稱"):
        Config().merged({"llm": {"api_key_env": "sk-or-v1-deadbeef"}})


# --- 報告 ---------------------------------------------------------------


def test_report_carries_metrics_but_no_query_text(built, config: Config) -> None:
    """查詢原文是語料衍生物、帶真實識別碼；報告是唯一設計為可外流的產出。"""
    from yedai.telemetry import TelemetryStore, build_report

    index, searcher = built
    secret = "AEPOL1 微粒偏高 這串不該出現在報告裡"
    es = EvalSet(items=[EvalItem(secret, index.docs[0].concept_id, IDENTIFIER_KIND)])
    result = evaluate(es, searcher, k=5)

    report = build_report(index, TelemetryStore.create(config), config, evaluation=result)
    blob = json.dumps(report, ensure_ascii=False)
    assert secret not in blob
    assert report["evaluation"]["overall"]
