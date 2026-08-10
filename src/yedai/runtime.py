"""HTTP 與 MCP 共用的載入路徑。

兩個介面都需要 config → dictionary → indexes → searchers → store 這條完全相同的鏈。
複製兩份必然在某次修改後分歧（其中一邊忘了驗簽章、另一邊用了不同的預設路徑），
而分歧的症狀是「同一個查詢在 HTTP 與 MCP 給出不同結果」——極難察覺。

向量庫在這裡一併建立。先前這條路徑建 `Searcher` 時不帶 `vectors`，於是模式 D/E
在 HTTP 與 MCP 通過參數驗證卻必定失敗——稠密腿只在 CLI 可用。分層之後每個索引
各自宣告 collection，載入路徑本來就要重寫，那個缺口在這裡順帶補上。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .embedding import build_embedder, load_dotenv
from .entities import EntityDictionary
from .index import Index
from .layers import LayeredSearcher
from .search import Searcher, VectorSearcher
from .taxonomy import Taxonomy
from .telemetry import TelemetryStore
from .vectors import VectorBackend

ENV_CONFIG = "YEDAI_CONFIG"


@dataclass
class Runtime:
    config: Config
    dictionary: EntityDictionary
    layered: LayeredSearcher
    taxonomy: Taxonomy
    store: TelemetryStore
    #: 全部索引共用的向量 backend。`None` 表示沒有任何索引宣告 collection。
    backend: VectorBackend | None = None

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Runtime:
        """明確參數 > 環境變數 > 內建預設值。"""
        cfg = Config.load(config_path or os.environ.get(ENV_CONFIG) or None)
        dictionary = EntityDictionary.from_config(cfg)
        specs = cfg.index_specs()

        # 一個 backend 服務全部 collection。每層各開一個 client 會讓本機檔案模式的
        # qdrant 在第二層就撞上獨佔鎖——而那時錯誤指向 qdrant，不指向設定。
        backend: VectorBackend | None = None
        if any(spec.collection for spec in specs.values()):
            load_dotenv()
            backend = VectorBackend(
                path=cfg.vector.get("path"),
                url=cfg.vector.get("url"),
                api_key=_env_or_none(cfg.vector.get("api_key_env")),
            )

        vectors: dict[str, VectorSearcher] = {}
        if backend is not None:
            embedder = build_embedder(cfg)
            for name, spec in specs.items():
                if not spec.collection:
                    continue
                store = backend.store(int(cfg.embedding["dim"]), spec.collection)
                # 沒有向量時不接上，讓該層的 D/E 明確「不可用」而不是回零筆——
                # 後者看起來像「稠密腿沒有用」，而那是會被當成結論的假象。
                if store.has_vectors():
                    vectors[name] = VectorSearcher(store, embedder)

        return cls(
            config=cfg,
            dictionary=dictionary,
            layered=LayeredSearcher.load(cfg, dictionary, vectors),
            taxonomy=Taxonomy.from_config(cfg),
            store=TelemetryStore.create(cfg),
            backend=backend,
        )

    # ------------------------------------------------------------------

    @property
    def index_names(self) -> list[str]:
        return self.layered.names

    def searcher(self, name: str | None = None) -> Searcher:
        """未指定名稱時回傳唯一的那一層；有多層時要求明確指定。

        多層時猜一個回傳，症狀會是「我查的是這一層嗎」——而呼叫端沒有辦法知道。
        """
        if name is not None:
            return self.layered.searcher(name)
        names = self.layered.names
        if len(names) != 1:
            raise ValueError(
                f"有 {len(names)} 個索引（{sorted(names)}），請明確指定要哪一個"
            )
        return self.layered.searcher(names[0])

    def index(self, name: str | None = None) -> Index:
        return self.searcher(name).index

    def close(self) -> None:
        if self.backend is not None:
            self.backend.close()


def _env_or_none(name: str | None) -> str | None:
    return os.environ.get(name) if name else None
