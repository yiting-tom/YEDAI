from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from yedai import api
from yedai.entities import EntityDictionary
from yedai.index import build_index


@pytest.fixture
def client(corpus: Path, config, dictionary_path: Path, tmp_path: Path, monkeypatch):
    dictionary = EntityDictionary.load(config.dictionary_path)
    build_index(corpus, config, dictionary).save(config.index_path)

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "dictionary_path": str(dictionary_path),
                "index_path": str(config.index_path),
                "log_dir": str(config.log_dir),
                "seed": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("YEDAI_CONFIG", str(cfg_path))
    monkeypatch.delenv("YEDAI_INDEX", raising=False)

    with TestClient(api.app) as c:
        yield c


def test_healthz(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["index_loaded"] is True


def test_stats(client) -> None:
    body = client.get("/stats").json()
    assert body["concepts"] > 0
    assert body["vocab_protected"] > 0
    assert body["entities_total"] > 0


def test_search_single_mode(client) -> None:
    r = client.get("/search", params={"q": "XTR-05 PARTICLE", "mode": "B", "k": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["query_id"]
    assert list(body["results"]) == ["B"]
    assert body["results"]["B"]["hits"]


def test_search_compare_mode(client) -> None:
    body = client.get("/search", params={"q": "XTR-05 PARTICLE", "mode": "compare", "k": 5}).json()
    assert set(body["results"]) == {"A", "B", "C"}
    assert {o["pair"] for o in body["overlaps"]} == {"A-B", "A-C", "B-C"}
    assert sorted(body["display_order"]) == ["A", "B", "C"]


def test_search_reports_entities(client) -> None:
    body = client.get("/search", params={"q": "XTR-05 PARTICLE", "mode": "C"}).json()
    canonicals = {e["canonical"] for e in body["entities"]}
    assert {"XTR-05", "PARTICLE"} <= canonicals


def test_search_missing_query_is_422(client) -> None:
    assert client.get("/search").status_code == 422


def test_search_invalid_mode_is_422(client) -> None:
    assert client.get("/search", params={"q": "x", "mode": "Z"}).status_code == 422


def test_search_invalid_k_is_422(client) -> None:
    assert client.get("/search", params={"q": "x", "k": 0}).status_code == 422


def test_feedback_roundtrip(client) -> None:
    search = client.get("/search", params={"q": "PARTICLE", "mode": "C", "k": 5}).json()
    hit = search["results"]["C"]["hits"][0]
    r = client.post(
        "/feedback",
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


def test_feedback_unknown_query_id_is_404(client) -> None:
    r = client.post(
        "/feedback",
        json={"query_id": "nope", "concept_id": "cpt_x", "rank": 1, "mode": "C"},
    )
    assert r.status_code == 404


def test_report_endpoint_has_no_corpus_content(client) -> None:
    client.get("/search", params={"q": "XTR-05 PARTICLE", "mode": "compare"})
    r = client.get("/report")
    assert r.status_code == 200
    blob = r.text
    for needle in ["XTR-05", "PARTICLE", "cpt_", "調查"]:
        assert needle not in blob, f"/report 洩漏了語料內容：{needle!r}"


def test_concept_fulltext_roundtrip(client) -> None:
    search = client.get("/search", params={"q": "PARTICLE", "mode": "B", "k": 5}).json()
    hit = search["results"]["B"]["hits"][0]

    r = client.get(f"/concept/{hit['concept_id']}")
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
    assert client.get("/concept/cpt_definitely_not_here").status_code == 404


def test_concept_missing_file_is_410(client, corpus, config) -> None:
    from yedai import api

    meta = api.state.index.doc_of("cpt_rare")
    (corpus / "b1" / meta.path).unlink()

    r = client.get("/concept/cpt_rare")
    assert r.status_code == 410
    assert "重建索引" in r.json()["detail"]


def test_concepts_batch(client) -> None:
    r = client.post(
        "/concepts",
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
    r = client.post("/concepts", json={"concept_ids": ["cpt_title-hit", "cpt_nope"]})
    assert r.status_code == 200
    body = r.json()
    assert body["returned"] == 1
    assert body["errors"][0]["reason"] == "not_found"


def test_concepts_include_raw_false(client) -> None:
    body = client.post(
        "/concepts", json={"concept_ids": ["cpt_title-hit"], "include_raw": False}
    ).json()
    assert "raw" not in body["concepts"][0]


def test_concepts_empty_list_is_422(client) -> None:
    assert client.post("/concepts", json={"concept_ids": []}).status_code == 422


def test_concepts_over_limit_is_422(client) -> None:
    assert client.post("/concepts", json={"concept_ids": ["x"] * 200}).status_code == 422


def test_neighbors_depth_one(client) -> None:
    r = client.get("/concept/cpt_title-hit/neighbors", params={"depth": 1, "direction": "out"})
    assert r.status_code == 200
    body = r.json()
    assert {n["concept_id"] for n in body["neighbors"]} == {"cpt_body-hit", "cpt_sibling"}
    assert body["dangling"] == ["cpt_ghost"]


def test_neighbors_inbound(client) -> None:
    body = client.get("/concept/cpt_body-hit/neighbors", params={"direction": "in"}).json()
    assert [n["concept_id"] for n in body["neighbors"]] == ["cpt_title-hit"]


def test_neighbors_unknown_is_404(client) -> None:
    assert client.get("/concept/cpt_nope/neighbors").status_code == 404


def test_neighbors_depth_over_limit_is_422(client) -> None:
    assert client.get("/concept/cpt_title-hit/neighbors", params={"depth": 5}).status_code == 422


def test_neighbors_bad_direction_is_422(client) -> None:
    r = client.get("/concept/cpt_title-hit/neighbors", params={"direction": "sideways"})
    assert r.status_code == 422


def test_grep_scoped(client) -> None:
    r = client.get("/grep", params={"pattern": "PARTICLE", "bundle_id": "bdl_b1"})
    assert r.status_code == 200
    assert r.json()["results"]


def test_grep_without_scope_is_422(client) -> None:
    r = client.get("/grep", params={"pattern": "PARTICLE"})
    assert r.status_code == 422
    assert "search" in r.json()["detail"]


def test_grep_unknown_bundle_is_404(client) -> None:
    r = client.get("/grep", params={"pattern": "x", "bundle_id": "bdl_nope"})
    assert r.status_code == 404


def test_grep_invalid_regex_is_422(client) -> None:
    r = client.get(
        "/grep", params={"pattern": "XTR-0(5", "bundle_id": "bdl_b1", "regex": "true"}
    )
    assert r.status_code == 422


def test_grep_scope_from_search_results(client) -> None:
    """agent 的實際用法：先 search 縮範圍，再拿 bundle_id 去 grep。"""
    search = client.get("/search", params={"q": "PARTICLE", "mode": "C", "k": 3}).json()
    bundle_id = search["results"]["C"]["hits"][0]["bundle_id"]
    r = client.get("/grep", params={"pattern": "PARTICLE", "bundle_id": bundle_id})
    assert r.status_code == 200
    assert r.json()["results"]


def test_openapi_lists_all_endpoints(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/search",
        "/feedback",
        "/stats",
        "/report",
        "/healthz",
        "/concept/{concept_id}",
        "/concepts",
        "/concept/{concept_id}/neighbors",
        "/grep",
    } <= set(paths)


def test_docs_page_served(client) -> None:
    r = client.get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()
