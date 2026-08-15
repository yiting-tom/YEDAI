"""分層合成資料集：層與層的差異，以及各衍生產物彼此對得上。

這些斷言的共同前提是：資料集若三層長得一樣、查表資源若彼此對不上，
分層機制的測試在這份資料上會永遠是綠的——即使機制壞掉。
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from yedai.config import Config
from yedai.entities import EntityDictionary
from yedai.formats import check_coverage, load_samples
from yedai.index import build_index
from yedai.parser import load_bundles
from yedai.synthetic import (
    DEFECT_CATALOGUE,
    LAYERS,
    TAX_ABSENT,
    TAX_FULL,
    TAX_NO_METHOD,
    generate,
)
from yedai.taxonomy import Taxonomy
from yedai.tokenizer import Tokenizer

_ID = re.compile(r"^id: ((?:cpt|sum|bdl)_\w+)", re.M)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("ds") / "synthetic"
    return generate(out, n_bundles=2, seed=42)


def _root(dataset: dict) -> Path:
    return Path(dataset["out_dir"])


def _concepts(dataset: dict, layer: str) -> list:
    bundles, _ = load_bundles(Path(dataset["layers"][layer]["source"]))
    return [c for b in bundles for c in b.concepts]


# --- 分層 ---------------------------------------------------------------


def test_corpus_is_split_by_layer(dataset: dict) -> None:
    for layer in LAYERS:
        source = Path(dataset["layers"][layer.name]["source"])
        assert source.is_dir()
        assert (source.parent.name, source.name) == ("corpus", layer.name)
        assert any(p.name == "manifest.json" for p in source.rglob("manifest.json"))


def test_per_layer_bundle_counts(dataset: dict) -> None:
    """`--bundles` 是每層的數量；由 defect 全集決定內容的那一層不受它影響。"""
    for layer in LAYERS:
        expected = 1 if layer.per_defect else 2
        assert dataset["layers"][layer.name]["bundles"] == expected


def test_concept_ids_are_disjoint_across_layers(dataset: dict) -> None:
    """三層會**同時**載入。id 相撞的後果是取全文取到錯的那一層、跨層融合對同一份
    文件重複加權——兩者都不會報錯，所以只能在這裡擋。"""
    seen: dict[str, set[str]] = {}
    for layer in LAYERS:
        root = Path(dataset["layers"][layer.name]["source"])
        seen[layer.name] = {
            m.group(1) for f in root.rglob("*.md") for m in _ID.finditer(f.read_text(encoding="utf-8"))
        }
    names = list(seen)
    for i, a in enumerate(names):
        assert seen[a], f"前提不成立：{a} 沒有抓到任何 id"
        for b in names[i + 1 :]:
            overlap = seen[a] & seen[b]
            assert not overlap, f"{a} 與 {b} 共用了 {len(overlap)} 個 id"


def test_layers_do_not_share_templates(dataset: dict) -> None:
    declared = {layer.name: set(layer.templates) for layer in LAYERS}
    for layer in LAYERS:
        others = {t for name, ts in declared.items() if name != layer.name for t in ts}
        seen = {c.type for c in _concepts(dataset, layer.name)}
        assert seen <= declared[layer.name]
        assert not (seen & (others - declared[layer.name]))


def test_identifier_density_differs_between_layers(dataset: dict) -> None:
    """密集層與稀少層的每篇平均識別碼數必須拉得開，否則 query 前處理的效果看不出來。"""

    def density(layer: str) -> float:
        concepts = _concepts(dataset, layer)
        hits = sum(
            len(re.findall(r"\b[A-Z]{3}-\d{2}\b", " ".join(c.field_texts().values())))
            for c in concepts
        )
        return hits / len(concepts)

    dense = density("cases")
    sparse = density("heuristics")
    assert dense > sparse * 3, f"cases={dense:.1f} heuristics={sparse:.1f} 差距不足以觀察"


def test_library_layer_covers_the_whole_catalogue(dataset: dict) -> None:
    titles = {c.title.split()[0] for c in _concepts(dataset, "library")}
    assert titles == {d.code for d in DEFECT_CATALOGUE}


# --- 衍生產物 -----------------------------------------------------------


def test_derived_products_agree_on_defect_codes(dataset: dict) -> None:
    """四份產物由同一份全集衍生。各寫各的就會慢慢漂開，而漂開的症狀
    （覆蓋率突然掉、字典對不到 code）都會被誤讀成程式的錯。"""
    codes = {d.code for d in DEFECT_CATALOGUE}

    dictionary = yaml.safe_load(Path(dataset["dictionary"]).read_text(encoding="utf-8"))
    assert {e["canonical"] for e in dictionary["defect_code"]} == codes

    with Path(dataset["defects_csv"]).open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert {r[1] for r in rows[1:]} == codes

    catalogue = yaml.safe_load(Path(dataset["defect_catalogue"]).read_text(encoding="utf-8"))
    assert set(catalogue) == codes

    taxonomy = yaml.safe_load(Path(dataset["taxonomy"]).read_text(encoding="utf-8"))
    assert set(taxonomy) <= codes


def test_csv_entity_sources_load(dataset: dict) -> None:
    config = Config(
        entity_sources=[
            {
                "type": "tool_id",
                "path": dataset["tools_csv"],
                "schema": "id_only",
                "child_type": "chamber_id",
            },
            {"type": "defect_code", "path": dataset["defects_csv"], "schema": "module_code_name"},
        ]
    )
    dictionary = EntityDictionary.from_config(config)
    assert len(dictionary) > 0, "CSV 實體來源應載入至少一筆"


def test_id_only_csv_lists_parents_of_every_hierarchical_row(dataset: dict) -> None:
    rows = [r.strip() for r in Path(dataset["tools_csv"]).read_text(encoding="utf-8").splitlines()]
    values = [r for r in rows[1:] if r]
    plain = {v for v in values if "#" not in v}
    parents = {v.split("#", 1)[0] for v in values if "#" in v}
    assert parents, "前提不成立：沒有任何層級列"
    assert parents <= plain, "層級列的父層識別碼必須也單獨成列"


# --- 查表資源 -----------------------------------------------------------


def test_taxonomy_ships_with_a_coverage_gap(dataset: dict) -> None:
    """覆蓋率恆為滿的資料集，唯一能驗證的是「統計不會爆炸」。缺口才是這個指標存在的理由。"""
    raw = yaml.safe_load(Path(dataset["taxonomy"]).read_text(encoding="utf-8"))
    states = Counter(d.taxonomy for d in DEFECT_CATALOGUE)
    assert states[TAX_FULL] and states[TAX_NO_METHOD] and states[TAX_ABSENT]

    with_method = [k for k, v in raw.items() if v.get("method")]
    without_method = [k for k, v in raw.items() if not v.get("method")]
    assert with_method and without_method
    assert len(raw) < len(DEFECT_CATALOGUE)


def test_taxonomy_loads_without_unknown_key_warnings(dataset: dict) -> None:
    catalogue = yaml.safe_load(Path(dataset["defect_catalogue"]).read_text(encoding="utf-8"))
    tx = Taxonomy.load(dataset["taxonomy"], defects=catalogue)
    assert tx.unknown_keys == []
    coverage = tx.coverage()
    assert 0 < coverage["covered"] < coverage["total"]


def test_identifier_samples_are_checkable(dataset: dict) -> None:
    """樣本必須真的能跑過 `check-formats`。

    刻意**不**斷言全數通過：`FL-A100` 這種「前綴 + 字母數字」的形狀不在內建預設樣式的
    涵蓋範圍內，會被判為碎裂。那是一個真的缺口，把樣本改成剛好符合樣式等於讓程式跟
    自己對答案——而那正是這個工具存在要防的事。
    """
    samples = load_samples(dataset["identifier_samples"])
    assert samples, "產物應含樣本"
    report = check_coverage(Tokenizer(), samples)
    assert report.configured
    assert report.results
    assert not report.types_without_samples


# --- 設定 ---------------------------------------------------------------


def test_generated_config_builds_every_index(dataset: dict) -> None:
    config = Config.load(dataset["config"])
    dictionary = EntityDictionary.load(config.dictionary_path)
    for name, spec in config.index_specs().items():
        index = build_index(Path(spec.source), config, dictionary, name=name)
        assert index.stats.parse_skipped == 0, f"{name} 不應有解析失敗：{index.skipped}"
        assert index.stats.concepts > 0


def test_generated_config_reflects_layer_character(dataset: dict) -> None:
    config = Config.load(dataset["config"])
    for layer in LAYERS:
        spec = config.index_specs()[layer.name]
        assert spec.keep_identifiers is layer.keep_identifiers
        assert spec.default_mode == layer.default_mode
        assert spec.top_k == layer.top_k
        assert tuple(spec.depends_on) == layer.depends_on
        assert spec.description and spec.when_to_use


def test_generated_config_declares_no_identifier_patterns(dataset: dict) -> None:
    """寫死一份樣式會讓人以為那組樣式對真實語料也成立。"""
    raw = yaml.safe_load(Path(dataset["config"]).read_text(encoding="utf-8"))
    assert "identifier_patterns" not in raw


# --- 使用限制 -----------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["config", "dictionary", "taxonomy", "defect_catalogue", "identifier_samples"],
)
def test_products_carry_the_disclaimer(dataset: dict, key: str) -> None:
    head = Path(dataset[key]).read_text(encoding="utf-8")[:400]
    assert "僅供驗證程式正確性" in head
    assert "不得用於調整參數" in head


def test_readme_ships_disclaimer(dataset: dict) -> None:
    note = (_root(dataset) / "README.txt").read_text(encoding="utf-8")
    assert "僅供驗證程式正確性" in note
    assert "不得用於調整參數" in note
