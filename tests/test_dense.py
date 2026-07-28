"""稠密腿、RRF 融合、與語料外流閘門。

這裡的測試**一律不觸網**。會觸網的測試同時變慢、變不穩、變貴，最後的下場是被跳過，
而被跳過的測試等於不存在。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yedai.config import Config
from yedai.embedding import CachedEmbedder, EmbeddingError, HttpEmbeddingClient
from yedai.search import LEXICAL_MODES, MODES, ModeUnavailable, Searcher, VectorSearcher, rrf
from yedai.vectors import CorpusLeakGuard, VectorStore, guard_corpus_leaves_process, is_synthetic_corpus


class FakeEmbedder:
    """把文字映到一個決定性的向量。相同文字 → 相同向量，不同文字 → 不同方向。"""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.model = "fake"
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for i, ch in enumerate(t):
                vec[(ord(ch) + i) % self.dim] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


# --- RRF ---------------------------------------------------------------


def test_rrf_uses_ranks_only() -> None:
    """C 排第 1、D 排第 10 → 1/(k+1) + 1/(k+10)，與兩腿的原始分數無關。"""
    k = 60
    fused = rrf([["a"] + [f"x{i}" for i in range(9)], [f"y{i}" for i in range(9)] + ["a"]], k=k)
    assert fused["a"] == pytest.approx(1 / (k + 1) + 1 / (k + 10))


def test_rrf_rewards_agreement_between_legs() -> None:
    """兩腿都排前面的，勝過只有一腿排第一的——這正是融合要的行為。"""
    fused = rrf([["both", "onlyA"], ["onlyB", "both"]], k=60)
    assert fused["both"] > fused["onlyA"]
    assert fused["both"] > fused["onlyB"]


def test_rrf_ignores_score_magnitude() -> None:
    """BM25 分數與餘弦相似度沒有共同尺度。RRF 不碰分數，所以不需要湊一個。"""
    a = rrf([["p", "q"]], k=60)
    b = rrf([["p", "q"]], k=60)
    assert a == b  # 沒有任何分數輸入，結果只由名次決定


# --- 外流閘門 ---------------------------------------------------------


def _synthetic(tmp_path: Path) -> Path:
    root = tmp_path / "syn"
    root.mkdir()
    (root / "README.txt").write_text("合成資料，僅供驗證程式正確性。\n", encoding="utf-8")
    return root


def test_real_corpus_with_untrusted_endpoint_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    with pytest.raises(CorpusLeakGuard) as exc:
        guard_corpus_leaves_process(real, "https://third-party.example/v1", trusted=False)
    # 訊息裡必須有那個 base_url——「送到哪裡」是使用者唯一需要判斷的事
    assert "third-party.example" in str(exc.value)


def test_synthetic_corpus_is_exempt(tmp_path: Path) -> None:
    """合成語料本來就是編造的。每次都要解閘的閘門會被找方法繞過，那等於沒有閘門。"""
    guard_corpus_leaves_process(_synthetic(tmp_path), "https://third-party.example/v1", trusted=False)


def test_explicit_trust_allows_real_corpus(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    guard_corpus_leaves_process(real, "http://litellm.internal/v1", trusted=True)


def test_marker_without_the_phrase_is_not_synthetic(tmp_path: Path) -> None:
    """光有 README.txt 不算數——否則任何語料放個同名檔就能繞過閘門。"""
    root = tmp_path / "x"
    root.mkdir()
    (root / "README.txt").write_text("just a readme\n", encoding="utf-8")
    assert not is_synthetic_corpus(root)


# --- Embedding 客戶端 -------------------------------------------------


def test_missing_key_names_the_variable(monkeypatch) -> None:
    monkeypatch.delenv("SOME_KEY_ENV", raising=False)
    client = HttpEmbeddingClient("https://x/v1", "m", 4, "SOME_KEY_ENV")
    with pytest.raises(EmbeddingError) as exc:
        client.embed(["hi"])
    assert "SOME_KEY_ENV" in str(exc.value)


def test_dimension_mismatch_fails_loudly(monkeypatch) -> None:
    """維度不符若被接受，相似度仍會算出看似正常的數字，而錯誤不會有任何徵兆。"""
    import httpx

    monkeypatch.setenv("K", "x")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **kw: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]}),
    )
    client = HttpEmbeddingClient("https://x/v1", "m", dim=4096, api_key_env="K")
    with pytest.raises(EmbeddingError) as exc:
        client.embed(["hi"])
    assert "4096" in str(exc.value) and "2" in str(exc.value)


def test_response_order_is_restored_from_index(monkeypatch) -> None:
    """規格沒保證回應順序等於輸入順序，而順序錯位不會報錯——
    它只會讓每個 concept 配到別人的向量，然後檢索變成隨機卻毫無徵兆。"""
    import httpx

    monkeypatch.setenv("K", "x")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **kw: httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [9.0]}, {"index": 0, "embedding": [1.0]}]},
        ),
    )
    client = HttpEmbeddingClient("https://x/v1", "m", dim=1, api_key_env="K")
    assert client.embed(["first", "second"]) == [[1.0], [9.0]]


# --- 查詢向量快取 -----------------------------------------------------


def test_cache_avoids_a_second_request(tmp_path: Path) -> None:
    inner = FakeEmbedder()
    cached = CachedEmbedder(inner, tmp_path / "c")
    cached.embed(["同一段查詢"])
    cached.embed(["同一段查詢"])
    assert len(inner.calls) == 1
    assert cached.hits == 1


def test_cache_is_keyed_by_model(tmp_path: Path) -> None:
    """換模型後沿用舊向量會產出無聲的錯誤結果。"""
    a = CachedEmbedder(FakeEmbedder(), tmp_path / "c")
    a.embed(["q"])
    other = FakeEmbedder()
    other.model = "another-model"
    b = CachedEmbedder(other, tmp_path / "c")
    b.embed(["q"])
    assert b.misses == 1  # 沒有沿用 a 寫下的那份


# --- 模式 D / E -------------------------------------------------------


@pytest.fixture
def dense_searcher(corpus: Path, config: Config):
    from yedai.entities import EntityDictionary
    from yedai.index import build_index

    dictionary = EntityDictionary.load(config.dictionary_path)
    index = build_index(corpus, config, dictionary)
    embedder = FakeEmbedder()
    store = VectorStore(dim=embedder.dim, path=None)  # :memory:
    store.ensure_collection()
    texts = [f"{m.title} {m.description}" for m in index.docs]
    store.upsert(list(zip([m.concept_id for m in index.docs], embedder.embed(texts), strict=True)))
    return Searcher(index, config, dictionary, vectors=VectorSearcher(store, embedder))


def test_dense_modes_become_available_with_vectors(dense_searcher) -> None:
    assert dense_searcher.available_modes == MODES
    for mode in ("D", "E"):
        assert dense_searcher.search("PARTICLE", mode=mode, k=3).mode == mode


def test_overlaps_cover_every_available_pair(dense_searcher) -> None:
    """固定寫死三組會在加入 D/E 後靜靜漏掉它們，而漏掉的正是新機制值不值得的依據。"""
    outcome = dense_searcher.compare("XTR-05 PARTICLE", k=5)
    pairs = {o.pair for o in outcome.overlaps}
    assert pairs == {
        "A-B", "A-C", "A-D", "A-E",
        "B-C", "B-D", "B-E",
        "C-D", "C-E",
        "D-E",
    }


def test_rrf_mode_reports_both_leg_ranks(dense_searcher) -> None:
    """一個文件為什麼排在這裡，看得到才追得下去。"""
    hits = dense_searcher.search("PARTICLE", mode="E", k=5).hits
    assert hits
    assert any(h.lexical_rank is not None for h in hits)
    assert any(h.dense_rank is not None for h in hits)


def test_lexical_modes_are_unaffected_by_the_dense_leg(dense_searcher, searcher) -> None:
    """加了 D/E 不該動到 A/B/C——否則先前所有的 A/B/C 結論都要重驗。"""
    for mode in LEXICAL_MODES:
        with_dense = dense_searcher.search("XTR-05 PARTICLE", mode=mode, k=5).ids
        without = searcher.search("XTR-05 PARTICLE", mode=mode, k=5).ids
        assert with_dense == without, mode


def test_vector_store_rebuilds_collection_on_dim_change() -> None:
    """維度不符的集合若沿用，留下的是一份部分舊模型、部分新模型的向量庫——
    那種混合不會報錯，只會讓相似度在不同文件之間不可比。"""
    store = VectorStore(dim=4, path=None)
    store.ensure_collection()
    store.upsert([("a", [1.0, 0, 0, 0])])
    assert store.count() == 1

    store.dim = 8
    store.ensure_collection()
    assert store.count() == 0  # 重建，而不是塞進維度不符的向量


def test_stale_vector_without_a_concept_is_skipped(dense_searcher) -> None:
    """重建索引與重建向量是兩個動作，兩者之間必然有一段不同步的時間。"""
    dense_searcher.vectors.store.upsert([("cpt_does_not_exist", [0.5] * 8)])
    hits = dense_searcher.search("PARTICLE", mode="D", k=10).hits
    assert all(h.concept_id != "cpt_does_not_exist" for h in hits)


# --- 設定 -------------------------------------------------------------


def test_config_rejects_a_key_pasted_into_api_key_env() -> None:
    """設定檔會進版控，把金鑰寫在這裡等同外洩。"""
    with pytest.raises(ValueError) as exc:
        Config().merged({"embedding": {"api_key_env": "sk-or-v1-deadbeef"}})
    assert "環境變數名稱" in str(exc.value)


def test_switching_to_litellm_is_config_only() -> None:
    """開發期 OpenRouter、production LiteLLM→vLLM，兩者只差設定。"""
    cfg = Config().merged(
        {"embedding": {"base_url": "http://litellm.internal/v1", "model": "qwen3-embedding-8b"}}
    )
    assert cfg.embedding["base_url"] == "http://litellm.internal/v1"
    assert cfg.embedding["dim"] == 4096  # 其餘欄位不受影響
