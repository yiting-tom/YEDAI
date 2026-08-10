"""defect → 判斷方法的查表資源。

**這不是一個檢索索引，而且刻意不是。**

taxonomy 是每個 defect 一條的判斷方法：看到這種形貌，該往哪些 module 查、依據
什麼判準。存取模式是「以 defect 為鍵取回那一條」，不是「回傳最相關的幾筆」。

把它放進倒排索引會有兩個後果。第一，呼叫端拿到的是「最像的幾列」而不是「那一條」，
而且沒有任何訊號告訴它拿到的不是要的。第二，模型會拿著另一個 defect 的判斷方法
去解讀影像——那比沒有方法更糟，因為錯誤的方法看起來跟正確的一樣有條理。

所以查無條目一律回傳「無此條目」，不做任何近似比對。上游必須自己處理
「這個 defect 還沒有整理過方法」的情況，而那是它該知道的事實。

覆蓋率（有條目的 defect 佔比）是這份資源的第一級指標：taxonomy 是部分填充的
衍生欄位，缺口本來就存在，看得見才追得動。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: defect 未宣告類別時歸入這裡。與實體覆蓋率的 UNKNOWN_TYPE 同樣的用意：
#: 沒有類別的條目不能從分母裡消失，否則覆蓋率會看起來比實際好。
UNKNOWN_CATEGORY = "uncategorised"

#: 條目接受的鍵。拼錯的鍵靜默忽略，症狀是「我明明寫了方法卻沒被讀到」。
ENTRY_KEYS: frozenset[str] = frozenset({"description", "method", "modules", "category", "notes"})


class TaxonomyNotFound(KeyError):
    """查無條目。刻意是例外而不是 None——沉默的 None 會被當成「沒有方法可用」
    一路傳下去，而呼叫端分不出那是「沒整理」還是「查錯鍵」。"""


@dataclass(frozen=True)
class TaxonomyEntry:
    defect: str
    #: 這個 defect 長什麼樣（給看圖的模型當判斷依據）。
    description: str = ""
    #: 怎麼從影像推出候選 module。**方法，不是答案**——它的正確性無法靜態檢查，
    #: 只能用歷史結案回放來驗證。
    method: str = ""
    #: 選填的候選 module 提示。留空是正常的：多數條目給的是方法而非清單。
    modules: tuple[str, ...] = ()
    category: str = UNKNOWN_CATEGORY
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "defect": self.defect,
            "description": self.description,
            "method": self.method,
            "modules": list(self.modules),
            "category": self.category,
            "notes": self.notes,
        }


@dataclass
class Taxonomy:
    entries: dict[str, TaxonomyEntry] = field(default_factory=dict)
    #: defect 全集。覆蓋率的**分母**——沒有它就只知道「有幾條」，
    #: 不知道「還缺幾條」，而缺口才是要追的東西。
    defects: dict[str, str] = field(default_factory=dict)  # defect → category
    #: 條目指向 defect 清單中沒有的鍵。保留而非丟棄：它可能表示清單缺漏，
    #: 而那本身是要處理的訊號。
    unknown_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        path: str | Path | None,
        defects: dict[str, str] | None = None,
    ) -> Taxonomy:
        """載入 taxonomy。未提供路徑時回傳空資源——系統仍須能正常啟動。"""
        tx = cls(defects=dict(defects or {}))
        if not path:
            return tx
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"taxonomy resource not found: {p}")
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            # 以空資源靜默啟動，症狀會是「所有 defect 都查不到方法」——
            # 那看起來跟「還沒整理」一模一樣。
            raise ValueError(f"taxonomy resource is not valid YAML: {p} — {exc}") from exc
        if raw is None:
            return tx
        if not isinstance(raw, dict):
            raise ValueError(f"taxonomy resource must be a YAML mapping: {p}")
        tx._ingest(raw, p)
        return tx

    @classmethod
    def from_config(cls, cfg: Any, defects: dict[str, str] | None = None) -> Taxonomy:
        """由設定載入 taxonomy 與它的分母。生產路徑一律走這裡。

        分成兩個入口的話，總有一條路徑會忘記載入 defect 清單，而症狀是覆蓋率
        回報 `total: null`——看起來像「沒設定」，實際上是「這條路徑漏了」。
        """
        if defects is None:
            defects = load_defect_catalogue(getattr(cfg, "defect_catalogue_path", None))
        return cls.load(getattr(cfg, "taxonomy_path", None), defects)

    def _ingest(self, raw: dict, path: Path) -> None:
        for key, value in raw.items():
            defect = str(key).strip()
            if not defect:
                raise ValueError(f"taxonomy resource has an empty defect key: {path}")
            if value is None:
                value = {}
            if not isinstance(value, dict):
                raise ValueError(f"taxonomy[{defect!r}] must be a mapping: {path}")
            unknown = set(value) - ENTRY_KEYS
            if unknown:
                raise ValueError(
                    f"taxonomy[{defect!r}] has unknown keys: {sorted(unknown)}; "
                    f"expected one of {sorted(ENTRY_KEYS)} ({path})"
                )
            modules = value.get("modules") or []
            if not isinstance(modules, list):
                raise ValueError(f"taxonomy[{defect!r}].modules must be a list: {path}")
            category = str(value.get("category") or "").strip()
            if not category:
                category = self.defects.get(defect, UNKNOWN_CATEGORY)
            self.entries[defect] = TaxonomyEntry(
                defect=defect,
                description=str(value.get("description") or ""),
                method=str(value.get("method") or ""),
                modules=tuple(str(m) for m in modules),
                category=category,
                notes=str(value.get("notes") or ""),
            )
            if self.defects and defect not in self.defects:
                self.unknown_keys.append(defect)
                self.warnings.append(
                    f"taxonomy 條目 {defect!r} 不在 defect 清單中——"
                    f"可能是清單缺漏，條目仍予保留"
                )

    # ------------------------------------------------------------------

    def get(self, defect: str) -> TaxonomyEntry:
        """以 defect 為鍵取回。查無條目時 raise，**不做近似比對**。"""
        entry = self.entries.get(defect)
        if entry is None:
            raise TaxonomyNotFound(defect)
        return entry

    def has(self, defect: str) -> bool:
        return defect in self.entries

    def __len__(self) -> int:
        return len(self.entries)

    # ------------------------------------------------------------------

    def coverage(self) -> dict[str, Any]:
        """覆蓋率統計。只以類別名為鍵——類別名屬 schema，defect 名屬語料內容。

        沒有 defect 清單時分母不可知：回報 `total: null` 而不是拿條目數當分母，
        後者會讓覆蓋率恆為 1.0，也就是永遠看不見缺口。
        """
        if not self.defects:
            return {
                "covered": len(self.entries),
                "total": None,
                "unknown_keys": len(self.unknown_keys),
                "by_category": {},
            }
        by_category: dict[str, dict[str, int]] = {}
        for defect, category in self.defects.items():
            bucket = by_category.setdefault(category or UNKNOWN_CATEGORY, {"covered": 0, "total": 0})
            bucket["total"] += 1
            if defect in self.entries:
                bucket["covered"] += 1
        return {
            "covered": sum(1 for d in self.defects if d in self.entries),
            "total": len(self.defects),
            "unknown_keys": len(self.unknown_keys),
            "by_category": dict(sorted(by_category.items())),
        }


def load_defect_catalogue(path: str | Path | None) -> dict[str, str]:
    """defect 全集：`defect → category`。覆蓋率的分母來源。

    內容屬 fab 專有知識，實際檔案走 `.local`。
    """
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"defect catalogue not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"defect catalogue must be a YAML mapping: {p}")
    out: dict[str, str] = {}
    for key, value in raw.items():
        defect = str(key).strip()
        if not defect:
            continue
        if isinstance(value, dict):
            out[defect] = str(value.get("category") or UNKNOWN_CATEGORY)
        else:
            out[defect] = str(value or UNKNOWN_CATEGORY)
    return out
