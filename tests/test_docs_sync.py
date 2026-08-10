"""守住 docs/api.md 與實際 API 的一致性。

文件漂移是預設的失敗模式：加一個參數、改一個狀態碼，沒有人會記得回去改文件。
這幾條測試讓它變成 CI 會擋下的事，而不是三個月後才被發現的謊言。
"""

from __future__ import annotations

import pathlib

import pytest

API_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "api.md"


@pytest.fixture(scope="module")
def doc() -> str:
    assert API_DOC.exists(), f"缺少 API 參考文件：{API_DOC}"
    return API_DOC.read_text(encoding="utf-8")


@pytest.fixture
def spec(client) -> dict:
    return client.get("/openapi.json").json()


def test_every_endpoint_is_documented(doc: str, spec: dict) -> None:
    missing = [p for p in spec["paths"] if p not in doc]
    assert not missing, f"docs/api.md 缺少端點：{missing}"


def test_every_parameter_is_documented(doc: str, spec: dict) -> None:
    missing = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            for prm in op.get("parameters", []):
                if f"`{prm['name']}`" not in doc:
                    missing.append(f"{method.upper()} {path} → {prm['name']}")
    assert not missing, f"docs/api.md 缺少參數：{missing}"


def _enum_values(spec: dict, node: dict) -> list[str]:
    """列舉值可能直接在 schema 上，也可能藏在 anyOf 分支或 $ref 之後。"""
    node = _resolve(spec, node)
    if "enum" in node:
        return [str(v) for v in node["enum"]]
    out: list[str] = []
    for branch in node.get("anyOf", []) + node.get("allOf", []):
        out.extend(_enum_values(spec, branch))
    return out


def test_every_enum_value_is_documented(doc: str, spec: dict) -> None:
    """列舉值漂移過一次：`mode` 加了 D/E，文件還寫著 `A` / `B` / `C`。

    參數名有沒有出現在文件裡，跟參數**吃什麼值**是兩件事。只檢查前者的話，
    新增一個模式不會讓任何測試變紅——而呼叫端看文件會以為那個值不存在。
    """
    missing = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            for prm in op.get("parameters", []):
                for value in _enum_values(spec, prm.get("schema", {})):
                    if f"`{value}`" not in doc:
                        missing.append(f"{method.upper()} {path} → {prm['name']}={value}")
    assert not missing, f"docs/api.md 缺少列舉值：{missing}"


def test_every_error_code_is_documented(doc: str, spec: dict) -> None:
    """狀態碼是呼叫端最需要、也最容易漏掉的契約。"""
    missing = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            for code in op["responses"]:
                if code != "200" and f"`{code}`" not in doc:
                    missing.append(f"{method.upper()} {path} → {code}")
    assert not missing, f"docs/api.md 缺少狀態碼：{missing}"


def test_every_tag_is_documented(doc: str, spec: dict) -> None:
    missing = [t["name"] for t in spec["tags"] if t["name"] not in doc]
    assert not missing, f"docs/api.md 缺少分類：{missing}"


def test_doc_declares_no_stale_endpoints(doc: str, spec: dict) -> None:
    """反向檢查：文件不該提到已不存在的端點。"""
    import re

    known = set(spec["paths"])
    referenced = set(re.findall(r"`(?:GET|POST|PUT|DELETE) (/[\w{}/-]+)`", doc))
    stale = {p for p in referenced if p not in known}
    assert not stale, f"docs/api.md 提到了不存在的端點：{stale}"


def _resolve(spec: dict, node: dict) -> dict:
    """跟著 $ref 走到實際的 schema 定義。"""
    while "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        node = spec["components"]["schemas"][name]
    return node


def _response_schema(spec: dict, op: dict) -> dict | None:
    content = op["responses"].get("200", {}).get("content", {})
    node = content.get("application/json", {}).get("schema")
    return _resolve(spec, node) if node else None


def test_every_json_endpoint_declares_a_response_schema(spec: dict) -> None:
    """沒有回應 schema 的端點，在 /docs 上是一片空白——呼叫端只能去讀原始碼。"""
    bare = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if path.endswith("/asset"):  # 回二進位檔案，沒有 JSON schema
                continue
            schema = _response_schema(spec, op)
            if not schema or not schema.get("properties"):
                bare.append(f"{method.upper()} {path}")
    assert not bare, f"這些端點的 200 回應沒有欄位描述：{bare}"


def test_response_fields_are_documented(doc: str, spec: dict) -> None:
    """回應欄位才是呼叫端真正要的東西，漏在文件外等於沒寫。"""
    missing = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            schema = _response_schema(spec, op)
            for field in (schema or {}).get("properties", {}):
                if f"`{field}`" not in doc and field not in doc:
                    missing.append(f"{method.upper()} {path} → {field}")
    assert not missing, f"docs/api.md 缺少回應欄位：{sorted(set(missing))}"


def test_declared_codes_match_actual_behaviour(client) -> None:
    """OpenAPI 宣告的錯誤碼必須是實際會發生的，不能只是裝飾。"""
    assert client.get("/v1/concept/cpt_nope").status_code == 404
    assert (
        client.get("/v1/concept/cpt_title-hit/asset", params={"path": "../x"}).status_code == 403
    )
    assert client.get("/v1/grep", params={"pattern": "x"}).status_code == 422
    assert client.get("/v1/grep", params={"pattern": "x", "bundle_id": "nope"}).status_code == 404
    assert (
        client.post(
            "/v1/feedback",
            json={"query_id": "nope", "concept_id": "x", "rank": 1, "mode": "C"},
        ).status_code
        == 404
    )


# --- 設定鍵 -------------------------------------------------------------

CONFIG_EXAMPLE = API_DOC.resolve().parents[1] / "config.example.yaml"
INDEXING_DOC = API_DOC.resolve().parent / "indexing.md"


def test_every_config_key_is_documented_somewhere() -> None:
    """每個設定鍵至少要在範例檔或某篇文件裡出現過。

    新增一個欄位卻沒有任何地方提到它，使用者不會知道它存在——而那正是索引宣告
    這種「不設就跑不起來」的鍵最不該發生的事。

    不強制全部塞進 `config.example.yaml`：稠密腿與 LLM 的設定在 dense.md /
    evaluation.md 有完整說明，硬搬進範例只會讓範例變成一份沒人讀完的清單。
    """
    import yaml

    from yedai.config import Config

    raw = yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8")) or {}
    unknown = set(raw) - set(Config().__dict__)
    assert not unknown, f"config.example.yaml 有不存在的設定鍵：{sorted(unknown)}"

    docs = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    for md in sorted(INDEXING_DOC.parent.glob("*.md")):
        docs += md.read_text(encoding="utf-8")

    missing = [key for key in Config().__dict__ if key not in docs]
    assert not missing, f"這些設定鍵沒有任何地方提到：{sorted(missing)}"


def test_index_declaration_keys_are_documented() -> None:
    """索引宣告的每個鍵都要在 indexing.md 有說明。

    這一組鍵不在 `Config` 的欄位裡（它們是 `indexes.<name>` 底下的），
    上面那條測試看不到它們。
    """
    from yedai.config import INDEX_SPEC_KEYS

    doc = INDEXING_DOC.read_text(encoding="utf-8")
    missing = [k for k in INDEX_SPEC_KEYS if f"`{k}`" not in doc]
    assert not missing, f"docs/indexing.md 缺少索引宣告鍵的說明：{sorted(missing)}"


# --- /docs 的範例 -------------------------------------------------------

#: 範例只是形狀示意，這幾個端點的回應結構本身已經自明或形狀不固定。
_NO_EXAMPLE_NEEDED = {"ReportOut", "Distribution"}


def _response_models(spec: dict) -> dict[str, dict]:
    """OpenAPI 裡實際被端點當成 200 回應的模型。"""
    out: dict[str, dict] = {}
    for ops in spec["paths"].values():
        for op in ops.values():
            content = (op.get("responses", {}).get("200", {}) or {}).get("content", {})
            schema = (content.get("application/json", {}) or {}).get("schema")
            if not schema:
                continue
            ref = schema.get("$ref", "")
            if ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                out[name] = spec["components"]["schemas"][name]
    return out


def test_every_response_model_carries_an_example(spec: dict) -> None:
    """`/docs` 是呼叫端唯一會讀的東西。

    一個「Example Value」比三段散文更快講清楚 `layers[]` 長什麼樣、
    空層為什麼還在裡面。新增回應模型卻沒給範例，文件頁就只剩型別名稱。
    """
    missing = [
        name
        for name, schema in _response_models(spec).items()
        if name not in _NO_EXAMPLE_NEEDED and "example" not in schema
    ]
    assert not missing, f"這些回應模型沒有範例：{sorted(missing)}"


def test_response_examples_validate_against_their_own_model() -> None:
    """範例會腐爛：欄位改名之後它還是照樣渲染，只是內容已經是假的。

    直接拿模型去驗證它自己的範例——那是唯一擋得住這件事的方法。
    """
    import yedai.schemas as S

    checked = 0
    for name in dir(S):
        model = getattr(S, name)
        if not (isinstance(model, type) and issubclass(model, S._Out) and model is not S._Out):
            continue
        example = (model.model_config.get("json_schema_extra") or {}).get("example")
        if example is None:
            continue
        model.model_validate(example)  # 不符就 raise
        checked += 1
    assert checked >= 8, f"只驗到 {checked} 個範例，這條測試可能已經失去覆蓋"


def test_named_examples_validate_against_their_model() -> None:
    """端點層的具名範例（Swagger 的下拉選單）同樣會腐爛。"""
    from yedai.schemas import SEARCH_EXAMPLES, TAXONOMY_EXAMPLES, LayeredSearchOut, TaxonomyOut

    for model, named in ((LayeredSearchOut, SEARCH_EXAMPLES), (TaxonomyOut, TAXONOMY_EXAMPLES)):
        assert len(named) >= 2, f"{model.__name__} 的具名範例少於兩個，下拉選單沒有意義"
        for key, entry in named.items():
            assert entry.get("summary"), f"{key} 沒有 summary——下拉選單只會顯示鍵名"
            model.model_validate(entry["value"])


def test_search_examples_cover_both_shapes() -> None:
    """兩個範例要真的示範不同的事，不能只是換個數字。"""
    from yedai.schemas import SEARCH_EXAMPLES

    layered = SEARCH_EXAMPLES["layered"]["value"]
    fused = SEARCH_EXAMPLES["fused"]["value"]

    assert layered["shape"] == "layered" and layered["fused"] is None
    assert fused["shape"] == "fused" and fused["fused"]
    # 預設那個範例必須含一個空層——那是整個分層設計最容易被誤解的地方
    assert any(not lr["hits"] for lr in layered["layers"]), "預設範例沒有示範空層"
    # 融合時分層結構仍然保留
    assert fused["layers"], "融合範例不該把 layers 拿掉"
    # 融合分數只由層內名次決定
    for f in fused["fused"]:
        assert abs(f["score"] - 1.0 / (60 + f["source_rank"])) < 1e-6


def test_examples_leak_no_real_values(spec: dict) -> None:
    """範例會出現在公開的 `/docs`。

    它們必須全部是編造值或 schema 層級的識別（層名、類型名）。真實的機台、
    批號、缺陷名、module 名進到這裡，等同於把語料放進 API 文件。
    """
    import json
    import re

    blob = json.dumps(spec, ensure_ascii=False)

    # 識別碼形狀：只准用 dictionary.example.yaml 那組編造值
    allowed_ids = {"XTR-05", "XTR-06", "QDN-01"}
    found = set(re.findall(r"\b[A-Z]{2,6}-\d{2,3}\b", blob))
    assert found <= allowed_ids, f"範例出現了未登記的識別碼：{sorted(found - allowed_ids)}"

    # defect / module 名：fab taxonomy，比識別碼更敏感。只准用佔位符。
    allowed_names = {
        "DEFECT_ALPHA", "DEFECT_BETA", "DEFECT_GAMMA", "DEFECT_DELTA", "DEFECT_EPSILON",
        "MODULE_ONE", "MODULE_TWO",
    }
    names = set(re.findall(r"(?:DEFECT|MODULE)_[A-Z]+", blob))
    assert names <= allowed_names, f"範例出現了未登記的 defect/module 名：{sorted(names - allowed_names)}"


def test_key_request_bodies_carry_an_example(spec: dict) -> None:
    """「Try it out」按下去要能直接跑，而不是先叫使用者自己編一份 JSON。"""
    missing = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            body = op.get("requestBody")
            if not body:
                continue
            schema = body["content"]["application/json"]["schema"]
            ref = schema.get("$ref", "")
            name = ref.rsplit("/", 1)[-1] if ref else None
            resolved = spec["components"]["schemas"].get(name, {}) if name else schema
            if "example" not in resolved and "example" not in body:
                missing.append(f"{method.upper()} {path}")
    assert not missing, f"這些端點的請求 body 沒有範例：{missing}"


# --- README --------------------------------------------------------------

README = API_DOC.resolve().parents[1] / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def _mermaid_blocks(text: str) -> list[str]:
    import re

    return re.findall(r"```mermaid\n(.*?)```", text, re.S)


def test_readme_mermaid_blocks_are_structurally_sound(readme: str) -> None:
    """完整渲染要 node + puppeteer，太重。這裡擋的是最常見的腐爛：
    `subgraph` 沒收尾、引用了沒定義的節點、方向宣告打錯。"""
    import re

    blocks = _mermaid_blocks(readme)
    assert len(blocks) >= 2, "README 應該有建立檢索與查詢演算法兩張圖"

    for i, b in enumerate(blocks, 1):
        assert b.lstrip().startswith("flowchart "), f"第 {i} 張圖沒有宣告 flowchart 方向"
        opens = len(re.findall(r"^\s*subgraph\b", b, re.M))
        ends = len(re.findall(r"^\s*end\s*$", b, re.M))
        assert opens == ends, f"第 {i} 張圖的 subgraph／end 不成對（{opens} vs {ends}）"

        # 先把引號內的標籤整段拿掉——標籤裡的 `load_bundles(` 之類會被誤認成節點定義
        bare = re.sub(r'"[^"]*"', '""', b)
        # 節點定義可以出現在鏈的任何位置：`P2 --> T1["…"] --> S1[("…")]`
        defined = set(re.findall(r"([A-Za-z_]\w*)\s*[\[\{\(]", bare))
        defined |= set(re.findall(r"^\s*subgraph\s+([A-Za-z_]\w*)", bare, re.M))
        referenced = set(re.findall(r"(?:^|\s)([A-Za-z_]\w*)\s*(?:--|-\.)", bare, re.M))
        referenced |= set(re.findall(r"(?:-->|\.->)\s*([A-Za-z_]\w*)(?=\s|$)", bare, re.M))
        unknown = {r for r in referenced - defined if r not in {"direction", "style", "end"}}
        assert not unknown, f"第 {i} 張圖引用了未定義的節點：{sorted(unknown)}"


def test_query_diagram_covers_every_mode(readme: str) -> None:
    """查詢演算法圖漏掉一個模式，讀者會以為它不存在。"""
    from yedai.search import MODES

    query_diagram = _mermaid_blocks(readme)[1]
    missing = [m for m in MODES if f'"{m}｜' not in query_diagram]
    assert not missing, f"查詢演算法圖沒有涵蓋模式：{missing}"


def test_readme_index_format_version_is_current(readme: str) -> None:
    """「支援 v8、載入的是 v7」這種例子會隨版本腐爛。"""
    from yedai.index import INDEX_FORMAT_VERSION

    assert f"v{INDEX_FORMAT_VERSION}" in readme, (
        f"README 沒有提到目前的索引格式版本 v{INDEX_FORMAT_VERSION}"
    )


def test_readme_lists_every_mcp_tool(readme: str) -> None:
    """工具數量與名稱都會漂——先前 README 停在「六個工具」而實際有七個。"""
    from yedai.mcp_server import _tools

    names = {t.name for t in _tools()}
    missing = [n for n in names if f"`{n}`" not in readme]
    assert not missing, f"README 的工具清單漏了：{sorted(missing)}"

    zh = {6: "六", 7: "七", 8: "八", 9: "九"}
    assert f"{zh[len(names)]}個工具" in readme, f"README 的工具數量與實際的 {len(names)} 個不符"


def test_readme_lists_every_endpoint(readme: str, spec: dict) -> None:
    """README 的端點表是多數人第一眼看到的東西，漏一條就等於那個端點不存在。"""
    missing = [p for p in spec["paths"] if p not in readme]
    assert not missing, f"README 的端點表缺少：{sorted(missing)}"
