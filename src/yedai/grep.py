"""限定範圍的字面／正則搜尋。

這是整個設計的收斂點：**用檢索把 N 個 bundle 縮到 2~3 個，然後在那個縮小的
範圍裡跑原本就有效的 agentic file search。** 前半段由 search 完成，這裡是後半段。

因此範圍是**必填**，而不是選填的效能保護。允許無範圍搜尋等於留一條繞過檢索層的
退路——agent 會用它，然後我們回到「grep 整個語料、拿回三百條命中、無從分流」的原點。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .fulltext import resolve_path
from .index import Index

DEFAULT_MAX_RESULTS = 100
MAX_MAX_RESULTS = 1000


class ScopeRequired(ValueError):
    """未指定任何 bundle 或 concept 範圍。"""


class UnknownScope(KeyError):
    """指定的 bundle 或 concept 不在索引中。"""


class InvalidPattern(ValueError):
    """正則無法編譯。"""


def grep(
    index: Index,
    pattern: str,
    bundle_ids: Iterable[str] | None = None,
    concept_ids: Iterable[str] | None = None,
    regex: bool = False,
    ignore_case: bool = False,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> dict[str, Any]:
    bundles = list(dict.fromkeys(bundle_ids or []))
    concepts = list(dict.fromkeys(concept_ids or []))

    if not pattern:
        raise ValueError("pattern must not be empty")
    if not bundles and not concepts:
        raise ScopeRequired(
            "grep 必須限定範圍：請提供 bundle_ids 或 concept_ids。"
            "範圍應取自 search 結果中的 bundle_id——先用 search 把語料縮小，再在範圍內搜尋。"
        )

    unknown_bundles = [b for b in bundles if b not in index.bundle_roots]
    if unknown_bundles:
        raise UnknownScope(f"未知的 bundle_id: {', '.join(unknown_bundles)}")
    unknown_concepts = [c for c in concepts if not index.has(c)]
    if unknown_concepts:
        raise UnknownScope(f"未知的 concept_id: {', '.join(unknown_concepts)}")

    max_results = max(1, min(int(max_results), MAX_MAX_RESULTS))
    matcher = _matcher(pattern, regex, ignore_case)

    targets = list(concepts)
    if bundles:
        wanted = set(bundles)
        targets += [d.concept_id for d in index.docs if d.bundle_id in wanted]
    targets = list(dict.fromkeys(targets))

    results: list[dict[str, Any]] = []
    searched = skipped = 0
    truncated = False

    for concept_id in targets:
        if len(results) >= max_results:
            truncated = True
            break
        try:
            meta, path = resolve_path(index, concept_id)
            text = path.read_text(encoding="utf-8")
        except (OSError, KeyError, PermissionError):
            # 檔案已移除或路徑異常：略過並繼續，不讓單一壞檔中斷整批
            skipped += 1
            continue
        searched += 1

        for lineno, line in enumerate(text.splitlines(), start=1):
            if not matcher(line):
                continue
            if len(results) >= max_results:
                truncated = True
                break
            results.append(
                {
                    "concept_id": meta.concept_id,
                    "bundle_id": meta.bundle_id,
                    "type": meta.type,
                    "title": meta.title,
                    "path": meta.path,
                    "line": lineno,
                    "text": line.rstrip(),
                }
            )

    return {
        "pattern": pattern,
        "regex": regex,
        "ignore_case": ignore_case,
        "scope": {"bundle_ids": bundles, "concept_ids": concepts},
        "files_searched": searched,
        "files_skipped": skipped,
        "max_results": max_results,
        "truncated": truncated,
        "results": results,
    }


def _matcher(pattern: str, regex: bool, ignore_case: bool):
    """預設字面比對。正則需明確開啟——使用者提供的正則可能觸發災難性回溯，
    而 Python 的 re 沒有執行時間上限。"""
    if regex:
        try:
            compiled = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as exc:
            raise InvalidPattern(f"無效的正則樣式：{exc}") from exc
        return lambda line: compiled.search(line) is not None

    if ignore_case:
        needle = pattern.casefold()
        return lambda line: needle in line.casefold()
    return lambda line: pattern in line
