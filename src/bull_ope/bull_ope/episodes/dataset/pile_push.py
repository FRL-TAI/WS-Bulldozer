"""
学習データ用のエピソード：前方に緩い土の山を積み、それを押しながら進む（要 AGX_GRID_CONTROL）。

置き場所: bull_ope/episodes/dataset/pile_push.py

- 土の山は、地形の加工 loose_layer_rect（範囲内に「緩い土（締固め 1/膨張率）」の層を積む）で作る。
  sandbox の ex_terrain_loose_pile と同じ仕組み
- 山は、開始時の刃先から 1.5 m 以上前に置く。切削深さの基準 ground_h0 は刃先の 0.5 m 前で測るので、
  山がその測定に入らないようにするため
- 山の幅は 3.0 m（排土板の幅 2.96 m とほぼ同じ）
- 深さは 0〜6 cm（元の地面の高さ〜少し削る）。山を押すことが主で、地山は浅く削る
- 山の大きさ・位置は param_pile_* として episodes.jsonl に記録される。山の体積（緩い状態）は
  pile_length × 3.0 × pile_height で計算できる
"""
from ..episode import Command, Episode, TerrainOp
from .flat_cut import DATASET_SOIL, SPEED_RANGE

PILE_WIDTH = 3.0     # m


class PilePush(Episode):
    """前方に緩い土の山を積み、それを押しながら 14 m 進む"""
    name = "pile_push"
    description = "前方 1.5〜4 m に緩い土の山（長さ 1〜3 m、高さ 0.2〜0.5 m）を積み、深さ 0〜6 cm で押しながら 14 m 進む（要 AGX_GRID_CONTROL）"
    SOIL_RANGES = DATASET_SOIL
    REQUIRES_GRID_CONTROL = True
    MAX_DISTANCE = 14.0
    TIMEOUT = 70.0

    def sample_params(self, rng):
        return {
            "pile_start": float(rng.uniform(2.0, 4.0)),    # 開始時の刃先からの距離 [m]（1.5 → 2.0。走り出してから当たるように）
            "pile_length": float(rng.uniform(1.0, 2.5)),   # 前後の長さ [m]（3.0 → 2.5）
            "pile_height": float(rng.uniform(0.2, 0.4)),   # 高さ [m]（0.5 → 0.4）
            "depth": float(rng.uniform(0.0, 0.04)),        # 切削深さ [m]（0.06 → 0.04）
            "speed": float(rng.uniform(*SPEED_RANGE)),     # m/s
        }

    def terrain_ops(self):
        p = self.params
        return [TerrainOp("loose_layer_rect", p["pile_start"], p["pile_start"] + p["pile_length"],
                          -PILE_WIDTH / 2, PILE_WIDTH / 2, value=p["pile_height"])]

    def operation(self, obs):
        return Command(speed=self.params["speed"], depth=self.params["depth"])