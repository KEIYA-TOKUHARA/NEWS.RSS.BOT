"""上り幅ルールによるTPマトリクス生成エンジン（仕様書 6〜7章）。

基本原則:
  1つのベースマトリクスから、他の全料金ランクのマトリクスを生成する。
  このとき、ベースからの上り幅（差分）を維持する。

計算式:
  上り幅 = 元の料金 - 元のベース料金
  新しい料金 = 新しいベース料金 + 上り幅

その後、MASTERに基づいて上下限打ち止め・切り上げを行う。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .master import Master, Rank, parse_rank


@dataclass
class Matrix:
    """DATAシート上の1つのTPマトリクス。"""

    room_type: str
    base_rank: Rank
    lead_times: list[int]  # リードタイム軸（行）
    stock_axis: list[int]  # 残室軸（列）
    cells: list[list[Rank]]  # cells[リードタイム行][残室列]
    excluded_room_type: str = ""
    stock_note: str = "※手仕舞いの場合、セルに「手仕舞い」と入力してください。"

    def __post_init__(self) -> None:
        if len(self.cells) != len(self.lead_times):
            raise ValueError(
                f"マトリクス行数({len(self.cells)})がリードタイム軸({len(self.lead_times)})と一致しません"
            )
        for i, row in enumerate(self.cells):
            if len(row) != len(self.stock_axis):
                raise ValueError(
                    f"リードタイム{self.lead_times[i]}の列数({len(row)})が"
                    f"残室軸({len(self.stock_axis)})と一致しません"
                )


@dataclass
class RuleType:
    """1つのルールタイプ（例: 平日/週末用、特日用）。

    ベースマトリクスと適用範囲を持ち、範囲内の各料金ランクの
    マトリクスを上り幅ルールで生成する。
    """

    name: str
    base: Matrix
    apply_from: Rank  # 適用範囲の下限ランク
    apply_to: Rank  # 適用範囲の上限ランク


def apply_uphaba(cell_amount: int, orig_base: int, new_base: int, master: Master) -> Rank:
    """1セル分の上り幅適用（打ち止め・切り上げ込み）。"""
    uphaba = cell_amount - orig_base
    return master.resolve(new_base + uphaba)


def generate_matrix(base: Matrix, new_base_rank: Rank, master: Master) -> Matrix:
    """ベースマトリクスから、新しいベース料金ランクのマトリクスを生成する。"""
    new_cells = [
        [apply_uphaba(cell.amount, base.base_rank.amount, new_base_rank.amount, master) for cell in row]
        for row in base.cells
    ]
    return Matrix(
        room_type=base.room_type,
        base_rank=new_base_rank,
        lead_times=list(base.lead_times),
        stock_axis=list(base.stock_axis),
        cells=new_cells,
        excluded_room_type=base.excluded_room_type,
        stock_note=base.stock_note,
    )


def generate_all(rules: list[RuleType], master: Master) -> list[Matrix]:
    """全ルールタイプの適用範囲分のマトリクスを、MASTERのランク順に生成する。"""
    matrices: list[Matrix] = []
    for rule in rules:
        for rank in master.range(rule.apply_from, rule.apply_to):
            matrices.append(generate_matrix(rule.base, rank, master))
    return matrices


def rules_from_config(config: dict) -> tuple[Master, list[RuleType]]:
    """設定dict（YAML由来）から Master と RuleType 一覧を組み立てる。"""
    if "master" in config and config["master"]:
        master = Master.from_strings(config["master"])
    else:
        master = Master.default()

    rules: list[RuleType] = []
    for rc in config["rules"]:
        base_rank = parse_rank(rc["base_rank"])
        if not master.contains(base_rank):
            raise ValueError(f"ベース料金ランク {base_rank} がMASTERに存在しません")
        cells = [[parse_rank(c) for c in row] for row in rc["matrix"]]
        base = Matrix(
            room_type=config["room_type"],
            base_rank=base_rank,
            lead_times=[int(v) for v in rc["lead_times"]],
            stock_axis=[int(v) for v in rc["stock_axis"]],
            cells=cells,
            excluded_room_type=config.get("excluded_room_type", "") or "",
        )
        rules.append(
            RuleType(
                name=rc["name"],
                base=base,
                apply_from=parse_rank(rc["apply_from"]),
                apply_to=parse_rank(rc["apply_to"]),
            )
        )
    return master, rules
