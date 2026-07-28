"""消融檢索模式與模式間比較。

A — 天真 BM25F，識別碼被一般斷詞切碎（水位線）
B — BM25F + 識別碼保護斷詞（隔離「斷詞層」的貢獻）
C — B + 實體字典匹配加權（隔離「字典」的額外貢獻）
D — 純稠密向量（與關鍵字腿失效模式相反的那一半）
E — RRF(C, D)（隔離「融合」的額外貢獻）

每個模式跑在同一份語料、同一套參數上，唯一的差異就是上面那句話裡的變因。

D 與 E 需要向量庫。沒有向量時它們是**不可用**，不是退化成 C——
靜默退化會讓報告顯示「稠密腿沒有帶來差異」，而真相是它根本沒有執行。
那種假象會被當成結論。
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Config
from .embedding import EmbeddingClient
from .entities import EntityDictionary, EntityExtractor, EntityHit
from .index import Index
from .tokenizer import Tokenizer
from .vectors import VectorHit, VectorStore


class ModeUnavailable(RuntimeError):
    pass

#: 只需要關鍵字索引的模式。
LEXICAL_MODES: tuple[str, ...] = ("A", "B", "C")
#: 需要向量庫的模式。
DENSE_MODES: tuple[str, ...] = ("D", "E")
MODES: tuple[str, ...] = LEXICAL_MODES + DENSE_MODES


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
    dense_score: float = 0.0
    #: 模式 E 專用：該文件在兩腿各自的名次。看得到才追得下去「它為什麼排在這裡」。
    lexical_rank: int | None = None
    dense_rank: int | None = None

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


def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion：每份排名貢獻 `1/(k + rank)`，rank 從 1 起算。

    **只吃排名，不吃分數**。BM25 分數與餘弦相似度沒有共同尺度，要把它們加起來就得先
    湊一個正規化與一組權重——而那組權重無法從原理推導，只能靠猜，最後變成一個
    沒人敢動也沒人解釋得了的魔術數字。RRF 沒有這個問題：它唯一的常數 `k` 只控制
    「前幾名比後幾名重要多少」，而且對它不敏感。
    """
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return fused


class Searcher:
    def __init__(
        self,
        index: Index,
        config: Config,
        dictionary: EntityDictionary | None = None,
        vectors: "VectorSearcher | None" = None,
    ) -> None:
        self.index = index
        self.config = config
        self.tokenizer = Tokenizer(config.identifier_specs())
        self.dictionary = (
            dictionary if dictionary is not None else EntityDictionary.from_config(config)
        )
        self.extractor = EntityExtractor(self.dictionary, self.tokenizer)
        self.vectors = vectors
        self._rng = random.Random(config.seed)
        self._by_id = {meta.concept_id: i for i, meta in enumerate(index.docs)}

    @property
    def available_modes(self) -> tuple[str, ...]:
        """向量不可用時 D/E 不在此列——呼叫端因此拿得到「不可用」而不是錯的結果。"""
        if self.vectors is None:
            return LEXICAL_MODES
        return MODES

    # ------------------------------------------------------------------

    def extract_query_entities(self, query: str) -> list[EntityHit]:
        return self.extractor.extract(query)

    def search(self, query: str, mode: str = "C", k: int | None = None) -> ModeResult:
        mode = mode.upper()
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r} (expected one of {', '.join(MODES)})")
        if mode not in self.available_modes:
            raise ModeUnavailable(
                f"模式 {mode} 需要向量庫，但目前沒有。先跑 `yedai embed`。\n"
                f"這裡刻意不退回模式 C——那會讓報告顯示「稠密腿沒有帶來差異」，"
                f"而真相是它根本沒有執行。"
            )
        # 不可寫成 `k or self.config.top_k`——那會讓 k=0 被靜默替換成預設值，驗證形同虛設
        k = self.config.top_k if k is None else k
        if k <= 0:
            raise ValueError("k must be > 0")

        if mode == "A":
            return self._lexical_only(query, mode, k, naive=True)
        if mode == "B":
            return self._lexical_only(query, mode, k, naive=False)
        if mode == "C":
            return self._hybrid(query, k)
        if mode == "D":
            return self._dense(query, k)
        return self._rrf(query, k)

    def compare(self, query: str, k: int | None = None) -> SearchOutcome:
        k = k or self.config.top_k
        modes = self.available_modes
        results = {mode: self.search(query, mode, k) for mode in modes}
        order = list(modes)
        self._rng.shuffle(order)
        overlaps = []
        # 所有**可用**模式的兩兩配對。固定寫死三組會在加入 D/E 後靜靜地漏掉它們，
        # 而漏掉的那幾組正好是新機制值不值得的依據。
        pairs = [(a, b) for i, a in enumerate(modes) for b in modes[i + 1 :]]
        for left, right in pairs:
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

    def _dense(self, query: str, k: int) -> ModeResult:
        assert self.vectors is not None
        hits = self.vectors.search(query, k)
        out: list[Hit] = []
        for i, vh in enumerate(hits):
            doc = self._by_id.get(vh.concept_id)
            # 向量庫可能還留著已從語料移除的 concept。跳過而不是報錯——
            # 重建索引與重建向量是兩個動作，兩者之間必然有一段不同步的時間。
            if doc is None:
                continue
            out.append(self._hit(len(out) + 1, doc, vh.score, dense=vh.score))
        return ModeResult(mode="D", hits=out, candidates=len(hits))

    def _rrf(self, query: str, k: int) -> ModeResult:
        """RRF(C, D)。兩腿各取較深的名次再融合——只取前 k 名會讓融合幾乎沒有東西可混。"""
        depth = max(k * 5, k)
        lexical = self._hybrid(query, depth)
        dense = self._dense(query, depth)
        fused = rrf([lexical.ids, dense.ids], k=self.config.rrf_k)

        lex_rank = {cid: i + 1 for i, cid in enumerate(lexical.ids)}
        dense_rank = {cid: i + 1 for i, cid in enumerate(dense.ids)}
        ranked = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        out: list[Hit] = []
        for i, (cid, score) in enumerate(ranked):
            doc = self._by_id.get(cid)
            if doc is None:
                continue
            hit = self._hit(len(out) + 1, doc, score)
            # 保留兩腿各自的名次：一個文件為什麼排在這裡，看得到才追得下去。
            hit.lexical_rank = lex_rank.get(cid)
            hit.dense_rank = dense_rank.get(cid)
            out.append(hit)
        return ModeResult(mode="E", hits=out, candidates=len(fused))

    def _hit(
        self,
        rank: int,
        doc: int,
        score: float,
        lexical: float = 0.0,
        entity: float = 0.0,
        dense: float = 0.0,
    ) -> Hit:
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
            dense_score=dense,
        )


class VectorSearcher:
    """查詢向量 → 向量庫。查詢向量走快取，同一組 queries.txt 重跑不重複付費。"""

    def __init__(self, store: "VectorStore", embedder: "EmbeddingClient") -> None:
        self.store = store
        self.embedder = embedder

    def search(self, query: str, k: int) -> list["VectorHit"]:
        vector = self.embedder.embed([query])[0]
        return self.store.search(vector, k)
