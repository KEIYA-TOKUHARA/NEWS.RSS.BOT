"""料金ランク（MASTER）の定義と操作。

料金ランクは「(カテゴリ) 金額」の形式（例: "(平日) 4000"）。
カテゴリは金額帯で決まる:
  (平日) 2500〜5000 / (週末) 5100〜7900 / (特別) 8000〜18000
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RANK_PATTERN = re.compile(r"^\(([^)]+)\)\s*(\d+)$")


@dataclass(frozen=True, order=True)
class Rank:
    """1つの料金ランク。金額で順序付けする。"""

    amount: int
    category: str

    def __str__(self) -> str:
        return f"({self.category}) {self.amount}"


def parse_rank(text: str) -> Rank:
    """"(平日) 4000" 形式の文字列を Rank に変換する。"""
    if isinstance(text, Rank):
        return text
    m = RANK_PATTERN.match(str(text).strip())
    if not m:
        raise ValueError(f"料金ランクの形式が不正です: {text!r}")
    return Rank(amount=int(m.group(2)), category=m.group(1))


def _default_amounts() -> list[tuple[str, int]]:
    """仕様書 4.4 の典型的な料金ランク一覧（100個）を生成する。"""
    amounts: list[tuple[str, int]] = []
    # (平日) 2500, 2700, 2900, 3000〜5000（100円刻み）
    for a in [2500, 2700, 2900] + list(range(3000, 5001, 100)):
        amounts.append(("平日", a))
    # (週末) 5100〜7900（100円刻み）
    for a in range(5100, 7901, 100):
        amounts.append(("週末", a))
    # (特別) 8000〜8900（100円刻み）
    for a in range(8000, 8901, 100):
        amounts.append(("特別", a))
    # (特別) 9100〜12900（200円刻み）
    for a in range(9100, 12901, 200):
        amounts.append(("特別", a))
    # (特別) 13200〜18000（300円刻み）
    for a in range(13200, 18001, 300):
        amounts.append(("特別", a))
    return amounts


class Master:
    """施設で使用可能な全料金ランクの一覧。

    上り幅計算の切り上げ先、および上下限打ち止めの基準となる。
    """

    def __init__(self, ranks: list[Rank]):
        if not ranks:
            raise ValueError("MASTERに料金ランクが1つもありません")
        self.ranks = sorted(ranks)
        self._amounts = [r.amount for r in self.ranks]
        self._by_amount = {r.amount: r for r in self.ranks}
        if len(self._by_amount) != len(self.ranks):
            raise ValueError("MASTERに同一金額のランクが重複しています")

    @classmethod
    def default(cls) -> "Master":
        return cls([Rank(amount=a, category=c) for c, a in _default_amounts()])

    @classmethod
    def from_strings(cls, texts: list[str]) -> "Master":
        return cls([parse_rank(t) for t in texts])

    @property
    def min_rank(self) -> Rank:
        return self.ranks[0]

    @property
    def max_rank(self) -> Rank:
        return self.ranks[-1]

    def contains(self, rank: Rank) -> bool:
        return self._by_amount.get(rank.amount) == rank

    def resolve(self, amount: int) -> Rank:
        """金額から適用ランクを決定する。

        - MASTER最低金額以下 → 最低ランクで打ち止め
        - MASTER最高金額以上 → 最高ランクで打ち止め
        - MASTERに存在しない金額 → 最も近い上位ランクに切り上げ
        """
        if amount <= self.min_rank.amount:
            return self.min_rank
        if amount >= self.max_rank.amount:
            return self.max_rank
        exact = self._by_amount.get(amount)
        if exact is not None:
            return exact
        import bisect

        idx = bisect.bisect_left(self._amounts, amount)
        return self.ranks[idx]

    def range(self, lower: Rank, upper: Rank) -> list[Rank]:
        """lower〜upper（両端含む）のランクをMASTER順で返す。"""
        return [r for r in self.ranks if lower.amount <= r.amount <= upper.amount]
