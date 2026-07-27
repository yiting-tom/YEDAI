from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from yedai.config import Config
from yedai.entities import EntityDictionary
from yedai.index import build_index
from yedai.search import Searcher


def write_concept(
    okf: Path,
    name: str,
    *,
    frontmatter: dict | None = None,
    body: str = "## 內容\n\n預設內文。\n",
    delimited: bool = True,
) -> Path:
    fm = {"id": f"cpt_{name}", "type": "case_investigation", "title": name} | (frontmatter or {})
    blob = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=10_000)
    text = f"---\n{blob}---\n\n{body}" if delimited else f"{blob}\n{body}"
    path = okf / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


#: 1x1 透明 PNG，讓資產測試用的是真實檔案而非空殼
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fd7fd0ff0000000049454e44ae426082"
)


def make_bundle(root: Path, name: str) -> Path:
    okf = root / name / "okf"
    (okf / "_assets").mkdir(parents=True, exist_ok=True)
    (root / name / "manifest.json").write_text(
        json.dumps({"id": f"bdl_{name}", "name": name}), encoding="utf-8"
    )
    return okf


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """一份刻意設計過的小語料，讓每個檢索行為都有明確的預期答案。"""
    root = tmp_path / "bundles"
    okf = make_bundle(root, "b1")

    # 標題含 XTR-05；用來測「標題命中優於內文」與識別碼區辨
    write_concept(
        okf,
        "title-hit",
        frontmatter={
            "title": "XTR-05 PARTICLE 調查",
            "description": "標題命中",
            "tags": ["yield"],
            # 含一個懸空引用，讓關聯展開的兩條路徑都有東西可測
            "related": ["cpt_body-hit", "cpt_sibling", "cpt_ghost"],
            "assets": ["_assets/slide_001.png", "_assets/notes.bin"],
        },
        body="## 現象\n\n這裡沒有關鍵詞。\n\n## Citations\n\n[1] [slide 1](_assets/slide_001.png)\n",
    )
    # 相同關鍵詞只出現在內文
    write_concept(
        okf,
        "body-hit",
        frontmatter={"title": "無關標題", "description": "內文命中"},
        body="## 現象\n\nXTR-05 出現 PARTICLE 異常。\n",
    )
    # 兄弟機台：模式 A 會與 XTR-05 混淆，模式 B/C 不會
    write_concept(
        okf,
        "sibling",
        frontmatter={"title": "XTR-06 PARTICLE 調查", "description": "兄弟機台"},
        body="## 現象\n\nXTR-06 出現 PARTICLE 異常。\n",
    )
    # 完全無關
    write_concept(
        okf,
        "unrelated",
        frontmatter={"title": "研磨製程訓練教材", "description": "無關內容"},
        body="## 學習目標\n\n研磨基本原理與操作。\n",
    )
    # 罕見實體只出現在這一份
    write_concept(
        okf,
        "rare",
        frontmatter={"title": "QDN-01 VOID 專案", "description": "罕見實體"},
        body="## 現象\n\nQDN-01 觀察到 VOID。\n",
    )
    # 真實資產檔
    (okf / "_assets" / "slide_001.png").write_bytes(PNG)
    (okf / "_assets" / "notes.bin").write_bytes(b"\x00\x01binary-asset")
    # 誘餌：在 bundle 內但不在 _assets 之下，白名單必須擋住它
    (okf / "not-an-asset.txt").write_text("這個檔案不該經由資產端點被讀到", encoding="utf-8")
    return root


@pytest.fixture
def graph_corpus(tmp_path: Path) -> Path:
    """關聯圖：A → B、C（外加一個懸空引用）；B → D；E 完全孤立。

        A ──→ B ──→ D
        │
        └──→ C          E（孤立）
        └──→ cpt_ghost（懸空）
    """
    root = tmp_path / "graph"
    okf = make_bundle(root, "g1")
    write_concept(okf, "a", frontmatter={"id": "cpt_a", "title": "A",
                                         "related": ["cpt_b", "cpt_c", "cpt_ghost"]})
    write_concept(okf, "b", frontmatter={"id": "cpt_b", "title": "B", "related": ["cpt_d"]})
    write_concept(okf, "c", frontmatter={"id": "cpt_c", "title": "C"})
    write_concept(okf, "d", frontmatter={"id": "cpt_d", "title": "D"})
    write_concept(okf, "e", frontmatter={"id": "cpt_e", "title": "E"})
    return root


@pytest.fixture
def graph_index(graph_corpus: Path, config):
    from yedai.index import build_index

    return build_index(graph_corpus, config, EntityDictionary.load(config.dictionary_path))


@pytest.fixture
def dictionary_path(tmp_path: Path) -> Path:
    path = tmp_path / "dict.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "tool_id": [
                    {"canonical": "XTR-05", "aliases": ["五號機"]},
                    {"canonical": "XTR-06"},
                    {"canonical": "QDN-01"},
                ],
                "defect_code": [
                    {"canonical": "PARTICLE", "aliases": ["particle", "微粒"]},
                    {"canonical": "VOID", "aliases": ["void"]},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def config(tmp_path: Path, dictionary_path: Path) -> Config:
    return Config(
        dictionary_path=str(dictionary_path),
        index_path=str(tmp_path / ".index" / "test.pkl"),
        log_dir=str(tmp_path / "logs"),
        seed=1,
    )


@pytest.fixture
def searcher(corpus: Path, config: Config) -> Searcher:
    dictionary = EntityDictionary.load(config.dictionary_path)
    index = build_index(corpus, config, dictionary)
    return Searcher(index, config, dictionary)
