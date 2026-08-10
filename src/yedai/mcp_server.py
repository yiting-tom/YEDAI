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
from .index import Index
from .runtime import Runtime
from .search import MODES
from .taxonomy import TaxonomyNotFound

SERVER_NAME = "yedai"
SERVER_VERSION = "0.1.0"

WORKFLOW = (
    "建議流程：search 取菜單 → 挑 3~7 筆 → get_concepts 取全文 → "
    "需要時用 neighbors 沿關聯展開、或用 grep 在已縮小的範圍裡做字面搜尋。"
)


def _layer_guide(rt: Runtime | None) -> str:
    """把各層的說明**從設定**組進工具描述。

    寫死一組例子（「心法 / 已結案 / 缺陷登錄」）在別人的部署上就是錯的提示——
    索引名稱是設定檔裡的任意鍵。工具描述是 agent 唯一的手冊，它必須描述
    這一套實際載入的層，不是我當初想像的那一套。
    """
    if rt is None:
        return ""
    lines = []
    for name in rt.index_names:
        spec = rt.config.index_spec(name)
        parts = [f"- `{name}`"]
        if spec.description:
            parts.append(f"：{spec.description}")
        if spec.when_to_use:
            parts.append(f"\n    什麼時候用：{spec.when_to_use}")
        lines.append("".join(parts))
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "\n\n**這套系統目前載入的層**（名稱與說明來自設定）：\n"
        f"{body}\n\n"
        "沒有說明的層表示設定裡沒寫——那時只能從 stats 的 type 分佈推測，"
        "不要假裝知道它是什麼。\n"
    )


def _tools(rt: Runtime | None = None) -> list[types.Tool]:
    return [
        types.Tool(
            name="search",
            description=(
                "在語料中檢索 concept。\n\n"
                "**預設分層回傳**：每一類知識各自是一個索引，各自有自己的結果與分數，"
                "**不跨層排序**。回傳的 layers 陣列每層一筆。"
                + _layer_guide(rt)
                + "\n"
                "**空的層是有意義的**：某一層 hits 為空，表示這類知識裡沒有對應的東西，"
                "那本身就是資訊，不是「沒找到」。上面每一層的說明會告訴你那代表什麼。\n\n"
                "**只回摘要清單，不含內容**——要讀內容請以回傳的 concept_id 呼叫 "
                "get_concept 或 get_concepts。由你決定讀哪幾份完整文件，比讓系統塞片段給你更準。\n\n"
                "index 可指定只查某一層（名稱見 stats 的 indexes）。不確定要查哪層時**不要指定**——"
                "分層全查會讓你看見別層也有東西。\n\n"
                "mode 省略時各層用自己宣告的預設。A=天真斷詞（識別碼會被切碎）、"
                "B=識別碼保護斷詞、C=B 加上實體字典加權、D=純向量、E=RRF(C,D)。\n\n"
                + WORKFLOW
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查詢字串", "minLength": 1},
                    "index": {"type": "string", "description": "只查這一層；省略則分層全查"},
                    "mode": {"type": "string", "enum": list(MODES)},
                    "k": {"type": "integer", "minimum": 1, "maximum": 100},
                    "fuse": {
                        "type": "boolean",
                        "default": False,
                        "description": "額外附上跨層 RRF 融合清單。分層結構仍然保留",
                    },
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
            name="taxonomy",
            description=(
                "以 defect 為鍵取回它的判斷方法。\n\n"
                "**這是查表不是檢索**：查無條目會明確回報「沒有這一條」，不會給你"
                "最接近的那一筆。拿另一個 defect 的判斷方法去解讀影像，比沒有方法更糟——"
                "錯的方法看起來跟對的一樣有條理。\n\n"
                "條目內容是**方法不是答案**：它說明怎麼從影像推出候選 module，"
                "而不是直接給你 module 清單。沒有條目時請據實說明，不要自行編一套判準。"
            ),
            inputSchema={
                "type": "object",
                "properties": {"defect": {"type": "string", "minLength": 1}},
                "required": ["defect"],
            },
        ),
        types.Tool(
            name="stats",
            description=(
                "各層語料統計：索引名稱清單，以及每一層的 bundle 數、concept 數、"
                "type 分佈、詞彙量、實體覆蓋率、可用模式。\n\n"
                "**先呼叫這個**來知道有哪些層、各層叫什麼名字，再決定要不要對 search "
                "指定 index。也含 taxonomy 覆蓋率（有多少 defect 已經整理過判斷方法）。"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


def _indexes(rt: Runtime) -> dict[str, Index]:
    return {name: s.index for name, s in rt.layered.searchers.items()}


def _owning(rt: Runtime, concept_id: str) -> Index:
    """哪一層持有這個 concept。agent 不必記得它從哪一層來。

    各層語料應該互斥；真的重複時取宣告順序的第一層，答案至少是穩定的。
    重複量由 `stats` 的 `id_overlap` 揭露。
    """
    owner = rt.layered.owner_of(concept_id)
    if owner is None:
        raise ConceptNotFound(concept_id)
    return _indexes(rt)[owner]


def _dispatch(rt: Runtime, name: str, args: dict[str, Any]) -> Any:
    if name == "search":
        outcome = rt.layered.search(
            args["query"],
            index=args.get("index"),
            mode=args.get("mode"),
            k=args.get("k"),
            fuse=bool(args.get("fuse", False)),
        )
        query_id = rt.store.log_layered(outcome, requested_index=args.get("index"))
        payload: dict[str, Any] = {
            "query_id": query_id,
            "shape": outcome.shape,
            "layers": [
                {
                    "index": lr.index,
                    "mode": lr.mode,
                    "candidates": lr.candidates,
                    "prepared_query": lr.prepared_query,
                    "hits": [h.to_dict() for h in lr.hits],
                }
                for lr in outcome.layers
            ],
            "note": (
                "這是分層摘要清單，不含內容。空的層代表那一類知識裡沒有對應的東西，"
                "那本身是資訊。要讀內容請以 concept_id 呼叫 get_concepts。"
            ),
        }
        if outcome.fused is not None:
            payload["fused"] = [fh.to_dict() for fh in outcome.fused]
        return payload

    if name == "get_concept":
        return load_concept(_owning(rt, args["concept_id"]), args["concept_id"])

    if name == "get_concepts":
        ids = list(args["concept_ids"])
        if not ids:
            raise ValueError("concept_ids must not be empty")
        if len(ids) > MAX_BATCH:
            raise ValueError(f"最多 {MAX_BATCH} 筆，收到 {len(ids)} 筆")
        # 先歸屬再逐層取。不先歸屬的話，跨層重複的 id 會被每一層各取一次，
        # 回傳的清單裡就會有重複條目，而 agent 會把它當成兩份不同的證據。
        by_layer: dict[str, list[str]] = {}
        missing: list[str] = []
        for cid in dict.fromkeys(ids):  # 去重但保序
            owner = rt.layered.owner_of(cid)
            if owner is None:
                missing.append(cid)
            else:
                by_layer.setdefault(owner, []).append(cid)
        found: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = [
            {"concept_id": cid, "reason": "not_found", "detail": "不在任何已載入的索引中"}
            for cid in missing
        ]
        for iname, mine in by_layer.items():
            got, errs = load_concepts(
                _indexes(rt)[iname], mine, include_raw=args.get("include_raw", True)
            )
            found.extend(got)
            errors.extend(errs)
        return {"requested": len(ids), "returned": len(found), "concepts": found, "errors": errors}

    if name == "neighbors":
        # 關聯邊不跨索引解析，所以展開只在持有它的那一層之內。
        return neighbors(
            _owning(rt, args["concept_id"]),
            args["concept_id"],
            depth=args.get("depth", 1),
            direction=args.get("direction", "both"),
        )

    if name == "grep":
        bundle_ids = list(args.get("bundle_ids") or [])
        concept_ids = list(args.get("concept_ids") or [])
        owners = {
            iname: index
            for iname, index in _indexes(rt).items()
            if any(index.has(c) for c in concept_ids) or any(b in index.bundle_roots for b in bundle_ids)
        }
        if len(owners) > 1:
            raise ValueError(
                f"範圍跨越多個索引（{sorted(owners)}）；請分別搜尋，"
                f"跨索引的結果來自兩份不同的語料，無法合併解讀"
            )
        # 沒有比對到任何索引時交給 grep 自己報錯——它區分得出
        # 「沒給範圍」與「範圍不存在」，那兩種錯誤的處置不同。
        target = next(iter(owners.values()), next(iter(_indexes(rt).values())))
        return grep(
            target,
            args["pattern"],
            bundle_ids=bundle_ids or None,
            concept_ids=concept_ids or None,
            regex=args.get("regex", False),
            ignore_case=args.get("ignore_case", False),
            max_results=args.get("max_results", DEFAULT_MAX_RESULTS),
        )

    if name == "taxonomy":
        try:
            return rt.taxonomy.get(args["defect"]).to_dict()
        except TaxonomyNotFound:
            return {
                "error": "no_entry",
                "defect": args["defect"],
                "detail": (
                    "taxonomy 沒有這個 defect 的條目。這裡刻意不回傳最接近的一筆——"
                    "拿另一個 defect 的判斷方法去解讀影像，比沒有方法更糟。"
                    "請據實說明尚無既定判準，不要自行編一套。"
                ),
            }

    if name == "stats":
        per_index = {}
        for iname, index in sorted(_indexes(rt).items()):
            s = index.stats
            spec = rt.config.index_spec(iname)
            per_index[iname] = {
                # 這一層裝什麼、什麼時候該用它。空字串表示設定裡沒寫。
                "description": spec.description,
                "when_to_use": spec.when_to_use,
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
                "available_modes": list(rt.layered.searchers[iname].available_modes),
            }
        return {
            "indexes": sorted(per_index),
            "by_index": per_index,
            "taxonomy": rt.taxonomy.coverage(),
            "id_overlap": rt.layered.id_overlap.to_dict(),
            # 沒寫說明的層，agent 只能從名字猜——讓它知道自己在猜
            "indexes_without_description": rt.config.undescribed_indexes(),
        }

    raise ValueError(f"unknown tool: {name}")


def build_server(rt: Runtime) -> Server:
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _tools(rt)

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
