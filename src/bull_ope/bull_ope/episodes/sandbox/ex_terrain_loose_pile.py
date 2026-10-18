"""【地形：盛土】前方に緩い土の山（厚さ 0.50 m）を積み、排土板を地面の高さにして押し広げる（敷き均し）。

要 AGX_GRID_CONTROL（無効ならスキップされる）。
loose_layer_rect は、範囲内に指定の厚さの「緩い土（締固め 1/膨張率）」の層を積む＝地形の形を変えられる。
"""
from ..episode import Command, Episode, TerrainOp


class ExTerrainLoosePile(Episode):
    name = "ex_terrain_loose_pile"
    description = "【地形】前方 2〜4 m に厚さ 50 cm の緩い土の山を積み、地面の高さで押し広げる"
    REQUIRES_GRID_CONTROL = True

    def terrain_ops(self):
        # x：開始時の刃先から前方 [m]、y：左方 [m]（排土板の幅より広くとる）
        return [TerrainOp("loose_layer_rect", x_start=2.0, x_end=4.0, y_min=-1.5, y_max=1.5, value=0.50)]

    def operation(self, obs):
        return Command(speed=0.5, depth=0.0)     # 元の地面の高さで押す
