"""沿 `related` 展開 concept 關聯。

agent 目前在小規模語料上是靠 `related` 手動跳轉的——這個模組把那個行為變成
一次呼叫。同時提供**入向**（誰指向我），那是 agent 自己拼不出來、但排查時
最想知道的東西：「還有哪些文件引用了這個概念」。

深度上限 2。再深就是圖查詢，不是這個工具該做的事——以 YED 的查案場景來看，
2 跳已經涵蓋絕大多數關聯，而不設限會讓回應在高連通度的語料上爆掉。
"""

from __future__ import annotations

from typing import Any, Literal

from .fulltext import ConceptNotFound
from .index import Index

Direction = Literal["out", "in", "both"]
DIRECTIONS: tuple[str, ...] = ("out", "in", "both")
MAX_DEPTH = 2


def neighbors(
    index: Index,
    concept_id: str,
    depth: int = 1,
    direction: str = "both",
) -> dict[str, Any]:
    if not index.has(concept_id):
        raise ConceptNotFound(concept_id)
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction: {direction!r} (expected one of {', '.join(DIRECTIONS)})")
    if not 1 <= depth <= MAX_DEPTH:
        raise ValueError(f"depth must be between 1 and {MAX_DEPTH}, got {depth}")

    seen = {concept_id}
    frontier = [concept_id]
    found: list[dict[str, Any]] = []

    for hop in range(1, depth + 1):
        nxt: list[str] = []
        for current in frontier:
            for target, edge in _edges(index, current, direction):
                if target in seen:
                    continue
                seen.add(target)
                nxt.append(target)
                meta = index.doc_of(target)
                if meta is None:  # 理論上不會發生：edges 只回傳已解析的目標
                    continue
                found.append(
                    {
                        "concept_id": meta.concept_id,
                        "bundle_id": meta.bundle_id,
                        "type": meta.type,
                        "title": meta.title,
                        "description": meta.description,
                        "path": meta.path,
                        "index_line": meta.index_line(),
                        "depth": hop,
                        "direction": edge,
                        "via": current,
                    }
                )
        frontier = nxt
        if not frontier:
            break

    return {
        "concept_id": concept_id,
        "depth": depth,
        "direction": direction,
        "neighbors": found,
        # 懸空引用單獨列出：模型產出的 related 指向不存在的 id 是常見的品質問題，
        # 混進正常清單會讓 agent 以為那些 concept 存在。
        "dangling": list(index.dangling.get(concept_id, [])),
    }


def _edges(index: Index, concept_id: str, direction: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if direction in ("out", "both"):
        out += [(t, "out") for t in index.related_out.get(concept_id, [])]
    if direction in ("in", "both"):
        out += [(t, "in") for t in index.related_in.get(concept_id, [])]
    return out
