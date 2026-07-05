#!/usr/bin/env python3
"""手間いらずTP設定Excelファイルの生成CLI。

使い方:
  設定ファイルから生成:
    python generate_tp.py generate --config config/sample_facility.yaml --out output.xlsx

  既存の元ファイル（Excel）から設定YAMLを抽出:
    python generate_tp.py import --xlsx 元ファイル.xlsx --out config/施設名.yaml

  生成済みファイルの検証のみ:
    python generate_tp.py validate --xlsx output.xlsx
"""

from __future__ import annotations

import argparse
import sys

import yaml

from tp.engine import generate_all, rules_from_config
from tp.excel_writer import write_workbook
from tp.importer import read_data_sheet, read_master_sheet, to_config
from tp.master import Master
from tp.validator import validate_file


def cmd_generate(args: argparse.Namespace) -> int:
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    master, rules = rules_from_config(config)
    matrices = generate_all(rules, master)
    write_workbook(matrices, master, args.out)

    print(f"生成完了: {args.out}")
    print(f"  マトリクス総数: {len(matrices)}個")
    for rule in rules:
        count = len(master.range(rule.apply_from, rule.apply_to))
        print(f"  - {rule.name}: {count}個（{rule.apply_from} 〜 {rule.apply_to}）")

    print("\n検証チェックリスト:")
    results = validate_file(args.out, master, expected_count=len(matrices))
    for r in results:
        print(f"  {r}")
    return 0 if all(r.passed for r in results) else 1


def cmd_import(args: argparse.Namespace) -> int:
    matrices = read_data_sheet(args.xlsx)
    master_strings = read_master_sheet(args.xlsx)
    config = to_config(matrices, master_strings)

    with open(args.out, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False, width=200)

    print(f"抽出完了: {args.out}")
    print(f"  読み取ったマトリクス: {len(matrices)}個")
    print(f"  特定したルールタイプ: {len(config['rules'])}種類")
    for rule in config["rules"]:
        print(f"  - {rule['name']}: ベース {rule['base_rank']}（{rule['apply_from']} 〜 {rule['apply_to']}）")
    print("※ 抽出された適用範囲・ベースは必ず施設の運用方針と照合してください。")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    master_strings = read_master_sheet(args.xlsx)
    master = Master.from_strings(master_strings) if master_strings else Master.default()
    results = validate_file(args.xlsx, master)
    for r in results:
        print(r)
    return 0 if all(r.passed for r in results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="手間いらずTP設定ファイル生成ツール")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="設定YAMLからTP設定Excelを生成")
    p_gen.add_argument("--config", required=True, help="施設設定YAMLのパス")
    p_gen.add_argument("--out", required=True, help="出力xlsxのパス")
    p_gen.set_defaults(func=cmd_generate)

    p_imp = sub.add_parser("import", help="既存の元ファイルから設定YAMLを抽出")
    p_imp.add_argument("--xlsx", required=True, help="元ファイル（xlsx）のパス")
    p_imp.add_argument("--out", required=True, help="出力する設定YAMLのパス")
    p_imp.set_defaults(func=cmd_import)

    p_val = sub.add_parser("validate", help="生成済みxlsxの検証")
    p_val.add_argument("--xlsx", required=True, help="検証対象のxlsx")
    p_val.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
