from __future__ import annotations

from yedai.tokenizer import Tokenizer, normalise_identifier


def test_identifier_variants_normalise_identically() -> None:
    forms = ["XTR-05", "XTR05", "xtr 05", "XTR_05", "xtr-05"]
    assert len({normalise_identifier(f) for f in forms}) == 1


def test_sibling_identifiers_share_no_token_in_protected_mode() -> None:
    tok = Tokenizer()
    a = set(tok.protected("XTR-05 出現異常"))
    b = set(tok.protected("XTR-06 出現異常"))
    ids_a = {t for t in a if t.startswith("ID:")}
    ids_b = {t for t in b if t.startswith("ID:")}
    assert ids_a and ids_b
    assert not (ids_a & ids_b), "保護斷詞下兄弟機台不得共享任何識別碼詞元"


def test_naive_mode_shatters_identifiers() -> None:
    a = set(Tokenizer.naive("XTR-05 出現異常"))
    b = set(Tokenizer.naive("XTR-06 出現異常"))
    assert "xtr" in a and "xtr" in b, "天真斷詞應把前綴切成共用詞元"
    assert "05" in a and "06" in b
    assert not any(t.startswith("ID:") for t in a)


def test_cjk_produces_unigrams_and_bigrams() -> None:
    tokens = Tokenizer.naive("量測結果")
    assert {"量", "測", "結", "果"} <= set(tokens)
    assert {"量測", "測結", "結果"} <= set(tokens)


def test_latin_lowercased() -> None:
    assert "particle" in Tokenizer.naive("Particle 異常")


def test_protected_keeps_surrounding_text() -> None:
    tok = Tokenizer()
    tokens = tok.protected("XTR-05 出現 particle")
    assert "ID:XTR05" in tokens
    assert "particle" in tokens
    assert {"出", "現", "出現"} & set(tokens)


def test_custom_patterns_replace_defaults() -> None:
    tok = Tokenizer([r"ZZZ\d+"])
    assert "ID:ZZZ9" in tok.protected("ZZZ9 測試")
    # 預設樣式已被取代，XTR-05 不再被視為識別碼
    assert not any(t.startswith("ID:XTR") for t in tok.protected("XTR-05"))


def test_find_identifiers_reports_spans() -> None:
    tok = Tokenizer()
    found = tok.find_identifiers("機台 XTR-05 與 QDN-01")
    norms = {n for _raw, n, _s, _e in found}
    assert {"XTR05", "QDN01"} <= norms
