"""【動き：旋回】角速度（yaw_rate）を変えて S 字に曲がりながら削り、同じ軌跡を後退でたどって戻る。

旋回させると、終了後の自動の後退（まっすぐ後退するだけ）では開始位置に戻れない。
そこで、前進中に送った指令を覚えておき、逆の順番・逆の符号で送り直して、元の場所へ戻ってから終える
（スリップがあるので、戻る位置には多少の誤差が出る）。
"""
import math

from ..episode import Command, Episode


class ExTurning(Episode):
    name = "ex_turning"
    description = "【動き】S 字に曲がりながら 12 秒削り、同じ軌跡を後退でたどって戻る"
    SPEED = 0.5             # m/s
    YAW_AMP = 0.15          # 角速度の振幅 [rad/s]（正で左旋回）
    PERIOD = 12.0           # S 字1周期の時間 [s]
    TIMEOUT = 60.0

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.history = []        # 前進中に送った (時刻, 角速度)
        self.back_start = None   # 後退を始めた時刻

    def operation(self, obs):
        if obs.t < self.PERIOD:                                   # 前進（削る）
            w = self.YAW_AMP * math.sin(2 * math.pi * obs.t / self.PERIOD)
            self.history.append((obs.t, w))
            return Command(speed=self.SPEED, depth=0.04, yaw_rate=w)
        if self.back_start is None:
            self.back_start = obs.t
        # 後退：前進のときの指令を、後ろから順に、符号を逆にして送る
        tb = self.PERIOD - (obs.t - self.back_start)
        w = next((w for t, w in reversed(self.history) if t <= tb), 0.0)
        return Command(speed=-self.SPEED, depth=None, yaw_rate=-w)

    def is_done(self, obs):
        returned = self.back_start is not None and obs.t - self.back_start >= self.PERIOD
        return returned or obs.t >= self.TIMEOUT
