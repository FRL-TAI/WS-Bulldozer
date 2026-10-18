"""
特定の土質で、5 m の区間を3往復するエピソード

前進しながら一定の深さで削り、区間の端で排土板を上げて後退し、開始位置に戻る。これを3回くり返す。
"""
from ..episode import Command, Episode

# 使用する土質（OperaSim の TerrainMaterial（dirt_1）の設定値）
SOIL = {"cohesion": 2100.0, "friction_angle_deg": 39.98, "density": 1474.0}


class Shuttle(Episode):
    name = "ex_shuttle_3x5m"
    description = "【動き】特定の土質で、5 m の区間を3往復する"
    SOIL_RANGES = {k: (v, v) for k, v in SOIL.items()}   # 下限 = 上限 にして土質を固定

    LENGTH = 5.0          # 区間の長さ [m]
    ROUND_TRIPS = 3       # 往復の回数
    DEPTH = 0.05          # 切削深さ [m]
    SPEED = 0.5           # 前進・後退の速さ [m/s]
    TIMEOUT = 300.0       # 走行時間の上限 [s]

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.forward = True   # True: 前進中、False: 後退中
        self.count = 0        # 終わった往復の数

    def operation(self, obs):
        if self.forward and obs.distance >= self.LENGTH:
            self.forward = False              # 区間の端に着いたら後退へ
        elif not self.forward and obs.distance <= 0.2:
            self.forward = True               # 開始位置に戻ったら前進へ
            self.count += 1

        if self.forward:
            return Command(speed=self.SPEED, depth=self.DEPTH)
        return Command(speed=-self.SPEED, depth=None)   # 後退中は排土板を上げる

    def is_done(self, obs):
        return self.count >= self.ROUND_TRIPS or obs.t >= self.TIMEOUT