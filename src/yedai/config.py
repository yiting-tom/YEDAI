"""設定。所有影響實驗結果的參數都必須能從這裡覆寫並被記錄下來，否則實驗不可重現。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .tokenizer import DEFAULT_IDENTIFIER_PATTERNS

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
    identifier_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IDENTIFIER_PATTERNS))

    # --- BM25F ---
    k1: float = 1.2
    b: float = 0.75
    field_weights: dict[str, float] = field(default_factory=_default_field_weights)

    # --- 實體 ---
    dictionary_path: str | None = None
    entity_field_weights: dict[str, float] = field(default_factory=_default_entity_weights)
    require_entities: bool = False

    # --- 模式 C 融合 ---
    fusion_lexical: float = 0.4
    fusion_entity: float = 0.6

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

    # ------------------------------------------------------------------

    def field_weight_vector(self) -> list[float]:
        return [float(self.field_weights[f]) for f in FIELDS]

    def entity_weight_vector(self) -> dict[str, float]:
        return {f: float(self.entity_field_weights[f]) for f in FIELDS}

    def max_entity_weight(self) -> float:
        return max(self.entity_field_weights[f] for f in FIELDS)

    def index_signature(self, dictionary_fingerprint: str = "") -> str:
        """只涵蓋會改變索引內容的設定；計分權重在查詢期套用，不影響快取有效性。"""
        payload = {
            "fields": list(FIELDS),
            "identifier_patterns": list(self.identifier_patterns),
            "entity_field_weights": {f: self.entity_field_weights[f] for f in FIELDS},
            "dictionary": dictionary_fingerprint,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

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
