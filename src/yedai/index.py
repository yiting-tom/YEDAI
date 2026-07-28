"""索引建構與計分。

刻意保持在記憶體內：30 個 bundle 約 660 個 concept，引入外部服務只會提高實驗門檻
而不會改變結論。索引同時保存兩套詞彙空間（naive / protected），
讓模式 A 與模式 B 能在完全相同的語料上比較。
"""

from __future__ import annotations

import math
import pickle
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import FIELDS, Config
from .entities import UNKNOWN_TYPE, EntityDictionary, EntityExtractor, EntityHit
from .models import Concept
from .parser import load_bundles
from .tokenizer import Tokenizer

# v2：新增 by_id 與 bundle_roots，使 concept 全文可於請求時從磁碟定位
# v3：新增 related_out / related_in / dangling，使 agent 能沿 related 展開
#: 4：識別碼支援 `#` 與父子層級展開，詞彙空間因此與 v3 不相容。
INDEX_FORMAT_VERSION = 4
N_FIELDS = len(FIELDS)


@dataclass
class DocMeta:
    concept_id: str
    bundle_id: str
    type: str
    title: str
    description: str
    path: str
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""
    confidence: str = ""
    n_figures: int = 0
    n_chars: int = 0

    def index_line(self) -> str:
        return f"{self.concept_id} . {self.type} . [{Path(self.path).name}]({self.path}) . {self.description}"


@dataclass
class TermSpace:
    """一套詞彙空間的倒排索引 + BM25F 所需的欄位長度統計。"""

    postings: dict[str, dict[int, list[int]]] = field(default_factory=dict)
    df: dict[str, int] = field(default_factory=dict)
    doc_field_len: list[list[int]] = field(default_factory=list)
    avg_field_len: list[float] = field(default_factory=lambda: [0.0] * N_FIELDS)

    def add(self, doc_idx: int, field_tokens: list[list[str]]) -> None:
        assert doc_idx == len(self.doc_field_len), "documents must be added in order"
        self.doc_field_len.append([len(toks) for toks in field_tokens])
        per_term: dict[str, list[int]] = defaultdict(lambda: [0] * N_FIELDS)
        for fi, toks in enumerate(field_tokens):
            for tok in toks:
                per_term[tok][fi] += 1
        for term, tfs in per_term.items():
            self.postings.setdefault(term, {})[doc_idx] = tfs
            self.df[term] = self.df.get(term, 0) + 1

    def finalise(self) -> None:
        n = len(self.doc_field_len)
        if n == 0:
            return
        for fi in range(N_FIELDS):
            self.avg_field_len[fi] = sum(dl[fi] for dl in self.doc_field_len) / n

    @property
    def n_docs(self) -> int:
        return len(self.doc_field_len)

    @property
    def vocab_size(self) -> int:
        return len(self.postings)

    def score(
        self,
        query_tf: Counter,
        weights: list[float],
        k1: float,
        b: float,
        candidates: set[int] | None = None,
    ) -> dict[int, float]:
        n = self.n_docs
        if n == 0:
            return {}
        out: dict[int, float] = defaultdict(float)
        for term, qn in query_tf.items():
            post = self.postings.get(term)
            if not post:
                continue
            df = self.df.get(term, 0)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for doc, tfs in post.items():
                if candidates is not None and doc not in candidates:
                    continue
                tilde = 0.0
                dl = self.doc_field_len[doc]
                for fi, tf in enumerate(tfs):
                    if not tf:
                        continue
                    avg = self.avg_field_len[fi]
                    norm = (1.0 - b + b * (dl[fi] / avg)) if avg > 0 else 1.0
                    if norm <= 0:
                        norm = 1.0
                    tilde += weights[fi] * tf / norm
                if tilde > 0:
                    out[doc] += qn * idf * (tilde / (k1 + tilde))
        return dict(out)


@dataclass
class EntitySpace:
    """實體倒排索引。權重為實體在該 concept 中出現過的最高欄位權重。"""

    postings: dict[str, dict[int, float]] = field(default_factory=dict)
    df: dict[str, int] = field(default_factory=dict)
    source: dict[str, str] = field(default_factory=dict)  # key -> "dict" | "regex"
    etype: dict[str, str] = field(default_factory=dict)
    n_docs: int = 0

    def add(self, doc_idx: int, weighted: dict[str, float], meta: dict[str, tuple[str, str]]) -> None:
        self.n_docs = max(self.n_docs, doc_idx + 1)
        for key, weight in weighted.items():
            self.postings.setdefault(key, {})[doc_idx] = weight
            self.df[key] = self.df.get(key, 0) + 1
            if key in meta:
                self.etype[key], self.source[key] = meta[key]

    def idf(self, key: str) -> float:
        df = self.df.get(key, 0)
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(
        self,
        query_keys: list[str],
        max_weight: float,
        candidates: set[int] | None = None,
    ) -> dict[int, float]:
        """回傳 doc -> [0,1] 的查詢實體加權涵蓋率。

        分母使用「所有查詢實體 × 最高欄位權重」，因此只有在最高權重欄位中
        完整涵蓋所有查詢實體的 concept 才會拿到 1.0。查詢實體若語料中不存在，
        仍計入分母——語料無法涵蓋的查詢本來就不該拿滿分。
        """
        if not query_keys or max_weight <= 0:
            return {}
        idfs = {k: self.idf(k) for k in dict.fromkeys(query_keys)}
        den = sum(idfs.values()) * max_weight
        if den <= 0:
            return {}
        out: dict[int, float] = defaultdict(float)
        for key, idf in idfs.items():
            post = self.postings.get(key)
            if not post:
                continue
            for doc, weight in post.items():
                if candidates is not None and doc not in candidates:
                    continue
                out[doc] += idf * weight
        return {doc: value / den for doc, value in out.items()}

    def docs_with_all(self, query_keys: list[str]) -> set[int] | None:
        keys = list(dict.fromkeys(query_keys))
        if not keys:
            return None
        result: set[int] | None = None
        for key in keys:
            docs = set(self.postings.get(key, {}))
            result = docs if result is None else (result & docs)
            if not result:
                return set()
        return result

    def coverage(self) -> dict[str, int]:
        dict_hits = sum(1 for k in self.postings if self.source.get(k) == "dict")
        regex_hits = sum(1 for k in self.postings if self.source.get(k) == "regex")
        return {"total": len(self.postings), "dict": dict_hits, "regex": regex_hits}

    def coverage_by_type(self) -> dict[str, dict[str, int]]:
        """依實體類型拆解的覆蓋率。

        全域比例會把性質相反的兩種作用平均掉：字典對一般詞（缺陷名）是語義正規化，
        缺了整條腿歸零；對結構化識別碼（機台）只是擋掉 regex 誤圈，缺了僅精確度下降。
        「fallback 佔 60%」在前者是災難、在後者可能無所謂——不拆開就分不出來。

        鍵是類型名稱（schema），不是正規名稱（語料內容）——報告要能帶出受管制環境。
        """
        out: dict[str, dict[str, int]] = {}
        for key in self.postings:
            etype = key.split(":", 1)[0] if ":" in key else UNKNOWN_TYPE
            bucket = out.setdefault(etype, {"total": 0, "dict": 0, "regex": 0})
            bucket["total"] += 1
            src = self.source.get(key)
            if src in ("dict", "regex"):
                bucket[src] += 1
        return dict(sorted(out.items()))


@dataclass
class CorpusStats:
    bundles: int = 0
    concepts: int = 0
    avg_concept_chars: float = 0.0
    avg_figures: float = 0.0
    vocab_naive: int = 0
    vocab_protected: int = 0
    entities_total: int = 0
    entities_dict: int = 0
    entities_regex: int = 0
    #: 實體類型 → {total, dict, regex}。全域數字保留，但只有拆解過的數字能解讀。
    entities_by_type: dict[str, dict[str, int]] = field(default_factory=dict)
    parse_skipped: int = 0
    parse_warnings: int = 0
    #: `related` 指向語料中不存在的 id 的總筆數。模型產出的 concept，這個數字本身
    #: 就是語料品質的訊號，所以留在統計裡而不是靜默丟棄。
    dangling_related: int = 0
    types: dict[str, int] = field(default_factory=dict)


@dataclass
class Index:
    signature: str
    docs: list[DocMeta] = field(default_factory=list)
    naive: TermSpace = field(default_factory=TermSpace)
    protected: TermSpace = field(default_factory=TermSpace)
    entities: EntitySpace = field(default_factory=EntitySpace)
    stats: CorpusStats = field(default_factory=CorpusStats)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: concept_id → docs 的位置。沒有它就得線性掃描 200 萬筆才能定位一個 concept。
    by_id: dict[str, int] = field(default_factory=dict)
    #: bundle_id → 該 bundle 的絕對根目錄。以 bundle 為單位登錄，
    #: 不逐筆存進 DocMeta——否則同一個字串會在 200 萬筆資料裡重複。
    bundle_roots: dict[str, str] = field(default_factory=dict)
    #: concept_id → 它 `related` 指向且確實存在的 concept
    related_out: dict[str, list[str]] = field(default_factory=dict)
    #: concept_id → 哪些 concept 指向它。建索引時算好——這是 agent 最需要
    #: 但最難自己拼出來的資訊（「還有哪些文件引用了這個概念」）。
    related_in: dict[str, list[str]] = field(default_factory=dict)
    #: concept_id → 它 `related` 指向但語料中不存在的 id
    dangling: dict[str, list[str]] = field(default_factory=dict)
    format_version: int = INDEX_FORMAT_VERSION

    # ------------------------------------------------------------------

    def doc_of(self, concept_id: str) -> DocMeta | None:
        pos = self.by_id.get(concept_id)
        return None if pos is None else self.docs[pos]

    def has(self, concept_id: str) -> bool:
        return concept_id in self.by_id

    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as fh:
            pickle.dump(self, fh, protocol=pickle.HIGHEST_PROTOCOL)
        return p

    @staticmethod
    def load(path: str | Path) -> Index:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"index not found: {p} — 請先執行 `yedai index <bundles-dir>`")
        with p.open("rb") as fh:
            idx = pickle.load(fh)
        if not isinstance(idx, Index) or idx.format_version != INDEX_FORMAT_VERSION:
            raise ValueError(f"index format mismatch at {p} — 請重建索引")
        return idx

    def check_signature(self, expected: str) -> None:
        if self.signature != expected:
            raise ValueError(
                "索引快取與目前設定不相容（斷詞樣式或字典已變更）——請以 --rebuild 重建索引"
            )


def build_index(
    root: str | Path,
    config: Config,
    dictionary: EntityDictionary | None = None,
) -> Index:
    dictionary = dictionary if dictionary is not None else EntityDictionary.from_config(config)
    tokenizer = Tokenizer(config.identifier_patterns)
    extractor = EntityExtractor(dictionary, tokenizer)
    entity_weights = config.entity_weight_vector()

    bundles, report = load_bundles(root)
    index = Index(signature=config.index_signature(dictionary.fingerprint()))
    index.skipped = list(report.skipped)
    index.warnings = list(report.warnings)

    total_chars = 0
    total_figures = 0
    types: Counter = Counter()
    raw_related: dict[str, list[str]] = {}

    doc_idx = 0
    for bundle in bundles:
        index.bundle_roots[bundle.bundle_id] = str(Path(bundle.root).resolve())
        for concept in bundle.concepts:
            fields = concept.field_texts()
            texts = [fields[f] for f in FIELDS]

            index.naive.add(doc_idx, [Tokenizer.naive(t) for t in texts])
            index.protected.add(doc_idx, [tokenizer.protected(t) for t in texts])

            weighted, meta = _concept_entities(concept, extractor, entity_weights)
            index.entities.add(doc_idx, weighted, meta)

            # 重複 id 不覆蓋先出現者——靜默覆蓋會讓「取全文」拿到另一份文件
            if concept.concept_id in index.by_id:
                index.warnings.append(
                    f"重複的 concept_id {concept.concept_id!r}："
                    f"保留先出現的 {index.docs[index.by_id[concept.concept_id]].path}，"
                    f"忽略 {concept.path}"
                )
            else:
                index.by_id[concept.concept_id] = doc_idx
                if concept.related:
                    raw_related[concept.concept_id] = list(concept.related)

            index.docs.append(_doc_meta(concept))
            total_chars += len(concept.body)
            total_figures += len(concept.figures)
            types[concept.type or "(untyped)"] += 1
            doc_idx += 1

    index.naive.finalise()
    index.protected.finalise()
    index.entities.n_docs = doc_idx
    dangling_total = _build_related_edges(index, raw_related)

    coverage = index.entities.coverage()
    n = max(doc_idx, 1)
    index.stats = CorpusStats(
        bundles=report.bundles,
        concepts=doc_idx,
        avg_concept_chars=total_chars / n,
        avg_figures=total_figures / n,
        vocab_naive=index.naive.vocab_size,
        vocab_protected=index.protected.vocab_size,
        entities_total=coverage["total"],
        entities_dict=coverage["dict"],
        entities_regex=coverage["regex"],
        entities_by_type=index.entities.coverage_by_type(),
        parse_skipped=len(report.skipped),
        parse_warnings=len(report.warnings),
        dangling_related=dangling_total,
        types=dict(types.most_common()),
    )
    return index


def _build_related_edges(index: Index, raw_related: dict[str, list[str]]) -> int:
    """把 frontmatter 的 related 拆成「可解析的邊」與「懸空引用」。

    必須等全部 concept 都掃過才能判定懸空——否則前向引用會被誤判。
    入向邊在這裡一次算完，查詢時就不必遍歷全部文件。
    """
    dangling_total = 0
    for source, targets in raw_related.items():
        resolved: list[str] = []
        missing: list[str] = []
        for target in dict.fromkeys(targets):  # 去重但保序
            if target == source:
                continue  # 自我引用不成邊
            if index.has(target):
                resolved.append(target)
                index.related_in.setdefault(target, []).append(source)
            else:
                missing.append(target)
        if resolved:
            index.related_out[source] = resolved
        if missing:
            index.dangling[source] = missing
            dangling_total += len(missing)
    return dangling_total


def _doc_meta(concept: Concept) -> DocMeta:
    return DocMeta(
        concept_id=concept.concept_id,
        bundle_id=concept.bundle_id,
        type=concept.type,
        title=concept.title,
        description=concept.description,
        path=concept.path,
        tags=list(concept.tags),
        timestamp=concept.timestamp,
        confidence=concept.confidence,
        n_figures=len(concept.figures),
        n_chars=len(concept.body),
    )


def _concept_entities(
    concept: Concept,
    extractor: EntityExtractor,
    weights: dict[str, float],
) -> tuple[dict[str, float], dict[str, tuple[str, str]]]:
    fields = concept.field_texts()
    weighted: dict[str, float] = {}
    meta: dict[str, tuple[str, str]] = {}
    for fname in FIELDS:
        w = weights.get(fname, 1.0)
        for hit in extractor.extract(fields.get(fname, "")):
            weighted[hit.key] = max(weighted.get(hit.key, 0.0), w)
            meta.setdefault(hit.key, (hit.type, hit.source))
    return weighted, meta


def entity_keys_of(hits: list[EntityHit]) -> list[str]:
    return [h.key for h in hits]
