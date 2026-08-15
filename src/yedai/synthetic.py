"""合成 OKF bundle 產生器。

存在理由：真實語料為公司機密、開發者無法取得，但程式仍需端到端驗證。

產出的是一份**分層**資料集：三層語料性質各異，外加它們共同依賴的字典、CSV 實體來源、
taxonomy、defect 全集、識別碼樣本，與一份指向以上全部的設定。三層若性質相同，
統計隔離與 query 前處理的效果在這份資料上就無法被觀察到——那樣的資料集跑得起來，
但證明不了任何事。

⚠️ 合成資料**僅供驗證程式正確性**。它的詞頻分佈、識別碼密度、模板多樣性都是編造的，
   不得用於調整 BM25 參數、欄位權重、融合權重，也不得用於推論任何檢索效果數字。
   所有效果結論必須來自在真實語料上跑出的報告。
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

DISCLAIMER = (
    "合成資料，僅供驗證程式正確性。\n"
    "不得用於調整參數，也不得用於推論任何檢索效果數字。\n"
    "所有效果結論必須來自真實語料上產出的去識別化報告。\n"
)

#: 產物檔頭。每一份衍生檔都要帶上——資料集越完整，越容易被誤當成基準。
_HEADER = "".join(f"# {line}\n" for line in DISCLAIMER.strip().splitlines())

# 1x1 透明 PNG，讓 _assets 是真實檔案而非空殼
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fd7fd0ff0000000049454e44ae426082"
)

TOOL_PREFIXES = ["XTR", "LMB", "QDN", "VRC", "TSK"]
CHAMBERS = ["PM1", "PM2", "PM3", "PM4", "PM5", "PM6"]
PROCESSES = ["P-M1ETCH", "P-M2CMP", "P-M3DEP", "P-M4LITHO", "P-M5CLEAN"]
FLOWS = ["FL-A100", "FL-A101", "FL-A102", "FL-A103", "FL-A104"]

# 相似識別碼刻意成對存在，用來驗證模式 A 會混淆、模式 B/C 能區分
TOOLS = [f"{p}-{i:02d}" for p in TOOL_PREFIXES for i in range(1, 13)]


# --------------------------------------------------------------------------
# defect 全集 —— 衍生產物的單一事實來源
#
# 一個 defect 要同時出現在字典、CSV、taxonomy、defect 全集檔與登錄層語料裡。
# 各檔各寫一份的話它們會慢慢漂開，而漂開的症狀（覆蓋率突然掉、字典對不到 code）
# 都會被誤讀成程式的錯。全部值皆為編造。
# --------------------------------------------------------------------------

#: taxonomy 狀態。三種都必須存在——覆蓋率恆為滿的資料集無法暴露覆蓋率統計本身的錯誤。
TAX_FULL = "full"  # 有描述也有判斷方法
TAX_NO_METHOD = "no_method"  # 已登錄，方法尚未整理
TAX_ABSENT = "absent"  # 不在 taxonomy 中


@dataclass(frozen=True)
class DefectSpec:
    code: str
    name: str
    aliases: tuple[str, ...]
    category: str
    module: str
    taxonomy: str


DEFECT_CATALOGUE: tuple[DefectSpec, ...] = (
    DefectSpec("PARTICLE", "微粒", ("particle", "微粒", "顆粒"), "particle", "ETCH", TAX_FULL),
    DefectSpec("SCRATCH", "刮傷", ("scratch", "刮傷"), "physical", "CMP", TAX_FULL),
    DefectSpec("BRIDGE", "短橋", ("bridge", "短橋"), "pattern", "PHOTO", TAX_FULL),
    DefectSpec("RESIDUE", "殘留", ("residue", "殘留"), "residue", "CLEAN", TAX_FULL),
    DefectSpec("VOID", "空洞", ("void", "空洞"), "film", "THIN", TAX_FULL),
    DefectSpec("COLLAPSE", "圖案倒塌", ("collapse", "倒塌"), "pattern", "PHOTO", TAX_FULL),
    DefectSpec("DELAM", "剝離", ("delamination", "剝離"), "film", "THIN", TAX_FULL),
    DefectSpec("HAZE", "霧化", ("haze", "霧化"), "film", "CLEAN", TAX_FULL),
    DefectSpec("PIT", "凹坑", ("pit", "凹坑"), "physical", "ETCH", TAX_FULL),
    DefectSpec("STAIN", "水痕", ("stain", "水痕"), "residue", "CLEAN", TAX_FULL),
    DefectSpec("CRACK", "裂痕", ("crack", "裂痕"), "physical", "CMP", TAX_NO_METHOD),
    DefectSpec("MOUND", "凸起", ("mound", "凸起"), "film", "DEP", TAX_NO_METHOD),
    DefectSpec("DISCOLOR", "變色", ("discolor", "變色"), "film", "DIFF", TAX_NO_METHOD),
    DefectSpec("FLAKE", "剝落物", ("flake", "剝落物"), "particle", "DEP", TAX_ABSENT),
    DefectSpec("HILLOCK", "丘狀突起", ("hillock", "丘狀突起"), "film", "DIFF", TAX_ABSENT),
    DefectSpec("BURR", "毛邊", ("burr", "毛邊"), "physical", "ETCH", TAX_ABSENT),
)

DEFECTS = [d.code for d in DEFECT_CATALOGUE]
DEFECT_ALIASES = {d.code: list(d.aliases) for d in DEFECT_CATALOGUE}


# --------------------------------------------------------------------------
# 層
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerSpec:
    """一層語料的性質。

    層與層之間**必須**在文本長度與識別碼密度上有可觀察的差異：三層長得一樣時，
    統計隔離的回歸測試在這份資料上會永遠是綠的——即使隔離壞掉。
    """

    name: str
    slug: str
    templates: dict[str, list[str]]
    #: True 時句子一律帶識別碼；False 時只有少數帶。取「稀少 / 密集」而非「零 / 全部」——
    #: 後者會讓 query 前處理的效果被高估。
    dense_identifiers: bool
    sentences_per_paragraph: tuple[int, int]
    figures: tuple[int, int]
    concepts_per_bundle: tuple[int, int]
    keep_identifiers: bool
    default_mode: str
    top_k: int
    depends_on: tuple[str, ...]
    description: str
    when_to_use: str
    #: True 時忽略上面的數量設定，改為每個 defect 一條、固定一個 bundle。
    per_defect: bool = False


LAYERS: tuple[LayerSpec, ...] = (
    LayerSpec(
        name="library",
        slug="yed-lib",
        templates={"defect_entry": ["形貌", "常見成因", "關聯缺陷"]},
        dense_identifiers=False,
        sentences_per_paragraph=(1, 2),
        figures=(1, 2),
        concepts_per_bundle=(0, 0),
        keep_identifiers=True,
        default_mode="C",
        top_k=5,
        depends_on=(),
        description="缺陷登錄。人寫，每個 defect 一條，是實體字典的來源。",
        when_to_use="想知道「眼前這個東西叫什麼、它的權威定義是什麼」",
        per_defect=True,
    ),
    LayerSpec(
        name="heuristics",
        slug="yed-heu",
        templates={
            "troubleshooting_guide": ["適用情境", "先確認什麼", "分支判斷", "常見誤判", "何時升級處理"],
            "experience_note": ["起因", "當時的判斷", "事後回看", "留給下一個人的話"],
            "training": ["學習目標", "原理說明", "操作步驟", "常見錯誤", "小結"],
        },
        dense_identifiers=False,
        sentences_per_paragraph=(4, 7),
        figures=(2, 4),
        concepts_per_bundle=(10, 18),
        keep_identifiers=False,
        default_mode="B",
        top_k=5,
        depends_on=("library",),
        description="查案心法。人寫，量大，無固定格式。",
        when_to_use="想知道「這類問題該從哪裡開始追」",
    ),
    LayerSpec(
        name="cases",
        slug="yed-cas",
        templates={
            "case_investigation": ["背景", "現象", "量測數據", "分析", "根因", "對策", "後續追蹤"],
            "case_closure": ["結案摘要", "驗證數據", "水平展開", "追蹤項目"],
        },
        dense_identifiers=True,
        sentences_per_paragraph=(2, 4),
        figures=(4, 14),
        concepts_per_bundle=(15, 30),
        keep_identifiers=True,
        default_mode="C",
        top_k=10,
        depends_on=("library",),
        description="已結案的 defect report。固定格式、持續累積，識別碼是主訊號。",
        when_to_use="想知道「這個現象以前發生過什麼、最後查到哪裡」",
    ),
)


#: 帶識別碼的句子。cases 層的主體。
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

#: 不帶任何識別碼的敘述句。heuristics 與 library 層的主體——那兩層的識別碼是雜訊。
NARRATIVE_SENTENCES = [
    "先確認這個現象在同一站點是否重複出現，只發生一次的異常多半不值得先追。",
    "把時間軸拉長到三個月再看一次，短窗看到的趨勢常常是取樣造成的。",
    "在改任何條件之前，先確定量測本身沒有問題，否則後面全部的比對都不成立。",
    "同時變動兩個條件會讓結果無法歸因，一次只動一個。",
    "如果影像上的特徵邊界很銳利，通常指向機械性成因而非製程漂移。",
    "分佈落在晶圓邊緣時，優先看夾持與傳送，而不是先看配方。",
    "找不到根因不代表沒有根因，先把已排除的項目寫下來，下一個人才不會重跑一遍。",
    "對策若無法被驗證，就不算對策，只是猜測加上一個工單編號。",
    "相同形貌可能來自完全不同的成因，形貌只縮小範圍，不給答案。",
    "問「什麼時候開始的」比問「為什麼會這樣」更快收斂。",
    "歷史案件的價值在於排除法，不在於直接套用它的結論。",
    "資料量不足時，不要用統計語言描述結論，那會讓後面的人誤以為已經被證實。",
]

#: 登錄層的句型。以 defect 本身為主詞，不帶機台識別碼。
DEFECT_SENTENCES = {
    "形貌": [
        "{defect} 在影像上呈現可辨識的局部特徵，與背景紋理的對比是主要判別依據。",
        "{alias} 的邊界形狀是判斷的起點，規則邊界與不規則邊界指向不同成因。",
        "同一個 {defect} 在不同放大倍率下的外觀差異很大，紀錄倍率才有比較基礎。",
    ],
    "常見成因": [
        "{defect} 的成因通常不只一種，形貌只能縮小範圍。",
        "環境與傳送過程的干擾是 {alias} 較常被忽略的來源。",
        "製程條件漂移造成的 {defect} 多半伴隨時間上的連續性。",
    ],
    "關聯缺陷": [
        "{defect} 常與 {other} 一起出現，兩者的判別要點不同。",
        "在初判階段 {alias} 容易被誤標為 {other}，複判時要回到形貌本身。",
        "若同時觀察到 {other}，優先確認兩者是否共用同一個成因。",
    ],
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _identifier_sentence(rng: random.Random) -> str:
    tool = rng.choice(TOOLS)
    tool2 = _sibling(tool)
    defect = rng.choice(DEFECTS)
    return rng.choice(SENTENCES).format(
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


def _sentence(rng: random.Random, dense: bool = True) -> str:
    if dense or rng.random() < 0.15:
        return _identifier_sentence(rng)
    return rng.choice(NARRATIVE_SENTENCES)


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


def _paragraph(rng: random.Random, n: int, dense: bool = True) -> str:
    return "".join(_sentence(rng, dense) for _ in range(n))


def _section_body(rng: random.Random, layer: LayerSpec) -> str:
    lo, hi = layer.sentences_per_paragraph
    dense = layer.dense_identifiers
    lines = [_paragraph(rng, rng.randint(lo, hi), dense)]
    if rng.random() < 0.6:
        lines.append("")
        for _ in range(rng.randint(2, 4)):
            lines.append(f"- {_sentence(rng, dense)}")
    lines.append("")
    lines.append(_paragraph(rng, max(1, rng.randint(lo, hi) - 1), dense))
    return "\n".join(lines)


def _defect_section_body(rng: random.Random, heading: str, spec: DefectSpec) -> str:
    others = [d.code for d in DEFECT_CATALOGUE if d.code != spec.code]
    lines = []
    for template in DEFECT_SENTENCES[heading]:
        lines.append(
            template.format(
                defect=spec.code,
                alias=rng.choice(spec.aliases),
                other=rng.choice(others),
            )
        )
    return "".join(lines)


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


def _defect_figures(rng: random.Random, n: int, spec: DefectSpec) -> list[dict]:
    return [
        {
            "file_id": f"slide_{i + 1:03d}",
            "type": "sem_image",
            "title": f"{spec.code} 典型形貌 {i + 1}",
            "description": f"{spec.code}（{spec.name}）在標準倍率下的典型形貌。",
            "key_points": [rng.choice(NARRATIVE_SENTENCES)],
        }
        for i in range(n)
    ]


def _concept_markdown(
    rng: random.Random,
    cid: str,
    ctype: str,
    idx: int,
    bundle_slug: str,
    layer: LayerSpec,
    ns: str = "",
    defect_spec: DefectSpec | None = None,
) -> tuple[str, str, str]:
    headings = layer.templates[ctype]
    slug = f"{bundle_slug}-{idx:02d}"
    src = f"{bundle_slug}.pptx"

    if defect_spec is not None:
        title = f"{defect_spec.code} {defect_spec.name}"
        description = f"{defect_spec.code}（{defect_spec.name}）的登錄條目，類別為 {defect_spec.category}。"
        figures = _defect_figures(rng, rng.randint(*layer.figures), defect_spec)
        tags = list(dict.fromkeys([defect_spec.code.lower(), defect_spec.category, "library"]))
        body_parts = [
            f"## {h}\n\n{_defect_section_body(rng, h, defect_spec)}\n" for h in headings
        ]
    else:
        tool = rng.choice(TOOLS)
        defect = rng.choice(DEFECTS)
        if layer.dense_identifiers:
            title = f"{tool} {defect} {ctype.replace('_', ' ')} #{idx:02d}"
            description = (
                f"{tool} 於 {rng.choice(PROCESSES)} 出現 {defect}，依 {rng.choice(FLOWS)} 流程檢討。"
            )
        else:
            # 識別碼在這一層是雜訊，標題與描述都不放——放了等於偷偷把它變回識別碼查詢。
            title = f"{ctype.replace('_', ' ')} #{idx:02d}｜{rng.choice(headings)}"
            description = rng.choice(NARRATIVE_SENTENCES)
        figures = _figures(rng, rng.randint(*layer.figures))
        tags = rng.sample(
            [defect.lower(), tool.lower(), "yield", "defect", "review", "training"], 3
        )
        body_parts = [f"## {h}\n\n{_section_body(rng, layer)}\n" for h in headings]

    slides = sorted(rng.sample(range(1, 40), rng.randint(2, 5)))

    body_parts.append("## Related Concepts\n")
    body_parts.append(f"- {rng.choice(PROCESSES)} 相關站點說明")
    body_parts.append(
        f"- [{bundle_slug}-{max(1, idx - 1):02d}.md](./{bundle_slug}-{max(1, idx - 1):02d}.md)\n"
    )

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
        "tags": tags,
        "related": [f"cpt_{_hash(f'{ns}{bundle_slug}{max(1, idx - 1)}')[:12]}"],
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


def _summary_markdown(
    rng: random.Random,
    bundle_slug: str,
    concept_ids: list[str],
    layer: LayerSpec,
    ns: str = "",
) -> str:
    """刻意採用**無 `---` 分隔線**的 frontmatter，以覆蓋解析器的該條路徑。"""
    fm = {
        "id": f"sum_{_hash(ns + bundle_slug)[:12]}",
        "type": "bundle_summary",
        "title": f"{bundle_slug} 摘要",
        "slug": f"{bundle_slug}-summary",
        "description": f"{bundle_slug} 的整體摘要與涵蓋範圍。",
        "generated": True,
        "content_hash": _hash(ns + bundle_slug),
        "confidence": rng.choice(["high", "low"]),
        "resource": f"derived://{bundle_slug}.pptx",
        "provenance": [f"file://{bundle_slug}.pptx"],
        "tags": ["summary", layer.name],
        "related": concept_ids[:5],
        "model": "synthetic-generator-0.1",
        "timestamp": datetime(2026, 6, 1, tzinfo=timezone.utc).isoformat(),
    }
    head = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=10_000)
    dense = layer.dense_identifiers
    body = [
        "## 摘要",
        "",
        _paragraph(rng, 4, dense),
        "",
        "## 涵蓋範圍",
        "",
        *[f"- {rng.choice(PROCESSES)} 至 {rng.choice(PROCESSES)} 的站點" for _ in range(3)],
        "",
        "## 關鍵結論",
        "",
        *[f"- {_sentence(rng, dense)}" for _ in range(3)],
        "",
    ]
    return head + "\n".join(body)


# --------------------------------------------------------------------------
# 語料
# --------------------------------------------------------------------------


def _write_bundle(
    broot: Path,
    bundle_slug: str,
    layer: LayerSpec,
    rng: random.Random,
    ns: str,
    defects: list[DefectSpec] | None,
    n_concepts: int,
) -> int:
    okf = broot / "okf"
    assets = okf / "_assets"
    assets.mkdir(parents=True, exist_ok=True)
    for n in range(1, 40):
        (assets / f"slide_{n:03d}.png").write_bytes(_PNG)

    types = list(layer.templates)
    # 一個 bundle 以單一模板為主，重現類型重複性
    main_type = rng.choice(types)
    entries: list[tuple[str, str, str, str]] = []

    for ci in range(1, n_concepts + 1):
        cid = f"cpt_{_hash(f'{ns}{bundle_slug}{ci}')[:12]}"
        spec = defects[ci - 1] if defects else None
        if spec is not None:
            this_type = types[0]
        else:
            # 少量混入其他模板，避免語料完全同質
            this_type = main_type if rng.random() < 0.85 or len(types) == 1 else rng.choice(types)
        text, slug, desc = _concept_markdown(
            rng, cid, this_type, ci, bundle_slug, layer, ns, defect_spec=spec
        )
        (okf / f"{slug}.md").write_text(text, encoding="utf-8")
        entries.append((cid, this_type, f"{slug}.md", desc))

    (okf / "summary.md").write_text(
        _summary_markdown(rng, bundle_slug, [e[0] for e in entries], layer, ns), encoding="utf-8"
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
        + "\n".join(f"{cid} . {ct} . [{fn}]({fn}) . {desc}" for cid, ct, fn, desc in entries)
        + "\n",
        encoding="utf-8",
    )
    (broot / "manifest.json").write_text(
        json.dumps(
            {
                "id": f"bdl_{_hash(ns + bundle_slug)[:12]}",
                "name": bundle_slug,
                "source_file": f"{bundle_slug}.pptx",
                "doc_type": main_type,
                "concept_count": n_concepts,
                "layer": layer.name,
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
    return n_concepts


def _generate_layer(
    root: Path, layer: LayerSpec, n_bundles: int, seed: int, rng: random.Random
) -> dict:
    # 命名空間納入層名。三層會**同時載入**，id 相撞的後果是取全文取到錯的那一層、
    # 跨層融合對同一份文件重複加權——兩者都不會報錯。
    ns = f"s{seed}-{layer.name}-"
    root.mkdir(parents=True, exist_ok=True)

    if layer.per_defect:
        # 登錄層的內容由 defect 全集決定，與 --bundles 無關
        concepts = _write_bundle(
            root / f"{layer.slug}-001",
            f"{layer.slug}-001",
            layer,
            rng,
            ns,
            list(DEFECT_CATALOGUE),
            len(DEFECT_CATALOGUE),
        )
        return {"bundles": 1, "concepts": concepts, "source": str(root)}

    total = 0
    for bi in range(n_bundles):
        slug = f"{layer.slug}-{bi + 1:03d}"
        total += _write_bundle(
            root / slug, slug, layer, rng, ns, None, rng.randint(*layer.concepts_per_bundle)
        )
    return {"bundles": n_bundles, "concepts": total, "source": str(root)}


# --------------------------------------------------------------------------
# 衍生產物
# --------------------------------------------------------------------------


def _dictionary_yaml() -> str:
    data = {
        "tool_id": [{"canonical": t} for t in TOOLS],
        "chamber": [{"canonical": c} for c in CHAMBERS],
        "chamber_id": [{"canonical": c} for c in _dictionary_chambers()],
        "process_id": [{"canonical": p} for p in PROCESSES],
        "flow_id": [{"canonical": f} for f in FLOWS],
        "defect_code": [
            {"canonical": d.code, "aliases": list(d.aliases)} for d in DEFECT_CATALOGUE
        ],
    }
    return _HEADER + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=10_000)


def _tools_csv() -> str:
    """單欄 `id_only`。含 `#` 的列會被歸入 child_type，父層識別碼另外單獨成列。"""
    rows = ["tool_id"]
    rows.extend(TOOLS)
    rows.extend(_dictionary_chambers())
    return "\n".join(rows) + "\n"


def _defects_csv() -> str:
    """三欄 `Module, defect code, defect name`。code 全域唯一為正規名稱，name 為別名。"""
    rows = ["Module,defect code,defect name"]
    rows.extend(f"{d.module},{d.code},{d.name}" for d in DEFECT_CATALOGUE)
    return "\n".join(rows) + "\n"


def _taxonomy_yaml() -> str:
    """刻意不完整：缺口是這份產物的必要性質，不是瑕疵。"""
    data: dict[str, dict] = {}
    for i, d in enumerate(DEFECT_CATALOGUE):
        if d.taxonomy == TAX_ABSENT:
            continue
        entry: dict = {
            "category": d.category,
            "description": f"{d.code}（{d.name}）在影像上的可觀察特徵。此處為合成佔位文字。",
        }
        if d.taxonomy == TAX_FULL:
            entry["method"] = (
                f"先確認形貌是否符合 {d.code} 的判準，再依分佈位置與時間連續性縮小候選 module。"
                "偏向多給候選：漏掉真正的 module 會讓查案走錯方向。此處為合成佔位文字。"
            )
            if i % 3 == 0:
                entry["modules"] = [d.module]
        data[d.code] = entry
    header = _HEADER + (
        "#\n"
        "# 這份資源不進任何索引，存取方式是以 defect 為鍵取回那一條。\n"
        "# 刻意留有缺口：部分 defect 無條目、部分有條目但無 method。\n"
    )
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=10_000)


def _catalogue_yaml() -> str:
    data = {d.code: d.category for d in DEFECT_CATALOGUE}
    header = _HEADER + "#\n# defect 全集：taxonomy 覆蓋率的分母。\n"
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=10_000)


def _identifier_samples_yaml() -> str:
    """樣本取自實際產生的識別碼，涵蓋形狀變體。`check-formats` 會逐條驗。"""
    data = {
        "tool_id": [TOOLS[0], TOOLS[4], TOOLS[12], TOOLS[-1]],
        "chamber_id": [f"{TOOLS[0]}#{CHAMBERS[0]}", f"{TOOLS[4]}#{CHAMBERS[3]}"],
        "process_id": list(PROCESSES[:3]),
        "flow_id": list(FLOWS[:2]),
        "defect_code": [d.code for d in DEFECT_CATALOGUE[:4]],
    }
    header = _HEADER + (
        "#\n"
        "# 這些值是編造的合成識別碼。真實樣本屬敏感資料，請寫進 *-samples.local.yaml。\n"
    )
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=10_000)


def _config_yaml(out: Path, layers: dict[str, dict]) -> str:
    """指向同次產出全部檔案的設定。

    路徑寫**絕對路徑**：設定載入器不會把相對路徑接到設定檔所在目錄，而是接到當下的工作目錄。
    寫相對路徑的話這份設定只有從輸出目錄執行時才成立，從別處執行會得到指向錯誤位置的
    「目錄不存在」——而錯誤訊息不會說出真正的原因。
    """
    indexes = {}
    for layer in LAYERS:
        spec: dict = {
            "source": layers[layer.name]["source"],
            "path": str(out / ".index" / f"{layer.name}.pkl"),
            "description": layer.description,
            "when_to_use": layer.when_to_use,
        }
        if layer.depends_on:
            spec["depends_on"] = list(layer.depends_on)
        spec["keep_identifiers"] = layer.keep_identifiers
        spec["default_mode"] = layer.default_mode
        spec["top_k"] = layer.top_k
        indexes[layer.name] = spec

    data = {
        "dictionary_path": str(out / "dictionary.yaml"),
        "entity_sources": [
            {
                "type": "tool_id",
                "path": str(out / "tools.csv"),
                "schema": "id_only",
                "child_type": "chamber_id",
            },
            {
                "type": "defect_code",
                "path": str(out / "defects.csv"),
                "schema": "module_code_name",
            },
        ],
        "taxonomy_path": str(out / "taxonomy.yaml"),
        "defect_catalogue_path": str(out / "defects.catalogue.yaml"),
        "identifier_samples_path": str(out / "identifier-samples.yaml"),
        "log_dir": str(out / "logs"),
        "indexes": indexes,
    }
    header = _HEADER + (
        "#\n"
        "# 由 yedai gen-synthetic 產生，指向同次產出的全部檔案。\n"
        "# 用法：yedai index -c <這個檔案>\n"
        "#\n"
        "# 這裡不宣告 identifier_patterns：合成識別碼的形狀由產生器決定，沿用內建預設即可。\n"
        "# 寫死一份會讓人以為那組樣式對真實語料也成立。\n"
    )
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=10_000)


# --------------------------------------------------------------------------


def generate(out_dir: str | Path, n_bundles: int = 10, seed: int = 42) -> dict:
    """產生分層合成資料集。

    `n_bundles` 是**每層**的 bundle 數；登錄層例外，其內容由 defect 全集決定，固定一個 bundle。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.txt").write_text(DISCLAIMER, encoding="utf-8")

    rng = random.Random(seed)
    corpus = out / "corpus"
    layers = {
        layer.name: _generate_layer(corpus / layer.name, layer, n_bundles, seed, rng)
        for layer in LAYERS
    }

    products = {
        "dictionary": (out / "dictionary.yaml", _dictionary_yaml()),
        "tools_csv": (out / "tools.csv", _tools_csv()),
        "defects_csv": (out / "defects.csv", _defects_csv()),
        "taxonomy": (out / "taxonomy.yaml", _taxonomy_yaml()),
        "defect_catalogue": (out / "defects.catalogue.yaml", _catalogue_yaml()),
        "identifier_samples": (out / "identifier-samples.yaml", _identifier_samples_yaml()),
        "config": (out / "config.yaml", _config_yaml(out, layers)),
    }
    for path, text in products.values():
        path.write_text(text, encoding="utf-8")

    return {
        "out_dir": str(out),
        "layers": layers,
        "bundles": sum(v["bundles"] for v in layers.values()),
        "concepts": sum(v["concepts"] for v in layers.values()),
        **{key: str(path) for key, (path, _) in products.items()},
        "disclaimer": DISCLAIMER.strip(),
    }
