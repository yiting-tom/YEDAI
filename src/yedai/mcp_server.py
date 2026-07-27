"""MCP server（stdio），供 claude-agent-sdk 等支援 MCP 的 agent 直接連接。

工具說明是 agent 唯一的使用手冊，因此三件事必須寫進 description：

1. `search` 只回菜單，要內容得呼叫 `get_concept` / `get_concepts`
2. `grep` 必須先有範圍，範圍取自 `search` 結果的 `bundle_id`
3. 建議流程：search → 挑 3~7 筆 → get_concepts → 需要時 neighbors 或 grep

若只寫「搜尋 concept」，agent 會把 `search` 當唯一入口，然後抱怨資訊不足。
"""

from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from .fulltext import MAX_BATCH, ConceptFileMissing, ConceptNotFound, load_concept, load_concepts
from .graph import DIRECTIONS, MAX_DEPTH, neighbors
from .grep import DEFAULT_MAX_RESULTS, InvalidPattern, ScopeRequired, UnknownScope, grep
from .runtime import Runtime
from .search import MODES, SearchOutcome

SERVER_NAME = "yedai"
SERVER_VERSION = "0.1.0"

WORKFLOW = (
    "建議流程：search 取菜單 → 挑 3~7 筆 → get_concepts 取全文 → "
    "需要時用 neighbors 沿關聯展開、或用 grep 在已縮小的範圍裡做字面搜尋。"
)


def _tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search",
            description=(
                "在 OKF 語料中檢索 concept。\n\n"
                "**只回摘要清單，不含內容**——要讀內容請以回傳的 concept_id 呼叫 "
                "get_concept 或 get_concepts。這是刻意的：由你決定讀哪幾份完整文件，"
                "比讓系統塞片段給你更準。\n\n"
                "mode 是消融實驗用的檢索模式：A=天真斷詞（識別碼會被切碎）、"
                "B=識別碼保護斷詞、C=B 加上實體字典加權。一般用途請用 C。\n\n"
                + WORKFLOW
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查詢字串", "minLength": 1},
                    "mode": {"type": "string", "enum": list(MODES), "default": "C"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_concept",
            description=(
                "取回單一 concept 的完整內容：原始 markdown 全文（raw）、"
                "解析後的 frontmatter、依 ## 切分的 sections、figures 與 related。\n\n"
                "要一次讀多份請用 get_concepts，不要連續呼叫本工具。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string", "description": "來自 search 結果的 concept_id"}
                },
                "required": ["concept_id"],
            },
        ),
        types.Tool(
            name="get_concepts",
            description=(
                f"批次取回多個 concept 的完整內容，最多 {MAX_BATCH} 筆。\n\n"
                "**部分成功**：單一 id 失敗不影響其餘，失敗者列在 errors，"
                "reason 區分 not_found（id 錯）與 file_missing（索引過期）。\n\n"
                "只需要標題與結構時可設 include_raw=false，省下大量 context。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": MAX_BATCH,
                    },
                    "include_raw": {"type": "boolean", "default": True},
                },
                "required": ["concept_ids"],
            },
        ),
        types.Tool(
            name="neighbors",
            description=(
                "沿 concept 的 related 關聯展開。\n\n"
                "direction=out 是「這份文件指向誰」，in 是「誰指向這份文件」——"
                "後者在排查時特別有用（還有哪些文件引用了這個概念），而且你無法自己拼出來。\n\n"
                f"depth 上限 {MAX_DEPTH}。回傳同樣是摘要清單，要內容請再呼叫 get_concepts。\n"
                "指向不存在 concept 的懸空引用會列在 dangling，不會混進正常清單。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string"},
                    "depth": {"type": "integer", "minimum": 1, "maximum": MAX_DEPTH, "default": 1},
                    "direction": {"type": "string", "enum": list(DIRECTIONS), "default": "both"},
                },
                "required": ["concept_id"],
            },
        ),
        types.Tool(
            name="grep",
            description=(
                "在**已限定的範圍內**做字面或正則搜尋。\n\n"
                "**必須提供 bundle_ids 或 concept_ids 至少其一**，否則會被拒絕。"
                "範圍請取自 search 結果中的 bundle_id：先用 search 把語料縮到 2~3 個 bundle，"
                "再在那個範圍裡搜尋——那正是小規模檔案搜尋有效的條件。\n\n"
                "預設字面比對。regex=true 才啟用正則。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1},
                    "bundle_ids": {"type": "array", "items": {"type": "string"}},
                    "concept_ids": {"type": "array", "items": {"type": "string"}},
                    "regex": {"type": "boolean", "default": False},
                    "ignore_case": {"type": "boolean", "default": False},
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1000,
                        "default": DEFAULT_MAX_RESULTS,
                    },
                },
                "required": ["pattern"],
            },
        ),
        types.Tool(
            name="stats",
            description=(
                "語料統計：bundle 數、concept 數、type 分佈、詞彙量、實體覆蓋率、"
                "懸空關聯數與解析失敗數。用來了解語料的規模與形狀。"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def _dispatch(rt: Runtime, name: str, args: dict[str, Any]) -> Any:
    if name == "search":
        mode = args.get("mode", "C")
        k = args.get("k")
        result = rt.searcher.search(args["query"], mode=mode, k=k)
        outcome = SearchOutcome(
            query=args["query"],
            k=k or rt.config.top_k,
            results={result.mode: result},
            entities=rt.searcher.extract_query_entities(args["query"]),
        )
        query_id = rt.store.log_query(outcome, requested_mode=f"mcp:{mode}")
        return {
            "query_id": query_id,
            "mode": result.mode,
            "candidates": result.candidates,
            "hits": [h.to_dict() for h in result.hits],
            "entities": [
                {"type": e.type, "canonical": e.canonical, "source": e.source} for e in outcome.entities
            ],
            "note": "這是摘要清單，不含內容。要讀內容請以 concept_id 呼叫 get_concepts。",
        }

    if name == "get_concept":
        return load_concept(rt.index, args["concept_id"])

    if name == "get_concepts":
        ids = list(args["concept_ids"])
        if not ids:
            raise ValueError("concept_ids must not be empty")
        if len(ids) > MAX_BATCH:
            raise ValueError(f"最多 {MAX_BATCH} 筆，收到 {len(ids)} 筆")
        found, errors = load_concepts(rt.index, ids, include_raw=args.get("include_raw", True))
        return {"requested": len(ids), "returned": len(found), "concepts": found, "errors": errors}

    if name == "neighbors":
        return neighbors(
            rt.index,
            args["concept_id"],
            depth=args.get("depth", 1),
            direction=args.get("direction", "both"),
        )

    if name == "grep":
        return grep(
            rt.index,
            args["pattern"],
            bundle_ids=args.get("bundle_ids"),
            concept_ids=args.get("concept_ids"),
            regex=args.get("regex", False),
            ignore_case=args.get("ignore_case", False),
            max_results=args.get("max_results", DEFAULT_MAX_RESULTS),
        )

    if name == "stats":
        s = rt.index.stats
        return {
            "bundles": s.bundles,
            "concepts": s.concepts,
            "avg_concept_chars": round(s.avg_concept_chars, 1),
            "avg_figures_per_concept": round(s.avg_figures, 2),
            "vocab_naive": s.vocab_naive,
            "vocab_protected": s.vocab_protected,
            "entities_total": s.entities_total,
            "entities_from_dictionary": s.entities_dict,
            "entities_from_regex_fallback": s.entities_regex,
            "dangling_related": s.dangling_related,
            "parse_skipped": s.parse_skipped,
            "types": s.types,
        }

    raise ValueError(f"unknown tool: {name}")


def build_server(rt: Runtime) -> Server:
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _tools()

    # validate_input=False：參數驗證在 _dispatch 裡做，錯誤才能以「工具結果」
    # 的形式回給 agent 讓它自行修正，而不是以協定錯誤中斷。
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        try:
            payload = _dispatch(rt, name, arguments or {})
        except ConceptNotFound as exc:
            payload = {"error": "not_found", "detail": f"查無 concept_id: {exc.args[0] if exc.args else ''}"}
        except ConceptFileMissing as exc:
            payload = {"error": "file_missing", "detail": str(exc)}
        except ScopeRequired as exc:
            payload = {"error": "scope_required", "detail": str(exc)}
        except UnknownScope as exc:
            payload = {"error": "unknown_scope", "detail": str(exc.args[0] if exc.args else exc)}
        except InvalidPattern as exc:
            payload = {"error": "invalid_pattern", "detail": str(exc)}
        except Exception as exc:  # 工具失敗回錯誤結果，不中斷連線
            payload = {"error": type(exc).__name__, "detail": str(exc)}
        return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server


async def serve_stdio(rt: Runtime) -> None:
    server = build_server(rt)
    options = InitializationOptions(
        server_name=SERVER_NAME,
        server_version=SERVER_VERSION,
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(), experimental_capabilities={}
        ),
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options)


def main(config_path: str | None = None) -> None:
    import anyio

    rt = Runtime.load(config_path)
    anyio.run(serve_stdio, rt)
