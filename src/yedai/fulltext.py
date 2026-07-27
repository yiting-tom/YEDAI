"""依 concept id 取回完整內容。

全文**於請求時從磁碟讀取**，不存進索引。理由：

- 220 萬個 concept × 300 行 ≈ 30–40 GB，塞進 pickle 會讓索引無法載入
- 檔案是唯一真相，改一個 `.md` 立即反映，不必重建索引
- 單檔讀取在任何規模下都可忽略

本模組只依賴 `Index` 與 `parser`，不依賴 FastAPI——HTTP、CLI 與後續的 MCP server
都直接重用同一份實作，不會出現三套行為略有差異的取全文邏輯。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .index import DocMeta, Index
from .parser import parse_concept, split_frontmatter

#: 批次上限。超過這個量代表 agent 該先縮範圍，而不是把整個 bundle 拉進 context。
MAX_BATCH = 50


class ConceptNotFound(KeyError):
    """concept_id 不在索引中——打錯 id，或屬於另一份語料。"""


class ConceptFileMissing(FileNotFoundError):
    """id 在索引中但檔案已不在磁碟上——語料在建索引後變動過，需重建索引。

    刻意與 ConceptNotFound 分開：兩者需要的處置完全不同。
    """


class ConceptPathEscape(PermissionError):
    """解析後的路徑落在 bundle 根目錄之外。索引被竄改或人工編輯出錯時的防線。"""


def resolve_path(index: Index, concept_id: str) -> tuple[DocMeta, Path]:
    meta = index.doc_of(concept_id)
    if meta is None:
        raise ConceptNotFound(concept_id)

    root_raw = index.bundle_roots.get(meta.bundle_id)
    if root_raw is None:
        raise ConceptFileMissing(
            f"索引中沒有 bundle {meta.bundle_id!r} 的根目錄登錄——請重建索引"
        )

    root = Path(root_raw).resolve()
    path = (root / meta.path).resolve()
    if not path.is_relative_to(root):
        raise ConceptPathEscape(f"{concept_id!r} 的路徑逸出 bundle 根目錄：{meta.path!r}")
    return meta, path


def load_concept(index: Index, concept_id: str) -> dict[str, Any]:
    """回傳單一 concept 的完整內容。

    同時給出 `raw`（原始全文，agent 直接餵進 context）與解析後的
    `frontmatter` / `sections`（程式化消費者用）。兩者內容有重疊是刻意的——
    在單一 concept 的尺度上，重複一份遠比逼每個呼叫端各自實作解析便宜。
    """
    meta, path = resolve_path(index, concept_id)
    if not path.is_file():
        raise ConceptFileMissing(
            f"{concept_id!r} 的檔案已不存在：{meta.path!r} — 語料在建索引後變動過，請重建索引"
        )

    raw = path.read_text(encoding="utf-8")
    root = Path(index.bundle_roots[meta.bundle_id]).resolve()

    # 重用建索引時的同一條解析路徑，確保「檢索看到的結構」與「取全文看到的結構」一致
    concept = parse_concept(path, meta.bundle_id, root, text=raw)
    frontmatter, _body = split_frontmatter(raw)

    return {
        "concept_id": concept.concept_id,
        "bundle_id": concept.bundle_id,
        "type": concept.type,
        "title": concept.title,
        "slug": concept.slug,
        "description": concept.description,
        "path": concept.path,
        "index_line": concept.index_line(),
        "confidence": concept.confidence,
        "timestamp": concept.timestamp,
        "resource": concept.resource,
        "provenance": concept.provenance,
        "subpath": concept.subpath,
        "content_hash": concept.content_hash,
        "model": concept.model,
        "generated": concept.generated,
        "tags": list(concept.tags),
        "related": list(concept.related),
        "assets": list(concept.assets),
        "figures": [
            {
                "file_id": f.file_id,
                "type": f.type,
                "title": f.title,
                "description": f.description,
                "key_points": list(f.key_points),
            }
            for f in concept.figures
        ],
        "sections": [
            {"index": s.index, "heading": s.heading, "text": s.text} for s in concept.sections
        ],
        "frontmatter": frontmatter,
        "raw": raw,
    }


def load_concepts(
    index: Index,
    concept_ids: Iterable[str],
    include_raw: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """批次取回，**部分成功**語意。

    單一 id 失敗就讓整批失敗，會逼 agent 退回逐筆呼叫，等於白做這個介面。
    錯誤原因區分 not_found（id 打錯）與 file_missing（索引過期）——
    兩者需要的處置完全不同。
    """
    concepts: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for concept_id in concept_ids:
        try:
            data = load_concept(index, concept_id)
        except ConceptNotFound:
            errors.append(
                {"concept_id": concept_id, "reason": "not_found", "detail": "索引中查無此 concept_id"}
            )
            continue
        except ConceptFileMissing as exc:
            errors.append({"concept_id": concept_id, "reason": "file_missing", "detail": str(exc)})
            continue
        except ConceptPathEscape as exc:
            errors.append({"concept_id": concept_id, "reason": "path_escape", "detail": str(exc)})
            continue
        if not include_raw:
            data.pop("raw", None)
        concepts.append(data)

    return concepts, errors
