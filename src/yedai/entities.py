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

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .tokenizer import (
    CJK,
    HIERARCHY_SEP,
    Tokenizer,
    language_segments,
    normalise_identifier,
)

UNKNOWN_TYPE = "unknown"

#: `id_only` 來源中含層級分隔符的列，歸入這個類型。
#: 這是資料本身的性質（機台與腔體同表、以 `#` 區分），不是使用者偏好，
#: 所以給預設值而非強迫每份設定重寫一次；需要時仍可在來源宣告中覆寫。
DEFAULT_CHILD_TYPE = "chamber_id"

CSV_SCHEMAS: tuple[str, ...] = ("id_only", "module_code_name")

#: 選填標頭的辨識字。CSV 由 MES 匯出，有沒有標頭列不固定。
_ID_ONLY_HEADERS = {"id", "tool", "tool_id", "equipment", "equipment_id", "eqp", "eqp_id", "chamber"}
_CODE_HEADERS = {"defect code", "defect_code", "code"}

_HAS_CJK = re.compile(rf"[{CJK}]")
_HAS_LATIN = re.compile(r"[A-Za-z]")


class EntitySourceError(ValueError):
    """實體來源檔的格式錯誤。訊息必須帶檔名與列號——靜默略過畸形列會產出看似正常的錯字典。"""


def _mixed_segments(name: str) -> list[str]:
    """同時含中日韓與拉丁字元時，回傳各語言區塊；否則回傳空清單。

    只在混合時才分段：純中文或純英文的別名分段後等於自己，多註冊沒有意義。
    """
    if not (_HAS_CJK.search(name) and _HAS_LATIN.search(name)):
        return []
    return [seg for seg in language_segments(name) if seg != name]


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
    def load(
        cls, path: str | Path | None, sources: list[dict[str, Any]] | None = None
    ) -> EntityDictionary:
        d = cls()
        if path:
            d._load_yaml(Path(path))
        for src in sources or []:
            d._load_source(src)
        return d

    @classmethod
    def from_config(cls, cfg: Any) -> EntityDictionary:
        """由設定載入 YAML 與所有 CSV 來源。生產路徑一律走這裡。

        分成兩個入口的話，總有一條路徑會忘記載入 CSV，而症狀是「字典有些條目查不到」
        ——那極難對應回成因。
        """
        return cls.load(getattr(cfg, "dictionary_path", None), getattr(cfg, "entity_sources", None))

    # ---- 來源 ----

    def _load_yaml(self, p: Path) -> None:
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
                self.add(str(etype), canonical, [str(n) for n in names])

    def _load_source(self, src: dict[str, Any]) -> None:
        schema = str(src.get("schema") or "")
        etype = str(src.get("type") or "")
        raw_path = src.get("path")
        if schema not in CSV_SCHEMAS:
            raise EntitySourceError(
                f"未知的 entity source schema: {schema!r}；支援的有 {list(CSV_SCHEMAS)}"
            )
        if not etype:
            raise EntitySourceError(f"entity source 缺少 type：{src!r}")
        if not raw_path:
            raise EntitySourceError(f"entity source 缺少 path：{src!r}")
        p = Path(str(raw_path))
        if not p.exists():
            raise FileNotFoundError(f"entity source not found: {p}")
        if schema == "id_only":
            self._load_id_only(p, etype, str(src.get("child_type") or DEFAULT_CHILD_TYPE))
        else:
            self._load_module_code_name(p, etype)

    def _load_id_only(self, p: Path, etype: str, child_type: str) -> None:
        """單欄識別碼。含 `#` 者為子層實體（機台與腔體同表，以分隔符區分）。"""
        for lineno, row in self._rows(p):
            if len(row) != 1:
                raise EntitySourceError(f"{p}:{lineno} id_only 須為單欄，實得 {len(row)} 欄")
            value = row[0].strip()
            if not value:
                continue
            if lineno == 1 and value.lower() in _ID_ONLY_HEADERS:
                continue
            this_type = child_type if HIERARCHY_SEP in value else etype
            self.add(this_type, normalise_identifier(value), [value])

    def _load_module_code_name(self, p: Path, etype: str) -> None:
        """三欄 `Module, defect code, defect name`。

        `Module` 是中繼資料：code 全域唯一，把 Module 併進識別會讓同一個缺陷分裂成多個實體。
        `name` 是別名——「微粒」「刮傷」這類一般詞沒有結構可讓正則辨識，只有字典能對到 code。
        """
        for lineno, row in self._rows(p):
            if len(row) != 3:
                raise EntitySourceError(
                    f"{p}:{lineno} module_code_name 須為三欄（Module, defect code, defect name），"
                    f"實得 {len(row)} 欄"
                )
            _module, code, name = (c.strip() for c in row)
            if not code:
                continue
            if lineno == 1 and code.lower() in _CODE_HEADERS:
                continue
            names = [code] + ([name] if name else [])
            self.add(etype, code, names)

    @staticmethod
    def _rows(p: Path):
        with p.open(encoding="utf-8-sig", newline="") as fh:
            for lineno, row in enumerate(csv.reader(fh), start=1):
                if not row or all(not c.strip() for c in row):
                    continue
                yield lineno, row

    # ---- 註冊 ----

    def add(self, etype: str, canonical: str, names: list[str]) -> None:
        self.types.add(etype)
        for name in names:
            name = name.strip()
            if not name:
                continue
            self._register(etype, canonical, name)
            # 同格中英混合（`Particle 微粒`）時，使用者可能只打其中一種語言。
            # 兩種都註冊就不必事先知道來源是哪種混合形式。
            for seg in _mixed_segments(name):
                self._register(etype, canonical, seg)

    def _register(self, etype: str, canonical: str, name: str) -> None:
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

        for hit in self.tok.find_identifiers(text):
            norm = hit.normalised
            found = self.dict.lookup_normalised(norm)
            if found:
                # 字典優先於形狀：字典是人維護的，形狀是從樣式推的。
                etype, canonical = found
                src = "dict"
            else:
                # 形狀能決定類型時就用它——否則這個實體會掉進 `unknown`，
                # 而該類型的覆蓋率分母就只剩字典自己，比例恆為 1.0，看不見缺口。
                etype, canonical, src = hit.type or UNKNOWN_TYPE, norm, "regex"
            if (etype, canonical) in seen:
                continue
            seen.add((etype, canonical))
            hits.append(EntityHit(etype, canonical, hit.raw, src))

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
