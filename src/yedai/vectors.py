"""向量儲存（Qdrant）與語料外流閘門。

未指定伺服器位址時走本機檔案模式。要求使用者先架一套服務，實際效果是這個實驗不會被跑——
架設成本會直接變成「之後再說」的理由，而「之後」不會來。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import QdrantClient, models

#: 合成語料產生器寫下的免責檔。用它判定「這份語料是編造的」。
SYNTHETIC_MARKER = "README.txt"
SYNTHETIC_PHRASE = "僅供驗證程式正確性"


class CorpusLeakGuard(RuntimeError):
    pass


def is_synthetic_corpus(root: Path | str) -> bool:
    marker = Path(root) / SYNTHETIC_MARKER
    if not marker.is_file():
        return False
    try:
        return SYNTHETIC_PHRASE in marker.read_text(encoding="utf-8")
    except OSError:
        return False


def guard_corpus_leaves_process(
    root: Path | str, base_url: str, trusted: bool, config_key: str = "embedding"
) -> None:
    """把 concept 全文送出程序之前的最後一道閘。

    擋的不是惡意，是「拿開發設定跑了真語料」這種一次就無法挽回的意外——
    送出去就收不回來，所以預設必須是拒絕，而不是警告。

    合成語料不受限：它本來就是編造的，而拿它驗證程式正確性是常態操作。
    每次都要解閘的閘門會被找方法繞過，那就等於沒有閘門。
    """
    if trusted or is_synthetic_corpus(root):
        return
    raise CorpusLeakGuard(
        f"拒絕執行：這會把 {Path(root)} 的 concept 全文送到\n"
        f"    {base_url}\n"
        f"而該語料不是合成的。語料一旦送出就收不回來。\n\n"
        f"若該端點確實是可信的（例如自架的 LiteLLM），在設定中宣告：\n"
        f"    {config_key}:\n      trusted_endpoint: true\n\n"
        f"注意 `embedding` 與 `llm` 的宣告**各自獨立**——把信任從一個端點自動延伸到"
        f"另一個，正是這道閘門要防的事，即使兩者指向同一個位址。"
    )


@dataclass
class VectorHit:
    concept_id: str
    score: float


class VectorStore:
    def __init__(
        self,
        dim: int,
        path: Path | str | None = None,
        url: str | None = None,
        collection: str = "yedai",
        api_key: str | None = None,
    ) -> None:
        self.dim = dim
        self.collection = collection
        if url:
            self.client = QdrantClient(url=url, api_key=api_key)
        elif path is None:
            self.client = QdrantClient(":memory:")
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))

    def ensure_collection(self) -> None:
        """維度不符的既有集合必須重建，不能沿用。

        Qdrant 會直接拒絕維度不符的寫入，但若沿用集合而寫入失敗一半，
        留下的是一份「部分是舊模型、部分是新模型」的向量庫——
        那種混合不會報錯，只會讓相似度在不同文件之間不可比。
        """
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection in existing:
            info = self.client.get_collection(self.collection)
            current = info.config.params.vectors
            size = current.size if hasattr(current, "size") else None
            if size == self.dim:
                return
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE),
        )

    def upsert(self, items: list[tuple[str, list[float]]]) -> None:
        if not items:
            return
        points = [
            models.PointStruct(
                # concept_id 是字串，Qdrant 的 id 只收 int 或 UUID——
                # 由 concept_id 導出 UUID 使同一個 concept 重跑時覆蓋而非重複寫入。
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, cid)),
                vector=vec,
                payload={"concept_id": cid},
            )
            for cid, vec in items
        ]
        self.client.upsert(self.collection, points=points)

    def search(self, vector: list[float], k: int) -> list[VectorHit]:
        points = self.client.query_points(self.collection, query=vector, limit=k).points
        return [VectorHit(concept_id=p.payload["concept_id"], score=float(p.score)) for p in points]

    def count(self) -> int:
        return int(self.client.count(self.collection).count)

    def has_vectors(self) -> bool:
        try:
            existing = {c.name for c in self.client.get_collections().collections}
            return self.collection in existing and self.count() > 0
        except Exception:
            return False

    def close(self) -> None:
        self.client.close()
