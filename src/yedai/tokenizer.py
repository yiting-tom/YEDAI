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
    # 父子層級（機台#腔體）。**必須排在最前面**——否則較短的樣式會先咬掉 `aepol1`，
    # `#pm1` 被丟到一般斷詞，層級關係就此消失。
    # 誤圈面：`page.html#section` 這類片段也會中。與其他樣式一樣偏 recall，
    # 誤圈量會出現在報告的 regex fallback 統計裡。
    r"[A-Za-z0-9]{2,12}#[A-Za-z0-9]{1,10}",
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
    """`tel-05` / `TEL 05` / `TEL_05` → `TEL05`。實體字典也用同一個正規化。

    `#` **刻意不移除**：它標示父子層級的分界（`AEPOL1#PM1`）。移除後分界無法可靠還原——
    父層與子層都是變長的，沒有辦法從 `AEPOL1PM1` 推回切點。
    而 `#` 不需要做寫法收斂：沒有人把 `aepol1#pm1` 寫成 `aepol1 # pm1`。
    """
    return re.sub(r"[-_\s]+", "", s).upper()


#: 父子層級的分隔符。字典載入器也用它判定某列是父層還是子層實體。
HIERARCHY_SEP = "#"


def expand_hierarchy(normalised: str) -> list[str]:
    """`AEPOL1#PM1` → `[AEPOL1#PM1, AEPOL1]`；無分隔符者原樣回傳。

    展開的理由：現場文件多半直接寫到腔體層，不展開的話「查機台」會漏掉那些文件，
    而漏抓比誤抓難察覺。父層詞元因此變高頻——那個鑑別力損失由 BM25 的 idf 自動吸收，
    不需要額外調參。

    只依字串結構，**不查字典**：字典覆蓋率正是本實驗要量測的未知數，
    拿它當另一個機制的前提會讓兩者的效果無法區分。
    """
    if HIERARCHY_SEP not in normalised:
        return [normalised]
    parent = normalised.split(HIERARCHY_SEP, 1)[0]
    if not parent:
        return [normalised]
    return [normalised, parent]


_LANG_RUN = re.compile(rf"[{CJK}]+|[^{CJK}]+")
_MEANINGFUL = re.compile(rf"[0-9A-Za-z{CJK}]")
_EDGE_JUNK = re.compile(rf"^[^0-9A-Za-z{CJK}]+|[^0-9A-Za-z{CJK}]+$")


def language_segments(s: str) -> list[str]:
    """把混合語言字串切成語言區塊：`Pattern Collapse 圖案倒塌` → `Pattern Collapse`、`圖案倒塌`。

    切在 CJK 與非 CJK 的交界，而**不是**沿用 `Tokenizer._plain` 的詞元切法。
    那個切法會把 `Pattern Collapse` 拆成 `Pattern` 與 `Collapse` 兩個別名，
    於是任何提到 "pattern" 的文件都會被判定含有該缺陷——別名要的是完整名稱，不是詞元。
    """
    segs: list[str] = []
    for m in _LANG_RUN.finditer(s or ""):
        seg = _EDGE_JUNK.sub("", m.group(0).strip())
        if seg and _MEANINGFUL.search(seg):
            segs.append(seg)
    return segs


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
            out.extend("ID:" + tok for tok in expand_hierarchy(normalise_identifier(m.group(0))))
            cursor = m.end()
        out.extend(self._plain(text[cursor:]))
        return out

    def find_identifiers(self, text: str) -> list[tuple[str, str, int, int]]:
        """回傳 (raw, normalised, start, end)，給實體抽取的 regex fallback 用。

        層級展開必須與 `protected()` 同步。只改一邊會造成詞彙腿認得父層、實體腿不認得——
        同一個查詢在模式 B 與模式 C 對「找不找得到腔體文件」表現不一致，
        而那種不一致會被誤讀成「實體腿沒有用」。

        父層沒有獨立的位置區間（它是子層區間的一部分），沿用子層的區間。
        位置資訊目前只用於除錯，重疊不影響正確性。
        """
        out: list[tuple[str, str, int, int]] = []
        for m in self._ident_re.finditer(text or ""):
            raw = m.group(0)
            for tok in expand_hierarchy(normalise_identifier(raw)):
                out.append((raw, tok, m.start(), m.end()))
        return out

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
