"""Chat 客戶端：OpenAI 相容的 `/chat/completions`，與 embedding 同一套結構。

供應商同樣不寫進程式。內部的 LiteLLM 代理 Kimi 與外部服務只差 base_url 與 model，
把任何一家綁進程式的代價是「開發跟 production 跑的不是同一條路」。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Protocol

import httpx


class ChatError(RuntimeError):
    pass


class ChatClient(Protocol):
    """讓測試能離線替換。測試觸網會變慢、變不穩、變貴，最後的下場是被跳過。"""

    model: str

    def complete(self, system: str, user: str) -> str: ...


class HttpChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str,
        temperature: float = 0.0,
        timeout: float = 120.0,
        max_retries: int = 4,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_env = api_key_env
        # 溫度預設 0：評估集重跑時應該盡量得到同一組標籤，否則兩次評估無法比較。
        # LLM 不保證決定性，所以還有快取這一層。
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def _key(self) -> str:
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise ChatError(
                f"缺少環境變數 {self.api_key_env}。金鑰不放設定檔——設定檔會進版控。"
            )
        return key

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self._key()}", "Content-Type": "application/json"}
        data = self._post(payload, headers)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatError(f"回應結構不符預期：{str(data)[:300]}") from exc

    def _post(self, payload: dict, headers: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        delay = 1.0
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.json()
                # 429／5xx 是暫時性的；其餘 4xx 是設定錯誤，重試只是浪費時間與配額。
                if resp.status_code != 429 and resp.status_code < 500:
                    raise ChatError(f"{url} 回傳 {resp.status_code}：{resp.text[:300]}")
                last = ChatError(f"{url} 回傳 {resp.status_code}")
            except httpx.HTTPError as exc:
                last = exc
            if attempt < self.max_retries - 1:
                time.sleep(delay)
                delay *= 2
        raise ChatError(f"{url} 重試 {self.max_retries} 次仍失敗：{last}")


class CachedChat:
    """落地快取，鍵含模型名稱。

    產一次評估集要對每個取樣 concept 各發一次請求。不快取的話，任何一次調整
    （改提示、改取樣數）都要整批重付——而那會讓「調整」變成不敢做的事。

    鍵含模型：換模型後沿用舊標籤會讓兩批標籤混在一起，而混合的標籤集
    無法對應到任何一個可解釋的產生過程。
    """

    def __init__(self, inner: ChatClient, cache_dir: Path | str | None) -> None:
        self.inner = inner
        self.model = inner.model
        self.dir = Path(cache_dir) if cache_dir else None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def _path(self, system: str, user: str) -> Path | None:
        if not self.dir:
            return None
        digest = hashlib.sha256(
            json.dumps([self.model, system, user], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return self.dir / f"{digest}.txt"

    def complete(self, system: str, user: str) -> str:
        path = self._path(system, user)
        if path and path.exists():
            self.hits += 1
            return path.read_text(encoding="utf-8")
        self.misses += 1
        out = self.inner.complete(system, user)
        if path:
            path.write_text(out, encoding="utf-8")
        return out


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def parse_json_block(text: str) -> Any:
    """從 LLM 回應裡取出 JSON。

    模型很常把 JSON 包在 ```json 圍欄裡，或在前後加一句「以下是結果：」。
    嚴格解析會讓一個純粹的格式習慣變成整批失敗，所以這裡容忍那幾種包裝——
    但**不**嘗試修復畸形的 JSON：那會把「模型答錯了」變成「我們猜它想說什麼」。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("回應為空")
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    else:
        # 沒有圍欄時，取第一個 `[` 或 `{` 到最後一個對應括號之間
        starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
        if starts:
            start = min(starts)
            end = max(text.rfind("]"), text.rfind("}"))
            if end > start:
                text = text[start : end + 1]
    return json.loads(text)
