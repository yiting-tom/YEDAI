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
        frontmatter={"title": "XTR-05 PARTICLE 調查", "description": "標題命中", "tags": ["yield"]},
        body="## 現象\n\n這裡沒有關鍵詞。\n",
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
    return root


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
