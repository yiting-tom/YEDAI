from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from yedai.entities import EntityDictionary
from yedai.index import build_index
from yedai.mcp_server import _dispatch, _tools, build_server
from yedai.runtime import Runtime
from yedai.search import Searcher
from yedai.telemetry import TelemetryStore

EXPECTED_TOOLS = {"search", "get_concept", "get_concepts", "neighbors", "grep", "stats"}


@pytest.fixture
def runtime(corpus: Path, config) -> Runtime:
    dictionary = EntityDictionary.load(config.dictionary_path)
    index = build_index(corpus, config, dictionary)
    return Runtime(
        config=config,
        dictionary=dictionary,
        index=index,
        searcher=Searcher(index, config, dictionary),
        store=TelemetryStore.create(config),
    )


# --- 工具定義 -----------------------------------------------------------


def test_tool_set() -> None:
    assert {t.name for t in _tools()} == EXPECTED_TOOLS


def test_every_tool_has_input_schema() -> None:
    for tool in _tools():
        assert tool.inputSchema["type"] == "object"
        assert tool.description


def test_search_description_points_to_fulltext() -> None:
    """工具說明是 agent 唯一的手冊。沒寫清楚它就會把 search 當唯一入口。"""
    desc = next(t for t in _tools() if t.name == "search").description
    assert "get_concepts" in desc
    assert "不含內容" in desc


def test_grep_description_requires_scope() -> None:
    desc = next(t for t in _tools() if t.name == "grep").description
    assert "必須提供" in desc
    assert "search" in desc


# --- dispatch -----------------------------------------------------------


def test_dispatch_search_returns_menu(runtime) -> None:
    out = _dispatch(runtime, "search", {"query": "XTR-05 PARTICLE", "mode": "C", "k": 5})
    assert out["hits"]
    assert out["query_id"]
    assert "note" in out
    # 菜單不含全文
    assert all("raw" not in h for h in out["hits"])


def test_dispatch_get_concept(runtime) -> None:
    out = _dispatch(runtime, "get_concept", {"concept_id": "cpt_title-hit"})
    assert out["raw"].startswith("---")


def test_dispatch_get_concepts_batch(runtime) -> None:
    out = _dispatch(runtime, "get_concepts", {"concept_ids": ["cpt_title-hit", "cpt_nope"]})
    assert out["returned"] == 1
    assert out["errors"][0]["reason"] == "not_found"


def test_dispatch_get_concepts_rejects_oversize(runtime) -> None:
    with pytest.raises(ValueError):
        _dispatch(runtime, "get_concepts", {"concept_ids": ["cpt_x"] * 200})


def test_dispatch_neighbors(runtime, graph_index) -> None:
    rt = runtime
    rt.index = graph_index
    out = _dispatch(rt, "neighbors", {"concept_id": "cpt_a", "depth": 1, "direction": "out"})
    assert {n["concept_id"] for n in out["neighbors"]} == {"cpt_b", "cpt_c"}


def test_dispatch_grep(runtime) -> None:
    out = _dispatch(runtime, "grep", {"pattern": "PARTICLE", "bundle_ids": ["bdl_b1"]})
    assert out["results"]


def test_dispatch_stats(runtime) -> None:
    out = _dispatch(runtime, "stats", {})
    assert out["concepts"] > 0
    assert "dangling_related" in out


def test_dispatch_unknown_tool(runtime) -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        _dispatch(runtime, "nope", {})


# --- 真正跑一次 MCP 協定 -------------------------------------------------


def _run(coro_fn, runtime):
    async def main():
        async with create_connected_server_and_client_session(build_server(runtime)) as session:
            await session.initialize()
            return await coro_fn(session)

    return anyio.run(main)


def test_protocol_list_tools(runtime) -> None:
    result = _run(lambda s: s.list_tools(), runtime)
    assert {t.name for t in result.tools} == EXPECTED_TOOLS


def test_protocol_call_search(runtime) -> None:
    result = _run(lambda s: s.call_tool("search", {"query": "PARTICLE", "mode": "B", "k": 3}), runtime)
    payload = json.loads(result.content[0].text)
    assert payload["hits"]
    assert payload["mode"] == "B"


def test_protocol_call_get_concept(runtime) -> None:
    result = _run(lambda s: s.call_tool("get_concept", {"concept_id": "cpt_title-hit"}), runtime)
    payload = json.loads(result.content[0].text)
    assert payload["concept_id"] == "cpt_title-hit"
    assert payload["raw"].startswith("---")


def test_protocol_tool_failure_returns_error_not_crash(runtime) -> None:
    """工具失敗必須回錯誤結果，不能中斷連線——否則 agent 整段對話報廢。"""
    result = _run(lambda s: s.call_tool("get_concept", {"concept_id": "cpt_nope"}), runtime)
    payload = json.loads(result.content[0].text)
    assert payload["error"] == "not_found"


def test_protocol_grep_without_scope_returns_guidance(runtime) -> None:
    result = _run(lambda s: s.call_tool("grep", {"pattern": "PARTICLE"}), runtime)
    payload = json.loads(result.content[0].text)
    assert payload["error"] == "scope_required"
    assert "search" in payload["detail"]


def test_protocol_matches_http_ordering(runtime) -> None:
    """兩個介面共用 runtime，同一查詢的排序必須一致。"""
    via_mcp = json.loads(
        _run(lambda s: s.call_tool("search", {"query": "PARTICLE", "mode": "C", "k": 5}), runtime)
        .content[0]
        .text
    )
    direct = runtime.searcher.search("PARTICLE", mode="C", k=5)
    assert [h["concept_id"] for h in via_mcp["hits"]] == [h.concept_id for h in direct.hits]
