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
from dataclasses import dataclass
from typing import NamedTuple

CJK = r"一-鿿㐀-䶿豈-﫿"
_CJK_RUN = re.compile(rf"[{CJK}]+")
_LATIN = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class IdentifierPattern:
    """一條識別碼樣式，可選地宣告它的形狀決定了什麼類型。

    `type` 只在**形狀能唯一決定類型**時填。多個類型共用同一形狀時猜一個填進去，
    會讓覆蓋率統計拿到一個自信而錯誤的分母——那比沒有分母更難察覺，
    因為錯的分母跟對的分母長得一模一樣。

    `parent_type` 是層級展開後父層詞元的類型，**不**沿用子層的：
    `AEPOL1#PM1` 是 chamber_id，其父層 `AEPOL1` 是 tool_id。
    同一個字串必須永遠得到同一個類型，否則查詢端與文件端會產出不同的實體鍵而比對不到。
    """

    pattern: str
    type: str | None = None
    parent_type: str | None = None
    #: 這條樣式是否**涵蓋該類型的每一次出現**。成立時該類型的
    #: 「字典命中 / 全部出現」才是一個真的比例，覆蓋率才有分母可算。
    #: 只在 `type` 有值時有意義；父層類型一律不成立——會被展開出來，
    #: 就表示它也可以裸寫，而裸寫的形狀無法與其他類型區分。
    shape_complete: bool = False


class IdentifierHit(NamedTuple):
    raw: str
    normalised: str
    type: str | None
    start: int
    end: int


# 識別碼樣式。刻意寬鬆：demo 階段寧可多圈一點，統計會告訴我們哪些是雜訊。
# 使用者可在 config 覆寫這份清單（覆寫時只能給字串，因此一律無類型宣告——
# 我們無法替使用者判斷他的樣式形狀決定了什麼類型）。
DEFAULT_IDENTIFIER_SPECS: list[IdentifierPattern] = [
    # 父子層級（機台#腔體）。**必須排在最前面**——否則較短的樣式會先咬掉 `aepol1`，
    # `#pm1` 被丟到一般斷詞，層級關係就此消失。
    # 誤圈面：`page.html#section` 這類片段也會中。與其他樣式一樣偏 recall，
    # 誤圈量會出現在報告的 regex fallback 統計裡。
    # 父層允許含 `-` `_`：`XTR-05#PM1` 這種寫法若不放進來，會先被較短的樣式
    # 咬掉 `XTR-05`，剩下的 `#PM1` 變成獨立的 `ID:PM1`——跨機台共用，正是要修的那個病。
    IdentifierPattern(
        r"[A-Za-z0-9][A-Za-z0-9_-]{1,14}#[A-Za-z0-9][A-Za-z0-9_-]{0,11}",
        type="chamber_id",
        parent_type="tool_id",
        # 腔體一律寫成 `機台#腔體`——裸寫的 `PM1` 是腔體**名稱**（另一個類型 `chamber`），
        # 不是腔體識別碼。所以這條樣式涵蓋 chamber_id 的每一次出現。
        shape_complete=True,
    ),
    # 批號：`xxxxxx.00`。後綴 `00` 指批本身，其餘為片號——依使用者填的樣本，
    # 不是依推測。分成兩條樣式的唯一作用是統計桶的標籤：兩者的 `ID:` 詞元一字不差，
    # 所以就算這個分流判斷錯了，檢索行為完全不變。
    # 小數點前 6 碼為跑完整 flow 的量產批、超過 6 碼為 control wafer——
    # 這裡不區分兩者（那是語義不是斷詞），但**必須**兩者都圈得到：
    # 舊樣式只抓得到 6 碼那種，剛好在語義分界線上表現不一致。
    # `shape_complete` 為否：批號也可以裸寫（`AB1234`），而裸寫的形狀與其他類型
    # 無法區分，分母只會是下界、比例因此偏高——偏高的方向正好是「字典夠用、不必維護」。
    IdentifierPattern(r"[A-Za-z0-9]{6,}\.00\b", type="lot", parent_type="lot"),
    # 晶圓號。父層是批底（批號去掉後綴），與批號本身共用同一個詞元，
    # 「查批號找得到晶圓文件」就是靠這裡會合。父層類型必須與上一條一致，
    # 否則同一個字串會因為先看到哪個兄弟而拿到不同的實體鍵。
    IdentifierPattern(r"[A-Za-z0-9]{6,}\.\d{2}\b", type="wafer", parent_type="lot", shape_complete=True),
    # 作業序號：純數字，小數點後三碼——位數與批號不同，這是兩者唯一可靠的區分點。
    # 前置 `\b` 不可省：少了它，`10234.000` 會從第二個字元咬進去，
    # 產出 `1` + `ID:0234.000`——一個憑空捏造的識別碼，比完全沒抓到還糟。
    # 小數點前的位數放寬到 6：規格寫的是 3~4 碼，但真實樣本有 5 碼。
    IdentifierPattern(r"\b\d{3,6}\.\d{3}\b", type="op_no", shape_complete=True),
    # 以下樣式的形狀**不決定類型**：機台、製程、流程、料號共用這些形狀。
    # 猜一個填上去會讓覆蓋率的分母錯得看不出來，所以一律留白 → `unknown`。
    IdentifierPattern(r"cpt_[0-9A-Za-z]+"),
    IdentifierPattern(r"[A-Za-z]{1,2}\d{1,2}[-_][A-Za-z]{2,12}"),  # M1-etch, W2_poly
    IdentifierPattern(r"[A-Za-z]{2,6}[-_ ]?\d{1,5}(?:[-_][A-Za-z0-9]{1,8})+"),  # FL-A100-02
    IdentifierPattern(r"[A-Za-z]{2,6}[-_]\d{1,5}"),  # TEL-05, XTR-12
    # 空白分隔（TEL 05）。刻意收進來：真實文件常這樣寫，漏抓會讓模式 B/C 被低估，
    # 反而導出「識別碼不重要」的錯誤結論。代價是會誤圈 "slide 005" 這類詞組——
    # 誤圈量會出現在報告的 regex fallback 統計裡，而且整份樣式清單可由 config 覆寫。
    IdentifierPattern(r"[A-Za-z]{2,6} \d{1,5}\b"),
    IdentifierPattern(r"[A-Za-z]{2,5}\d{1,4}\b"),  # PM3, TEL05
    IdentifierPattern(r"\d{1,2}[A-Za-z]{1,3}\d{2,4}"),  # 3M12 之類料號樣式
    # 製程世代（tech）刻意**不放樣式**。
    #
    # 真實樣本是 `A16` / `n02` / `n5` / `n3`——前綴不固定、位數不固定，
    # 能涵蓋它們的正則是 `[A-Za-z]\d{1,2}`，那會連 `p5`、`Q3`、`v2` 一起圈進來。
    #
    # 更關鍵的是：只涵蓋一部分比完全不涵蓋更糟。`\b[Nn]\d{2}\b` 抓得到 `n02`
    # 卻抓不到 `n5`，於是同一個類型內部行為不一致——那正是 lot 在 6 碼與 7 碼
    # 之間表現不一致的同一種錯誤，而那種不一致不會報錯，只會讓數據悄悄偏掉。
    #
    # tech 是極小的封閉集合，交給實體字典（CSV 單欄即可）比正則精確得多。
    # 沒有樣式時它仍是完整的單一詞元（`a16`），模式 B 相對 A 的鑑別力不受影響。
]

#: 設定檔介面維持「字串清單」不變——設定檔給不了類型宣告，也不該給。
DEFAULT_IDENTIFIER_PATTERNS: list[str] = [spec.pattern for spec in DEFAULT_IDENTIFIER_SPECS]

#: 小數點後綴的層級分隔。與 `#` 分開處理：`.` 也出現在作業序號裡，
#: 而作業序號的小數點分隔的是序號本身的組成，不是父子關係。
SUFFIX_SEP = "."


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
    if HIERARCHY_SEP in normalised:
        parent = normalised.split(HIERARCHY_SEP, 1)[0]
        return [normalised, parent] if parent else [normalised]

    if SUFFIX_SEP in normalised:
        parent = normalised.split(SUFFIX_SEP, 1)[0]
        # 純數字者是作業序號（`1234.000`），小數點分隔的是序號本身的組成。
        # 展開它會產生 `1234` 這個與滿地無關數字碰撞的詞元，是淨損失。
        if parent and not parent.isdigit():
            return [normalised, parent]

    return [normalised]


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


_BUILTIN_BY_PATTERN = {spec.pattern: spec for spec in DEFAULT_IDENTIFIER_SPECS}


def resolve_specs(
    patterns: "list[str] | list[IdentifierPattern] | list[dict]",
) -> list[IdentifierPattern]:
    """把樣式字串還原成 spec。字串與內建樣式**逐條比對**，相同者沿用其類型宣告。

    設定檔只能給字串，所以這一步不做的話，類型宣告會在「設定 → Tokenizer」之間
    被靜靜丟掉，覆蓋率又會退回恆為 1.0——而且沒有任何地方會報錯。這正是本次要修的病，
    不該在修它的路上重現一次。

    逐條而非整份比對：使用者加一條自訂樣式，不該讓其他樣式的宣告一起失效。
    相同的樣式字串就是相同的形狀，沿用它的判斷是安全的。
    使用者自訂的字串樣式沒有宣告，其命中歸入 `unknown`——我們確實不知道那些是什麼類型。

    設定也可以改給 mapping：`{pattern, type, parent_type, shape_complete}`，自行宣告。
    這條路存在的理由是保密邊界——敏感的識別碼組成規則必須能住在未進版控的本機設定，
    而只收字串會迫使使用者在「斷詞正確」與「統計正確」之間二選一。
    """
    out: list[IdentifierPattern] = []
    for p in patterns:
        if isinstance(p, IdentifierPattern):
            out.append(p)
        elif isinstance(p, dict):
            out.append(
                IdentifierPattern(
                    pattern=p["pattern"],
                    type=p.get("type"),
                    parent_type=p.get("parent_type"),
                    shape_complete=bool(p.get("shape_complete", False)),
                )
            )
        else:
            out.append(_BUILTIN_BY_PATTERN.get(p, IdentifierPattern(p)))
    return out


class Tokenizer:
    def __init__(self, identifier_patterns: list[str] | list[IdentifierPattern] | None = None) -> None:
        specs = resolve_specs(identifier_patterns) if identifier_patterns else DEFAULT_IDENTIFIER_SPECS
        self.specs = specs
        self.identifier_patterns = [s.pattern for s in specs]
        # 長樣式優先，避免 `FL-A100-02` 被短樣式先咬掉一半
        self._ident_re = re.compile("|".join(f"(?:{s.pattern})" for s in specs))
        self._spec_res = [re.compile(s.pattern) for s in specs]

    @property
    def shape_complete_types(self) -> frozenset[str]:
        """分母可測的類型——由**實際使用的樣式**導出，不是寫死的常數。

        使用者換掉樣式清單時，能不能算比例也跟著變。寫死會讓一組改過的樣式
        繼續配著一個不再成立的完整性宣稱，而那不會報錯。
        """
        return frozenset(s.type for s in self.specs if s.type and s.shape_complete)

    def _spec_of(self, matched: str) -> IdentifierPattern:
        """回推是哪一條樣式產生了這段命中。

        交替式取的是**第一條在該位置比對得到**的樣式，所以只要依序找出第一條能
        `fullmatch` 這段文字的樣式，就是當初的贏家：更前面的樣式若能完整比對這段，
        它當初就會贏，不會輪到後面。

        用命名群組讀 `lastgroup` 會更快，但使用者自訂樣式若含捕捉群組就會失準——
        一個安靜失準的歸類正是本次要修掉的那種錯誤。
        """
        for spec, rx in zip(self.specs, self._spec_res, strict=True):
            if rx.fullmatch(matched):
                return spec
        return IdentifierPattern(matched)  # 理論上不會發生；退回無類型宣告

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

    def find_identifier_spans(self, text: str) -> list[tuple[int, int]]:
        """原始比對命中的位置區間，不含層級展開。

        給格式檢查用：判斷一個樣本是否被**整段**圈出，需要的是實際比對到幾段、
        蓋住哪些位置，而不是展開後有幾個詞元。
        """
        return [(m.start(), m.end()) for m in self._ident_re.finditer(text or "")]

    def find_identifiers(self, text: str) -> list[IdentifierHit]:
        """回傳每個詞元的 (raw, normalised, type, start, end)，給實體抽取的 regex fallback 用。

        `type` 是**形狀決定的類型**，未宣告者為 `None`（呼叫端歸為 `unknown`）。
        父層帶的是樣式另行宣告的父層類型，不沿用子層——`AEPOL1#PM1` 是腔體，
        `AEPOL1` 是機台，把父層標成腔體會讓腔體的覆蓋率分母混進機台。

        層級展開必須與 `protected()` 同步。只改一邊會造成詞彙腿認得父層、實體腿不認得——
        同一個查詢在模式 B 與模式 C 對「找不找得到腔體文件」表現不一致，
        而那種不一致會被誤讀成「實體腿沒有用」。

        父層沒有獨立的位置區間（它是子層區間的一部分），沿用子層的區間。
        位置資訊目前只用於除錯，重疊不影響正確性。
        """
        out: list[IdentifierHit] = []
        for m in self._ident_re.finditer(text or ""):
            raw = m.group(0)
            spec = self._spec_of(raw)
            toks = expand_hierarchy(normalise_identifier(raw))
            for i, tok in enumerate(toks):
                etype = spec.type if i == 0 else spec.parent_type
                out.append(IdentifierHit(raw, tok, etype, m.start(), m.end()))
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
