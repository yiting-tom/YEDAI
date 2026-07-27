"""OKF 資料模型。欄位對齊使用者提供的 bundle 格式，未知欄位一律保留在 extra。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Figure:
    file_id: str = ""
    type: str = ""
    title: str = ""
    description: str = ""
    key_points: list[str] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Any) -> Figure:
        if not isinstance(raw, dict):
            return cls(description=str(raw))
        kp = raw.get("key_points") or []
        if isinstance(kp, str):
            kp = [kp]
        return cls(
            file_id=str(raw.get("file_id") or ""),
            type=str(raw.get("type") or ""),
            title=str(raw.get("title") or ""),
            description=str(raw.get("description") or ""),
            key_points=[str(x) for x in kp],
        )

    def text(self) -> str:
        return " ".join([self.title, self.description, *self.key_points]).strip()


@dataclass
class Section:
    """concept body 的一個 `## ` 區段。heading 之後會用來做 role 正規化。"""

    heading: str
    text: str
    index: int = 0


@dataclass
class Concept:
    concept_id: str
    bundle_id: str
    path: str
    type: str = ""
    title: str = ""
    slug: str = ""
    description: str = ""
    confidence: str = ""
    timestamp: str = ""
    resource: str = ""
    provenance: str = ""
    subpath: str = ""
    content_hash: str = ""
    model: str = ""
    generated: bool | None = None
    tags: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    body: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    # ---- 檢索欄位（BM25F 的 field 切分就從這裡來）----

    def field_texts(self) -> dict[str, str]:
        headings = " ".join(s.heading for s in self.sections)
        figures = " ".join(f.text() for f in self.figures)
        return {
            "title": self.title,
            "description": self.description,
            "tags": " ".join(self.tags),
            "headings": headings,
            "figures": figures,
            "body": self.body,
        }

    def index_line(self) -> str:
        """回傳與 bundle 內 index.md 相同的一行格式，讓 agent 的既有讀法可以直接沿用。"""
        fname = Path(self.path).name
        return f"{self.concept_id} . {self.type} . [{fname}]({self.path}) . {self.description}"


@dataclass
class BundleDoc:
    """bundle 內的 summary.md（也支援 log.md / index.md，但那兩個不進檢索）。"""

    bundle_id: str
    doc_id: str = ""
    type: str = ""
    title: str = ""
    description: str = ""
    body: str = ""
    related: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Bundle:
    bundle_id: str
    root: str
    manifest: dict[str, Any] = field(default_factory=dict)
    summary: BundleDoc | None = None
    concepts: list[Concept] = field(default_factory=list)
