"""
【締固め】排土板を上げたまま同じ区間を往復し、履帯で地面を踏み固めるエピソード（実験A）

前進で LENGTH [m] 進み、排土板を上げたまま後退して開始位置に戻る。これを ROUND_TRIPS 回くり返す。
1往復で走路の上を2回（前進・後退）通る。

Unity 側の CompactionProbe（名前が "ex_compaction" で始まるエピソードのときだけ記録する）が、
走路と対照の列の地表の高さと締固めの程度を一定間隔で CSV に書き出す。
"""
from ..episode import Command, Episode
from ..turnaround import PassesByProgressMixin

# 使用する土質（OperaSim の TerrainMaterial（dirt_1）の設定値。ex_shuttle と同じ）
SOIL = {"cohesion": 2100.0, "friction_angle_deg": 39.98, "density": 1474.0}


class CompactionPasses(Episode):
    name = "ex_compaction_passes"
    description = "【締固め】排土板を上げたまま 8 m の区間を往復し、履帯で地面を踏み固める"
    SOIL_RANGES = {k: (v, v) for k, v in SOIL.items()}   # 下限 = 上限 にして土質を固定
    RECORD_COMPACTION = True

    LENGTH = 8.0          # 区間の長さ [m]
    ROUND_TRIPS = 4       # 往復の回数（走路の上を通る回数は 2 倍）
    SPEED = 0.5           # 前進・後退の速さ [m/s]
    TIMEOUT = 600.0       # 走行時間の上限 [s]

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.forward = True   # True: 前進中、False: 後退中
        self.count = 0        # 終わった往復の数

    def sample_params(self, rng):
        return {"length": self.LENGTH, "round_trips": self.ROUND_TRIPS, "speed": self.SPEED}

    def operation(self, obs):
        if self.forward and obs.distance >= self.LENGTH:
            self.forward = False              # 区間の端に着いたら後退へ
        elif not self.forward and obs.distance <= 0.2:
            self.forward = True               # 開始位置に戻ったら前進へ
            self.count += 1

        speed = self.SPEED if self.forward else -self.SPEED
        return Command(speed=speed, depth=None)   # 前進・後退とも排土板は上げたまま

    def is_done(self, obs):
        return self.count >= self.ROUND_TRIPS or obs.t >= self.TIMEOUT

# ---- T31：折り返しを「開始時の向きへの進み」で判定する別名版（decisions/2026-11-18_折り返しは進みの判定の別名版と失敗の検出で直す.md）
# 上のクラスの動きは変えない（phase0 の再現性のため）。失敗しない場合の動きは同じ
class CompactionPassesV2(PassesByProgressMixin, CompactionPasses):
    name = "ex_compaction_passes_v2"
    description = "【締固め】ex_compaction_passes と同じ往復。折り返しを刃先の開始時の向きへの進みで判定する"


class CompactionPassesV2Rho1900(CompactionPassesV2):
    name = "ex_compaction_passes_v2_rho1900"
    description = "【締固め】ex_compaction_passes_v2 を ρ 1,900 で（maxDensity は Unity の案D で 1.357·ρ）"
    SOIL_RANGES = {**CompactionPasses.SOIL_RANGES, "density": (1900.0, 1900.0)}
