"""三種消融檢索模式與模式間比較。

A — 天真 BM25F，識別碼被一般斷詞切碎（水位線）
B — BM25F + 識別碼保護斷詞（隔離「斷詞層」的貢獻）
C — B + 實體字典匹配加權（隔離「字典」的額外貢獻）

三者跑在同一份語料、同一套 BM25F 參數上，唯一的差異就是上面那句話裡的變因。
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Config
from .entities import EntityDictionary, EntityExtractor, EntityHit
from .index import Index
from .tokenizer import Tokenizer

MODES: tuple[str, ...] = ("A", "B", "C")


@dataclass
class Hit:
    rank: int
    concept_id: str
    bundle_id: str
    type: str
    title: str
    description: str
    path: str
    score: float
    lexical_score: float = 0.0
    entity_score: float = 0.0

    def index_line(self) -> str:
        return f"{self.concept_id} . {self.type} . [{Path(self.path).name}]({self.path}) . {self.description}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["index_line"] = self.index_line()
        return data


@dataclass
class ModeResult:
    mode: str
    hits: list[Hit] = field(default_factory=list)
    candidates: int = 0

    @property
    def ids(self) -> list[str]:
        return [h.concept_id for h in self.hits]


@dataclass
class Overlap:
    pair: str
    jaccard: float
    kendall_tau: float | None
    common: int


@dataclass
class SearchOutcome:
    query: str
    k: int
    results: dict[str, ModeResult]
    entities: list[EntityHit] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)
    display_order: list[str] = field(default_factory=list)


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


def kendall_tau(a: list[str], b: list[str]) -> float | None:
    """只在兩份排序的共同項目上計算。少於兩個共同項目時無定義，回傳 None。"""
    sb = set(b)
    common = [x for x in a if x in sb]
    if len(common) < 2:
        return None
    rank_b = {x: i for i, x in enumerate(b)}
    concordant = discordant = 0
    for i in range(len(common)):
        for j in range(i + 1, len(common)):
            delta = rank_b[common[j]] - rank_b[common[i]]
            if delta > 0:
                concordant += 1
            elif delta < 0:
                discordant += 1
    total = concordant + discordant
    if total == 0:
        return None
    return (concordant - discordant) / total


class Searcher:
    def __init__(
        self,
        index: Index,
        config: Config,
        dictionary: EntityDictionary | None = None,
    ) -> None:
        self.index = index
        self.config = config
        self.tokenizer = Tokenizer(config.identifier_patterns)
        self.dictionary = (
            dictionary if dictionary is not None else EntityDictionary.from_config(config)
        )
        self.extractor = EntityExtractor(self.dictionary, self.tokenizer)
        self._rng = random.Random(config.seed)

    # ------------------------------------------------------------------

    def extract_query_entities(self, query: str) -> list[EntityHit]:
        return self.extractor.extract(query)

    def search(self, query: str, mode: str = "C", k: int | None = None) -> ModeResult:
        mode = mode.upper()
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r} (expected one of {', '.join(MODES)})")
        # 不可寫成 `k or self.config.top_k`——那會讓 k=0 被靜默替換成預設值，驗證形同虛設
        k = self.config.top_k if k is None else k
        if k <= 0:
            raise ValueError("k must be > 0")

        if mode == "A":
            return self._lexical_only(query, mode, k, naive=True)
        if mode == "B":
            return self._lexical_only(query, mode, k, naive=False)
        return self._hybrid(query, k)

    def compare(self, query: str, k: int | None = None) -> SearchOutcome:
        k = k or self.config.top_k
        results = {mode: self.search(query, mode, k) for mode in MODES}
        order = list(MODES)
        self._rng.shuffle(order)
        overlaps = []
        for left, right in (("A", "B"), ("A", "C"), ("B", "C")):
            a, b = results[left].ids, results[right].ids
            overlaps.append(
                Overlap(
                    pair=f"{left}-{right}",
                    jaccard=jaccard(a, b),
                    kendall_tau=kendall_tau(a, b),
                    common=len(set(a) & set(b)),
                )
            )
        return SearchOutcome(
            query=query,
            k=k,
            results=results,
            entities=self.extract_query_entities(query),
            overlaps=overlaps,
            display_order=order,
        )

    # ------------------------------------------------------------------

    def _lexical_only(self, query: str, mode: str, k: int, naive: bool) -> ModeResult:
        space = self.index.naive if naive else self.index.protected
        tokens = Tokenizer.naive(query) if naive else self.tokenizer.protected(query)
        scores = space.score(
            Counter(tokens),
            self.config.field_weight_vector(),
            self.config.k1,
            self.config.b,
        )
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        hits = [self._hit(i + 1, doc, score, lexical=score) for i, (doc, score) in enumerate(ranked)]
        return ModeResult(mode=mode, hits=hits, candidates=len(scores))

    def _hybrid(self, query: str, k: int) -> ModeResult:
        cfg = self.config
        entities = self.extract_query_entities(query)
        keys = [h.key for h in entities]

        candidates: set[int] | None = None
        if cfg.require_entities and keys:
            candidates = self.index.entities.docs_with_all(keys)
            if not candidates:
                return ModeResult(mode="C", hits=[], candidates=0)

        lexical = self.index.protected.score(
            Counter(self.tokenizer.protected(query)),
            cfg.field_weight_vector(),
            cfg.k1,
            cfg.b,
            candidates=candidates,
        )
        entity = self.index.entities.score(
            keys,
            cfg.max_entity_weight(),
            candidates=candidates,
        )

        # 詞彙腿以結果集內最大值正規化；實體腿依定義已落在 [0,1]（查詢實體的加權涵蓋率），
        # 再做一次 max 正規化會抹掉它的絕對意義，所以保持原值。
        max_lex = max(lexical.values(), default=0.0)
        docs = set(lexical) | set(entity)
        fused: dict[int, tuple[float, float, float]] = {}
        for doc in docs:
            lex = lexical.get(doc, 0.0)
            lex_n = (lex / max_lex) if max_lex > 0 else 0.0
            ent = entity.get(doc, 0.0)
            fused[doc] = (cfg.fusion_lexical * lex_n + cfg.fusion_entity * ent, lex_n, ent)

        ranked = sorted(fused.items(), key=lambda kv: (-kv[1][0], kv[0]))[:k]
        hits = [
            self._hit(i + 1, doc, parts[0], lexical=parts[1], entity=parts[2])
            for i, (doc, parts) in enumerate(ranked)
        ]
        return ModeResult(mode="C", hits=hits, candidates=len(docs))

    def _hit(self, rank: int, doc: int, score: float, lexical: float = 0.0, entity: float = 0.0) -> Hit:
        meta = self.index.docs[doc]
        return Hit(
            rank=rank,
            concept_id=meta.concept_id,
            bundle_id=meta.bundle_id,
            type=meta.type,
            title=meta.title,
            description=meta.description,
            path=meta.path,
            score=score,
            lexical_score=lexical,
            entity_score=entity,
        )
