from __future__ import annotations

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
    by_type = report["entities"]["by_type"]
    assert by_type, "拆解結構不該是空的，否則這條斷言等於沒測"
    for etype in by_type:
        assert ":" not in etype, f"類型鍵疑似夾帶了正規名稱：{etype!r}"
    for key in searcher.index.entities.postings:
        canonical = key.split(":", 1)[1] if ":" in key else key
        assert canonical not in by_type


def test_report_contains_required_metrics(searcher, config) -> None:
    store = TelemetryStore.create(config)
    store.log_query(searcher.compare("XTR-05 PARTICLE", k=5), requested_mode="compare")

    report = build_report(searcher.index, store, config)

    assert report["corpus"]["concepts"] > 0
    assert report["corpus"]["vocab_naive"] > 0
    assert report["corpus"]["vocab_protected"] > 0
    assert report["entities"]["distinct_entities"] > 0
    assert report["entities"]["dictionary_coverage"] is not None
    # 全域數字無法解讀——字典對一般詞是「有或沒有」，對識別碼只是精確度差異
    by_type = report["entities"]["by_type"]
    assert by_type
    for counts in by_type.values():
        assert counts["dict"] + counts["regex"] <= counts["total"]
    assert sum(c["total"] for c in by_type.values()) == report["entities"]["distinct_entities"]
    assert "query_entity_by_type" in report["queries"]
    assert report["queries"]["total_queries"] == 1
    assert set(report["mode_overlap"]) == {"A-B", "A-C", "B-C"}
    for mode in ("A", "B", "C"):
        assert report["modes"][mode]["zero_result_rate"] is not None
    # 實驗參數必須被記錄，否則數字不可重現
    assert report["experiment_params"]["k1"] == config.k1
    assert report["experiment_params"]["fusion_entity"] == config.fusion_entity


def test_report_works_with_no_queries(searcher, config) -> None:
    store = TelemetryStore.create(config)
    report = build_report(searcher.index, store, config)

    assert report["queries"]["total_queries"] == 0
    assert report["corpus"]["concepts"] > 0
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
