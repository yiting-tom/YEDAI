"""設定。所有影響實驗結果的參數都必須能從這裡覆寫並被記錄下來，否則實驗不可重現。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .entities import CSV_SCHEMAS
from .tokenizer import DEFAULT_IDENTIFIER_PATTERNS, IdentifierPattern, resolve_specs

#: BM25F 的欄位順序。索引一旦建立就固定，變更會使快取失效。
FIELDS: tuple[str, ...] = ("title", "description", "tags", "headings", "figures", "body")


def _default_field_weights() -> dict[str, float]:
    # 這些數字是猜的。實驗的目的之一就是修正它們。
    return {"title": 3.0, "description": 2.0, "tags": 2.0, "headings": 1.5, "figures": 1.5, "body": 1.0}


def _default_entity_weights() -> dict[str, float]:
    return {"title": 3.0, "description": 2.0, "tags": 2.0, "headings": 2.0, "figures": 1.5, "body": 1.0}


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

    # --- 路徑 ---
    index_path: str = ".index/yedai.pkl"
    log_dir: str = "logs"

    # --- 其他 ---
    top_k: int = 10
    seed: int | None = None

    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        cfg = cls()
        if not path:
            return cfg
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"config not found: {p}")
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"config must be a YAML mapping: {p}")
        return cfg.merged(raw)

    def merged(self, overrides: dict[str, Any]) -> Config:
        data = asdict(self)
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

    # ------------------------------------------------------------------

    def field_weight_vector(self) -> list[float]:
        return [float(self.field_weights[f]) for f in FIELDS]

    def entity_weight_vector(self) -> dict[str, float]:
        return {f: float(self.entity_field_weights[f]) for f in FIELDS}

    def max_entity_weight(self) -> float:
        return max(self.entity_field_weights[f] for f in FIELDS)

    def index_signature(self, dictionary_fingerprint: str = "") -> str:
        """只涵蓋會改變索引內容的設定；計分權重在查詢期套用，不影響快取有效性。

        `entity_sources` 刻意**不**列入：字典指紋由實際載入的條目導出，
        已經涵蓋 CSV 的內容。把路徑也放進來只會讓「換個檔名、內容相同」白白失效一次索引。
        """
        payload = {
            "fields": list(FIELDS),
            "identifier_patterns": list(self.identifier_patterns),
            "entity_field_weights": {f: self.entity_field_weights[f] for f in FIELDS},
            "dictionary": dictionary_fingerprint,
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
        }
