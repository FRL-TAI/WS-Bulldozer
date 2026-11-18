"""
往復するエピソードの折り返しの判定（共通）

「開始時の向きへの進み」p = (刃先 − 開始時の刃先)·u で、前進の端と開始位置に戻ったことを判定する。
u は、最初の前進で刃先が開始時から DIR_DISTANCE [m] 進んだ時点の向き（水平面の単位ベクトル）とする。
u が決まるまでは、開始時の刃先からの直線距離を p とする（最初の前進の途中なので、進みと同じ向き）。

開始位置からの直線距離（obs.distance）で判定すると、往復で向きが少しずつずれて横に 0.2 m 以上離れたとき、
開始位置に戻ったと判定されずに後退し続ける（T12 の ρ 1,900 で起きた）。進み p は横のずれの影響を受けない。
横のずれ（往復ごとに最大 0.16 m）は直さない（向きの帰還は入れない）。
決定：notes の decisions/2026-11-18_折り返しは進みの判定の別名版と失敗の検出で直す.md
"""
import math

from .episode import Command

DIR_DISTANCE = 0.5      # u を決める、最初の前進での刃先の移動距離 [m]


class ProgressTracker:
    """刃先（blade_state の edge_x・edge_y、ワールドの水平面）から、開始時の向きへの進みを求める"""

    def __init__(self, dir_distance=DIR_DISTANCE):
        self.dir_distance = dir_distance
        self.e0 = None   # 開始時の刃先 (x, y)
        self.u = None    # 開始時の向き (ux, uy)

    def progress(self, obs):
        ex, ey = obs.blade["edge_x"], obs.blade["edge_y"]
        if self.e0 is None:
            self.e0 = (ex, ey)
        dx, dy = ex - self.e0[0], ey - self.e0[1]
        if self.u is None:
            r = math.hypot(dx, dy)
            if r < self.dir_distance:
                return r
            self.u = (dx / r, dy / r)
        return dx * self.u[0] + dy * self.u[1]


class PassesByProgressMixin:
    """CompactionPasses（forward・count・LENGTH・SPEED を持つ）の折り返しを、進み p で判定する。
    前進で p ≥ LENGTH なら後退へ、後退で p ≤ RETURN_TOL なら前進へ（往復を1回数える）"""
    RETURN_TOL = 0.2    # 開始位置に戻ったとみなす進み [m]（ex_compaction_passes の直線距離 0.2 m と同じ）

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.tracker = ProgressTracker()

    def operation(self, obs):
        p = self.tracker.progress(obs)
        if self.forward and p >= self.LENGTH:
            self.forward = False
        elif not self.forward and p <= self.RETURN_TOL:
            self.forward = True
            self.count += 1
        speed = self.SPEED if self.forward else -self.SPEED
        return Command(speed=speed, depth=None)
