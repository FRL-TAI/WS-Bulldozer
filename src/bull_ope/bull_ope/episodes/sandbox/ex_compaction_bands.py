"""
【実験B1：締固めと切削抵抗】締固めの程度を設定した帯を、一定の深さ・速さで横切って削るエピソード

地山（締固めの程度 1.0）の帯と、締固めの程度を変えた帯を交互に並べ、一定の深さで削る。
帯の並びはシードで4通りに切り替える（同じ条件の帯が毎回同じ位置に来ないようにするため）。

  seed % 4 = 0 : 地山 → 1.16 → 地山 → 1.08 → 地山
  seed % 4 = 1 : 地山 → 1.08 → 地山 → 1.16 → 地山
  seed % 4 = 2 : 地山 → 1.16 → 地山 → 緩み → 地山
  seed % 4 = 3 : 地山 → 緩み → 地山 → 1.16 → 地山

  1.16：履帯で十分に踏み固めた地表の値（実験A）、1.08：その中間、緩み：1 / 膨張率

帯の範囲（エピソード座標：開始時の刃先の中点が原点、x が前方）と締固めの程度は terrain_ops() で決まる。
解析（check_cut_bands.py）は、記録のエピソード名とシードからこのクラスを作り直して帯の範囲を得る。

名前が "ex_compaction" で始まるので、Unity 側の CompactionProbe も地形の高さと締固めの程度を記録する。
Unity 側で AGX_GRID_CONTROL が有効である必要がある。
"""
from ..episode import Command, Episode, TerrainOp

# 使用する土質（OperaSim の TerrainMaterial（dirt_1）の設定値。ex_shuttle・ex_compaction_passes と同じ）
SOIL = {"cohesion": 2100.0, "friction_angle_deg": 39.98, "density": 1474.0}
DEFAULT_SWELL = 1.28        # 膨張率を指定しないときに使う値（dirt_1 の設定値）

BANK = 1.0
LOOSE = "loose"             # 1 / 膨張率 に置き換える
VARIANTS = [
    [BANK, 1.16, BANK, 1.08, BANK],
    [BANK, 1.08, BANK, 1.16, BANK],
    [BANK, 1.16, BANK, LOOSE, BANK],
    [BANK, LOOSE, BANK, 1.16, BANK],
]


class CompactionBands(Episode):
    name = "ex_compaction_bands"
    description = "【実験B1】締固めの程度を変えた帯（地山・踏み固め・緩み）を一定の深さで横切って削る"
    SOIL_RANGES = {k: (v, v) for k, v in SOIL.items()}   # 下限 = 上限 にして土質を固定
    REQUIRES_GRID_CONTROL = True
    RECORD_COMPACTION = True

    BAND_START = 1.0        # 最初の帯の始まり [m]（刃先の開始位置から）
    BAND_LENGTH = 2.0       # 帯の長さ [m]
    HALF_WIDTH = 2.0        # 帯の左右の幅の半分 [m]（排土板の幅 2.96 m より広く）
    SET_DEPTH = 0.8         # 締固めの程度を設定する深さ [m]（実験A で締固めが届いた深さ）
    DEPTH = 0.08            # 切削深さ [m]
    SPEED = 0.5             # 前進の速さ [m/s]
    MAX_DISTANCE = 13.5     # 走行距離 [m]。刃先は機体の約 2.8 m 前、履帯の後端は約 1.1 m 後ろにあるので、
                            # 最後の締固めの帯（刃先の座標で 9 m まで）の上を履帯が通り切るには約 13 m 必要

    def sample_params(self, rng):
        return {"variant": int(self.seed % len(VARIANTS)), "depth": self.DEPTH, "speed": self.SPEED,
                "band_start": self.BAND_START, "band_length": self.BAND_LENGTH, "set_depth": self.SET_DEPTH}

    def levels(self):
        """帯ごとの締固めの程度（緩みは 1 / 膨張率 に置き換えた値）"""
        swell = self.soil.swell_factor or DEFAULT_SWELL
        return [1.0 / swell if v == LOOSE else float(v) for v in VARIANTS[self.params["variant"]]]

    def terrain_ops(self):
        ops = []
        for i, value in enumerate(self.levels()):
            x0 = self.BAND_START + i * self.BAND_LENGTH
            if value == BANK:
                continue            # 地山の帯は加工しない（最初から締固めの程度 1.0）
            ops.append(TerrainOp("compaction_rect", x0, x0 + self.BAND_LENGTH,
                                 -self.HALF_WIDTH, self.HALF_WIDTH, value=value, depth=self.SET_DEPTH))
        return ops

    def bands(self):
        """解析用：[(開始, 終わり, 締固めの程度)]（地山の帯も含む）"""
        return [(self.BAND_START + i * self.BAND_LENGTH, self.BAND_START + (i + 1) * self.BAND_LENGTH, v)
                for i, v in enumerate(self.levels())]

    def operation(self, obs):
        return Command(speed=self.SPEED, depth=self.DEPTH)