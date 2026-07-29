"""從真實語料取樣產生查詢清單，供 `mode_overlap` 使用。

自己產查詢有一個明顯的失敗方式：憑空編，等於自己選了決定答案的那個變因。
A/B/C 的分野幾乎完全由「查詢裡有沒有識別碼、是哪一種」決定；D/E 的分野則由
「有沒有無識別碼的自然語查詢」決定。編出來的分佈會直接決定結論。

所以這裡只造**句型**。識別碼、別名、描述詞全部從索引與字典取樣，
識別碼的分佈因此是語料的真實分佈，而不是想像。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable

from .entities import EntityDictionary, EntityExtractor
from .index import Index
from .tokenizer import Tokenizer

#: 各組成的比例。**這是一個沒有根據的假設**，所以它是參數而非常數，
#: 而且會被寫進產出檔的檔頭——使用者換一組重跑就能看出結論對它有多敏感。
DEFAULT_MIX: dict[str, float] = {
    "bare_identifier": 0.30,  # 「AEPOL1#2」——模式 A 該輸的那一組
    "identifier_context": 0.20,  # 「AEPOL1 微粒異常」
    "two_identifiers": 0.15,  # 「AEPOL1 AB1234.01」
    "alias": 0.15,  # 「五號機 微粒」——只有字典認得，模式 C 該贏的那一組
    "descriptive": 0.20,  # 「蝕刻後圖案倒塌」——關鍵字腿該落空、模式 D 該贏的那一組
}

#: 識別碼加上下文時的句型。只有這裡是造的。
_CONTEXT_TEMPLATES = ("{id} {term}", "{term} {id}", "{id} 的 {term}")


@dataclass
class QuerySet:
    queries: list[str] = field(default_factory=list)
    #: 組成名稱 → 實際產出筆數。與請求的比例可能不同（某組素材不足時）。
    composition: dict[str, int] = field(default_factory=dict)
    #: 素材不足而少產的組成，附原因。缺口要看得見，不能靜靜補到別組去。
    shortfalls: dict[str, str] = field(default_factory=dict)
    #: 各組的**素材**有幾種（不是產出幾條）。素材種類太少時該組會反覆抽到同幾條，
    #: 那組的重疊度就變成一兩個樣本的性質而不是統計量——使用者必須看得到這件事。
    pool_sizes: dict[str, int] = field(default_factory=dict)


def _weighted_sample(rng: random.Random, items: list[str], weights: list[float], n: int) -> list[str]:
    """依權重取樣（可重複）。常見的識別碼比罕見的更常被查——
    均勻取樣會系統性高估罕見識別碼的影響。"""
    if not items or n <= 0:
        return []
    return rng.choices(items, weights=weights, k=n)


def _strip_entities(text: str, extractor: EntityExtractor) -> str:
    """把**所有**實體從文字中挖掉：正則識別碼與字典實體都要。

    描述性查詢必須完全不含實體，否則那一組就測不到它要測的東西——
    該組存在的理由是「關鍵字腿會落空」，夾帶一個識別碼就會命中；
    夾帶一個字典認得的缺陷名，模式 C 更會靠實體腿直接贏，
    於是「稠密腿有沒有用」變成無法回答。

    只挖正則識別碼是不夠的：缺陷名沒有識別碼形狀，只有字典認得它。
    """
    spans = list(extractor.tok.find_identifier_spans(text))
    lowered = text.lower()
    for raw, _etype, _canonical in extractor.dict.literal_scan(text):
        start = lowered.find(raw.lower())
        if start >= 0:
            spans.append((start, start + len(raw)))
    if not spans:
        return " ".join(text.split())

    keep, cursor = [], 0
    for start, end in sorted(spans):
        if start >= cursor:
            keep.append(text[cursor:start])
        cursor = max(cursor, end)
    keep.append(text[cursor:])
    return " ".join("".join(keep).split())


#: 挖掉實體後剩下的常是「於 出現 ，依 流程檢討」這種殘骸。純標點或只剩一兩個字的
#: 不是查詢，是雜訊——把它們當查詢會讓該組的零結果率變成量測誤差而不是訊號。
_MIN_CONTENT_CHARS = 6


def _content_chars(s: str) -> int:
    return sum(1 for ch in s if ch.isalnum())


def _descriptive_terms(index: Index, extractor: EntityExtractor) -> list[str]:
    seen: set[str] = set()
    for meta in index.docs:
        for raw in (meta.title, meta.description):
            term = _strip_entities(raw or "", extractor)
            if _content_chars(term) >= _MIN_CONTENT_CHARS:
                seen.add(term)
    return sorted(seen)


def _alias_forms(dictionary: EntityDictionary | None) -> list[str]:
    """字典登記的**非正規**寫法。

    用正規名稱造查詢問不出字典的價值——正規名稱本身就是識別碼形狀，
    模式 B 自己就抓得到，那條查詢在 B 與 C 上會給出一樣的結果。
    """
    if dictionary is None:
        return []
    out: set[str] = set()
    for (_etype, canonical), surfaces in dictionary.surface_forms().items():
        canon = canonical.lower()
        for s in surfaces:
            if s and s.lower() != canon and len(s) >= 2:
                out.add(s)
    return sorted(out)


def generate(
    index: Index,
    dictionary: EntityDictionary | None,
    n: int,
    tokenizer: Tokenizer,
    seed: int = 7,
    mix: dict[str, float] | None = None,
) -> QuerySet:
    rng = random.Random(seed)
    mix = dict(mix or DEFAULT_MIX)

    keys = list(index.entities.postings)
    # 鍵是 `type:CANONICAL`；查詢裡要出現的是後半段。
    idents = [k.split(":", 1)[1] for k in keys if ":" in k]
    weights = [float(index.entities.df.get(k, 1)) for k in keys if ":" in k]

    extractor = EntityExtractor(dictionary or EntityDictionary.load(None), tokenizer)
    terms = _descriptive_terms(index, extractor)
    aliases = _alias_forms(dictionary)

    counts = {name: int(round(n * frac)) for name, frac in mix.items()}
    # 四捨五入的殘差補到最大的那一組，總數才會剛好是 n
    drift = n - sum(counts.values())
    if counts:
        counts[max(counts, key=lambda k: counts[k])] += drift

    out: list[str] = []
    produced: dict[str, int] = {}
    short: dict[str, str] = {}

    def take(name: str, produce) -> None:
        want = counts.get(name, 0)
        made = produce(want)
        produced[name] = len(made)
        if len(made) < want:
            short[name] = f"素材不足，要 {want} 筆只產出 {len(made)} 筆"
        out.extend(made)

    take("bare_identifier", lambda w: _weighted_sample(rng, idents, weights, w))
    take(
        "identifier_context",
        lambda w: [
            rng.choice(_CONTEXT_TEMPLATES).format(id=i, term=rng.choice(terms))
            for i in _weighted_sample(rng, idents, weights, w)
        ]
        if terms
        else [],
    )
    take(
        "two_identifiers",
        lambda w: [
            f"{a} {b}"
            for a, b in zip(
                _weighted_sample(rng, idents, weights, w),
                _weighted_sample(rng, idents, weights, w),
                strict=True,
            )
            if a != b
        ],
    )
    take("alias", lambda w: [rng.choice(aliases) for _ in range(w)] if aliases else [])
    take("descriptive", lambda w: [rng.choice(terms) for _ in range(w)] if terms else [])

    if not aliases:
        short.setdefault("alias", "字典未提供或沒有非正規寫法——模式 C 的那條腿無從測試")
    if not terms:
        short.setdefault("descriptive", "語料的標題／描述挖掉識別碼後沒有足夠長的殘餘")

    pools = {"identifier": len(set(idents)), "alias": len(aliases), "descriptive": len(terms)}
    # 素材種類少於產出筆數時，該組必然重複抽樣。這不是錯誤，但會讓該組的
    # 重疊度反映的是少數幾條查詢的性質，而不是一個分佈。
    for name, want_key in (("alias", "alias"), ("descriptive", "descriptive")):
        want = counts.get(name, 0)
        have = pools[want_key]
        if 0 < have < want:
            short.setdefault(
                name, f"素材只有 {have} 種，要產 {want} 條必然重複——該組的重疊度會是少數樣本的性質"
            )

    rng.shuffle(out)
    return QuerySet(queries=out, composition=produced, shortfalls=short, pool_sizes=pools)


def render(qs: QuerySet, seed: int, mix: dict[str, float], index_path: str) -> str:
    """檔頭記錄比例與種子。比例是一個沒有根據的假設，記錄下來才能被檢查、被換掉。"""
    lines = [
        "# 由 `yedai gen-queries` 產生。**含真實識別碼，不要進版控。**",
        "#",
        "# 這份清單能回答：這些機制在你的語料上會不會改變結果。",
        "#   識別碼與其頻率分佈都是真的，所以排名變化是一個真的量測。",
        "# 它不能回答：工程師是不是真的這樣查。句型是造的，下面的比例也是訂的。",
        "#   換一組比例重跑，就能看出結論對這個假設有多敏感。",
        "#",
        f"# seed={seed}  index={index_path}  總數={len(qs.queries)}",
        "# 組成（請求比例 → 實際筆數）：",
    ]
    for name, frac in mix.items():
        lines.append(f"#   {name:20} {frac:>5.0%}  → {qs.composition.get(name, 0)}")
    lines.append("# 素材種類數（少於產出筆數者必然重複抽樣）：")
    for name, size in qs.pool_sizes.items():
        lines.append(f"#   {name:20} {size}")
    for name, why in qs.shortfalls.items():
        lines.append(f"# ⚠ {name}: {why}")
    lines.append("")
    lines.extend(qs.queries)
    return "\n".join(lines) + "\n"


def load(path) -> list[str]:
    """讀回查詢清單，忽略註解與空行。"""
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8")
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def iter_nonempty(lines: Iterable[str]) -> list[str]:
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
