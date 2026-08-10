"""分層檢索：跨多個具名索引的協調。

每個索引由自己的 `Searcher` 服務，各自用自己的統計、自己的檢索設定、自己的
query 前處理。這一層只負責協調與呈現，**不**把不同索引的文件合進同一次計分。

預設回傳分層結構而不是一份混好的排序，理由是：

    RRF 融合的前提是兩份排名在回答同一個問題。

跨模式（C 與 D）滿足——同一份語料、同一個問題、失效模式互補。跨索引不滿足：
「這篇心法比那筆已結案更相關」不是一個有意義的命題，它們回答的不是同一件事。
要讓它們比大小就得發明一個共同尺度，而那個尺度不存在。

分層另有一個具體好處：**缺席變成訊號**。某一層為空，意思是「這類問題在這層沒有
對應的知識」，那是有用的資訊；壓成一份扁平清單之後，它與「排在回傳筆數之外」
不可區分。

融合仍然保留為顯式選項——這個決定應該被量測，不是被宣稱。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config, IndexSpec
from .entities import EntityDictionary
from .index import Index, load_index_for_spec
from .search import Hit, ModeResult, Searcher, VectorSearcher


class UnknownIndex(ValueError):
    pass


@dataclass(frozen=True)
class IdOverlap:
    """跨層重複的 concept_id。

    各層語料應該互斥——同一個 id 出現在兩層，不是「這份文件屬於兩類知識」，
    而是語料重複收錄了，或 id 產生方式沒有跨語料唯一。兩種都要修在上游。

    它的症狀全部是**靜默**的，所以必須量出來：取全文會取到 dict 順序第一層的版本、
    跨層融合會對同一份文件重複加權、批次取回會回傳重複條目。
    """

    total: int
    #: `"a↔b"` → 該配對重複的 id 數。只留層名（schema），不留 id（語料內容）。
    pairs: dict[str, int]

    @classmethod
    def measure(cls, indexes: dict[str, Index]) -> IdOverlap:
        """集合交集，成本與語料規模成線性。

        `LayeredSearcher` 與 `yedai report` 都要用——各自算一次，遲早會有一邊
        用不同的判準，而症狀是「同一份報告從 CLI 與 HTTP 產出的數字不一樣」。
        """
        names = list(indexes)
        seen: set[str] = set()
        pairs: dict[str, int] = {}
        for i, a in enumerate(names):
            ids_a = set(indexes[a].by_id)
            for b in names[i + 1 :]:
                common = ids_a & set(indexes[b].by_id)
                if common:
                    pairs[f"{a}↔{b}"] = len(common)
                    seen |= common
        return cls(total=len(seen), pairs=pairs)

    def __bool__(self) -> bool:
        return self.total > 0

    def to_dict(self) -> dict:
        return {"total": self.total, "pairs": dict(sorted(self.pairs.items()))}


@dataclass
class LayerResult:
    """一層的檢索結果。無命中時 `hits` 為空清單，但這一層仍然存在於輸出中。"""

    index: str
    mode: str
    hits: list[Hit] = field(default_factory=list)
    candidates: int = 0
    #: 這一層實際收到的查詢字串（前處理之後）。與原始查詢不同時，
    #: 沒有它就無法還原「這一層到底拿到了什麼」。
    prepared_query: str = ""

    @property
    def ids(self) -> list[str]:
        return [h.concept_id for h in self.hits]

    @property
    def empty(self) -> bool:
        return not self.hits

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "mode": self.mode,
            "candidates": self.candidates,
            "prepared_query": self.prepared_query,
            "hits": [h.to_dict() for h in self.hits],
        }


@dataclass
class FusedHit:
    """跨索引融合後的一筆。保留來源，否則呼叫端無從判斷這一筆該怎麼讀。"""

    rank: int
    index: str
    #: 這一筆在它**自己那一層**的名次。融合分數看不出來源深淺，這個看得出來。
    source_rank: int
    score: float
    hit: Hit

    def to_dict(self) -> dict:
        # 融合欄位必須放在 hit 展開**之後**。`Hit.to_dict()` 也有 `rank` 與 `score`
        # （層內的名次與分數），先寫融合值再展開 hit 會被它靜默蓋掉——回應看起來
        # 完全正常，只是 rank 重複、score 是層內分數而不是融合分數。
        return {
            **self.hit.to_dict(),
            "rank": self.rank,
            "index": self.index,
            "source_rank": self.source_rank,
            "score": self.score,
        }


@dataclass
class LayeredOutcome:
    query: str
    layers: list[LayerResult] = field(default_factory=list)
    #: 只有在明確要求融合時才非 None。預設是 None，而不是空清單——
    #: 空清單會讓「沒要求融合」與「融合後沒有結果」不可區分。
    fused: list[FusedHit] | None = None

    @property
    def fusion_requested(self) -> bool:
        return self.fused is not None

    @property
    def shape(self) -> str:
        """這次回傳的形態。遙測要能分開統計分層與融合，否則兩者的分佈會混在一起。"""
        return "fused" if self.fusion_requested else "layered"

    def layer(self, name: str) -> LayerResult | None:
        return next((lr for lr in self.layers if lr.index == name), None)

    def to_dict(self) -> dict:
        out: dict = {
            "query": self.query,
            "shape": self.shape,
            "layers": [lr.to_dict() for lr in self.layers],
        }
        if self.fused is not None:
            out["fused"] = [fh.to_dict() for fh in self.fused]
        return out


class LayeredSearcher:
    """持有每一層的 `Searcher`，並協調分層檢索與（選用的）跨索引融合。"""

    def __init__(self, searchers: dict[str, Searcher], config: Config) -> None:
        if not searchers:
            raise ValueError("LayeredSearcher 需要至少一個索引")
        self.searchers = searchers
        self.config = config
        self.id_overlap = self._measure_overlap()

    def _measure_overlap(self) -> IdOverlap:
        """建構時量一次跨層 id 重複，之後直接讀。"""
        return IdOverlap.measure({n: s.index for n, s in self.searchers.items()})

    def owner_of(self, concept_id: str) -> str | None:
        """哪一層持有這個 concept。

        重複時取**宣告順序的第一層**，而不是碰運氣的字典順序——結果錯不錯是一回事，
        每次呼叫給出不同的答案是另一回事。重複本身由 `id_overlap` 揭露。
        """
        for name, searcher in self.searchers.items():
            if searcher.index.has(concept_id):
                return name
        return None

    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        config: Config,
        dictionary: EntityDictionary,
        vectors: dict[str, VectorSearcher] | None = None,
    ) -> LayeredSearcher:
        """依設定載入全部索引，各自建立綁定的 `Searcher`。"""
        specs = config.index_specs()
        vectors = vectors or {}
        searchers: dict[str, Searcher] = {}
        for name in config.index_build_order():
            spec = specs[name]
            index = load_index_for_spec(spec, config, dictionary)
            searchers[name] = cls.searcher_for(spec, index, config, dictionary, vectors.get(name))
        return cls(searchers, config)

    @staticmethod
    def searcher_for(
        spec: IndexSpec,
        index: Index,
        config: Config,
        dictionary: EntityDictionary,
        vectors: VectorSearcher | None = None,
    ) -> Searcher:
        """把索引層級的檢索設定套進一個綁定該索引的 `Searcher`。"""
        return Searcher(
            index,
            spec.config_for(config),
            dictionary,
            vectors=vectors,
            keep_identifiers=spec.keep_identifiers,
        )

    # ------------------------------------------------------------------

    @property
    def names(self) -> list[str]:
        return list(self.searchers)

    def searcher(self, name: str) -> Searcher:
        if name not in self.searchers:
            raise UnknownIndex(f"未宣告的索引名稱 {name!r}；可用的有 {sorted(self.searchers)}")
        return self.searchers[name]

    def _specs(self) -> dict[str, IndexSpec]:
        return self.config.index_specs()

    def _mode_and_k(self, name: str, mode: str | None, k: int | None) -> tuple[str, int]:
        """每一層的預設模式與深度取自它自己的宣告。

        沒有全域 top-k 可以切分——分層回傳的深度本來就是各層獨立的參數。
        """
        spec = self._specs().get(name)
        resolved_mode = (mode or (spec.default_mode if spec else "C")).upper()
        resolved_k = k if k is not None else (spec.top_k if spec else self.config.top_k)
        return resolved_mode, resolved_k

    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        index: str | None = None,
        mode: str | None = None,
        k: int | None = None,
        fuse: bool = False,
    ) -> LayeredOutcome:
        """未指定 `index` 時對全部已載入索引檢索並分層回傳；指定時只查該層。

        `fuse` 預設關閉。開啟時額外附上跨索引平權 RRF 的融合清單——分層結構
        仍然保留，因為融合之後就看不出某一層是不是整個沒有東西了。
        """
        names = [index] if index is not None else self.names
        if index is not None and index not in self.searchers:
            raise UnknownIndex(f"未宣告的索引名稱 {index!r}；可用的有 {sorted(self.searchers)}")

        layers: list[LayerResult] = []
        for name in names:
            searcher = self.searchers[name]
            resolved_mode, resolved_k = self._mode_and_k(name, mode, k)
            result: ModeResult = searcher.search(query, resolved_mode, resolved_k)
            layers.append(
                LayerResult(
                    index=name,
                    mode=result.mode,
                    hits=result.hits,
                    candidates=result.candidates,
                    prepared_query=searcher.prepare_query(query),
                )
            )

        outcome = LayeredOutcome(query=query, layers=layers)
        if fuse:
            outcome.fused = self.fuse(layers)
        return outcome

    def fuse(self, layers: list[LayerResult]) -> list[FusedHit]:
        """跨索引平權 RRF。

        平權而非依語料規模加權：無法從原理推導的權重會變成一個沒人敢動也沒人
        解釋得了的常數（同 `search.rrf` 的理由）。四層大小相差數個數量級時，
        平權的意思是「每一類知識都派代表出席」——那是一個可以講清楚的立場，
        而一組猜出來的權重不是。
        """
        # 同一個 concept_id 理論上只屬於一層。真的重複時取名次較前的那一層，
        # 並且**只計一次**——RRF 對出現在多份排名的文件會逐份累加，那在「多個模式
        # 排同一份語料」是對的（獨立證據），在「多層排各自的語料」是錯的：
        # 同一份文件被收錄兩次不是兩份證據，卻會拿到 2× 分數而系統性壓過其他文件。
        origin: dict[str, tuple[str, int, Hit]] = {}
        for layer in layers:
            for rank, hit in enumerate(layer.hits, start=1):
                current = origin.get(hit.concept_id)
                if current is None or rank < current[1]:
                    origin[hit.concept_id] = (layer.index, rank, hit)
        if not origin:
            return []

        # 每個 concept 只以它最好的名次計一次分。各層互斥時這與 `rrf()` 逐份累加
        # 完全等價（每個 id 本來就只出現在一份排名裡）；重複時它避開了重複加權。
        # 不直接呼叫 `rrf()` 是因為那個函式吃的是排名清單，而這裡要在「同一份文件
        # 出現在多份清單」時壓成一次——那個判斷只有這一層知道。
        k = self.config.rrf_k
        scores = {cid: 1.0 / (k + rank) for cid, (_, rank, _) in origin.items()}

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        out: list[FusedHit] = []
        for cid, score in ranked:
            found = origin.get(cid)
            if found is None:
                continue
            layer_name, source_rank, hit = found
            out.append(
                FusedHit(
                    rank=len(out) + 1,
                    index=layer_name,
                    source_rank=source_rank,
                    score=score,
                    hit=hit,
                )
            )
        return out
