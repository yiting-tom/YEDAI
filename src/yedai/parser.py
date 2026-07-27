"""解析 OKF bundle 目錄。

預期結構：

    <bundle-name>/
      manifest.json
      okf/
        _assets/...
        summary.md
        log.md
        index.md
        <concept>.md ...

解析刻意寬鬆：frontmatter 缺欄位、缺 `---` 分隔線（使用者的 summary.md 範例即如此）、
manifest 缺失，都不應該讓整個 bundle 掛掉——實務上一定會遇到不合格的檔案，
demo 階段要能跑完並回報有幾份壞掉，而不是中途爆炸。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Bundle, BundleDoc, Concept, Figure, Section

RESERVED = {"summary.md", "log.md", "index.md"}
_FM_DELIMITED = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
_H2 = re.compile(r"^##\s+(.*)$", re.M)


@dataclass
class ParseReport:
    bundles: int = 0
    concepts: int = 0
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """支援兩種寫法：標準 `---` 包夾，以及沒有分隔線、frontmatter 直接接 `##` 的變體。"""
    m = _FM_DELIMITED.match(text)
    if m:
        return _safe_yaml(m.group(1)), m.group(2)

    # 無分隔線：抓第一個 markdown 標題之前的內容當 YAML
    lines = text.splitlines()
    cut = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("#")), None)
    if cut is None or cut == 0:
        return {}, text
    fm = _safe_yaml("\n".join(lines[:cut]))
    if not fm:
        return {}, text
    return fm, "\n".join(lines[cut:])


def _safe_yaml(blob: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(blob)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x).strip()]
    return [str(v)]


def parse_sections(body: str) -> list[Section]:
    matches = list(_H2.finditer(body))
    if not matches:
        return [Section(heading="", text=body.strip(), index=0)]
    out: list[Section] = []
    lead = body[: matches[0].start()].strip()
    if lead:
        out.append(Section(heading="", text=lead, index=0))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append(
            Section(heading=m.group(1).strip(), text=body[m.end() : end].strip(), index=len(out))
        )
    return out


KNOWN_FIELDS = {
    "id", "type", "title", "slug", "description", "generated", "content_hash",
    "confidence", "resource", "provenance", "tags", "related", "model",
    "timestamp", "assets", "subpath", "figures",
}


def parse_concept(path: Path, bundle_id: str, bundle_root: Path, text: str | None = None) -> Concept:
    """`text` 讓呼叫端把已讀入的檔案內容傳進來，避免同一個檔案被讀兩次。"""
    fm, body = split_frontmatter(path.read_text(encoding="utf-8") if text is None else text)
    rel = str(path.relative_to(bundle_root))
    cid = str(fm.get("id") or "").strip() or f"path:{rel}"
    return Concept(
        concept_id=cid,
        bundle_id=bundle_id,
        path=rel,
        type=str(fm.get("type") or ""),
        title=str(fm.get("title") or path.stem),
        slug=str(fm.get("slug") or ""),
        description=str(fm.get("description") or ""),
        confidence=str(fm.get("confidence") or ""),
        timestamp=str(fm.get("timestamp") or ""),
        resource=str(fm.get("resource") or ""),
        provenance=str(fm.get("provenance") or ""),
        subpath=str(fm.get("subpath") or ""),
        content_hash=str(fm.get("content_hash") or ""),
        model=str(fm.get("model") or ""),
        generated=fm.get("generated") if isinstance(fm.get("generated"), bool) else None,
        tags=_as_list(fm.get("tags")),
        related=_as_list(fm.get("related")),
        assets=_as_list(fm.get("assets")),
        figures=[Figure.from_raw(f) for f in (fm.get("figures") or [])],
        sections=parse_sections(body),
        body=body,
        extra={k: v for k, v in fm.items() if k not in KNOWN_FIELDS},
    )


def parse_bundle_doc(path: Path, bundle_id: str) -> BundleDoc:
    fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return BundleDoc(
        bundle_id=bundle_id,
        doc_id=str(fm.get("id") or ""),
        type=str(fm.get("type") or ""),
        title=str(fm.get("title") or ""),
        description=str(fm.get("description") or ""),
        body=body,
        related=_as_list(fm.get("related")),
        extra={k: v for k, v in fm.items() if k not in KNOWN_FIELDS},
    )


def _okf_dir(bundle_root: Path) -> Path | None:
    okf = bundle_root / "okf"
    if okf.is_dir():
        return okf
    # 容忍沒有 okf/ 這層、md 直接放在 bundle 根目錄的情況
    return bundle_root if any(bundle_root.glob("*.md")) else None


def parse_bundle(bundle_root: Path, report: ParseReport) -> Bundle | None:
    okf = _okf_dir(bundle_root)
    if okf is None:
        return None

    manifest: dict[str, Any] = {}
    mpath = bundle_root / "manifest.json"
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.warnings.append(f"{mpath}: manifest 解析失敗 ({exc})")

    bundle_id = str(manifest.get("id") or manifest.get("name") or bundle_root.name)
    bundle = Bundle(bundle_id=bundle_id, root=str(bundle_root), manifest=manifest)

    for md in sorted(okf.rglob("*.md")):
        if "_assets" in md.parts:
            continue
        try:
            if md.name in RESERVED:
                if md.name == "summary.md":
                    bundle.summary = parse_bundle_doc(md, bundle_id)
                continue
            bundle.concepts.append(parse_concept(md, bundle_id, bundle_root))
        except Exception as exc:  # 單一壞檔不該拖垮整批
            report.skipped.append(f"{md}: {type(exc).__name__}: {exc}")

    return bundle


def load_bundles(root: str | Path) -> tuple[list[Bundle], ParseReport]:
    root = Path(root).expanduser().resolve()
    report = ParseReport()
    if not root.is_dir():
        raise NotADirectoryError(f"bundle root not found: {root}")

    candidates = [p for p in sorted(root.iterdir()) if p.is_dir()]
    if not candidates and _okf_dir(root):
        candidates = [root]  # 直接指到單一 bundle

    bundles: list[Bundle] = []
    for cand in candidates:
        b = parse_bundle(cand, report)
        if b is None:
            continue
        bundles.append(b)
        report.bundles += 1
        report.concepts += len(b.concepts)
    return bundles, report
