"""中英混合斷詞，兩種模式。

naive     — 一個「沒做任何聰明事」的水位線：非字母數字全部當分隔符，
            所以 `TEL-05` 會碎成 `tel` + `05`，`TEL-06` 也碎成 `tel` + `06`，
            兩者共享 `tel` 這個高頻低鑑別力的 token。這就是我們要打敗的對象。

protected — 先用正則把識別碼整段圈出來、正規化成單一 token（`TEL-05` → `ID:TEL05`），
            剩下的文字才做一般斷詞。中文一律 unigram + bigram（不依賴詞典，
            對領域專有詞比 jieba 穩定）。
"""

from __future__ import annotations

import re

CJK = r"一-鿿㐀-䶿豈-﫿"
_CJK_RUN = re.compile(rf"[{CJK}]+")
_LATIN = re.compile(r"[A-Za-z0-9]+")

# 識別碼樣式。刻意寬鬆：demo 階段寧可多圈一點，統計會告訴我們哪些是雜訊。
# 使用者可在 config 覆寫這份清單。
DEFAULT_IDENTIFIER_PATTERNS: list[str] = [
    r"cpt_[0-9A-Za-z]+",
    r"[A-Za-z]{1,2}\d{1,2}[-_][A-Za-z]{2,12}",        # M1-etch, W2_poly
    r"[A-Za-z]{2,6}[-_ ]?\d{1,5}(?:[-_][A-Za-z0-9]{1,8})+",  # FL-A100-02
    r"[A-Za-z]{2,6}[-_]\d{1,5}",                       # TEL-05, XTR-12
    # 空白分隔（TEL 05）。刻意收進來：真實文件常這樣寫，漏抓會讓模式 B/C 被低估，
    # 反而導出「識別碼不重要」的錯誤結論。代價是會誤圈 "slide 005" 這類詞組——
    # 誤圈量會出現在報告的 regex fallback 統計裡，而且整份樣式清單可由 config 覆寫。
    r"[A-Za-z]{2,6} \d{1,5}\b",
    r"[A-Za-z]{2,5}\d{1,4}\b",                         # PM3, TEL05
    r"\d{1,2}[A-Za-z]{1,3}\d{2,4}",                    # 3M12 之類料號樣式
]


def normalise_identifier(s: str) -> str:
    """`tel-05` / `TEL 05` / `TEL_05` → `TEL05`。實體字典也用同一個正規化。"""
    return re.sub(r"[-_\s]+", "", s).upper()


class Tokenizer:
    def __init__(self, identifier_patterns: list[str] | None = None) -> None:
        pats = identifier_patterns or DEFAULT_IDENTIFIER_PATTERNS
        self.identifier_patterns = pats
        # 長樣式優先，避免 `FL-A100-02` 被短樣式先咬掉一半
        self._ident_re = re.compile("|".join(f"(?:{p})" for p in pats))

    # ---- naive ----

    @staticmethod
    def naive(text: str) -> list[str]:
        out: list[str] = []
        for chunk in re.split(r"[^0-9A-Za-z" + CJK + r"]+", text or ""):
            if not chunk:
                continue
            if re.fullmatch(rf"[{CJK}]+", chunk):
                out.extend(_cjk_grams(chunk))
            else:
                # 英數混合也拆開：TEL05 → tel, 05（天真斷詞的典型行為）
                for piece in re.findall(r"[A-Za-z]+|\d+", chunk):
                    out.append(piece.lower())
        return out

    # ---- protected ----

    def protected(self, text: str) -> list[str]:
        text = text or ""
        out: list[str] = []
        cursor = 0
        for m in self._ident_re.finditer(text):
            out.extend(self._plain(text[cursor : m.start()]))
            out.append("ID:" + normalise_identifier(m.group(0)))
            cursor = m.end()
        out.extend(self._plain(text[cursor:]))
        return out

    def find_identifiers(self, text: str) -> list[tuple[str, str, int, int]]:
        """回傳 (raw, normalised, start, end)，給實體抽取的 regex fallback 用。"""
        return [
            (m.group(0), normalise_identifier(m.group(0)), m.start(), m.end())
            for m in self._ident_re.finditer(text or "")
        ]

    @staticmethod
    def _plain(text: str) -> list[str]:
        out: list[str] = []
        for m in _CJK_RUN.finditer(text):
            out.extend(_cjk_grams(m.group(0)))
        for m in _LATIN.finditer(text):
            tok = m.group(0).lower()
            if len(tok) > 1 or tok.isdigit():
                out.append(tok)
        return out


def _cjk_grams(run: str) -> list[str]:
    """中文用 unigram + bigram。bigram 承載大部分鑑別力，unigram 保召回。"""
    grams = list(run)
    grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return grams
