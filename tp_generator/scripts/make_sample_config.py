#!/usr/bin/env python3
"""サンプル施設設定（config/sample_facility.yaml）を生成する。

仕様書の配列例（女性ドミトリー、ベース(平日)4000、リードタイム14段階×残室13段階）に
沿ったダミーのベースマトリクスを作る。実運用では必ず施設の元ファイルから
`generate_tp.py import` で抽出するか、実データに置き換えること。
"""

from __future__ import annotations

import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tp.master import Master  # noqa: E402


def build_matrix(base: int, lead_offsets: list[int], scarcities: list[int], master: Master) -> list[list[str]]:
    return [
        [str(master.resolve(base + lo + sc)) for sc in scarcities]
        for lo in lead_offsets
    ]


def main() -> None:
    master = Master.default()

    # 平日/週末用: リードタイム14段階（パターンA・0日前あり）× 残室13段階（35室）
    heijitsu_leads = [0, 14, 16, 18, 20, 23, 26, 30, 40, 50, 60, 90, 180, 365]
    heijitsu_stocks = [35, 30, 25, 22, 20, 18, 16, 14, 12, 10, 7, 5, 3]
    heijitsu_lead_offsets = [-500, 0, 100, 150, 200, 250, 300, 300, 350, 350, 400, 400, 400, 400]
    heijitsu_scarcities = [0, 100, 200, 300, 400, 600, 800, 1100, 1500, 2100, 3600, 6600, 11000]
    heijitsu_matrix = build_matrix(4000, heijitsu_lead_offsets, heijitsu_scarcities, master)

    # 特日用: リードタイム5段階 × 残室17段階
    tokujitsu_leads = [14, 60, 120, 180, 365]
    tokujitsu_stocks = [38, 36, 34, 32, 30, 28, 26, 24, 22, 20, 17, 15, 13, 10, 7, 5, 3]
    tokujitsu_lead_offsets = [0, 200, 400, 600, 1000]
    tokujitsu_scarcities = [0, 200, 400, 600, 900, 1200, 1600, 2000, 2500, 3000, 3600, 4300, 5100, 6000, 7200, 8500, 10000]
    tokujitsu_matrix = build_matrix(8000, tokujitsu_lead_offsets, tokujitsu_scarcities, master)

    config = {
        "room_type": "女性ドミトリー",
        "excluded_room_type": "",
        "rules": [
            {
                "name": "平日/週末用",
                "base_rank": "(平日) 4000",
                "apply_from": "(平日) 2500",
                "apply_to": "(週末) 7900",
                "lead_times": heijitsu_leads,
                "stock_axis": heijitsu_stocks,
                "matrix": heijitsu_matrix,
            },
            {
                "name": "特日用",
                "base_rank": "(特別) 8000",
                "apply_from": "(特別) 8000",
                "apply_to": "(特別) 18000",
                "lead_times": tokujitsu_leads,
                "stock_axis": tokujitsu_stocks,
                "matrix": tokujitsu_matrix,
            },
        ],
    }

    out = os.path.join(os.path.dirname(__file__), "..", "config", "sample_facility.yaml")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# サンプル施設設定（ダミーデータ）\n")
        f.write("# 実運用では generate_tp.py import で元ファイルから抽出するか、実データに置き換えること。\n")
        f.write("# master: を省略すると仕様書4.4の典型的な料金ランク一覧（100個）が使われる。\n")
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, width=200)
    print(f"生成: {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
