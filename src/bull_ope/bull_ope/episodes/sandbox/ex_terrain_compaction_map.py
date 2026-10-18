"""【地形：締固めの分布】締固めの程度を、前後・左右で異なるパッチ状に設定して削る。

要 AGX_GRID_CONTROL（無効ならスキップされる）。
左半分と右半分で値を変えると、排土板の左右で異なる状態の土を同時に削る状況を作れる。
"""
from ..episode import Command, Episode, TerrainOp

MAXIMUM_DENSITY = 2000.0


class ExTerrainCompactionMap(Episode):
    name = "ex_terrain_compaction_map"
    description = "【地形】前後 2 m × 左右 2 分割のパッチごとに締固めの程度を変えて削る"
    REQUIRES_GRID_CONTROL = True

    def sample_params(self, rng):
        c_max = 0.98 * MAXIMUM_DENSITY / self.soil.density     # 密度が上限を超えない範囲
        # 5 区間 × 左右 の締固めの程度（0.8：緩い 〜 c_max：踏み固め）
        return {"compaction": [[float(rng.uniform(0.8, c_max)) for _ in range(2)] for _ in range(5)]}

    def terrain_ops(self):
        ops = []
        for i, (left, right) in enumerate(self.params["compaction"]):
            x0, x1 = 1.0 + 2.0 * i, 3.0 + 2.0 * i
            ops.append(TerrainOp("compaction_rect", x0, x1, 0.0, 2.0, value=left, depth=0.5))
            ops.append(TerrainOp("compaction_rect", x0, x1, -2.0, 0.0, value=right, depth=0.5))
        return ops

    def operation(self, obs):
        return Command(speed=0.5, depth=0.06)
