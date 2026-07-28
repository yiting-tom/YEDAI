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

#: 判定。四種，而不是三種——因為「沒被圈成識別碼」和「被切碎」的後果差很多。
#:
#: full    整段被圈成單一識別碼
#: intact  沒被圈成識別碼，但斷詞後仍是**單一完整詞元**（`A16` → `a16`）。
#:         模式 B 相對模式 A 仍有鑑別力（A 會切成 `a` + `16`），檢索不受損；
#:         代價只是它不會進入實體空間——若該類型有字典，字典的字面掃描會補上。
#: partial 有比對命中但沒蓋滿整個樣本。**最危險的一種**：正則從中間咬進去，
#:         會憑空產生一個錯的識別碼（`10234.000` → `1` + `ID:0234.000`）。
#: none    沒被圈起來，斷詞後也碎了。
#:
#: 把 intact 和 partial 混為一談會讓這個工具喊太多狼——真正該修的那個就被淹掉了。
FULL = "full"
INTACT = "intact"
PARTIAL = "partial"
NONE = "none"

#: 視為通過的判定。intact 通過但會被提示。
PASSING = (FULL, INTACT)


@dataclass(frozen=True)
class SampleResult:
    type: str
    sample: str
    verdict: str
    tokens: list[str]

    @property
    def ok(self) -> bool:
        return self.verdict in PASSING


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
    def intact_only(self) -> list[SampleResult]:
        """通過，但不會進入實體空間——該類型若沒有字典，模式 C 就看不到它們。"""
        return [r for r in self.results if r.verdict == INTACT]

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
    if spans:
        if len(spans) == 1 and spans[0] == (0, len(sample)):
            return SampleResult("", sample, FULL, tokens)
        # 命中了但沒蓋滿：正則從中間咬進去，產出的識別碼是錯的
        return SampleResult("", sample, PARTIAL, tokens)
    # 沒被圈成識別碼。碎了才算失敗——完整的單一詞元在檢索上仍與模式 A 有區別。
    verdict = INTACT if len(tokens) == 1 else NONE
    return SampleResult("", sample, verdict, tokens)


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
