"""yedai — OKF bundle 關鍵字檢索 baseline harness。

在投入混合檢索與實體向量之前，先量出純關鍵字檢索的水位線，
並用 A/B/C 三組消融回答：識別碼到底需不需要特別處理？
"""

from .config import FIELDS, Config
from .entities import EntityDictionary, EntityExtractor, EntityHit
from .fulltext import (
    ConceptFileMissing,
    ConceptNotFound,
    ConceptPathEscape,
    load_concept,
    load_concepts,
)
from .graph import neighbors
from .grep import InvalidPattern, ScopeRequired, UnknownScope, grep
from .index import Index, build_index
from .models import Bundle, Concept, Figure, Section
from .parser import load_bundles
from .runtime import Runtime
from .search import MODES, Hit, ModeResult, SearchOutcome, Searcher
from .telemetry import TelemetryStore, build_report
from .tokenizer import Tokenizer, normalise_identifier

__version__ = "0.1.0"

__all__ = [
    "FIELDS",
    "MODES",
    "Bundle",
    "Concept",
    "ConceptFileMissing",
    "ConceptNotFound",
    "ConceptPathEscape",
    "Config",
    "EntityDictionary",
    "EntityExtractor",
    "EntityHit",
    "Figure",
    "Hit",
    "Index",
    "InvalidPattern",
    "ModeResult",
    "Runtime",
    "ScopeRequired",
    "SearchOutcome",
    "Searcher",
    "Section",
    "TelemetryStore",
    "Tokenizer",
    "UnknownScope",
    "build_index",
    "build_report",
    "grep",
    "load_bundles",
    "load_concept",
    "load_concepts",
    "neighbors",
    "normalise_identifier",
    "__version__",
]
