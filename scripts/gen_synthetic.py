#!/usr/bin/env python3
"""合成 OKF bundle 產生器的獨立入口（等同 `yedai gen-synthetic`）。

⚠️ 合成資料僅供驗證程式正確性，不得用於調參或推論檢索效果。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yedai.synthetic import DISCLAIMER, generate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out", type=Path, help="輸出目錄")
    ap.add_argument("-n", "--bundles", type=int, default=30, help="bundle 數量（預設 30）")
    ap.add_argument("-s", "--seed", type=int, default=42, help="隨機種子（相同種子產生相同輸出）")
    args = ap.parse_args()

    result = generate(args.out, n_bundles=args.bundles, seed=args.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n" + DISCLAIMER, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
