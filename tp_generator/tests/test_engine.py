"""仕様書の計算例・打ち止めルールに基づくテスト。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tp.engine import Matrix, RuleType, apply_uphaba, generate_all, generate_matrix
from tp.master import Master, Rank, parse_rank


@pytest.fixture
def master() -> Master:
    return Master.default()


class TestMaster:
    def test_default_has_100_ranks(self, master):
        assert len(master.ranks) == 100

    def test_category_boundaries(self, master):
        assert str(master.resolve(2500)) == "(平日) 2500"
        assert str(master.resolve(5000)) == "(平日) 5000"
        assert str(master.resolve(5100)) == "(週末) 5100"
        assert str(master.resolve(7900)) == "(週末) 7900"
        assert str(master.resolve(8000)) == "(特別) 8000"
        assert str(master.resolve(18000)) == "(特別) 18000"

    def test_roundup_to_next_rank(self, master):
        # (平日) 2500の次は2700（2600は存在しない）→上位に切り上げ
        assert str(master.resolve(2600)) == "(平日) 2700"
        # 9100〜は200円刻み → 9200は9300に切り上げ
        assert str(master.resolve(9200)) == "(特別) 9300"
        # 13200〜は300円刻み → 13000は13200に切り上げ
        assert str(master.resolve(13000)) == "(特別) 13200"


class TestUphaba:
    def test_spec_example_1_plus(self, master):
        """計算例1: ベース(平日)4000でセル(特別)15000 → (平日)2500に適用 = (特別)13500"""
        result = apply_uphaba(15000, 4000, 2500, master)
        assert str(result) == "(特別) 13500"

    def test_spec_example_2_lower_clamp(self, master):
        """計算例2: ベース(平日)4000でセル(平日)3500 → (平日)2500に適用 = 2000 → 下限打ち止め(平日)2500"""
        result = apply_uphaba(3500, 4000, 2500, master)
        assert str(result) == "(平日) 2500"

    def test_spec_example_3_category_transition(self, master):
        """計算例3: ベース(平日)4000でセル(週末)5400 → (週末)7000に適用 = 8400 → (特別)8400"""
        result = apply_uphaba(5400, 4000, 7000, master)
        assert str(result) == "(特別) 8400"

    def test_upper_clamp(self, master):
        """打ち止めルール: 21000円 → (特別)18000"""
        result = apply_uphaba(15000, 4000, 10100, master)  # 10100 + 11000 = 21100
        assert str(result) == "(特別) 18000"

    def test_lower_clamp_example(self, master):
        """打ち止めルール: 1900円 → (平日)2500"""
        result = apply_uphaba(3400, 4000, 2500, master)  # 2500 - 600 = 1900
        assert str(result) == "(平日) 2500"


def _base_matrix() -> Matrix:
    m = Master.default()
    return Matrix(
        room_type="女性ドミトリー",
        base_rank=parse_rank("(平日) 4000"),
        lead_times=[0, 14, 365],
        stock_axis=[35, 14, 3],
        cells=[
            [m.resolve(3500), m.resolve(5100), m.resolve(15000)],
            [m.resolve(4000), m.resolve(5400), m.resolve(15000)],
            [m.resolve(4400), m.resolve(6000), m.resolve(16500)],
        ],
    )


class TestGenerateMatrix:
    def test_base_regenerates_itself(self, master):
        base = _base_matrix()
        same = generate_matrix(base, base.base_rank, master)
        assert same.cells == base.cells

    def test_not_flat_100yen_addition(self, master):
        """注意点1: (平日)4100版は+100円加算ではなく上り幅の適用で作る。"""
        base = _base_matrix()
        gen = generate_matrix(base, parse_rank("(平日) 4100"), master)
        # 上り幅 -500 → 4100 - 500 = 3600 （+100円加算の3600と一致するケースもあるが）
        assert str(gen.cells[0][0]) == "(平日) 3600"
        # 上り幅 +11000 → 4100 + 11000 = 15100 → MASTERに無いので15300に切り上げ
        # （+100円加算なら15100でMASTER違反になるところ）
        assert str(gen.cells[0][2]) == "(特別) 15300"

    def test_generate_all_counts(self, master):
        """典型例: 平日/週末用53個＋特日用47個 = 100個"""
        base = _base_matrix()
        tokujitsu = Matrix(
            room_type="女性ドミトリー",
            base_rank=parse_rank("(特別) 8000"),
            lead_times=[14, 365],
            stock_axis=[25, 3],
            cells=[
                [master.resolve(8000), master.resolve(12000)],
                [master.resolve(9000), master.resolve(14000)],
            ],
        )
        rules = [
            RuleType("平日/週末用", base, parse_rank("(平日) 2500"), parse_rank("(週末) 7900")),
            RuleType("特日用", tokujitsu, parse_rank("(特別) 8000"), parse_rank("(特別) 18000")),
        ]
        matrices = generate_all(rules, master)
        assert len(matrices) == 100
        heijitsu = [m for m in matrices if len(m.lead_times) == 3]
        tokubetsu = [m for m in matrices if len(m.lead_times) == 2]
        assert len(heijitsu) == 53
        assert len(tokubetsu) == 47
        # MASTER順に並んでいる
        amounts = [m.base_rank.amount for m in heijitsu]
        assert amounts == sorted(amounts)

    def test_lower_clamp_at_lowest_base(self, master):
        """下限打ち止め確認: (平日)2500マトリクスの0日前・残室多 = (平日)2500"""
        base = _base_matrix()
        gen = generate_matrix(base, parse_rank("(平日) 2500"), master)
        assert str(gen.cells[0][0]) == "(平日) 2500"

    def test_upper_clamp_at_highest_base(self, master):
        """上限打ち止め確認: (特別)18000マトリクスの365日前・残室少 = (特別)18000"""
        base = _base_matrix()
        gen = generate_matrix(base, parse_rank("(特別) 18000"), master)
        assert str(gen.cells[2][2]) == "(特別) 18000"
