"""yedai — OKF bundle 關鍵字檢索 baseline harness。

在投入混合檢索與實體向量之前，先量出純關鍵字檢索的水位線，
並用 A/B/C 三組消融回答：識別碼到底需不需要特別處理？
"""

from .config import FIELDS, Config
from .entities import EntityDictionary, EntityExtractor, EntityHit
from .fulltext import ConceptFileMissing, ConceptNotFound, ConceptPathEscape, load_concept
from .index import Index, build_index
from .models import Bundle, Concept, Figure, Section
from .parser import load_bundles
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
    "ModeResult",
    "SearchOutcome",
    "Searcher",
    "Section",
    "TelemetryStore",
    "Tokenizer",
    "build_index",
    "build_report",
    "load_bundles",
    "load_concept",
    "normalise_identifier",
    "__version__",
]
