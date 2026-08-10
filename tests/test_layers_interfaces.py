"""分層在介面層的行為：CLI 輸出、向量庫分離、遙測依層記錄。

與 `test_layers.py` 分開：那邊測的是分層本身的性質，這邊測的是「使用者與遙測
看到的東西對不對」。前者壞了是設計破了，後者壞了是設計對但沒被呈現出來。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from yedai.cli import app
from yedai.config import Config
from yedai.entities import EntityDictionary
from yedai.index import build_all_indexes
from yedai.layers import LayeredSearcher
from yedai.telemetry import TelemetryStore, build_report
from yedai.vectors import VectorBackend

from .conftest import make_bundle, write_concept


@pytest.fixture
def two_layer_cfg(tmp_path: Path, dictionary_path: Path):
    """兩層語料，其中一層對某個查詢必定無命中——空層的呈現是要測的重點。"""
    for layer, entries in {
        "heuristics": {"how": {"id": "cpt_h", "title": "overlay 的查法"}},
        "cases": {"case": {"id": "cpt_c", "title": "XTR-05 overlay 超規"}},
    }.items():
        okf = make_bundle(tmp_path / layer, "b1")
        for name, fm in entries.items():
            write_concept(okf, name, frontmatter=fm)

    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "dictionary_path": str(dictionary_path),
                "log_dir": str(tmp_path / "logs"),
                "seed": 1,
                "indexes": {
                    "heuristics": {
                        "source": str(tmp_path / "heuristics"),
                        "path": str(tmp_path / ".index" / "heuristics.pkl"),
                        "keep_identifiers": False,
                    },
                    "cases": {
                        "source": str(tmp_path / "cases"),
                        "path": str(tmp_path / ".index" / "cases.pkl"),
                        "depends_on": ["heuristics"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return cfg_path, Config.load(cfg_path)


def _run(*args) -> object:
    return CliRunner().invoke(app, list(args))


# --- CLI ----------------------------------------------------------------


def test_index_builds_every_layer_in_dependency_order(two_layer_cfg) -> None:
    cfg_path, cfg = two_layer_cfg
    result = _run("index", "-c", str(cfg_path))
    assert result.exit_code == 0, result.output
    assert "heuristics" in result.output and "cases" in result.output
    # 上游先於下游：反過來建會讓下游用到舊字典，而那不會報錯
    assert result.output.index("索引 heuristics 已寫入") < result.output.index("索引 cases 已寫入")
    for name in ("heuristics", "cases"):
        assert Path(cfg.index_spec(name).path).exists()


def test_index_single_layer_leaves_the_others_alone(two_layer_cfg) -> None:
    cfg_path, cfg = two_layer_cfg
    _run("index", "-c", str(cfg_path))
    other = Path(cfg.index_spec("cases").path)
    stamp = other.stat().st_mtime_ns

    assert _run("index", "-i", "heuristics", "-c", str(cfg_path)).exit_code == 0
    assert other.stat().st_mtime_ns == stamp, "重建一層不該動到其他層的索引檔"


def test_index_unknown_name_lists_the_available_ones(two_layer_cfg) -> None:
    cfg_path, _ = two_layer_cfg
    result = _run("index", "-i", "nope", "-c", str(cfg_path))
    assert result.exit_code == 2
    assert "heuristics" in result.output and "cases" in result.output


def test_search_prints_every_layer_including_empty_ones(two_layer_cfg) -> None:
    """空層在終端也要看得見——層的缺席本身是訊號。"""
    cfg_path, _ = two_layer_cfg
    _run("index", "-c", str(cfg_path))
    result = _run("search", "zzzqqq", "-c", str(cfg_path), "--no-log")
    assert result.exit_code == 0, result.output
    assert "索引 heuristics" in result.output
    assert "索引 cases" in result.output
    assert "這一層沒有命中" in result.output


def test_search_marks_a_layer_whose_query_was_preprocessed(two_layer_cfg) -> None:
    cfg_path, _ = two_layer_cfg
    _run("index", "-c", str(cfg_path))
    result = _run("search", "XTR-05 overlay", "-c", str(cfg_path), "--no-log")
    assert "查詢經前處理" in result.output, "剝除識別碼的層必須讓使用者看到它實際查的是什麼"


def test_compare_requires_an_index_when_there_are_several(two_layer_cfg) -> None:
    """跨索引比模式是在比兩件不同的事——重疊度會變成「兩層語料有多像」。"""
    cfg_path, _ = two_layer_cfg
    _run("index", "-c", str(cfg_path))
    result = _run("compare", "overlay", "-c", str(cfg_path))
    assert result.exit_code == 2
    assert "-i" in result.output

    ok = _run("compare", "overlay", "-i", "cases", "-c", str(cfg_path))
    assert ok.exit_code == 0, ok.output
    assert "索引：cases" in ok.output


# --- 向量庫依索引分離 ---------------------------------------------------


def test_each_index_uses_its_own_collection(tmp_path: Path) -> None:
    """兩層寫進不同 collection，互不影響——不同層的稠密腿價值不同，
    分開才能分開決定要不要付這筆 embedding 成本。

    **兩個 collection 必須在同一個儲存位置上**。先前這條測試一個用記憶體、
    一個用另一個資料夾，於是它測的是兩個不相干的東西，剛好避開唯一會壞的組合。
    """
    backend = VectorBackend(path=str(tmp_path / "q"))
    try:
        a = backend.store(dim=4, collection="layer-a")
        b = backend.store(dim=4, collection="layer-b")
        a.ensure_collection()
        b.ensure_collection()
        a.upsert([("cpt_a", [1.0, 0.0, 0.0, 0.0])])
        assert a.count() == 1
        assert b.has_vectors() is False, "寫進 a 不該讓 b 出現向量"
    finally:
        backend.close()


def test_several_layers_share_one_client_on_the_same_storage(tmp_path: Path) -> None:
    """本機檔案模式的 qdrant 對儲存資料夾持有獨佔鎖。

    每層各開一個 client 的話，第二個有向量的層會讓整個載入炸掉，而症狀是
    「跑過 embed 的層一旦超過一個，服務就起不來」——錯誤訊息還指向 qdrant，
    不指向設定。這條釘住「一個 backend 服務全部 collection」。
    """
    backend = VectorBackend(path=str(tmp_path / "q"))
    try:
        for i in range(4):
            s = backend.store(dim=4, collection=f"layer-{i}")
            s.ensure_collection()
            s.upsert([(f"cpt_{i}", [float(i), 1.0, 0.0, 0.0])])
        assert all(backend.store(4, f"layer-{i}").count() == 1 for i in range(4))
    finally:
        backend.close()


def test_shared_store_close_does_not_kill_the_backend(tmp_path: Path) -> None:
    """關掉別人還在用的 client，症狀會是另一層的檢索突然開始丟例外。"""
    backend = VectorBackend(path=str(tmp_path / "q"))
    try:
        a = backend.store(dim=4, collection="a")
        a.ensure_collection()
        a.close()  # 共用的 client 不該被關掉
        b = backend.store(dim=4, collection="b")
        b.ensure_collection()
        assert b.count() == 0
    finally:
        backend.close()


def test_runtime_loads_with_several_embedded_layers(two_layer_cfg, tmp_path: Path) -> None:
    """端對端的形狀：兩層都跑過 embed 之後，服務仍須起得來。"""
    from yedai.runtime import Runtime

    cfg_path, cfg = two_layer_cfg
    build_all_indexes(cfg, EntityDictionary.load(cfg.dictionary_path))

    qdrant = tmp_path / "qdrant"
    decl = {
        name: {**raw, "collection": f"c-{name}"} for name, raw in cfg.indexes.items()
    }
    vec_cfg = cfg.merged({"indexes": decl, "vector": {**cfg.vector, "path": str(qdrant)}})

    backend = VectorBackend(path=str(qdrant))
    try:
        for name in vec_cfg.index_build_order():
            s = backend.store(int(vec_cfg.embedding["dim"]), f"c-{name}")
            s.ensure_collection()
            s.upsert([(f"cpt_seed_{name}", [0.1] * int(vec_cfg.embedding["dim"]))])
    finally:
        backend.close()

    path = tmp_path / "vec.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "dictionary_path": vec_cfg.dictionary_path,
                "log_dir": vec_cfg.log_dir,
                "indexes": decl,
                "vector": {**cfg.vector, "path": str(qdrant)},
            }
        ),
        encoding="utf-8",
    )
    rt = Runtime.load(path)
    try:
        assert sorted(rt.index_names) == ["cases", "heuristics"]
        for name in rt.index_names:
            assert rt.layered.searcher(name).available_modes == ("A", "B", "C", "D", "E")
    finally:
        rt.close()


def test_index_without_collection_has_no_dense_leg(two_layer_cfg) -> None:
    cfg_path, cfg = two_layer_cfg
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    build_all_indexes(cfg, dictionary)
    layered = LayeredSearcher.load(cfg, dictionary)
    # 兩層都沒宣告 collection → D/E 明確不可用，而不是回傳零筆看似正常的結果
    for name in layered.names:
        assert layered.searcher(name).available_modes == ("A", "B", "C")


# --- 遙測 ---------------------------------------------------------------


def test_log_records_each_layer_and_its_prepared_query(two_layer_cfg) -> None:
    cfg_path, cfg = two_layer_cfg
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    build_all_indexes(cfg, dictionary)
    layered = LayeredSearcher.load(cfg, dictionary)
    store = TelemetryStore.create(cfg)

    store.log_layered(layered.search("XTR-05 overlay"))
    rec = store.read_queries()[-1]

    assert rec["shape"] == "layered"
    assert sorted(rec["indexes"]) == ["cases", "heuristics"]
    by_index = {lr["index"]: lr for lr in rec["layers"]}
    # 沒有 prepared_query 就無法還原「這一層到底拿到了什麼」
    assert by_index["cases"]["prepared_query"] == "XTR-05 overlay"
    assert "XTR-05" not in by_index["heuristics"]["prepared_query"]


def test_report_counts_empty_layers_per_index(two_layer_cfg) -> None:
    """某層無命中時只有那一層的計數增加，其他層不受影響。"""
    cfg_path, cfg = two_layer_cfg
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    indexes = build_all_indexes(cfg, dictionary)
    layered = LayeredSearcher.load(cfg, dictionary)
    store = TelemetryStore.create(cfg)

    # 只有 cases 有 XTR-05；heuristics 那層剝掉識別碼後仍找得到 overlay
    store.log_layered(layered.search("overlay"))
    store.log_layered(layered.search("zzzqqq"))

    report = build_report(indexes, store, cfg)
    rates = report["retrieval_shape"]["layered"]["empty_layer_rate_by_index"]
    assert rates["heuristics"] == 0.5
    assert rates["cases"] == 0.5
    assert report["retrieval_shape"]["layered"]["queries"] == 2
    assert report["retrieval_shape"]["fused"]["queries"] == 0


def test_report_keeps_layered_and_fused_statistics_apart(two_layer_cfg) -> None:
    """融合後的名次是跨層競爭的結果，分層的名次是層內競爭的結果，兩者不可比。"""
    cfg_path, cfg = two_layer_cfg
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    indexes = build_all_indexes(cfg, dictionary)
    layered = LayeredSearcher.load(cfg, dictionary)
    store = TelemetryStore.create(cfg)

    store.log_layered(layered.search("overlay"))
    store.log_layered(layered.search("overlay", fuse=True))

    shape = build_report(indexes, store, cfg)["retrieval_shape"]
    assert shape["layered"]["queries"] == 1
    assert shape["fused"]["queries"] == 1
    assert shape["fused"]["fused_rank_distribution"]["n"] > 0
    assert "fused_rank_distribution" not in shape["layered"]
    # 平權 RRF 的實際出席比例——「每類知識都派代表」是不是真的發生了
    assert set(shape["fused"]["fused_contributions_by_index"]) <= {"heuristics", "cases"}


def test_feedback_records_the_source_index(two_layer_cfg) -> None:
    cfg_path, cfg = two_layer_cfg
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    indexes = build_all_indexes(cfg, dictionary)
    layered = LayeredSearcher.load(cfg, dictionary)
    store = TelemetryStore.create(cfg)

    qid = store.log_layered(layered.search("overlay"))
    store.log_feedback(qid, "cpt_c", rank=1, mode="C", index="cases")

    report = build_report(indexes, store, cfg)
    assert report["feedback"]["clicks_per_index"] == {"cases": 1}
    # 層內名次，不是跨層合併名次
    assert report["feedback"]["clicked_rank_distribution"]["max"] == 1


def test_report_breaks_corpus_stats_down_by_index(two_layer_cfg) -> None:
    cfg_path, cfg = two_layer_cfg
    dictionary = EntityDictionary.load(cfg.dictionary_path)
    indexes = build_all_indexes(cfg, dictionary)
    report = build_report(indexes, TelemetryStore.create(cfg), cfg)

    assert sorted(report["by_index"]) == ["cases", "heuristics"]
    for name in ("cases", "heuristics"):
        assert report["by_index"][name]["corpus"]["concepts"] == 1
    # 彙總只含加得起來的量
    assert report["corpus"]["concepts"] == 2
    assert report["corpus"]["indexes"] == 2
    assert "vocab_naive" not in report["corpus"]
    blob = json.dumps(report, ensure_ascii=False)
    assert "b1" not in blob, "bundle 名稱屬語料內容，不得因為新增拆解而洩漏"


def test_cli_and_api_report_measure_overlap_the_same_way(two_layer_cfg) -> None:
    """同一份報告從 CLI 與 HTTP 產出的數字不一樣，比缺一個欄位更難察覺。"""
    from yedai.layers import IdOverlap

    cfg_path, cfg = two_layer_cfg
    indexes = build_all_indexes(cfg, EntityDictionary.load(cfg.dictionary_path))
    report = build_report(
        indexes,
        TelemetryStore.create(cfg),
        cfg,
        id_overlap=IdOverlap.measure(indexes).to_dict(),
    )
    layered = LayeredSearcher.load(cfg, EntityDictionary.load(cfg.dictionary_path))
    assert report["id_overlap"] == layered.id_overlap.to_dict()
    assert report["id_overlap"]["total"] == 0


def test_cli_report_fills_id_overlap(two_layer_cfg, tmp_path: Path) -> None:
    cfg_path, _ = two_layer_cfg
    _run("index", "-c", str(cfg_path))
    out = tmp_path / "r.json"
    assert _run("report", "-o", str(out), "-c", str(cfg_path)).exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["id_overlap"] is not None, "CLI 報告漏了 id_overlap，與 HTTP 不一致"
    assert data["id_overlap"]["total"] == 0


# --- 層要自己說明自己 -----------------------------------------------------


def _described_cfg(tmp_path: Path, cfg: Config) -> Config:
    decl = dict(cfg.indexes)
    decl["cases"] = {
        **decl["cases"],
        "description": "已結案的 defect report。",
        "when_to_use": "想知道以前發生過什麼。",
    }
    return cfg.merged({"indexes": decl})


def test_index_declares_what_it_is(two_layer_cfg, tmp_path: Path) -> None:
    """索引名稱是設定檔裡的任意鍵——`cases`、`sop`、`a` 都合法。

    agent 只看得到那個字串，所以「這層是什麼」必須是可宣告的資料，不是註解。
    """
    _, cfg = two_layer_cfg
    described = _described_cfg(tmp_path, cfg)
    spec = described.index_spec("cases")
    assert spec.description and spec.when_to_use
    # 沒宣告的層要被點名，呼叫端才知道自己在猜
    assert described.undescribed_indexes() == ["heuristics"]


def test_mcp_tool_description_is_built_from_config_not_hardcoded(two_layer_cfg, tmp_path: Path) -> None:
    """寫死一組例子（「心法 / 已結案」）在別人的部署上就是錯的提示。

    工具說明是 agent 唯一的手冊，它必須描述實際載入的那一套層。
    """
    from yedai.entities import EntityDictionary
    from yedai.layers import LayeredSearcher
    from yedai.mcp_server import _tools
    from yedai.runtime import Runtime
    from yedai.taxonomy import Taxonomy

    _, cfg = two_layer_cfg
    described = _described_cfg(tmp_path, cfg)
    dictionary = EntityDictionary.from_config(described)
    build_all_indexes(described, dictionary)
    rt = Runtime(
        config=described,
        dictionary=dictionary,
        layered=LayeredSearcher.load(described, dictionary),
        taxonomy=Taxonomy.load(None),
        store=TelemetryStore.create(described),
    )
    try:
        desc = next(t.description for t in _tools(rt) if t.name == "search")
    finally:
        rt.close()

    assert "`cases`" in desc and "已結案的 defect report。" in desc
    assert "想知道以前發生過什麼。" in desc
    # 沒有 runtime 時（測試、靜態檢視）不得憑空編出一套層
    plain = next(t.description for t in _tools() if t.name == "search")
    assert "cases" not in plain and "心法" not in plain


def test_stats_carries_layer_descriptions(two_layer_cfg, tmp_path: Path) -> None:
    from yedai.entities import EntityDictionary
    from yedai.layers import LayeredSearcher
    from yedai.mcp_server import _dispatch
    from yedai.runtime import Runtime
    from yedai.taxonomy import Taxonomy

    _, cfg = two_layer_cfg
    described = _described_cfg(tmp_path, cfg)
    dictionary = EntityDictionary.from_config(described)
    build_all_indexes(described, dictionary)
    rt = Runtime(
        config=described,
        dictionary=dictionary,
        layered=LayeredSearcher.load(described, dictionary),
        taxonomy=Taxonomy.load(None),
        store=TelemetryStore.create(described),
    )
    try:
        st = _dispatch(rt, "stats", {})
    finally:
        rt.close()

    assert st["by_index"]["cases"]["description"] == "已結案的 defect report。"
    assert st["by_index"]["heuristics"]["description"] == ""
    assert st["indexes_without_description"] == ["heuristics"]
