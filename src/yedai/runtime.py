"""HTTP 與 MCP 共用的載入路徑。

兩個介面都需要 config → dictionary → index → searcher → store 這條完全相同的鏈。
複製兩份必然在某次修改後分歧（其中一邊忘了驗簽章、另一邊用了不同的預設路徑），
而分歧的症狀是「同一個查詢在 HTTP 與 MCP 給出不同結果」——極難察覺。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .entities import EntityDictionary
from .index import Index
from .search import Searcher
from .telemetry import TelemetryStore

ENV_CONFIG = "YEDAI_CONFIG"
ENV_INDEX = "YEDAI_INDEX"


@dataclass
class Runtime:
    config: Config
    dictionary: EntityDictionary
    index: Index
    searcher: Searcher
    store: TelemetryStore

    @classmethod
    def load(
        cls,
        config_path: str | Path | None = None,
        index_path: str | Path | None = None,
    ) -> Runtime:
        """明確參數 > 環境變數 > 設定檔預設值。"""
        cfg = Config.load(config_path or os.environ.get(ENV_CONFIG) or None)
        dictionary = EntityDictionary.from_config(cfg)
        index = Index.load(index_path or os.environ.get(ENV_INDEX) or cfg.index_path)
        index.check_signature(cfg.index_signature(dictionary.fingerprint()))
        return cls(
            config=cfg,
            dictionary=dictionary,
            index=index,
            searcher=Searcher(index, cfg, dictionary),
            store=TelemetryStore.create(cfg),
        )
