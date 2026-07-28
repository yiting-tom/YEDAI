"""識別碼格式樣本：驗證樣式涵蓋得了真實形狀。

存在的理由：模式 B 與 C 的全部效果都建立在「識別碼被當成一個整體」之上，
但真實識別碼屬敏感資料、不能進版控，於是樣式從來沒有被真實形狀驗證過。
結果是合成語料產出的 id 剛好符合樣式，測試全綠，而樣式其實一條也沒對上真實形狀——
程式在跟自己對答案。

樣本檔留在使用者本機（gitignore），只有「涵蓋 / 未涵蓋」這個判定會被拿來把關。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .tokenizer import Tokenizer

#: 判定。`partial` 刻意與 `none` 分開——被切成兩段的識別碼看起來「有被抓到」，
#: 但那正是模式 B 失效的形式，比完全沒抓到更容易被忽略。
FULL = "full"
PARTIAL = "partial"
NONE = "none"


@dataclass(frozen=True)
class SampleResult:
    type: str
    sample: str
    verdict: str
    tokens: list[str]

    @property
    def ok(self) -> bool:
        return self.verdict == FULL


@dataclass
class CoverageReport:
    results: list[SampleResult]
    #: 設定裡宣告了、但一個樣本都沒有的類型。缺口要看得見才會被補。
    types_without_samples: list[str]
    configured: bool

    @property
    def failures(self) -> list[SampleResult]:
        return [r for r in self.results if not r.ok]

    @property
    def ok(self) -> bool:
        return not self.failures

    def by_type(self) -> dict[str, list[SampleResult]]:
        out: dict[str, list[SampleResult]] = {}
        for r in self.results:
            out.setdefault(r.type, []).append(r)
        return out


def load_samples(path: str | Path | None) -> dict[str, list[str]]:
    """載入 `類型 → 樣本清單`。未設定路徑回空 dict；設定了但檔案不存在則明確失敗。"""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"identifier samples not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"identifier samples must be a YAML mapping: {p}")
    out: dict[str, list[str]] = {}
    for etype, entries in raw.items():
        items = [str(e).strip() for e in (entries or []) if str(e).strip()]
        out[str(etype)] = items
    return out


def check_sample(tokenizer: Tokenizer, sample: str) -> SampleResult:
    """樣本是否被當成單一識別碼完整圈出。

    判定嚴格：命中超過一段、或命中範圍沒有蓋滿整個樣本，都算 partial。
    「圈到一半」與「切成兩段」在檢索上的後果相同——識別碼失去了鑑別力。
    """
    spans = tokenizer.find_identifier_spans(sample)
    tokens = tokenizer.protected(sample)
    if not spans:
        return SampleResult("", sample, NONE, tokens)
    if len(spans) == 1 and spans[0] == (0, len(sample)):
        return SampleResult("", sample, FULL, tokens)
    return SampleResult("", sample, PARTIAL, tokens)


def check_coverage(tokenizer: Tokenizer, samples: dict[str, list[str]]) -> CoverageReport:
    results: list[SampleResult] = []
    empty: list[str] = []
    for etype, items in sorted(samples.items()):
        if not items:
            empty.append(etype)
            continue
        for sample in items:
            r = check_sample(tokenizer, sample)
            results.append(SampleResult(etype, r.sample, r.verdict, r.tokens))
    return CoverageReport(results=results, types_without_samples=empty, configured=bool(samples))
