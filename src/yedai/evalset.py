"""LLM 產生的評估集，與依模式、依查詢種類拆解的檢索指標。

`mode_overlap` 只能說五個模式**不一樣**，說不出哪個**比較對**——因為沒有標準答案。
這個模組補的就是標準答案：讓 LLM 讀一篇 concept，產出「這篇文件是哪個問題的答案」。

標籤有兩個必須一直帶著的偏誤，見 `EVALSET_CAVEATS`。
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .index import Index

IDENTIFIER_KIND = "identifier"
SYMPTOM_KIND = "symptom"
KINDS = (IDENTIFIER_KIND, SYMPTOM_KIND)

EVALSET_CAVEATS = (
    "標籤只涵蓋單一相關文件：同一個查詢很可能有別的 concept 答得一樣好，"
    "而那些會被算成未命中。所以 recall@k 是下界、MRR 偏低，絕對值不可外推。",
    "五個模式面對同一組標籤與同一組偏誤，所以模式之間的相對差距成立。"
    "要下的結論是「B 比 A 好多少」，不是「B 的絕對 recall 是多少」。",
    "LLM 看著文件寫查詢會照抄罕見詞，使關鍵字模式虛胖、稠密腿被低估。"
    "提示詞只能壓抑而無法消除它，所以指標必須依查詢種類拆解。",
)

SYSTEM_PROMPT = (
    "你是半導體廠的資深製程／設備工程師。你要提出你在日常工作中會真的打進檢索框的問題。\n"
    "只輸出 JSON 陣列，不要任何說明文字。"
)

USER_TEMPLATE = """下面是一份內部知識文件。

請設想一位**沒有讀過這份文件**的工程師，他遇到了這份文件能解答的問題。寫出他會怎麼查。

輸出 JSON 陣列，每項為 {{"query": "...", "kind": "identifier" 或 "symptom"}}：

- `identifier` — {n_id} 條，會帶上文件裡出現的機台／批號／站點等識別碼
- `symptom` — {n_sym} 條，**完全不含任何識別碼與專有代號**，只描述現象、目的或條件

要求：
- 用工程師實際會打的長度與語氣，中英夾雜沒關係
- 不要照抄文件標題，也不要抄文件裡的整句話
- `symptom` 那幾條必須在不知道任何代號的情況下也問得出來

---
{text}
---"""


@dataclass
class EvalItem:
    query: str
    gold_concept_id: str
    kind: str


@dataclass
class EvalSet:
    items: list[EvalItem] = field(default_factory=list)
    #: 取樣了幾個 concept、其中幾個產生失敗。失敗數要看得見——
    #: 靜靜跳過會讓評估集悄悄偏向「LLM 剛好答得出來的那些文件」。
    sampled: int = 0
    failed: int = 0
    model: str = ""

    def by_kind(self) -> dict[str, list[EvalItem]]:
        out: dict[str, list[EvalItem]] = {}
        for item in self.items:
            out.setdefault(item.kind, []).append(item)
        return out


def sample_concepts(index: Index, n: int, seed: int = 7) -> list[int]:
    """跨 type 分層取樣。

    全部擠在同一類會讓評估集反映的是那一類的性質。真實查詢會落在各種文件上，
    而不同 type 的文件結構差很多（case_investigation 有數據、training 沒有）。
    """
    rng = random.Random(seed)
    by_type: dict[str, list[int]] = {}
    for i, meta in enumerate(index.docs):
        by_type.setdefault(meta.type, []).append(i)
    for docs in by_type.values():
        rng.shuffle(docs)

    out: list[int] = []
    types = sorted(by_type)
    cursor = 0
    while len(out) < n and any(by_type[t] for t in types):
        t = types[cursor % len(types)]
        if by_type[t]:
            out.append(by_type[t].pop())
        cursor += 1
    return out[:n]


def generate(
    index: Index,
    chat,
    n_concepts: int,
    text_of,
    n_identifier: int = 2,
    n_symptom: int = 1,
    seed: int = 7,
    max_chars: int = 4000,
) -> EvalSet:
    """對取樣到的每個 concept 各發一次請求，收集 (查詢, 標準答案, 種類)。"""
    picked = sample_concepts(index, n_concepts, seed=seed)
    out = EvalSet(sampled=len(picked), model=getattr(chat, "model", ""))

    for doc in picked:
        meta = index.docs[doc]
        prompt = USER_TEMPLATE.format(
            n_id=n_identifier, n_sym=n_symptom, text=text_of(meta)[:max_chars]
        )
        try:
            from .llm import parse_json_block

            rows = parse_json_block(chat.complete(SYSTEM_PROMPT, prompt))
            if not isinstance(rows, list):
                raise ValueError("回應不是陣列")
        except Exception:
            # 單一 concept 失敗不該讓整批中止——一批可能是幾百次請求，
            # 為了一次格式異常全部重來，代價是這個工具不會被再跑第二次。
            out.failed += 1
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            query = str(row.get("query", "")).strip()
            kind = str(row.get("kind", "")).strip()
            if query and kind in KINDS:
                out.items.append(EvalItem(query, meta.concept_id, kind))

    return out


# --- 落地 ---------------------------------------------------------------


def dump(es: EvalSet, path: Path | str) -> None:
    """JSONL，第一行是帶著偏誤說明的檔頭。

    偏誤必須跟著資料走。寫在文件裡的警語會與資料分家，而分家之後，
    絕對值遲早會被引用到不該被引用的地方。
    """
    lines = [
        json.dumps(
            {
                "_header": True,
                "model": es.model,
                "sampled": es.sampled,
                "failed": es.failed,
                "items": len(es.items),
                "caveats": list(EVALSET_CAVEATS),
                "note": "含真實語料衍生的查詢，不要進版控。",
            },
            ensure_ascii=False,
        )
    ]
    lines += [json.dumps(asdict(i), ensure_ascii=False) for i in es.items]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def load(path: Path | str) -> EvalSet:
    es = EvalSet()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("_header"):
            es.sampled = int(row.get("sampled", 0))
            es.failed = int(row.get("failed", 0))
            es.model = str(row.get("model", ""))
            continue
        es.items.append(EvalItem(row["query"], row["gold_concept_id"], row["kind"]))
    return es


# --- 指標 ---------------------------------------------------------------


def _metrics(ranks: list[int | None], k: int) -> dict[str, Any]:
    """`ranks` 為每個查詢中標準答案的名次（1 起算），未命中為 None。

    未命中**計入分母**。把找不到的查詢排除會讓表現差的模式看起來更好——
    那正好是這份量測要分辨的東西。
    """
    n = len(ranks)
    if not n:
        return {"n": 0, "recall_at_k": None, "mrr": None}
    hit = sum(1 for r in ranks if r is not None and r <= k)
    mrr = sum(1.0 / r for r in ranks if r is not None and r <= k) / n
    return {"n": n, "recall_at_k": round(hit / n, 4), "mrr": round(mrr, 4)}


def evaluate(es: EvalSet, searcher, k: int = 10) -> dict[str, Any]:
    """對每個**可用**模式算 recall@k 與 MRR，並依查詢種類拆解。"""
    modes = list(searcher.available_modes)
    ranks: dict[str, list[int | None]] = {m: [] for m in modes}
    ranks_by_kind: dict[str, dict[str, list[int | None]]] = {
        m: {kind: [] for kind in KINDS} for m in modes
    }

    for item in es.items:
        for mode in modes:
            ids = searcher.search(item.query, mode=mode, k=k).ids
            rank = ids.index(item.gold_concept_id) + 1 if item.gold_concept_id in ids else None
            ranks[mode].append(rank)
            if item.kind in ranks_by_kind[mode]:
                ranks_by_kind[mode][item.kind].append(rank)

    return {
        "k": k,
        "items": len(es.items),
        "model": es.model,
        # 限制跟著數字走。分家之後絕對值遲早會被引用到不該被引用的地方。
        "caveats": list(EVALSET_CAVEATS),
        "overall": {m: _metrics(ranks[m], k) for m in modes},
        "by_kind": {
            m: {kind: _metrics(rows, k) for kind, rows in kinds.items()}
            for m, kinds in ranks_by_kind.items()
        },
    }


def iter_queries(es: EvalSet) -> Iterable[str]:
    return (i.query for i in es.items)
