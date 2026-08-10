from __future__ import annotations

from .conftest import INDEX_NAME

import pytest


def test_healthz(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["index_loaded"] is True


def test_stats(client) -> None:
    body = client.get("/v1/stats").json()
    assert body["indexes"] == [INDEX_NAME]
    layer = body["by_index"][INDEX_NAME]
    assert layer["concepts"] > 0
    assert layer["vocab_protected"] > 0
    assert layer["entities_total"] > 0


def test_search_is_layered(client) -> None:
    r = client.get("/v1/search", params={"q": "XTR-05 PARTICLE", "mode": "B", "k": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["query_id"]
    assert body["shape"] == "layered"
    assert [lr["index"] for lr in body["layers"]] == [INDEX_NAME]
    assert body["layers"][0]["mode"] == "B"
    assert body["layers"][0]["hits"]
    # 預設不融合。空清單與「沒要求融合」必須可區分，所以是 null 不是 []
    assert body["fused"] is None


def test_search_keeps_empty_layers(client) -> None:
    """層的缺席本身是訊號——省略它會讓它與「排在 k 之外」不可區分。"""
    body = client.get("/v1/search", params={"q": "完全不存在zzzz", "mode": "C"}).json()
    assert [lr["index"] for lr in body["layers"]] == [INDEX_NAME]
    assert body["layers"][0]["hits"] == []


def test_search_unknown_index_is_422(client) -> None:
    r = client.get("/v1/search", params={"q": "x", "index": "nope"})
    assert r.status_code == 422
    assert INDEX_NAME in r.json()["detail"]


def test_search_fuse_keeps_source_and_rank(client) -> None:
    body = client.get(
        "/v1/search", params={"q": "PARTICLE", "mode": "C", "k": 5, "fuse": "true"}
    ).json()
    assert body["shape"] == "fused"
    assert body["layers"], "融合時分層結構仍須保留，否則看不出某層是否整個沒東西"
    for fh in body["fused"]:
        assert fh["index"] == INDEX_NAME
        assert fh["source_rank"] >= 1


def test_compare_endpoint(client) -> None:
    body = client.get("/v1/compare", params={"q": "XTR-05 PARTICLE", "k": 5}).json()
    assert body["index"] == INDEX_NAME
    assert set(body["results"]) == {"A", "B", "C"}
    assert {o["pair"] for o in body["overlaps"]} == {"A-B", "A-C", "B-C"}
    assert sorted(body["display_order"]) == ["A", "B", "C"]


def test_compare_reports_entities(client) -> None:
    body = client.get("/v1/compare", params={"q": "XTR-05 PARTICLE"}).json()
    canonicals = {e["canonical"] for e in body["entities"]}
    assert {"XTR-05", "PARTICLE"} <= canonicals


def test_taxonomy_unknown_defect_is_404(client) -> None:
    """查無條目回 404，而且不夾帶任何其他 defect 的條目。"""
    r = client.get("/v1/taxonomy/DEFECT_NOPE")
    assert r.status_code == 404
    assert "DEFECT_NOPE" in r.json()["detail"]


def test_search_missing_query_is_422(client) -> None:
    assert client.get("/v1/search").status_code == 422


def test_search_invalid_mode_is_422(client) -> None:
    assert client.get("/v1/search", params={"q": "x", "mode": "Z"}).status_code == 422


def test_search_invalid_k_is_422(client) -> None:
    assert client.get("/v1/search", params={"q": "x", "k": 0}).status_code == 422


def test_feedback_roundtrip(client) -> None:
    search = client.get("/v1/search", params={"q": "PARTICLE", "mode": "C", "k": 5}).json()
    hit = search["layers"][0]["hits"][0]
    r = client.post(
        "/v1/feedback",
        json={
            "query_id": search["query_id"],
            "concept_id": hit["concept_id"],
            "rank": hit["rank"],
            "mode": "C",
            "action": "click",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"
    # 省略 index 時由 concept_id 推定——要前端記住來源層只會讓回饋更難收集
    assert r.json()["index"] == INDEX_NAME


def test_feedback_unknown_query_id_is_404(client) -> None:
    r = client.post(
        "/v1/feedback",
        json={"query_id": "nope", "concept_id": "cpt_x", "rank": 1, "mode": "C"},
    )
    assert r.status_code == 404


def test_report_endpoint_has_no_corpus_content(client) -> None:
    client.get("/v1/search", params={"q": "XTR-05 PARTICLE", "mode": "compare"})
    r = client.get("/v1/report")
    assert r.status_code == 200
    blob = r.text
    for needle in ["XTR-05", "PARTICLE", "cpt_", "調查"]:
        assert needle not in blob, f"/v1/report 洩漏了語料內容：{needle!r}"


def test_concept_fulltext_roundtrip(client) -> None:
    search = client.get("/v1/search", params={"q": "PARTICLE", "mode": "B", "k": 5}).json()
    hit = search["layers"][0]["hits"][0]

    r = client.get(f"/v1/concept/{hit['concept_id']}")
    assert r.status_code == 200
    body = r.json()

    assert body["concept_id"] == hit["concept_id"]
    assert body["bundle_id"] == hit["bundle_id"]
    assert body["type"] == hit["type"]
    assert body["title"] == hit["title"]
    assert body["path"] == hit["path"]
    assert body["index_line"] == hit["index_line"]
    # 這是整個端點存在的理由：agent 拿得到全文
    assert body["raw"].startswith("---")
    assert isinstance(body["sections"], list) and body["sections"]
    assert isinstance(body["frontmatter"], dict)


def test_concept_unknown_id_is_404(client) -> None:
    assert client.get("/v1/concept/cpt_definitely_not_here").status_code == 404


def test_concept_missing_file_is_410(client, corpus, config) -> None:
    from yedai import api

    meta = api.state.indexes[INDEX_NAME].doc_of("cpt_rare")
    (corpus / "b1" / meta.path).unlink()

    r = client.get("/v1/concept/cpt_rare")
    assert r.status_code == 410
    assert "重建索引" in r.json()["detail"]


def test_concepts_batch(client) -> None:
    r = client.post(
        "/v1/concepts",
        json={"concept_ids": ["cpt_title-hit", "cpt_body-hit", "cpt_rare"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["returned"] == 3
    assert body["errors"] == []
    assert [c["concept_id"] for c in body["concepts"]] == [
        "cpt_title-hit",
        "cpt_body-hit",
        "cpt_rare",
    ]


def test_concepts_partial_success_is_200(client) -> None:
    r = client.post("/v1/concepts", json={"concept_ids": ["cpt_title-hit", "cpt_nope"]})
    assert r.status_code == 200
    body = r.json()
    assert body["returned"] == 1
    assert body["errors"][0]["reason"] == "not_found"


def test_concepts_include_raw_false(client) -> None:
    body = client.post(
        "/v1/concepts", json={"concept_ids": ["cpt_title-hit"], "include_raw": False}
    ).json()
    assert "raw" not in body["concepts"][0]


def test_concepts_empty_list_is_422(client) -> None:
    assert client.post("/v1/concepts", json={"concept_ids": []}).status_code == 422


def test_concepts_over_limit_is_422(client) -> None:
    assert client.post("/v1/concepts", json={"concept_ids": ["x"] * 200}).status_code == 422


def test_neighbors_depth_one(client) -> None:
    r = client.get("/v1/concept/cpt_title-hit/neighbors", params={"depth": 1, "direction": "out"})
    assert r.status_code == 200
    body = r.json()
    assert {n["concept_id"] for n in body["neighbors"]} == {"cpt_body-hit", "cpt_sibling"}
    assert body["dangling"] == ["cpt_ghost"]


def test_neighbors_inbound(client) -> None:
    body = client.get("/v1/concept/cpt_body-hit/neighbors", params={"direction": "in"}).json()
    assert [n["concept_id"] for n in body["neighbors"]] == ["cpt_title-hit"]


def test_neighbors_unknown_is_404(client) -> None:
    assert client.get("/v1/concept/cpt_nope/neighbors").status_code == 404


def test_neighbors_depth_over_limit_is_422(client) -> None:
    assert client.get("/v1/concept/cpt_title-hit/neighbors", params={"depth": 5}).status_code == 422


def test_neighbors_bad_direction_is_422(client) -> None:
    r = client.get("/v1/concept/cpt_title-hit/neighbors", params={"direction": "sideways"})
    assert r.status_code == 422


def test_grep_scoped(client) -> None:
    r = client.get("/v1/grep", params={"pattern": "PARTICLE", "bundle_id": "bdl_b1"})
    assert r.status_code == 200
    assert r.json()["results"]


def test_grep_without_scope_is_422(client) -> None:
    r = client.get("/v1/grep", params={"pattern": "PARTICLE"})
    assert r.status_code == 422
    assert "search" in r.json()["detail"]


def test_grep_unknown_bundle_is_404(client) -> None:
    r = client.get("/v1/grep", params={"pattern": "x", "bundle_id": "bdl_nope"})
    assert r.status_code == 404


def test_grep_invalid_regex_is_422(client) -> None:
    r = client.get(
        "/v1/grep", params={"pattern": "XTR-0(5", "bundle_id": "bdl_b1", "regex": "true"}
    )
    assert r.status_code == 422


def test_grep_scope_from_search_results(client) -> None:
    """agent 的實際用法：先 search 縮範圍，再拿 bundle_id 去 grep。"""
    search = client.get("/v1/search", params={"q": "PARTICLE", "mode": "C", "k": 3}).json()
    bundle_id = search["layers"][0]["hits"][0]["bundle_id"]
    r = client.get("/v1/grep", params={"pattern": "PARTICLE", "bundle_id": bundle_id})
    assert r.status_code == 200
    assert r.json()["results"]


def test_asset_download(client) -> None:
    from .conftest import PNG

    r = client.get("/v1/concept/cpt_title-hit/asset", params={"path": "_assets/slide_001.png"})
    assert r.status_code == 200
    assert r.content == PNG
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"].startswith("inline;")


def test_asset_from_declared_assets_array(client) -> None:
    """agent 的實際用法：/concept 取 assets → 逐項下載。"""
    declared = client.get("/v1/concept/cpt_title-hit").json()["assets"]
    assert declared
    for rel in declared:
        r = client.get("/v1/concept/cpt_title-hit/asset", params={"path": rel})
        assert r.status_code == 200, rel


def test_asset_unknown_media_type(client) -> None:
    r = client.get("/v1/concept/cpt_title-hit/asset", params={"path": "_assets/notes.bin"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"


def test_asset_download_flag_sets_attachment(client) -> None:
    r = client.get(
        "/v1/concept/cpt_title-hit/asset",
        params={"path": "_assets/slide_001.png", "download": "true"},
    )
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "slide_001.png" in r.headers["content-disposition"]


def test_asset_traversal_is_403(client) -> None:
    for bad in ["../../../../etc/passwd", "_assets/../not-an-asset.txt", "/etc/passwd"]:
        r = client.get("/v1/concept/cpt_title-hit/asset", params={"path": bad})
        assert r.status_code == 403, bad


def test_asset_outside_asset_dirs_is_403(client) -> None:
    r = client.get("/v1/concept/cpt_title-hit/asset", params={"path": "not-an-asset.txt"})
    assert r.status_code == 403
    assert "_assets" in r.json()["detail"]


def test_asset_missing_file_is_404(client) -> None:
    r = client.get("/v1/concept/cpt_title-hit/asset", params={"path": "_assets/nope.png"})
    assert r.status_code == 404


def test_asset_unknown_concept_is_404(client) -> None:
    r = client.get("/v1/concept/cpt_nope/asset", params={"path": "_assets/slide_001.png"})
    assert r.status_code == 404


def test_asset_missing_path_param_is_422(client) -> None:
    assert client.get("/v1/concept/cpt_title-hit/asset").status_code == 422


def test_version_endpoint(client) -> None:
    from yedai import __version__
    from yedai.api import API_VERSION
    from yedai.index import INDEX_FORMAT_VERSION

    body = client.get("/version").json()
    assert body["package"] == __version__
    assert body["api"] == API_VERSION
    # 「支援的索引格式」與「已載入索引的格式」必須是兩個獨立欄位——
    # 「支援 v3、載入的是 v2」正是最需要一眼看出的除錯情境
    assert body["index_format"] == INDEX_FORMAT_VERSION
    assert body["indexes"][INDEX_NAME]["format_version"] == INDEX_FORMAT_VERSION
    assert body["indexes"][INDEX_NAME]["signature"]


def test_version_works_without_index(monkeypatch, tmp_path) -> None:
    """索引未載入時仍須可查——這個端點的用途之一就是診斷載入失敗。"""
    from fastapi.testclient import TestClient

    from yedai import api

    # 未宣告任何索引：載入必定失敗，而 /version 仍須回應
    cfg_path = tmp_path / "empty.yaml"
    cfg_path.write_text("log_dir: logs\n", encoding="utf-8")
    monkeypatch.setenv("YEDAI_CONFIG", str(cfg_path))
    with TestClient(api.app) as c:
        assert c.get("/healthz").json()["index_loaded"] is False
        body = c.get("/version").json()
        assert body["package"] and body["api"]
        assert body["indexes"] == {}


@pytest.mark.parametrize(
    "legacy",
    ["/search", "/stats", "/report", "/grep", "/concepts", "/concept/cpt_title-hit", "/compare"],
)
def test_unversioned_paths_are_gone(client, legacy: str) -> None:
    assert client.get(legacy).status_code == 404


def test_healthz_and_version_are_unversioned(client) -> None:
    """監控與部署不該因為 API 從 v1 升到 v2 就失效。"""
    assert client.get("/healthz").status_code == 200
    assert client.get("/version").status_code == 200
    assert client.get("/v1/healthz").status_code == 404


def test_openapi_version_matches_package(client) -> None:
    from yedai import __version__

    assert client.get("/openapi.json").json()["info"]["version"] == __version__


def test_every_endpoint_has_exactly_one_known_tag(client) -> None:
    spec = client.get("/openapi.json").json()
    known = {"retrieval", "content", "graph", "telemetry", "ops"}
    assert {t["name"] for t in spec["tags"]} == known
    assert all(t.get("description") for t in spec["tags"]), "每個分類都要有說明"

    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            tags = op.get("tags", [])
            assert len(tags) == 1, f"{method.upper()} {path} 的標籤數應為 1，實為 {tags}"
            assert tags[0] in known, f"{method.upper()} {path} 用了未知標籤 {tags[0]}"


def test_retrieval_and_content_are_separate_tags(client) -> None:
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/v1/search"]["get"]["tags"] == ["retrieval"]
    assert spec["paths"]["/v1/concept/{concept_id}"]["get"]["tags"] == ["content"]


def test_telemetry_is_its_own_tag(client) -> None:
    """回饋與報告服務的是量測實驗，不該讓 agent 誤以為要呼叫。"""
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/v1/feedback"]["post"]["tags"] == ["telemetry"]
    assert spec["paths"]["/v1/report"]["get"]["tags"] == ["telemetry"]


def test_openapi_lists_all_endpoints(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/v1/search",
        "/v1/feedback",
        "/v1/stats",
        "/v1/report",
        "/healthz",
        "/v1/concept/{concept_id}",
        "/v1/concepts",
        "/v1/concept/{concept_id}/neighbors",
        "/v1/concept/{concept_id}/asset",
        "/v1/grep",
    } <= set(paths)


def test_docs_page_served(client) -> None:
    r = client.get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()


def test_concept_with_boolean_frontmatter_fields_serialises(client, corpus, config) -> None:
    """`generated: true` 這種布林 frontmatter 必須通過回應驗證。

    這條是端對端跑出來的迴歸點：`ConceptOut.generated` 曾誤宣告為 `str`，而
    `Concept.generated` 是 `bool | None`——於是任何帶 `generated: true` 的 concept
    在 `/v1/concept` 與 `/v1/concepts` 上都回 500。單元測試看不到，因為
    `conftest.write_concept` 從不寫這個欄位；而 `gen-synthetic` 產出的語料**每一篇都有**。
    """
    from .conftest import write_concept

    write_concept(
        corpus / "b1" / "okf",
        "boolflag",
        frontmatter={"id": "cpt_boolflag", "title": "布林旗標", "generated": True},
    )
    from yedai import api
    from yedai.entities import EntityDictionary
    from yedai.index import build_index

    idx = build_index(corpus, config, EntityDictionary.load(config.dictionary_path), name=INDEX_NAME)
    api.state.runtime.layered.searchers[INDEX_NAME].index = idx

    r = client.get("/v1/concept/cpt_boolflag")
    assert r.status_code == 200, r.text
    assert r.json()["generated"] is True

    rb = client.post("/v1/concepts", json={"concept_ids": ["cpt_boolflag"]})
    assert rb.status_code == 200, rb.text
    assert rb.json()["concepts"][0]["generated"] is True
