"""合成 OKF bundle 產生器。

存在理由：真實語料為公司機密、開發者無法取得，但程式仍需端到端驗證。

⚠️ 合成資料**僅供驗證程式正確性**。它的詞頻分佈、識別碼密度、模板多樣性都是編造的，
   不得用於調整 BM25 參數、欄位權重、融合權重，也不得用於推論任何檢索效果數字。
   所有效果結論必須來自在真實語料上跑出的報告。
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

DISCLAIMER = (
    "合成資料，僅供驗證程式正確性。\n"
    "不得用於調整參數，也不得用於推論任何檢索效果數字。\n"
    "所有效果結論必須來自真實語料上產出的去識別化報告。\n"
)

# 1x1 透明 PNG，讓 _assets 是真實檔案而非空殼
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fd7fd0ff0000000049454e44ae426082"
)

TOOL_PREFIXES = ["XTR", "LMB", "QDN", "VRC", "TSK"]
CHAMBERS = ["PM1", "PM2", "PM3", "PM4", "PM5", "PM6"]
PROCESSES = ["P-M1ETCH", "P-M2CMP", "P-M3DEP", "P-M4LITHO", "P-M5CLEAN"]
FLOWS = ["FL-A100", "FL-A101", "FL-A102", "FL-A103", "FL-A104"]
DEFECTS = ["PARTICLE", "SCRATCH", "BRIDGE", "RESIDUE", "VOID"]
DEFECT_ALIASES = {
    "PARTICLE": ["particle", "微粒", "顆粒"],
    "SCRATCH": ["scratch", "刮傷"],
    "BRIDGE": ["bridge", "短橋"],
    "RESIDUE": ["residue", "殘留"],
    "VOID": ["void", "空洞"],
}

# 相似識別碼刻意成對存在，用來驗證模式 A 會混淆、模式 B/C 能區分
TOOLS = [f"{p}-{i:02d}" for p in TOOL_PREFIXES for i in range(1, 13)]

TEMPLATES: dict[str, list[str]] = {
    "case_investigation": ["背景", "現象", "量測數據", "分析", "根因", "對策", "後續追蹤"],
    "training": ["學習目標", "原理說明", "操作步驟", "常見錯誤", "小結"],
    "meeting_minutes": ["會議資訊", "進度回報", "議題討論", "決議事項", "待辦追蹤"],
    "spec_definition": ["定義", "量測方法", "規格上下限", "判定準則", "例外處理"],
}

SENTENCES = [
    "於 {tool} 的 {chamber} 觀察到 {defect} 異常，發生站點為 {process}。",
    "本批次沿用 {flow} 流程，於 {process} 之後進行檢測。",
    "比對 {tool} 與 {tool2} 的歷史紀錄，兩者在 {defect} 的表現差異明顯。",
    "量測結果顯示 {defect} 計數自基線上升，需回溯 {flow} 的前段條件。",
    "{chamber} 的腔體狀態在保養後回穩，但 {defect} 仍偶發。",
    "工程師確認 {process} 的參數設定未變更，排除配方調整的可能。",
    "追蹤 {tool} 近三個月的資料，{defect} 呈現週期性復發。",
    "依 {flow} 的判定準則，本次結果落在規格邊界內但趨勢不利。",
    "建議對 {tool} 執行預防性保養，並持續監控 {defect} 的變化。",
    "跨站點比對後認為 {process} 並非主要貢獻來源。",
]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sentence(rng: random.Random) -> str:
    tool = rng.choice(TOOLS)
    tool2 = _sibling(tool)
    defect = rng.choice(DEFECTS)
    text = rng.choice(SENTENCES).format(
        tool=tool,
        tool2=tool2,
        # 腔體綁在機台上（`XTR-05#PM2`）——真實語料就是這樣寫的，機台與腔體同一個識別碼。
        # 早期版本這裡只寫 `PM2`，於是 `#` 的處理從未被合成語料碰到過，
        # 而斷詞器在 `#` 上是壞的卻沒有任何測試會紅。合成資料必須長得像真的，否則它只會確認既有的錯。
        chamber=_chamber_of(tool, rng),
        process=rng.choice(PROCESSES),
        flow=rng.choice(FLOWS),
        defect=rng.choice([defect, *DEFECT_ALIASES[defect]]),
    )
    return text


def _chamber_of(tool: str, rng: random.Random) -> str:
    return f"{tool}#{rng.choice(CHAMBERS)}"


#: 只有一半的機台把腔體列進字典。兩邊都要有，報告的 by_type 拆解才有東西可看——
#: 全部命中或全部落空都無法呈現「覆蓋率缺口」長什麼樣。
def _dictionary_chambers() -> list[str]:
    return [f"{t}#{c}" for t in TOOLS[: len(TOOLS) // 2] for c in CHAMBERS]


def _sibling(tool: str) -> str:
    """回傳僅末碼不同的兄弟機台——這正是模式 A 會搞混、模式 B/C 應該分開的情況。"""
    prefix, num = tool.rsplit("-", 1)
    return f"{prefix}-{(int(num) % 12) + 1:02d}"


def _paragraph(rng: random.Random, n: int) -> str:
    return "".join(_sentence(rng) for _ in range(n))


def _section_body(rng: random.Random, heading: str) -> str:
    lines = [_paragraph(rng, rng.randint(2, 4))]
    if rng.random() < 0.6:
        lines.append("")
        for _ in range(rng.randint(2, 4)):
            lines.append(f"- {_sentence(rng)}")
    lines.append("")
    lines.append(_paragraph(rng, rng.randint(1, 3)))
    return "\n".join(lines)


def _figures(rng: random.Random, n: int) -> list[dict]:
    out = []
    for i in range(n):
        tool = rng.choice(TOOLS)
        defect = rng.choice(DEFECTS)
        out.append(
            {
                "file_id": f"slide_{i + 1:03d}",
                "type": rng.choice(["trend_chart", "wafer_map", "sem_image", "table"]),
                "title": f"{tool} 於 {rng.choice(PROCESSES)} 的 {defect} 分佈",
                "description": f"呈現 {tool} 在 {_chamber_of(tool, rng)} 的 {defect} 計數變化，涵蓋 {rng.choice(FLOWS)} 流程。",
                "key_points": [_sentence(rng) for _ in range(rng.randint(2, 3))],
            }
        )
    return out


def _concept_markdown(rng: random.Random, cid: str, ctype: str, idx: int, bundle_slug: str) -> tuple[str, str, str]:
    headings = TEMPLATES[ctype]
    tool = rng.choice(TOOLS)
    defect = rng.choice(DEFECTS)
    title = f"{tool} {defect} {ctype.replace('_', ' ')} #{idx:02d}"
    slug = f"{bundle_slug}-{idx:02d}"
    description = f"{tool} 於 {rng.choice(PROCESSES)} 出現 {defect}，依 {rng.choice(FLOWS)} 流程檢討。"

    n_fig = max(1, int(rng.gauss(7, 3)))
    figures = _figures(rng, min(n_fig, 14))
    slides = sorted(rng.sample(range(1, 40), rng.randint(2, 5)))
    src = f"{bundle_slug}.pptx"

    body_parts = []
    for heading in headings:
        body_parts.append(f"## {heading}\n\n{_section_body(rng, heading)}\n")

    body_parts.append("## Related Concepts\n")
    body_parts.append(f"- {rng.choice(PROCESSES)} 相關站點說明")
    body_parts.append(f"- [{bundle_slug}-{max(1, idx - 1):02d}.md](./{bundle_slug}-{max(1, idx - 1):02d}.md)\n")

    body_parts.append("## Citations\n")
    for n in slides:
        body_parts.append(f"[{n}] [slide {n}](_assets/slide_{n:03d}.png)")
    body = "\n".join(body_parts) + "\n"

    frontmatter = {
        "id": cid,
        "type": ctype,
        "title": title,
        "slug": slug,
        "description": description,
        "generated": True,
        "content_hash": _hash(body),
        "confidence": rng.choice(["high", "high", "high", "low"]),
        "resource": f"file://{src}#slide={','.join(str(n) for n in slides)}",
        "provenance": f"file://{src}#slide={','.join(str(n) for n in slides)}",
        "tags": rng.sample([defect.lower(), tool.lower(), "yield", "defect", "review", "training"], 3),
        "related": [f"cpt_{_hash(f'{bundle_slug}{max(1, idx - 1)}')[:12]}"],
        "model": "synthetic-generator-0.1",
        "timestamp": (
            datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=rng.randint(0, 540))
        ).isoformat(),
        "assets": [f"_assets/slide_{n:03d}.png" for n in slides],
        "subpath": f"{ctype}/{slug}",
        "figures": figures,
    }
    fm = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False, width=10_000)
    return f"---\n{fm}---\n\n{body}", slug, description


def _summary_markdown(rng: random.Random, bundle_slug: str, concept_ids: list[str]) -> str:
    """刻意採用**無 `---` 分隔線**的 frontmatter，以覆蓋解析器的該條路徑。"""
    fm = {
        "id": f"sum_{_hash(bundle_slug)[:12]}",
        "type": "bundle_summary",
        "title": f"{bundle_slug} 摘要",
        "slug": f"{bundle_slug}-summary",
        "description": f"{bundle_slug} 的整體摘要與涵蓋範圍。",
        "generated": True,
        "content_hash": _hash(bundle_slug),
        "confidence": rng.choice(["high", "low"]),
        "resource": f"derived://{bundle_slug}.pptx",
        "provenance": [f"file://{bundle_slug}.pptx"],
        "tags": ["summary"],
        "related": concept_ids[:5],
        "model": "synthetic-generator-0.1",
        "timestamp": datetime(2026, 6, 1, tzinfo=timezone.utc).isoformat(),
    }
    head = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=10_000)
    body = [
        "## 摘要",
        "",
        _paragraph(rng, 4),
        "",
        "## 涵蓋範圍",
        "",
        *[f"- {rng.choice(PROCESSES)} 至 {rng.choice(PROCESSES)} 的站點" for _ in range(3)],
        "",
        "## 關鍵結論",
        "",
        *[f"- {_sentence(rng)}" for _ in range(3)],
        "",
    ]
    return head + "\n".join(body)


def generate(out_dir: str | Path, n_bundles: int = 30, seed: int = 42) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.txt").write_text(DISCLAIMER, encoding="utf-8")

    rng = random.Random(seed)
    total_concepts = 0

    for bi in range(n_bundles):
        bundle_slug = f"yed-deck-{bi + 1:03d}"
        broot = out / bundle_slug
        okf = broot / "okf"
        assets = okf / "_assets"
        assets.mkdir(parents=True, exist_ok=True)

        for n in range(1, 40):
            (assets / f"slide_{n:03d}.png").write_bytes(_PNG)

        n_concepts = rng.randint(15, 30)
        ctype = rng.choice(list(TEMPLATES))  # 一個 bundle 以單一模板為主，重現類型重複性
        entries: list[tuple[str, str, str, str]] = []

        for ci in range(1, n_concepts + 1):
            cid = f"cpt_{_hash(f'{bundle_slug}{ci}')[:12]}"
            # 少量混入其他模板，避免語料完全同質
            this_type = ctype if rng.random() < 0.85 else rng.choice(list(TEMPLATES))
            text, slug, desc = _concept_markdown(rng, cid, this_type, ci, bundle_slug)
            fname = f"{slug}.md"
            (okf / fname).write_text(text, encoding="utf-8")
            entries.append((cid, this_type, fname, desc))
            total_concepts += 1

        (okf / "summary.md").write_text(
            _summary_markdown(rng, bundle_slug, [e[0] for e in entries]), encoding="utf-8"
        )
        (okf / "log.md").write_text(
            "# 轉換紀錄\n\n"
            + "\n".join(
                f"- {datetime(2026, 6, 1, tzinfo=timezone.utc).isoformat()} 解析 slide 群組 {i + 1}，產出 {e[0]}"
                for i, e in enumerate(entries)
            )
            + "\n",
            encoding="utf-8",
        )
        (okf / "index.md").write_text(
            "[摘要](summary.md) [轉換紀錄](log.md)\n\n"
            + "\n".join(f"{cid} . {ctype_} . [{fn}]({fn}) . {desc}" for cid, ctype_, fn, desc in entries)
            + "\n",
            encoding="utf-8",
        )
        (broot / "manifest.json").write_text(
            json.dumps(
                {
                    "id": f"bdl_{_hash(bundle_slug)[:12]}",
                    "name": bundle_slug,
                    "source_file": f"{bundle_slug}.pptx",
                    "doc_type": ctype,
                    "concept_count": n_concepts,
                    "generated": True,
                    "synthetic": True,
                    "created": datetime(2026, 6, 1, tzinfo=timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    dict_path = out / "dictionary.yaml"
    dict_path.write_text(_dictionary_yaml(), encoding="utf-8")

    return {
        "out_dir": str(out),
        "bundles": n_bundles,
        "concepts": total_concepts,
        "dictionary": str(dict_path),
        "disclaimer": DISCLAIMER.strip(),
    }


def _dictionary_yaml() -> str:
    data = {
        "tool_id": [{"canonical": t} for t in TOOLS],
        "chamber": [{"canonical": c} for c in CHAMBERS],
        "chamber_id": [{"canonical": c} for c in _dictionary_chambers()],
        "process_id": [{"canonical": p} for p in PROCESSES],
        "flow_id": [{"canonical": f} for f in FLOWS],
        "defect_code": [{"canonical": d, "aliases": DEFECT_ALIASES[d]} for d in DEFECTS],
    }
    header = "# 合成語料配套字典 — 由 yedai gen-synthetic 產生，僅供程式驗證。\n"
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=10_000)
