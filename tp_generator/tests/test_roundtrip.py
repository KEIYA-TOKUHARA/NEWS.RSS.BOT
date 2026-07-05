"""生成 → Excel出力 → 読み戻し → 検証 のラウンドトリップテスト。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tp.engine import Matrix, RuleType, generate_all
from tp.excel_writer import write_workbook
from tp.importer import read_data_sheet, to_config
from tp.master import Master, parse_rank
from tp.validator import validate_file


def _rules(master: Master) -> list[RuleType]:
    base = Matrix(
        room_type="女性ドミトリー",
        base_rank=parse_rank("(平日) 4000"),
        lead_times=[0, 14, 365],
        stock_axis=[35, 14, 3],
        cells=[
            [master.resolve(3500), master.resolve(5100), master.resolve(15000)],
            [master.resolve(4000), master.resolve(5400), master.resolve(15000)],
            [master.resolve(4400), master.resolve(6000), master.resolve(16500)],
        ],
    )
    return [RuleType("平日/週末用", base, parse_rank("(平日) 2500"), parse_rank("(週末) 7900"))]


def test_roundtrip(tmp_path):
    master = Master.default()
    matrices = generate_all(_rules(master), master)
    path = str(tmp_path / "out.xlsx")
    write_workbook(matrices, master, path)

    # 読み戻して内容が一致すること
    loaded = read_data_sheet(path)
    assert len(loaded) == len(matrices) == 53
    for orig, back in zip(matrices, loaded):
        assert back.room_type == orig.room_type
        assert back.base_rank == orig.base_rank
        assert back.lead_times == orig.lead_times
        assert back.stock_axis == orig.stock_axis
        assert back.cells == orig.cells

    # 検証チェックリストが全て合格すること
    results = validate_file(path, master, expected_count=53)
    assert all(r.passed for r in results), [str(r) for r in results if not r.passed]


def test_import_to_config(tmp_path):
    master = Master.default()
    matrices = generate_all(_rules(master), master)
    path = str(tmp_path / "out.xlsx")
    write_workbook(matrices, master, path)

    config = to_config(read_data_sheet(path))
    assert config["room_type"] == "女性ドミトリー"
    assert len(config["rules"]) == 1
    rule = config["rules"][0]
    assert rule["apply_from"] == "(平日) 2500"
    assert rule["apply_to"] == "(週末) 7900"
    assert rule["lead_times"] == [0, 14, 365]
    assert rule["stock_axis"] == [35, 14, 3]
