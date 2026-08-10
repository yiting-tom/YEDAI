from __future__ import annotations

from .conftest import INDEX_NAME

import json

import pytest

from yedai.telemetry import TelemetryStore, build_report


def test_query_is_logged_with_id(searcher, config) -> None:
    store = TelemetryStore.create(config)
    outcome = searcher.compare("XTR-05 PARTICLE", k=5)
    qid = store.log_query(outcome, requested_mode="compare")

    records = store.read_queries()
    assert len(records) == 1
    assert records[0]["query_id"] == qid
    assert records[0]["query"] == "XTR-05 PARTICLE"  # 原文只存在本機日誌


def test_feedback_requires_known_query_id(searcher, config) -> None:
    store = TelemetryStore.create(config)
    with pytest.raises(KeyError):
        store.log_feedback("does-not-exist", "cpt_x", 1, "C")


def test_feedback_is_recorded(searcher, config) -> None:
    store = TelemetryStore.create(config)
    qid = store.log_query(searcher.compare("PARTICLE", k=3), requested_mode="compare")
    store.log_feedback(qid, "cpt_title-hit", 1, "C")

    feedback = store.read_feedback()
    assert feedback[0]["query_id"] == qid
    assert feedback[0]["rank"] == 1


def test_display_order_is_reproducible_with_seed(corpus, config) -> None:
    from yedai.entities import EntityDictionary
    from yedai.index import build_index
    from yedai.search import Searcher

    d = EntityDictionary.load(config.dictionary_path)
    index = build_index(corpus, config, d)
    first = Searcher(index, config, d).compare("PARTICLE", k=3).display_order
    second = Searcher(index, config, d).compare("PARTICLE", k=3).display_order
    assert first == second


# --- 去識別化報告：這是整份測試裡最重要的一條 --------------------------------


def test_report_leaks_no_corpus_content(searcher, config) -> None:
    """報告若洩漏任何內容，使用者就無法把它帶出公司，這次資料收集等於沒發生。"""
    store = TelemetryStore.create(config)
    query = "XTR-05 的 PARTICLE 問題"
    store.log_query(searcher.compare(query, k=5), requested_mode="compare")

    report = build_report(searcher.index, store, config)
    blob = json.dumps(report, ensure_ascii=False)

    forbidden = [
        query,
        "XTR-05",
        "XTR05",
        "PARTICLE",
        "五號機",
        "cpt_title-hit",
        "調查",  # concept 標題片段
        "b1",  # bundle 名稱
    ]
    for needle in forbidden:
        assert needle not in blob, f"報告洩漏了語料內容：{needle!r}"

    # concept 標題與描述也不得出現
    for doc in searcher.index.docs:
        assert doc.title not in blob
        if doc.description:
            assert doc.description not in blob

    # 依類型拆解的結構只能有類型名稱（schema），不能有正規名稱（語料內容）
    by_type = report["by_index"][INDEX_NAME]["entities"]["by_type"]
    assert by_type, "拆解結構不該是空的，否則這條斷言等於沒測"
    for etype in by_type:
        assert ":" not in etype, f"類型鍵疑似夾帶了正規名稱：{etype!r}"
    for key in searcher.index.entities.postings:
        canonical = key.split(":", 1)[1] if ":" in key else key
        assert canonical not in by_type

    # 索引名稱是唯一允許的識別，而它來自設定宣告——不得由語料內容衍生
    assert list(report["by_index"]) == [INDEX_NAME]


def test_report_index_keys_are_declared_names_not_corpus(searcher, config) -> None:
    """依索引拆解引入了新的鍵，那組鍵必須是 schema 而不是語料。

    taxonomy 覆蓋率同理：只以 defect 類別為鍵，defect 名稱與條目文字都不得出現。
    """
    from yedai.taxonomy import Taxonomy

    tx = Taxonomy.load(None, defects={"DEFECT_SECRET": "pattern"})
    report = build_report({INDEX_NAME: searcher.index}, TelemetryStore.create(config), config,
                          taxonomy=tx)
    blob = json.dumps(report, ensure_ascii=False)

    assert "DEFECT_SECRET" not in blob, "defect 名稱屬語料內容，不得進報告"
    assert report["taxonomy"]["total"] == 1
    assert report["taxonomy"]["covered"] == 0
    assert list(report["taxonomy"]["by_category"]) == ["pattern"]

    # bundle 名稱來自語料，索引名稱來自設定——只有後者可以出現
    for doc in searcher.index.docs:
        assert doc.bundle_id not in report["by_index"]


def test_report_contains_required_metrics(searcher, config) -> None:
    store = TelemetryStore.create(config)
    store.log_query(searcher.compare("XTR-05 PARTICLE", k=5), requested_mode="compare")

    report = build_report(searcher.index, store, config)

    layer = report["by_index"][INDEX_NAME]
    assert layer["corpus"]["concepts"] > 0
    assert layer["corpus"]["vocab_naive"] > 0
    assert layer["corpus"]["vocab_protected"] > 0
    assert layer["entities"]["distinct_entities"] > 0
    assert layer["entities"]["dictionary_coverage"] is not None
    # 彙總只含加得起來的量——詞彙量重疊程度未知，相加會系統性高估
    assert report["corpus"]["concepts"] == layer["corpus"]["concepts"]
    assert "vocab_naive" not in report["corpus"]
    # 全域數字無法解讀——字典對一般詞是「有或沒有」，對識別碼只是精確度差異
    by_type = layer["entities"]["by_type"]
    assert by_type
    for counts in by_type.values():
        assert counts["dict"] + counts["regex"] <= counts["total"]
    assert sum(c["total"] for c in by_type.values()) == layer["entities"]["distinct_entities"]
    assert "query_entity_by_type" in report["queries"]
    assert report["queries"]["total_queries"] == 1
    assert set(report["mode_overlap"]) == {"A-B", "A-C", "B-C"}
    for mode in ("A", "B", "C"):
        assert report["modes"][mode]["zero_result_rate"] is not None
    # 實驗參數必須被記錄，否則數字不可重現
    assert report["experiment_params"]["k1"] == config.k1
    assert report["experiment_params"]["fusion_entity"] == config.fusion_entity


def test_report_keeps_every_pair_the_search_produced(corpus, config) -> None:
    """配對清單寫死過三次（search / cli / 這裡），每次都是同一個病。

    報告是唯一設計為可外流的產出。含稠密腿的配對從 `mode_overlap` 消失時不會報錯，
    讀者看到的是「稠密腿沒有產生重疊資料」——那正好是這份量測要分辨的東西。
    """
    from tests.test_dense import FakeEmbedder
    from yedai.entities import EntityDictionary
    from yedai.index import build_index
    from yedai.search import Searcher, VectorSearcher
    from yedai.vectors import VectorStore

    dictionary = EntityDictionary.load(config.dictionary_path)
    index = build_index(corpus, config, dictionary, name=INDEX_NAME)
    embedder = FakeEmbedder()
    store_v = VectorStore(dim=embedder.dim, path=None)
    store_v.ensure_collection()
    texts = [f"{m.title} {m.description}" for m in index.docs]
    store_v.upsert(list(zip([m.concept_id for m in index.docs], embedder.embed(texts), strict=True)))
    searcher = Searcher(index, config, dictionary, vectors=VectorSearcher(store_v, embedder))

    store = TelemetryStore.create(config)
    outcome = searcher.compare("XTR-05 PARTICLE", k=5)
    store.log_query(outcome, requested_mode="compare")

    report = build_report(index, store, config)
    logged = {o.pair for o in outcome.overlaps}
    assert "C-D" in logged and "C-E" in logged, "前提不成立：這次 compare 沒有跑到稠密腿"
    assert set(report["mode_overlap"]) == logged


def test_report_works_with_no_queries(searcher, config) -> None:
    store = TelemetryStore.create(config)
    report = build_report(searcher.index, store, config)

    assert report["queries"]["total_queries"] == 0
    assert report["corpus"]["concepts"] > 0
    assert report["by_index"][INDEX_NAME]["corpus"]["concepts"] > 0
    assert report["feedback"]["total"] == 0


def test_report_records_click_rank_distribution(searcher, config) -> None:
    store = TelemetryStore.create(config)
    qid = store.log_query(searcher.compare("PARTICLE", k=5), requested_mode="compare")
    store.log_feedback(qid, "cpt_title-hit", 2, "C")
    store.log_feedback(qid, "cpt_body-hit", 4, "B")

    report = build_report(searcher.index, store, config)
    assert report["feedback"]["total"] == 2
    assert report["feedback"]["clicked_rank_distribution"]["n"] == 2
    assert report["feedback"]["clicks_per_mode"] == {"C": 1, "B": 1}
