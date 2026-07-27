"""資產（`_assets/slide_xxx.png` 等）的路徑解析與驗證。

這是整個 API 裡唯一**路徑直接來自呼叫端**的地方——`concept_id` 有索引可查，
系統自己組出路徑；資產路徑不是。所以路徑穿越在這裡是實際風險，不是理論風險。

三道防線，由便宜到昂貴：

1. 早期拒絕 — 空路徑、絕對路徑、含 `..` 片段，在接觸檔案系統之前就擋下
2. 容器檢查 — 解析後的絕對路徑必須位於該 concept 所屬 bundle 的根目錄之下（安全邊界）
3. 目錄白名單 — 必須位於 `asset_dirs`（預設 `_assets`）所列名稱的目錄之下（縱深防禦）

第 2 道是真正的邊界；沒有它就能讀到語料以外的任何檔案。
第 3 道讓這個端點不會退化成「讀取 bundle 內任意檔案」的泛用介面。
"""

from __future__ import annotations

import mimetypes
import posixpath
from pathlib import Path, PurePosixPath
from typing import Iterable

from .fulltext import resolve_path
from .index import Index

DEFAULT_ASSET_DIRS: tuple[str, ...] = ("_assets",)
FALLBACK_MEDIA_TYPE = "application/octet-stream"


class AssetNotFound(FileNotFoundError):
    """concept 存在，但這個資產檔案不在磁碟上。也可能是 frontmatter 列了不存在的檔案。"""


class AssetForbidden(PermissionError):
    """路徑違反約束：逸出 bundle，或不在允許的資產目錄之下。"""


def resolve_asset(
    index: Index,
    concept_id: str,
    asset_path: str,
    asset_dirs: Iterable[str] = DEFAULT_ASSET_DIRS,
) -> Path:
    """回傳已通過三道防線的絕對路徑。`concept_id` 不存在時丟出 ConceptNotFound。"""
    meta, concept_file = resolve_path(index, concept_id)  # 順帶驗證 concept 存在

    raw = (asset_path or "").strip()
    if not raw:
        raise AssetForbidden("asset path must not be empty")

    # --- 防線 1：接觸檔案系統之前 ---
    normalised = raw.replace("\\", "/")
    if normalised.startswith("/") or PurePosixPath(normalised).is_absolute():
        raise AssetForbidden(f"不接受絕對路徑：{raw!r}")
    if ntpath_drive(normalised):
        raise AssetForbidden(f"不接受含磁碟機代號的路徑：{raw!r}")
    if ".." in PurePosixPath(normalised).parts:
        raise AssetForbidden(f"不接受含上層目錄片段的路徑：{raw!r}")

    # posixpath.normpath 收掉 "./" 與重複斜線；上一步已排除 ".."
    candidate = (concept_file.parent / posixpath.normpath(normalised)).resolve()

    # --- 防線 2：容器檢查（安全邊界，resolve() 已展開 symlink）---
    bundle_root = Path(index.bundle_roots[meta.bundle_id]).resolve()
    if not candidate.is_relative_to(bundle_root):
        raise AssetForbidden(f"路徑逸出 bundle 根目錄：{raw!r}")

    # --- 防線 3：資產目錄白名單（縱深防禦）---
    allowed = tuple(asset_dirs) or DEFAULT_ASSET_DIRS
    relative = candidate.relative_to(bundle_root)
    if not any(part in allowed for part in relative.parts[:-1]):
        raise AssetForbidden(
            f"資產必須位於 {', '.join(allowed)} 目錄之下；{raw!r} 不符。"
            "若真實語料使用其他目錄名稱，請調整設定的 asset_dirs。"
        )

    if not candidate.is_file():
        raise AssetNotFound(f"{concept_id!r} 引用的資產不存在：{raw!r}")

    return candidate


def guess_media_type(path: Path | str) -> str:
    """只看副檔名。不做內容嗅探——避免把偽裝的檔案標成可內嵌或可執行的型別。"""
    media_type, _encoding = mimetypes.guess_type(str(path))
    return media_type or FALLBACK_MEDIA_TYPE


def ntpath_drive(path: str) -> bool:
    """偵測 `C:/...` 這類 Windows 磁碟機前綴——PurePosixPath 不會把它當絕對路徑。"""
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()
