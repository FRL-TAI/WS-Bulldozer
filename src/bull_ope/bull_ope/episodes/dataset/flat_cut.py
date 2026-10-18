"""
学習データ用のエピソード（段階7で導入）。関門1〜6の結果を反映した設計。

置き場所: bull_ope/episodes/dataset/flat_cut.py

設計の根拠
- 土質の範囲：関門6で調べた範囲（c 0〜30 kPa、φ 25〜50°、ρ 1200〜1900 kg/m³）。膨張率・ヤング率は変えない（AGX の既定値）
- 速度：関門6で、頭打ちの前後の力が速度にほぼ比例することが分かったため、0.3〜0.8 m/s で変える（関門6で調べた範囲）
- 深さ・距離：関門5・6で、頭打ちの特徴（Fx_sat、Fz_sat）が安定して取れることが分かったため、
  削った体積が 2 m³ を超えるようにする（深さ 6 cm × 幅 2.96 m × 14 m ≒ 2.5 m³）。深さの上限 12 cm は関門5で確認した範囲
- 後退しながら排土板を当てる動きは入れない（関門3：AGX ではその動きで土も力もほとんど生じない）
"""
from ..episode import Command, Episode

DATASET_SOIL = {
    "cohesion": (0.0, 30000.0),          # Pa
    "friction_angle_deg": (25.0, 50.0),  # deg
    "density": (1200.0, 1900.0),         # kg/m^3（Maximum Density 2000 を超えないこと）
}
DEPTH_RANGE = (0.06, 0.12)   # m
SPEED_RANGE = (0.3, 0.8)     # m/s


class FlatCut(Episode):
    """平らな地形を、一定の深さ・一定の速度で 14 m 削る"""
    name = "flat_cut"
    description = "平らな地形を、一定の深さ（6〜12 cm）・速度（0.3〜0.8 m/s）で 14 m 削る"
    SOIL_RANGES = DATASET_SOIL
    MAX_DISTANCE = 14.0      # m
    TIMEOUT = 70.0           # s（0.3 m/s で 14 m は約 47 秒）

    def sample_params(self, rng):
        return {
            "depth": float(rng.uniform(*DEPTH_RANGE)),
            "speed": float(rng.uniform(*SPEED_RANGE)),
        }

    def operation(self, obs):
        return Command(speed=self.params["speed"], depth=self.params["depth"])


class FlatPiecewise(Episode):
    """平らな地形を 14 m 削る。3つの区間ごとに深さと速度を変える（推定器が変化する条件を学べるように）"""
    name = "flat_piecewise"
    description = "平らな地形を 14 m 削る。約 4.7 m ごとに深さ（6〜12 cm）と速度（0.3〜0.8 m/s）を変える"
    SOIL_RANGES = DATASET_SOIL
    MAX_DISTANCE = 14.0
    TIMEOUT = 70.0
    N_SEGMENTS = 3

    def sample_params(self, rng):
        return {
            "depths": [float(d) for d in rng.uniform(*DEPTH_RANGE, self.N_SEGMENTS)],
            "speeds": [float(v) for v in rng.uniform(*SPEED_RANGE, self.N_SEGMENTS)],
        }

    def operation(self, obs):
        seg_len = self.MAX_DISTANCE / self.N_SEGMENTS
        i = min(int(max(obs.distance, 0.0) / seg_len), self.N_SEGMENTS - 1)
        return Command(speed=self.params["speeds"][i], depth=self.params["depths"][i])