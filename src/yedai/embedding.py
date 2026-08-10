"""Embedding 客戶端：OpenAI 相容的 `/embeddings`，不認得任何一家供應商。

開發期 base_url 指向 OpenRouter，production 指向 LiteLLM 代理的 self-host vLLM——
兩者只差設定。把供應商寫進程式的代價不是重寫成本，是「開發跟 production 跑的不是同一條路」，
於是開發期驗過的東西在 production 不算數。

金鑰只從環境變數讀。設定檔會進版控，而這個 repo 是公開的。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Protocol, Sequence

import httpx


class EmbeddingError(RuntimeError):
    pass


def load_dotenv(path: Path = Path(".env")) -> None:
    """把 `.env` 讀進環境變數。已存在的變數不覆蓋——explicit export 應該贏過檔案。

    放在這裡而不是 CLI：HTTP 與 MCP 也要建 embedder，而金鑰只從環境變數讀。
    留在 CLI 的話，走 API 起服務時金鑰會神秘地讀不到。
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def build_embedder(cfg) -> "CachedEmbedder":
    """由設定建立帶快取的 embedder。所有入口一律走這裡。

    分成兩個入口的話，其中一邊遲早會忘記包快取，而症狀是「同一組查詢重跑要再付一次費」。
    """
    load_dotenv()
    e = cfg.embedding
    client = HttpEmbeddingClient(
        base_url=e["base_url"],
        model=e["model"],
        dim=int(e["dim"]),
        api_key_env=e["api_key_env"],
        batch_size=int(e.get("batch_size", 32)),
        timeout=float(e.get("timeout", 60.0)),
        max_retries=int(e.get("max_retries", 4)),
    )
    return CachedEmbedder(client, e.get("cache_dir"))


class EmbeddingClient(Protocol):
    """讓測試能離線替換。測試觸網會同時變慢、變不穩、變貴，最後的下場是被跳過。"""

    dim: int
    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HttpEmbeddingClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        dim: int,
        api_key_env: str,
        batch_size: int = 32,
        timeout: float = 60.0,
        max_retries: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.api_key_env = api_key_env
        self.batch_size = max(1, batch_size)
        self.timeout = timeout
        self.max_retries = max_retries

    def _key(self) -> str:
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise EmbeddingError(
                f"缺少環境變數 {self.api_key_env}。金鑰不放設定檔——設定檔會進版控。\n"
                f"請寫進 .env（已 gitignore）或直接 export。"
            )
        return key

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            out.extend(self._embed_batch(list(texts[start : start + self.batch_size])))
        return out

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        if not batch:
            return []
        payload = {"model": self.model, "input": batch}
        headers = {"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json"}
        data = self._post(payload, headers)

        # **依 `index` 還原順序**，不假設回應順序等於輸入順序。規格沒有保證這件事，
        # 而順序錯位不會報錯——它只會讓每個 concept 配到別人的向量，
        # 然後檢索結果變成隨機，卻沒有任何徵兆指向這裡。
        rows = data.get("data")
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise EmbeddingError(f"回應筆數 {len(rows) if isinstance(rows, list) else '?'} 與輸入 {len(batch)} 不符")
        vectors: list[list[float] | None] = [None] * len(batch)
        for row in rows:
            idx = row.get("index")
            vec = row.get("embedding")
            if not isinstance(idx, int) or not (0 <= idx < len(batch)):
                raise EmbeddingError(f"回應的 index 無效：{idx!r}")
            if not isinstance(vec, list):
                raise EmbeddingError("回應缺少 embedding")
            if len(vec) != self.dim:
                raise EmbeddingError(
                    f"維度不符：設定 {self.dim}，端點回傳 {len(vec)}（model={self.model}）。\n"
                    f"維度不符若被接受，相似度仍會算出看似正常的數字，而錯誤不會有任何徵兆。"
                )
            vectors[idx] = [float(x) for x in vec]
        if any(v is None for v in vectors):
            raise EmbeddingError("回應未涵蓋全部輸入")
        return vectors  # type: ignore[return-value]

    def _post(self, payload: dict, headers: dict) -> dict:
        url = f"{self.base_url}/embeddings"
        delay = 1.0
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                # 429／5xx 是暫時性的，值得退避重試；4xx 其餘是設定錯誤，重試只是浪費時間與金錢。
                if resp.status_code != 429 and resp.status_code < 500:
                    raise EmbeddingError(f"{url} 回傳 {resp.status_code}：{resp.text[:300]}")
                last = EmbeddingError(f"{url} 回傳 {resp.status_code}")
            except httpx.HTTPError as exc:
                last = exc
            if attempt < self.max_retries - 1:
                time.sleep(delay)
                delay *= 2
        raise EmbeddingError(f"{url} 重試 {self.max_retries} 次仍失敗：{last}")


class CachedEmbedder:
    """落地快取。實驗的常態是拿同一份 queries.txt 反覆重跑。

    不快取的話每次重跑都要付費與等待，而那會直接減少實驗被執行的次數——
    一個跑得夠便宜的量測才會真的被拿來用。

    快取鍵含模型與維度：換模型後沿用舊向量會產出無聲的錯誤結果。
    """

    def __init__(self, inner: EmbeddingClient, cache_dir: Path | str | None) -> None:
        self.inner = inner
        self.dim = inner.dim
        self.model = inner.model
        self.dir = Path(cache_dir) if cache_dir else None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def _path(self, text: str) -> Path | None:
        if not self.dir:
            return None
        digest = hashlib.sha256(
            json.dumps([self.model, self.dim, text], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return self.dir / f"{digest}.json"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float] | None] = [None] * len(texts)
        pending: list[int] = []
        for i, text in enumerate(texts):
            path = self._path(text)
            if path and path.exists():
                out[i] = json.loads(path.read_text(encoding="utf-8"))
                self.hits += 1
            else:
                pending.append(i)
        if pending:
            self.misses += len(pending)
            fresh = self.inner.embed([texts[i] for i in pending])
            for i, vec in zip(pending, fresh, strict=True):
                out[i] = vec
                path = self._path(texts[i])
                if path:
                    path.write_text(json.dumps(vec), encoding="utf-8")
        return out  # type: ignore[return-value]
