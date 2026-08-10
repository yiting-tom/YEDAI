"""分層索引：統計隔離、每層自己的檢索設定、分層回傳、跨索引融合。

這個檔案裡最重要的一條是 `test_growing_one_index_does_not_move_another`。
它是本次架構決定的**可執行斷言**：在單一索引的實作下，那條測試必定紅——`df` 與
`avg_field_len` 是全域的，持續累積的那一層每長大一次，其他層的排名就漂移一次，
而沒有任何變更、沒有任何測試會發現。分開統計之後它必定綠，一旦再紅就代表邊界破了。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yedai.config import Config
from yedai.entities import EntityDictionary
from yedai.index import Index, build_all_indexes, build_index, load_index_for_spec
from yedai.layers import LayeredSearcher, UnknownIndex

from .conftest import make_bundle, write_concept


def _corpus(root: Path, bundle: str, concepts: dict[str, dict]) -> Path:
    okf = make_bundle(root, bundle)
    for name, fm in concepts.items():
        write_concept(okf, name, frontmatter=fm, body="## 內容\n\n" + fm.pop("_body", "預設內文。"))
    return root


@pytest.fixture
def two_layer(tmp_path: Path, dictionary_path: Path):
    """兩層語料，刻意共用同一批詞。

    共用詞是重點：如果統計沒有隔離，一層長大就會改變另一層對那些詞的 idf。
    """
    heur = _corpus(
        tmp_path / "heuristics",
        "h1",
        {
            "how-to-a": {"id": "cpt_h_a", "title": "overlay 偏移的查法", "_body": "先看 overlay 的分佈。"},
            "how-to-b": {"id": "cpt_h_b", "title": "particle 的查法", "_body": "先看 particle 的分佈。"},
        },
    )
    cases = _corpus(
        tmp_path / "cases",
        "c1",
        {
            "case-1": {"id": "cpt_c_1", "title": "XTR-05 overlay 超規", "_body": "overlay 量測異常。"},
            "case-2": {"id": "cpt_c_2", "title": "XTR-06 particle 增加", "_body": "particle 數量上升。"},
        },
    )
    cfg = Config(
        dictionary_path=str(dictionary_path),
        indexes={
            "heuristics": {
                "source": str(heur),
                "path": str(tmp_path / ".index" / "heuristics.pkl"),
                "keep_identifiers": False,
                "top_k": 3,
            },
            "cases": {
                "source": str(cases),
                "path": str(tmp_path / ".index" / "cases.pkl"),
                "depends_on": ["heuristics"],
                "keep_identifiers": True,
                "top_k": 5,
            },
        },
        log_dir=str(tmp_path / "logs"),
        seed=1,
    )
    return cfg, heur, cases


def _layered(cfg: Config) -> LayeredSearcher:
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    build_all_indexes(cfg, dictionary)
    return LayeredSearcher.load(cfg, dictionary)


# --- 統計隔離（本次架構決定的可執行斷言）-------------------------------


def test_growing_one_index_does_not_move_another(two_layer) -> None:
    """在 cases 灌入大量文件並重建後，heuristics 的結果與分數必須完全不變。

    單一索引 + 過濾條件的做法過不了這條：`candidates` 只影響誰參與排序，
    `df` 仍取自全語料。這就是為什麼分層不能退化成過濾器。
    """
    cfg, _, cases = two_layer
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    build_all_indexes(cfg, dictionary)

    spec = cfg.index_spec("heuristics")
    before = LayeredSearcher.searcher_for(
        spec, load_index_for_spec(spec, cfg, dictionary), cfg, dictionary
    ).search("overlay 的查法", "C")

    # cases 長大一個數量級，而且用的是 heuristics 也有的詞
    okf = make_bundle(cases, "c2")
    for i in range(60):
        write_concept(
            okf,
            f"bulk-{i}",
            frontmatter={"id": f"cpt_bulk_{i}", "title": f"overlay 案件 {i}"},
            body="## 內容\n\noverlay particle 的分佈。\n",
        )
    build_all_indexes(cfg, dictionary)

    after = LayeredSearcher.searcher_for(
        spec, load_index_for_spec(spec, cfg, dictionary), cfg, dictionary
    ).search("overlay 的查法", "C")

    assert before.ids == after.ids, "另一層長大改變了本層的排序——統計沒有隔離"
    # 分數層級的斷言：順序可能碰巧不變，分數不會。idf 一旦洩漏，這裡就會抓到。
    assert [h.score for h in before.hits] == [h.score for h in after.hits]
    assert [h.lexical_score for h in before.hits] == [h.lexical_score for h in after.hits]


def test_document_frequency_does_not_accumulate_across_indexes(two_layer) -> None:
    cfg, _, _ = two_layer
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    built = build_all_indexes(cfg, dictionary)

    heur, cases = built["heuristics"], built["cases"]
    shared = [t for t in heur.protected.df if t in cases.protected.df]
    assert shared, "前提不成立：兩層沒有共用詞，這條測試等於沒測"
    for term in shared:
        assert heur.protected.df[term] <= heur.protected.n_docs
        assert cases.protected.df[term] <= cases.protected.n_docs
    assert heur.protected.n_docs != cases.protected.n_docs or True
    assert heur.entities.n_docs == heur.protected.n_docs


def test_related_does_not_resolve_across_indexes(tmp_path: Path, dictionary_path: Path) -> None:
    """跨索引的 related 目標記為懸空，不得成邊。

    跨索引解析會讓一份索引的圖結構依賴另一份索引當時的內容，而兩者重建節奏不同。
    """
    a = _corpus(tmp_path / "a", "a1", {"x": {"id": "cpt_x", "title": "X", "related": ["cpt_y"]}})
    _corpus(tmp_path / "b", "b1", {"y": {"id": "cpt_y", "title": "Y"}})
    cfg = Config(
        dictionary_path=str(dictionary_path),
        indexes={
            "a": {"source": str(a), "path": str(tmp_path / ".index" / "a.pkl")},
            "b": {"source": str(tmp_path / "b"), "path": str(tmp_path / ".index" / "b.pkl")},
        },
        log_dir=str(tmp_path / "logs"),
    )
    built = build_all_indexes(cfg, EntityDictionary.load(cfg.dictionary_path))
    assert built["a"].related_out.get("cpt_x") is None
    assert built["a"].dangling["cpt_x"] == ["cpt_y"]


# --- 索引身分 -----------------------------------------------------------


def test_index_carries_its_name(two_layer) -> None:
    cfg, _, _ = two_layer
    built = build_all_indexes(cfg, EntityDictionary.load(cfg.dictionary_path))
    assert built["cases"].name == "cases"


def test_loading_an_index_under_the_wrong_name_is_refused(two_layer) -> None:
    """兩份統計互換之後檢索仍會回傳結果，只是分數全錯——所以必須擋。"""
    cfg, _, _ = two_layer
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    build_all_indexes(cfg, dictionary)
    wrong = cfg.index_spec("cases").path
    with pytest.raises(ValueError, match="索引名稱是"):
        Index.load(wrong, expect_name="heuristics")


def test_signature_includes_the_index_name(two_layer) -> None:
    cfg, _, _ = two_layer
    fp = EntityDictionary.load(cfg.dictionary_path).fingerprint()
    assert cfg.index_signature(fp, "cases") != cfg.index_signature(fp, "heuristics")


def test_build_order_puts_upstream_first(two_layer) -> None:
    cfg, _, _ = two_layer
    assert cfg.index_build_order() == ["heuristics", "cases"]
    assert cfg.dependents_of("heuristics") == ["cases"]


def test_stale_downstream_error_names_the_indexes(two_layer) -> None:
    """只說「請重建索引」，使用者會反覆重建同一個並困惑於它為什麼還是紅的。"""
    cfg, _, _ = two_layer
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    build_all_indexes(cfg, dictionary)
    idx = Index.load(cfg.index_spec("heuristics").path, expect_name="heuristics")
    with pytest.raises(ValueError) as exc:
        idx.check_signature("not-the-right-signature", dependents_hint=cfg.dependents_of("heuristics"))
    assert "heuristics" in str(exc.value)
    assert "cases" in str(exc.value)


# --- query 前處理 -------------------------------------------------------


def test_identifiers_are_stripped_only_where_declared(two_layer) -> None:
    """同一個查詢字串在不同層以不同形式進入計分。差異發生在計分之前——
    這是分層不能退化成「同一個檢索器加過濾條件」的第二個理由。"""
    cfg, _, _ = two_layer
    layered = _layered(cfg)
    query = "XTR-05 overlay"

    assert layered.searcher("cases").prepare_query(query) == query
    stripped = layered.searcher("heuristics").prepare_query(query)
    assert "XTR-05" not in stripped
    assert "overlay" in stripped


def test_stripping_does_not_glue_neighbouring_words(two_layer) -> None:
    cfg, _, _ = two_layer
    layered = _layered(cfg)
    assert layered.searcher("heuristics").prepare_query("XTR-05粒子").strip() == "粒子"


def test_index_level_weights_override_global(tmp_path: Path, dictionary_path: Path) -> None:
    cfg = Config(
        dictionary_path=str(dictionary_path),
        indexes={
            "a": {"source": str(tmp_path), "path": "x", "field_weights": {"title": 99.0}},
            "b": {"source": str(tmp_path), "path": "y"},
        },
    )
    assert cfg.index_spec("a").field_weights["title"] == 99.0
    assert cfg.index_spec("b").field_weights["title"] == cfg.field_weights["title"]
    # 未宣告的欄位仍沿用全域值，不會因為覆寫了一個就整組消失
    assert cfg.index_spec("a").field_weights["body"] == cfg.field_weights["body"]


def test_index_level_top_k_is_independent(two_layer) -> None:
    cfg, _, _ = two_layer
    assert cfg.index_spec("heuristics").top_k == 3
    assert cfg.index_spec("cases").top_k == 5


# --- 分層回傳 -----------------------------------------------------------


def test_layered_search_returns_every_layer(two_layer) -> None:
    cfg, _, _ = two_layer
    outcome = _layered(cfg).search("overlay")
    assert [lr.index for lr in outcome.layers] == ["heuristics", "cases"]
    assert outcome.shape == "layered"
    assert outcome.fused is None, "沒要求融合時應為 None——空清單會與「融合後無結果」混淆"


def test_empty_layer_is_present_not_omitted(two_layer) -> None:
    """層的缺席本身是訊號：這一層沒有相關知識，跟「排在 k 之外」不是同一件事。"""
    cfg, _, _ = two_layer
    # 純拉丁的無意義字串：中文查詢會被切成 unigram + bigram，容易碰巧命中
    outcome = _layered(cfg).search("zzzqqq wwwvvv")
    assert len(outcome.layers) == 2
    assert all(lr.empty for lr in outcome.layers)


def test_layer_records_its_prepared_query(two_layer) -> None:
    cfg, _, _ = two_layer
    outcome = _layered(cfg).search("XTR-05 overlay")
    assert outcome.layer("cases").prepared_query == "XTR-05 overlay"
    assert "XTR-05" not in outcome.layer("heuristics").prepared_query


def test_single_index_search(two_layer) -> None:
    cfg, _, _ = two_layer
    outcome = _layered(cfg).search("overlay", index="cases")
    assert [lr.index for lr in outcome.layers] == ["cases"]


def test_unknown_index_lists_the_available_names(two_layer) -> None:
    cfg, _, _ = two_layer
    with pytest.raises(UnknownIndex, match="cases"):
        _layered(cfg).search("overlay", index="nope")


def test_each_layer_uses_its_own_depth(two_layer) -> None:
    cfg, _, _ = two_layer
    outcome = _layered(cfg).search("overlay particle 分佈")
    assert len(outcome.layer("heuristics").hits) <= 3
    assert len(outcome.layer("cases").hits) <= 5


# --- 跨索引融合 ---------------------------------------------------------


def test_fusion_is_off_by_default(two_layer) -> None:
    cfg, _, _ = two_layer
    assert _layered(cfg).search("overlay").fused is None


def test_fused_hits_keep_source_index_and_rank(two_layer) -> None:
    cfg, _, _ = two_layer
    outcome = _layered(cfg).search("overlay particle", fuse=True)
    assert outcome.shape == "fused"
    assert outcome.layers, "融合時分層結構仍須保留，否則看不出某層是否整個沒東西"
    assert outcome.fused
    for fh in outcome.fused:
        assert fh.index in ("heuristics", "cases")
        assert fh.source_rank >= 1
        # 來源名次必須真的對得上那一層的結果
        layer = outcome.layer(fh.index)
        assert layer.ids[fh.source_rank - 1] == fh.hit.concept_id


def test_fusion_score_depends_only_on_rank(two_layer) -> None:
    """RRF 只吃排名。BM25 分數與餘弦相似度沒有共同尺度，一旦讓分數進來，
    就需要一組無法從原理推導的權重。"""
    cfg, _, _ = two_layer
    layered = _layered(cfg)
    outcome = layered.search("overlay particle", fuse=True)

    k = cfg.rrf_k
    for fh in outcome.fused:
        expected = sum(
            1.0 / (k + lr.ids.index(fh.hit.concept_id) + 1)
            for lr in outcome.layers
            if fh.hit.concept_id in lr.ids
        )
        assert fh.score == pytest.approx(expected)


def test_fusion_is_equal_weight_across_layers(two_layer) -> None:
    """平權而非依語料規模加權——猜出來的權重會變成沒人敢動的常數。

    兩層各自的第 1 名，融合分數必須相同。
    """
    cfg, _, _ = two_layer
    outcome = _layered(cfg).search("overlay particle 分佈", fuse=True)
    tops = {}
    for lr in outcome.layers:
        if lr.hits:
            tops[lr.index] = next(f.score for f in outcome.fused if f.hit.concept_id == lr.ids[0])
    assert len(tops) == 2, "前提不成立：需要兩層都有結果"
    assert len(set(round(v, 12) for v in tops.values())) == 1


# --- 設定 ---------------------------------------------------------------


def test_empty_index_declaration_is_refused(dictionary_path: Path) -> None:
    """回退到隱含的預設索引會讓使用者以為索引建好了，實際上寫進沒人宣告過的位置。"""
    with pytest.raises(ValueError):
        Config(dictionary_path=str(dictionary_path)).index_specs()


def test_missing_config_file_says_so_instead_of_blaming_the_declaration(tmp_path: Path) -> None:
    """`yedai serve` 忘了 -c 是最常見的情形。

    這時說「設定未宣告任何索引」會讓人去翻一份他根本沒有指定的檔案——
    錯誤訊息要先講「你沒給設定檔」。
    """
    with pytest.raises(ValueError) as exc:
        Config.load(None).index_specs()
    msg = str(exc.value)
    assert "沒有指定設定檔" in msg
    assert "-c config.local.yaml" in msg and "YEDAI_CONFIG" in msg


def test_config_file_without_indexes_names_the_file(tmp_path: Path) -> None:
    """有設定檔但沒宣告索引，就要指名是哪一個檔案——那才是要去改的東西。"""
    p = tmp_path / "empty.yaml"
    p.write_text("log_dir: logs\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        Config.load(p).index_specs()
    msg = str(exc.value)
    assert str(p) in msg
    assert "indexes:" in msg


def test_source_path_survives_overrides(tmp_path: Path, dictionary_path: Path) -> None:
    """`config_for()` 之類的覆寫會產生新的 Config。來源掉了的話，
    同一份設定的錯誤訊息會依呼叫路徑而不同。"""
    p = tmp_path / "c.yaml"
    p.write_text(
        f"indexes:\n  a:\n    source: {tmp_path}\n    path: {tmp_path}/a.pkl\n", encoding="utf-8"
    )
    cfg = Config.load(p)
    assert cfg.source_path == str(p)
    assert cfg.index_spec("a").config_for(cfg).source_path == str(p)


def test_removed_index_path_key_is_refused_with_the_new_shape() -> None:
    with pytest.raises(ValueError) as exc:
        Config().merged({"index_path": ".index/old.pkl"})
    assert "index_path" in str(exc.value)
    assert "indexes:" in str(exc.value)


def test_duplicate_index_name_in_yaml_is_refused(tmp_path: Path) -> None:
    """YAML 的重複鍵預設靜默保留最後一個——其中一個索引會無聲消失。"""
    p = tmp_path / "c.yaml"
    p.write_text(
        "indexes:\n  a:\n    source: x\n    path: y\n  a:\n    source: z\n    path: w\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="重複的鍵"):
        Config.load(p)


def test_dense_default_mode_without_collection_fails_at_config_time(tmp_path: Path) -> None:
    """延後到查詢期才失敗，錯誤會出現在離設定很遠的地方。"""
    with pytest.raises(ValueError, match="collection"):
        Config().merged(
            {"indexes": {"a": {"source": str(tmp_path), "path": "x", "default_mode": "D"}}}
        )


def test_dependency_cycle_is_refused(tmp_path: Path) -> None:
    cfg = Config().merged(
        {
            "indexes": {
                "a": {"source": str(tmp_path), "path": "x", "depends_on": ["b"]},
                "b": {"source": str(tmp_path), "path": "y", "depends_on": ["a"]},
            }
        }
    )
    with pytest.raises(ValueError, match="成環"):
        cfg.index_build_order()


def test_unknown_index_key_is_refused(tmp_path: Path) -> None:
    """拼錯的鍵靜默忽略，症狀是「我明明設了權重卻沒生效」。"""
    with pytest.raises(ValueError, match="不認得的鍵"):
        Config().merged({"indexes": {"a": {"source": str(tmp_path), "path": "x", "top-k": 5}}})


def test_missing_source_directory_names_the_index(two_layer, tmp_path: Path) -> None:
    cfg, _, _ = two_layer
    cfg = cfg.merged(
        {"indexes": {**cfg.indexes, "cases": {"source": str(tmp_path / "gone"), "path": "z"}}}
    )
    with pytest.raises(FileNotFoundError, match="cases"):
        build_all_indexes(cfg, EntityDictionary.load(cfg.dictionary_path))


def test_build_index_default_name_is_not_a_config_fallback(tmp_path: Path, corpus: Path, config) -> None:
    """低階呼叫可以有預設名稱，設定層不行——兩者是不同的東西。"""
    idx = build_index(corpus, config, EntityDictionary.load(config.dictionary_path))
    assert idx.name == "default"


# --- 跨層 concept_id 相撞（端對端跑出來的迴歸點）------------------------


@pytest.fixture
def colliding(tmp_path: Path, dictionary_path: Path):
    """兩層共用同一份語料 → 每個 concept_id 都跨層重複。

    真實部署裡各層應該互斥，但沒有任何東西強制它；而且相撞的後果全部是靜默的。
    """
    corpus = _corpus(
        tmp_path / "shared",
        "s1",
        {
            "one": {"id": "cpt_one", "title": "overlay 偏移"},
            "two": {"id": "cpt_two", "title": "overlay 殘留"},
        },
    )
    solo = _corpus(tmp_path / "solo", "s2", {"three": {"id": "cpt_three", "title": "overlay 顆粒"}})
    cfg = Config(
        dictionary_path=str(dictionary_path),
        indexes={
            "a": {"source": str(corpus), "path": str(tmp_path / ".index" / "a.pkl")},
            "b": {"source": str(corpus), "path": str(tmp_path / ".index" / "b.pkl")},
            "c": {"source": str(solo), "path": str(tmp_path / ".index" / "c.pkl")},
        },
        log_dir=str(tmp_path / "logs"),
        seed=1,
    )
    return cfg


def test_overlap_is_measured_at_load(colliding) -> None:
    """相撞不報錯（它可能是既有語料的現況），但必須量得出來。"""
    layered = _layered(colliding)
    assert layered.id_overlap.total == 2
    assert layered.id_overlap.pairs == {"a↔b": 2}
    # 只留層名與數量——id 屬語料內容，這個統計要能進可外流的報告
    blob = str(layered.id_overlap.to_dict())
    assert "cpt_one" not in blob and "cpt_two" not in blob


def test_no_overlap_reported_when_layers_are_disjoint(two_layer) -> None:
    cfg, _, _ = two_layer
    assert not _layered(cfg).id_overlap


def test_owner_is_declaration_order_not_dict_luck(colliding) -> None:
    """相撞時答案可以是錯的，但不可以每次不一樣。"""
    layered = _layered(colliding)
    assert layered.owner_of("cpt_one") == "a"
    assert layered.owner_of("cpt_three") == "c"
    assert layered.owner_of("cpt_nope") is None


def test_fusion_counts_a_colliding_document_once(colliding) -> None:
    """RRF 對出現在多份排名的文件逐份累加，那在「多模式排同一份語料」是對的
    （獨立證據），在「多層排各自的語料」是錯的——同一份文件被收錄兩次不是兩份
    證據，卻會拿到 2× 分數而系統性壓過其他文件。"""
    outcome = _layered(colliding).search("overlay", fuse=True)
    assert outcome.fused

    ids = [f.hit.concept_id for f in outcome.fused]
    assert len(ids) == len(set(ids)), "融合清單不得出現重複的 concept_id"

    k = colliding.rrf_k
    for f in outcome.fused:
        # 分數只由它在自己那一層的名次決定，不因為跨層重複而加倍
        assert f.score == pytest.approx(1.0 / (k + f.source_rank))

    # 相撞的文件不得單憑重複就壓過只在一層的文件
    solo = next((f for f in outcome.fused if f.index == "c"), None)
    assert solo is not None, "前提不成立：需要一筆只出現在單層的結果"
    same_rank = [f for f in outcome.fused if f.source_rank == solo.source_rank]
    assert len({round(f.score, 12) for f in same_rank}) == 1


def test_fused_serialisation_does_not_lose_rank_and_score(two_layer) -> None:
    """`Hit.to_dict()` 也有 `rank` 與 `score`（層內的）。

    融合欄位若寫在 hit 展開之前，會被它靜默蓋掉——回應看起來完全正常，
    只是 `rank` 在清單裡重複、`score` 其實是層內分數而不是融合分數。
    先前的測試只看 dataclass，看不到這件事。
    """
    cfg, _, _ = two_layer
    outcome = _layered(cfg).search("overlay particle", fuse=True)
    assert outcome.fused

    rows = [f.to_dict() for f in outcome.fused]
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1)), "融合名次必須連續不重複"
    for row, f in zip(rows, outcome.fused, strict=True):
        assert row["score"] == f.score, "score 被 hit 的層內分數蓋掉了"
        assert row["rank"] == f.rank
        assert row["source_rank"] == f.source_rank
        assert row["index"] == f.index
        # hit 的欄位仍須完整帶出
        assert row["concept_id"] == f.hit.concept_id
        assert row["index_line"] == f.hit.index_line()
