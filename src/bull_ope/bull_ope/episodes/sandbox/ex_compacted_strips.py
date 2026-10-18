from ..episode import Command, Episode, TerrainOp

MAXIMUM_DENSITY = 2000.0   # TerrainMaterial の Maximum Density [kg/m^3]
DEFAULT_SWELL = 1.28       # 膨張率を指定しないときに使う値（dirt_1 の設定値）


class CompactedStrips(Episode):
    """走行方向に、地山・踏み固めた土・緩んだ土の帯を交互に並べた地形を一定深さで削る。

    作業中に変化する土の状態（締固めの程度）を含むデータを作るためのエピソード。
    Unity 側で AGX_GRID_CONTROL が有効になっている必要がある。
    """
    name = "ex_compacted_strips"
    description = "【地形】締固めの程度が異なる帯（地山・踏み固め・緩み）を横切って一定深さで削る"
    REQUIRES_GRID_CONTROL = True

    def sample_params(self, rng):
        max_compaction = 0.98 * MAXIMUM_DENSITY / self.soil.density
        return {
            "depth": float(rng.uniform(0.05, 0.10)),
            "speed": float(rng.uniform(0.3, 1.0)),
            "strip_length": float(rng.uniform(1.0, 2.5)),
            "compaction_high": float(min(rng.uniform(1.05, 1.25), max_compaction)),
            "set_depth": 0.5,    # 締固めを設定する深さ [m]（切削深さより十分深く）
            "half_width": 2.0,   # 帯の左右の幅の半分 [m]（排土板の幅より広く）
        }

    def terrain_ops(self):
        p = self.params
        swell = self.soil.swell_factor or DEFAULT_SWELL
        levels = [1.0, p["compaction_high"], 1.0 / swell]   # 地山 → 踏み固め → 緩み の順に繰り返す
        ops, x, i = [], 1.0, 0
        while x < self.MAX_DISTANCE + 1.0:
            ops.append(TerrainOp("compaction_rect", x, x + p["strip_length"],
                                 -p["half_width"], p["half_width"],
                                 value=levels[i % 3], depth=p["set_depth"]))
            x += p["strip_length"]
            i += 1
        return ops

    def operation(self, obs):
        return Command(speed=self.params["speed"], depth=self.params["depth"])
