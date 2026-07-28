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
