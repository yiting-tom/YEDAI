"""實體字典：載入、正規化、抽取。

字典格式（YAML）——只放你願意放的部分，缺的靠 regex fallback 補：

    tool_id:
      - canonical: TEL-05
        aliases: [TEL05, "TEL 05", 五號機]
      - canonical: XTR-12
    defect_code:
      - canonical: PARTICLE
        aliases: [particle, 微粒, 顆粒]

抽取結果分兩種來源：
  dict   — 命中字典，有 type 與 canonical
  regex  — 沒命中字典但長得像識別碼，type = "unknown"
regex 這條是刻意保留的：它會告訴你字典的覆蓋率缺口有多大（報告裡會統計）。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from .tokenizer import Tokenizer, normalise_identifier

UNKNOWN_TYPE = "unknown"


@dataclass(frozen=True)
class EntityHit:
    type: str
    canonical: str
    raw: str
    source: str  # "dict" | "regex"

    @property
    def key(self) -> str:
        return f"{self.type}:{self.canonical}"


class EntityDictionary:
    def __init__(self) -> None:
        # 正規化後的 alias → (type, canonical)
        self._alias: dict[str, tuple[str, str]] = {}
        # 含中文/空白的 alias 需要用字面掃描，另存一份
        self._literal: dict[str, tuple[str, str]] = {}
        self.types: set[str] = set()
        self._max_literal_len = 0

    @classmethod
    def load(cls, path: str | Path | None) -> EntityDictionary:
        d = cls()
        if not path:
            return d
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"entity dictionary not found: {p}")
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for etype, entries in raw.items():
            for entry in entries or []:
                if isinstance(entry, str):
                    entry = {"canonical": entry}
                canonical = str(entry.get("canonical") or "").strip()
                if not canonical:
                    continue
                names = [canonical, *(entry.get("aliases") or [])]
                d.add(str(etype), canonical, [str(n) for n in names])
        return d

    def add(self, etype: str, canonical: str, names: list[str]) -> None:
        self.types.add(etype)
        for name in names:
            name = name.strip()
            if not name:
                continue
            self._alias[normalise_identifier(name)] = (etype, canonical)
            self._literal[name.lower()] = (etype, canonical)
            self._max_literal_len = max(self._max_literal_len, len(name))

    def __len__(self) -> int:
        return len({v for v in self._alias.values()})

    def fingerprint(self) -> str:
        """字典內容的指紋，納入索引簽章——換字典必須讓快取失效。"""
        import hashlib

        blob = "\n".join(f"{k}\t{v[0]}\t{v[1]}" for k, v in sorted(self._alias.items()))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def lookup_normalised(self, norm: str) -> tuple[str, str] | None:
        return self._alias.get(norm)

    def literal_scan(self, text: str) -> list[tuple[str, str, str]]:
        """對含中文/空白的 alias 做最長優先掃描。回傳 (raw, type, canonical)。"""
        if not self._literal:
            return []
        low = text.lower()
        hits: list[tuple[str, str, str]] = []
        i = 0
        n = len(low)
        while i < n:
            matched = False
            upper = min(self._max_literal_len, n - i)
            for length in range(upper, 0, -1):
                found = self._literal.get(low[i : i + length])
                if found:
                    hits.append((text[i : i + length], found[0], found[1]))
                    i += length
                    matched = True
                    break
            if not matched:
                i += 1
        return hits


class EntityExtractor:
    def __init__(self, dictionary: EntityDictionary, tokenizer: Tokenizer) -> None:
        self.dict = dictionary
        self.tok = tokenizer

    def extract(self, text: str) -> list[EntityHit]:
        hits: list[EntityHit] = []
        seen: set[tuple[str, str]] = set()

        for raw, norm, _s, _e in self.tok.find_identifiers(text):
            found = self.dict.lookup_normalised(norm)
            if found:
                etype, canonical = found
                src = "dict"
            else:
                etype, canonical, src = UNKNOWN_TYPE, norm, "regex"
            if (etype, canonical) in seen:
                continue
            seen.add((etype, canonical))
            hits.append(EntityHit(etype, canonical, raw, src))

        for raw, etype, canonical in self.dict.literal_scan(text):
            if (etype, canonical) in seen:
                continue
            seen.add((etype, canonical))
            hits.append(EntityHit(etype, canonical, raw, "dict"))

        return hits

    def extract_weighted(self, fields: dict[str, str], weights: dict[str, float]) -> dict[str, float]:
        """對 concept 的各欄位抽實體，回傳 key → 位置加權後的權重（取各欄位最大值）。"""
        out: dict[str, float] = defaultdict(float)
        for fname, text in fields.items():
            w = weights.get(fname, 1.0)
            for hit in self.extract(text):
                out[hit.key] = max(out[hit.key], w)
        return dict(out)


_QUOTED = re.compile(r"[\"'「『]([^\"'」』]{2,})[\"'」』]")


def query_literals(query: str) -> list[str]:
    """使用者用引號框起來的字串視為必須精確出現的字面詞。"""
    return [m.group(1).strip() for m in _QUOTED.finditer(query or "") if m.group(1).strip()]
