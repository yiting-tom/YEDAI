"""設定。所有影響實驗結果的參數都必須能從這裡覆寫並被記錄下來，否則實驗不可重現。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import yaml

from .entities import CSV_SCHEMAS
from .tokenizer import DEFAULT_IDENTIFIER_PATTERNS, IdentifierPattern, resolve_specs

#: BM25F 的欄位順序。索引一旦建立就固定，變更會使快取失效。
FIELDS: tuple[str, ...] = ("title", "description", "tags", "headings", "figures", "body")

#: 不經設定宣告、直接呼叫 `build_index` 時使用的索引名稱。
#:
#: 這**不是**設定層的預設值——`index_specs()` 對空宣告一律報錯。分層的整個重點是
#: 每一份統計都知道自己屬於哪一層，回退到隱含的預設會讓使用者以為索引建好了，
#: 實際上寫進一個沒人宣告過的名字底下。這個常數只服務單一索引的低階呼叫。
DEFAULT_INDEX_NAME = "default"

#: 索引宣告接受的鍵。未列出的鍵一律報錯——拼錯的鍵靜默忽略，
#: 症狀會是「我明明設了權重卻沒生效」，而那要花很久才查得出來。
INDEX_SPEC_KEYS: frozenset[str] = frozenset(
    {
        "source",
        "path",
        "description",
        "when_to_use",
        "collection",
        "depends_on",
        "keep_identifiers",
        "default_mode",
        "top_k",
        "field_weights",
        "entity_field_weights",
        "fusion_lexical",
        "fusion_entity",
        "require_entities",
    }
)

#: 需要向量庫才能執行的模式。與 `search.DENSE_MODES` 同義，在這裡重複一份是為了
#: 避免 config → search 的匯入相依（search 需要 config）。兩者不一致會被測試抓到。
_DENSE_MODES: frozenset[str] = frozenset({"D", "E"})

_INDEX_DECLARATION_EXAMPLE = """indexes:
  <name>:
    source: <語料根目錄>
    path: <索引檔輸出路徑>
    collection: <向量 collection，選用>
    depends_on: [<其他索引名稱>, ...]   # 選用：實體字典來源
    keep_identifiers: true              # 選用：query 前處理
    default_mode: C                     # 選用，其餘檢索設定同樣可在此覆寫"""


def _default_field_weights() -> dict[str, float]:
    # 這些數字是猜的。實驗的目的之一就是修正它們。
    return {"title": 3.0, "description": 2.0, "tags": 2.0, "headings": 1.5, "figures": 1.5, "body": 1.0}


def _default_entity_weights() -> dict[str, float]:
    return {"title": 3.0, "description": 2.0, "tags": 2.0, "headings": 2.0, "figures": 1.5, "body": 1.0}


class _DuplicateKeyLoader(yaml.SafeLoader):
    """對重複鍵報錯的 YAML 載入器。

    YAML mapping 的重複鍵預設靜默保留最後一個。對索引宣告而言那正好是最壞的行為：
    宣告了兩個同名索引，其中一個無聲消失，而使用者會以為兩份統計都建好了。
    """


def _no_duplicate_keys(loader: _DuplicateKeyLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            mark = key_node.start_mark
            raise ValueError(f"設定中有重複的鍵 {key!r}（第 {mark.line + 1} 行）")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


def _load_yaml_strict(path: Path) -> Any:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_DuplicateKeyLoader)


@dataclass(frozen=True)
class IndexSpec:
    """一個具名索引的完整宣告，索引層級覆寫已與全域值合併完畢。

    解析成獨立型別而不是到處傳 dict：索引層級的設定會被 `Searcher` 與建索引兩邊
    讀到，兩邊各自從 dict 裡挖鍵、各自決定「沒宣告時用什麼」，遲早會分歧。
    """

    name: str
    source: str
    path: str
    #: 這一層裝什麼。**索引名稱是設定檔裡的任意鍵**——`cases`、`sop`、`a` 都合法，
    #: 而 agent 只看得到那個字串。沒有這一句，它只能從名字猜這層是什麼。
    description: str
    #: 什麼情況下該查這一層。與 `description` 分開：前者說「這是什麼」，
    #: 後者說「你什麼時候需要它」——agent 要的是後者。
    when_to_use: str
    collection: str | None
    depends_on: tuple[str, ...]
    #: 進入這個索引之前，query 要不要保留識別碼。
    #: 識別碼在案件層是主訊號，在敘述性語料是雜訊——同一個查詢字串在不同層
    #: 該以不同形式進入計分，而差異發生在計分之前。
    keep_identifiers: bool
    default_mode: str
    top_k: int
    field_weights: dict[str, float]
    entity_field_weights: dict[str, float]
    fusion_lexical: float
    fusion_entity: float
    require_entities: bool

    def config_for(self, base: Config) -> Config:
        """把索引層級的檢索設定套回一份 `Config`。

        `Searcher` 因此不必知道 `IndexSpec` 存在——它拿到的仍是一份 Config，
        只是那份 Config 的檢索參數已經是這一層的。
        """
        return base.merged(
            {
                "field_weights": dict(self.field_weights),
                "entity_field_weights": dict(self.entity_field_weights),
                "fusion_lexical": self.fusion_lexical,
                "fusion_entity": self.fusion_entity,
                "require_entities": self.require_entities,
                "top_k": self.top_k,
                "vector": dict(base.vector) | {"collection": self.collection},
            }
        )


@dataclass
class Config:
    # --- 斷詞 ---
    #: 每一項可以是樣式字串，或 `{pattern, type, parent_type, shape_complete}`。
    #: 字串會逐條對回內建樣式取得類型宣告——直接把字串丟給 Tokenizer 會讓宣告
    #: 在這裡靜靜消失，覆蓋率統計退回恆為 1.0 且不會報錯。
    #:
    #: mapping 形式的用途是**保密邊界**：敏感的識別碼組成規則（例如機台編碼的
    #: 完整字元集）不該進公開 repo，但寫進本機設定後仍必須帶得動類型宣告，
    #: 否則使用者得在「斷詞正確」與「統計正確」之間二選一。
    #: 請放進 `config.local.yaml`（已 gitignore）。
    identifier_patterns: list[Any] = field(default_factory=lambda: list(DEFAULT_IDENTIFIER_PATTERNS))
    #: 識別碼格式樣本檔。用 `yedai check-formats` 驗證上面那份樣式涵蓋得了真實形狀。
    #: 樣本是真實識別碼，屬敏感資料——請指向 `*-samples.local.yaml`（已被 gitignore）。
    #: 不設也能跑，但那等於沒有任何機制能發現「樣式對不上真實語料」。
    identifier_samples_path: str | None = None

    # --- BM25F ---
    k1: float = 1.2
    b: float = 0.75
    field_weights: dict[str, float] = field(default_factory=_default_field_weights)

    # --- 實體 ---
    dictionary_path: str | None = None
    #: CSV 實體來源。每筆為 {type, path, schema, child_type?}。
    #: 真實字典由 MES 匯出，是 CSV 不是 YAML；要求維護者手工轉檔的結果就是字典會過期。
    #: 真實清單屬敏感資料——請指向 `*.local.csv`（已被 gitignore）。
    entity_sources: list[dict[str, Any]] = field(default_factory=list)
    entity_field_weights: dict[str, float] = field(default_factory=_default_entity_weights)
    require_entities: bool = False

    # --- 模式 C 融合 ---
    fusion_lexical: float = 0.4
    fusion_entity: float = 0.6

    # --- 稠密腿（模式 D / E）---
    #: OpenAI 相容的 `/embeddings`。開發期指向 OpenRouter，production 指向
    #: LiteLLM 代理的 self-host vLLM——兩者只差這個欄位。
    #: `api_key_env` 是**環境變數名稱**，不是金鑰本身：設定檔會進版控。
    #: `trusted_endpoint` 是語料外流閘門，預設關閉，詳見 vectors.guard_corpus_leaves_process。
    embedding: dict[str, Any] = field(
        default_factory=lambda: {
            "base_url": "https://openrouter.ai/api/v1",
            "model": "qwen/qwen3-embedding-8b",
            "dim": 4096,
            "api_key_env": "OPENROUTER_API_KEY",
            "batch_size": 32,
            "timeout": 60.0,
            "max_retries": 4,
            "cache_dir": ".index/embed-cache",
            "max_chars": 6000,
            "trusted_endpoint": False,
        }
    )
    #: 向量庫。`url` 留空即用本機檔案模式，不必另外架服務。
    vector: dict[str, Any] = field(
        default_factory=lambda: {
            "path": ".index/qdrant",
            "url": None,
            "collection": "yedai",
            "api_key_env": None,
        }
    )
    #: RRF 的平滑常數。固定 60（慣例值）——在有真實查詢與人工判斷之前調它，調的是雜訊。
    rrf_k: int = 60

    # --- LLM（評估集產生）---
    #: OpenAI 相容的 chat 端點。與 embedding 同一個 LiteLLM 時只差 model 名稱。
    #: `trusted_endpoint` **獨立於** embedding 的宣告——把信任從一個端點自動延伸到
    #: 另一個，正是語料外流閘門要防的事，即使兩者現在指向同一個位址。
    llm: dict[str, Any] = field(
        default_factory=lambda: {
            "base_url": "http://litellm.internal/v1",
            "model": "kimi-k2.7",
            "api_key_env": "LITELLM_API_KEY",
            "temperature": 0.0,
            "timeout": 120.0,
            "max_retries": 4,
            "cache_dir": ".index/llm-cache",
            "max_chars": 4000,
            "trusted_endpoint": False,
        }
    )

    # --- 資產 ---
    #: 允許透過資產端點讀取的目錄名稱。這是**服務期政策**，不進索引簽章——
    #: 改一個安全設定不該迫使 220 萬個 concept 重建索引。
    asset_dirs: list[str] = field(default_factory=lambda: ["_assets"])

    # --- 索引 ---
    #: 具名索引集合。鍵是索引名稱，值的可用鍵見 `INDEX_SPEC_KEYS`。
    #:
    #: 每個索引持有**完全獨立**的詞彙與實體統計。這不是整理上的偏好：混在一起時
    #: `df` 與 `avg_field_len` 是全域的，持續累積的那一層每長大一次，其他層的排名
    #: 就漂移一次——沒有任何變更、沒有任何測試會紅，檢索品質卻退化了。
    #: 見 `tests/test_layers.py::test_growing_one_index_does_not_move_another`。
    indexes: dict[str, Any] = field(default_factory=dict)
    #: taxonomy 查表資源。以 defect 為鍵取回，**不進任何索引**——它是每個 defect
    #: 一條的判斷方法，不是文件集合；放進倒排索引，呼叫端拿到的會是「最像的幾列」。
    #: 內容屬 fab 專有知識，請指向 `*.local.yaml`（已 gitignore）。
    taxonomy_path: str | None = None
    #: defect 全集（`defect → category`）。taxonomy 覆蓋率的**分母**。
    #: 不設也能跑，但那樣只知道「整理了幾條」，不知道「還缺幾條」——
    #: 而 taxonomy 是部分填充的衍生欄位，缺口才是要追的東西。
    defect_catalogue_path: str | None = None

    # --- 路徑 ---
    log_dir: str = "logs"

    # --- 其他 ---
    top_k: int = 10
    seed: int | None = None

    #: 這份設定從哪個檔案來；`None` 表示走內建預設值（沒有指定設定檔）。
    #: 刻意**不是** dataclass 欄位——它描述來源而不是設定內容，進了 `asdict()`
    #: 就會被 `merged()` 當成一個可覆寫的鍵，然後出現在 `unknown config key` 的清單裡。
    source_path: ClassVar[str | None] = None

    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        cfg = cls()
        if not path:
            # 記住「根本沒給設定檔」。少了這個區分，錯誤訊息只能說「未宣告任何索引」，
            # 而使用者會去翻一份他其實沒有指定的設定檔。
            cfg.source_path = None
            return cfg
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"config not found: {p}")
        raw = _load_yaml_strict(p) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"config must be a YAML mapping: {p}")
        cfg = cfg.merged(raw)
        cfg.source_path = str(p)
        return cfg

    def merged(self, overrides: dict[str, Any]) -> Config:
        data = asdict(self)
        if "index_path" in overrides:
            # 不自動轉換：舊設定沒有層的概念，替使用者猜一個名字就是猜錯。
            raise ValueError(
                "設定鍵 `index_path` 已移除，索引改以具名集合宣告。\n\n"
                f"{_INDEX_DECLARATION_EXAMPLE}\n\n"
                "既有索引檔的格式版本也已提升，請以 --rebuild 重建。"
            )
        for key, value in overrides.items():
            if key not in data:
                raise ValueError(f"unknown config key: {key}")
            if isinstance(data[key], dict) and isinstance(value, dict):
                merged = dict(data[key])
                merged.update(value)
                data[key] = merged
            else:
                data[key] = value
        cfg = Config(**data)
        # 來源要跟著傳下去。`config_for()` 之類的覆寫會產生新的 Config，
        # 掉了來源之後，同一份設定的錯誤訊息會依呼叫路徑而不同。
        cfg.source_path = self.source_path
        cfg.validate()
        return cfg

    def validate(self) -> None:
        missing = set(FIELDS) - set(self.field_weights)
        if missing:
            raise ValueError(f"field_weights missing entries: {sorted(missing)}")
        missing = set(FIELDS) - set(self.entity_field_weights)
        if missing:
            raise ValueError(f"entity_field_weights missing entries: {sorted(missing)}")
        if self.k1 <= 0:
            raise ValueError("k1 must be > 0")
        if not 0.0 <= self.b <= 1.0:
            raise ValueError("b must be in [0, 1]")
        if self.fusion_lexical < 0 or self.fusion_entity < 0:
            raise ValueError("fusion weights must be >= 0")
        if self.fusion_lexical + self.fusion_entity <= 0:
            raise ValueError("fusion weights must not both be zero")
        if not self.asset_dirs:
            raise ValueError("asset_dirs must not be empty — 留空等於關閉資產端點，請明確設定")
        if any("/" in d or "\\" in d or d in ("", ".", "..") for d in self.asset_dirs):
            raise ValueError("asset_dirs 必須是單純的目錄名稱，不可含路徑分隔符")
        for i, src in enumerate(self.entity_sources):
            if not isinstance(src, dict):
                raise ValueError(f"entity_sources[{i}] 必須是 mapping")
            missing = [k for k in ("type", "path", "schema") if not src.get(k)]
            if missing:
                raise ValueError(f"entity_sources[{i}] 缺少必要欄位: {missing}")
            if src["schema"] not in CSV_SCHEMAS:
                raise ValueError(
                    f"entity_sources[{i}] 的 schema {src['schema']!r} 不支援；"
                    f"可用的有 {list(CSV_SCHEMAS)}"
                )

        for i, pat in enumerate(self.identifier_patterns):
            if isinstance(pat, dict):
                if not pat.get("pattern"):
                    raise ValueError(f"identifier_patterns[{i}] 的 mapping 缺少 pattern")
                unknown = set(pat) - {"pattern", "type", "parent_type", "shape_complete"}
                if unknown:
                    raise ValueError(f"identifier_patterns[{i}] 有不認得的鍵：{sorted(unknown)}")
                # 沒有類型的完整性宣稱對不到任何分母——它會被靜默忽略，
                # 而使用者會以為自己開了一個其實沒開的東西。
                if pat.get("shape_complete") and not pat.get("type"):
                    raise ValueError(
                        f"identifier_patterns[{i}] 宣告了 shape_complete 卻沒有 type。"
                        f"沒有類型的完整性宣稱對應不到任何覆蓋率分母。"
                    )
                source = pat["pattern"]
            elif isinstance(pat, str):
                source = pat
            else:
                raise ValueError(f"identifier_patterns[{i}] 必須是字串或 mapping")
            # 當場編譯。等到建索引才炸，錯誤會出現在離設定很遠的地方。
            try:
                re.compile(source)
            except re.error as exc:
                raise ValueError(f"identifier_patterns[{i}] 不是合法的正則：{exc}") from exc

        if int(self.embedding.get("dim", 0)) <= 0:
            raise ValueError("embedding.dim must be > 0")
        if not str(self.embedding.get("base_url", "")).strip():
            raise ValueError("embedding.base_url must not be empty")
        if not str(self.embedding.get("model", "")).strip():
            raise ValueError("embedding.model must not be empty")
        # 金鑰本身出現在設定裡是外洩，不是設定錯誤——這裡要的是**環境變數名稱**。
        if str(self.embedding.get("api_key_env", "")).startswith("sk-"):
            raise ValueError(
                "embedding.api_key_env 是環境變數名稱，不是金鑰本身。"
                "設定檔會進版控，把金鑰寫在這裡等同外洩。"
            )
        if self.rrf_k <= 0:
            raise ValueError("rrf_k must be > 0")
        if not str(self.llm.get("base_url", "")).strip():
            raise ValueError("llm.base_url must not be empty")
        if not str(self.llm.get("model", "")).strip():
            raise ValueError("llm.model must not be empty")
        if str(self.llm.get("api_key_env", "")).startswith("sk-"):
            raise ValueError(
                "llm.api_key_env 是環境變數名稱，不是金鑰本身。"
                "設定檔會進版控，把金鑰寫在這裡等同外洩。"
            )

        self._validate_indexes()

    def _validate_indexes(self) -> None:
        """索引宣告的形狀檢查。空宣告在這裡放行，由 `index_specs()` 攔。

        Config 本身可以不宣告索引（斷詞、格式檢查等不碰索引的路徑仍要能建 Config），
        但任何真的要用到索引的呼叫都會經過 `index_specs()`。
        """
        if not isinstance(self.indexes, dict):
            raise ValueError("indexes 必須是 mapping：索引名稱 → 宣告")
        for name, raw in self.indexes.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("索引名稱必須是非空字串")
            if not isinstance(raw, dict):
                raise ValueError(f"indexes[{name!r}] 必須是 mapping")
            unknown = set(raw) - INDEX_SPEC_KEYS
            if unknown:
                raise ValueError(
                    f"indexes[{name!r}] 有不認得的鍵：{sorted(unknown)}；"
                    f"可用的有 {sorted(INDEX_SPEC_KEYS)}"
                )
            for required in ("source", "path"):
                if not str(raw.get(required) or "").strip():
                    raise ValueError(f"indexes[{name!r}] 缺少必要欄位 {required!r}")
            depends = raw.get("depends_on") or []
            if not isinstance(depends, list) or any(not isinstance(d, str) for d in depends):
                raise ValueError(f"indexes[{name!r}] 的 depends_on 必須是字串陣列")
            for dep in depends:
                if dep == name:
                    raise ValueError(f"indexes[{name!r}] 不能依賴自己")
                if dep not in self.indexes:
                    raise ValueError(
                        f"indexes[{name!r}] 依賴不存在的索引 {dep!r}；"
                        f"已宣告的有 {sorted(self.indexes)}"
                    )
            mode = str(raw.get("default_mode") or "C").upper()
            # 在載入設定時擋掉，而不是等到查詢才失敗——「宣告了 D 卻沒有向量庫」
            # 延後到查詢期報錯，錯誤會出現在離設定很遠的地方。
            if mode in _DENSE_MODES and not str(raw.get("collection") or "").strip():
                raise ValueError(
                    f"indexes[{name!r}] 的 default_mode 是 {mode}，需要向量庫，"
                    f"但沒有宣告 collection。"
                )
            top_k = raw.get("top_k")
            if top_k is not None and (not isinstance(top_k, int) or top_k <= 0):
                raise ValueError(f"indexes[{name!r}] 的 top_k 必須是正整數")
            for wkey in ("field_weights", "entity_field_weights"):
                weights = raw.get(wkey)
                if weights is None:
                    continue
                if not isinstance(weights, dict):
                    raise ValueError(f"indexes[{name!r}] 的 {wkey} 必須是 mapping")
                unknown_fields = set(weights) - set(FIELDS)
                if unknown_fields:
                    raise ValueError(
                        f"indexes[{name!r}] 的 {wkey} 有不認得的欄位：{sorted(unknown_fields)}"
                    )

    # ------------------------------------------------------------------

    def undescribed_indexes(self) -> list[str]:
        """哪些層沒有寫 `description`。

        不當成設定錯誤——單層或實驗用的設定不必寫。但多層而沒有說明時，
        agent 只能從索引名稱猜這層是什麼，那是它最沒有把握的一種判斷。
        """
        return sorted(n for n, s in self.index_specs().items() if not s.description)

    def index_specs(self) -> dict[str, IndexSpec]:
        """解析全部索引宣告，索引層級未給的項目沿用全域值。

        空宣告在這裡報錯而不是回退到某個預設路徑：回退會讓使用者以為索引建好了，
        實際上寫進一個沒人宣告過的位置，而且要等到查詢無結果才會發現。
        """
        if not self.indexes:
            if self.source_path is None:
                # 最常見的情形：`yedai serve` 忘了 -c。先講這件事，
                # 講「未宣告任何索引」會讓人去翻一份他沒有指定的檔案。
                raise ValueError(
                    "沒有指定設定檔，而內建預設值不含任何索引宣告。\n\n"
                    "  yedai serve -c config.local.yaml\n"
                    "  yedai mcp   -c config.local.yaml\n\n"
                    "或設定環境變數 YEDAI_CONFIG=<設定檔路徑>。\n"
                    "設定檔尚未建立時，從 config.example.yaml 複製一份。"
                )
            raise ValueError(
                f"設定檔 {self.source_path} 未宣告任何索引。索引必須以具名集合宣告：\n\n"
                f"{_INDEX_DECLARATION_EXAMPLE}"
            )
        return {name: self._resolve_index(name, raw) for name, raw in self.indexes.items()}

    def index_spec(self, name: str) -> IndexSpec:
        specs = self.index_specs()
        if name not in specs:
            raise ValueError(f"未宣告的索引名稱 {name!r}；可用的有 {sorted(specs)}")
        return specs[name]

    def _resolve_index(self, name: str, raw: dict[str, Any]) -> IndexSpec:
        collection = str(raw.get("collection") or "").strip() or None
        return IndexSpec(
            name=name,
            source=str(raw["source"]),
            path=str(raw["path"]),
            description=str(raw.get("description") or "").strip(),
            when_to_use=str(raw.get("when_to_use") or "").strip(),
            collection=collection,
            depends_on=tuple(raw.get("depends_on") or ()),
            keep_identifiers=bool(raw.get("keep_identifiers", True)),
            default_mode=str(raw.get("default_mode") or "C").upper(),
            top_k=int(raw.get("top_k") or self.top_k),
            field_weights=dict(self.field_weights) | dict(raw.get("field_weights") or {}),
            entity_field_weights=(
                dict(self.entity_field_weights) | dict(raw.get("entity_field_weights") or {})
            ),
            fusion_lexical=float(
                raw["fusion_lexical"] if raw.get("fusion_lexical") is not None else self.fusion_lexical
            ),
            fusion_entity=float(
                raw["fusion_entity"] if raw.get("fusion_entity") is not None else self.fusion_entity
            ),
            require_entities=bool(
                raw["require_entities"]
                if raw.get("require_entities") is not None
                else self.require_entities
            ),
        )

    def index_build_order(self) -> list[str]:
        """依 `depends_on` 拓撲排序，上游先於下游。

        依賴之所以存在：某個索引的內容同時是其他索引的實體字典來源，它變更後
        下游的實體抽取結果就會改變。沒有順序的話，實際發生的是「重建了全部索引，
        但下游用的是舊字典」——而那不會報錯。
        """
        specs = self.index_specs()
        order: list[str] = []
        state: dict[str, int] = {}  # 0=未訪 1=訪問中 2=完成

        def visit(name: str, trail: tuple[str, ...]) -> None:
            mark = state.get(name, 0)
            if mark == 2:
                return
            if mark == 1:
                cycle = " → ".join([*trail, name])
                raise ValueError(f"索引依賴成環：{cycle}")
            state[name] = 1
            for dep in specs[name].depends_on:
                visit(dep, (*trail, name))
            state[name] = 2
            order.append(name)

        for name in specs:
            visit(name, ())
        return order

    def dependents_of(self, name: str) -> list[str]:
        """哪些索引宣告依賴 `name`。上游重建後，這些會因簽章不符而過期。"""
        return sorted(n for n, spec in self.index_specs().items() if name in spec.depends_on)

    # ------------------------------------------------------------------

    def field_weight_vector(self) -> list[float]:
        return [float(self.field_weights[f]) for f in FIELDS]

    def entity_weight_vector(self) -> dict[str, float]:
        return {f: float(self.entity_field_weights[f]) for f in FIELDS}

    def max_entity_weight(self) -> float:
        return max(self.entity_field_weights[f] for f in FIELDS)

    def index_signature(
        self,
        dictionary_fingerprint: str = "",
        index_name: str = DEFAULT_INDEX_NAME,
    ) -> str:
        """只涵蓋會改變索引內容的設定；計分權重在查詢期套用，不影響快取有效性。

        `entity_sources` 刻意**不**列入：字典指紋由實際載入的條目導出，
        已經涵蓋 CSV 的內容。把路徑也放進來只會讓「換個檔名、內容相同」白白失效一次索引。

        `index_name` 列入，是為了讓「索引檔被放到另一個索引的路徑下」變成簽章不符
        而不是靜默採用——兩份統計互換之後，檢索仍會回傳結果，只是分數全錯。
        """
        payload = {
            "fields": list(FIELDS),
            "identifier_patterns": list(self.identifier_patterns),
            "entity_field_weights": {f: self.entity_field_weights[f] for f in FIELDS},
            "dictionary": dictionary_fingerprint,
            "index_name": index_name,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def identifier_specs(self) -> list[IdentifierPattern]:
        """樣式 + 類型宣告（內建的或設定自行宣告的）。建 `Tokenizer` 一律走這裡。"""
        return resolve_specs(self.identifier_patterns)

    def experiment_params(self) -> dict[str, Any]:
        """寫進去識別化報告，確保任何一組數字都能被追溯回它的設定。"""
        return {
            "k1": self.k1,
            "b": self.b,
            "field_weights": dict(self.field_weights),
            "entity_field_weights": dict(self.entity_field_weights),
            "fusion_lexical": self.fusion_lexical,
            "fusion_entity": self.fusion_entity,
            "require_entities": self.require_entities,
            "identifier_pattern_count": len(self.identifier_patterns),
            "top_k": self.top_k,
            "rrf_k": self.rrf_k,
            #: 只記名稱與形狀，不記 source / path——那些是本機路徑，報告要能外流。
            "indexes": sorted(self.indexes),
            "index_count": len(self.indexes),
        }
