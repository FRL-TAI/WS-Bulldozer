"""【動き：反力に応じた制御】観測した反力を見て、切削深さをその場で調整する。

前方の力が目標より小さければ深く、大きければ浅くする（熟練オペレータの「負荷を見て削る」を単純化）。
Observation.blade には blade_state の全項目（反力、地面の高さなど）が入っている。
"""
from ..episode import Command, Episode


class ExLoadControl(Episode):
    name = "ex_load_control"
    description = "【動き】前方の反力が 15 kN になるよう、切削深さを自動で調整しながら削る"
    F_TARGET = 15000.0          # 目標の反力 [N]
    GAIN = 2.0e-6               # 反力の誤差 1 N あたり、1 秒で変える深さ [m]
    D_MIN, D_MAX = 0.0, 0.15    # 深さの範囲 [m]

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.depth = 0.03       # 最初の深さ
        self.prev_t = 0.0

    def operation(self, obs):
        dt = max(0.0, obs.t - self.prev_t)
        self.prev_t = obs.t
        force = abs(obs.blade.get("F_total_x", 0.0))
        self.depth += self.GAIN * (self.F_TARGET - force) * dt
        self.depth = min(max(self.depth, self.D_MIN), self.D_MAX)
        return Command(speed=0.5, depth=self.depth)
