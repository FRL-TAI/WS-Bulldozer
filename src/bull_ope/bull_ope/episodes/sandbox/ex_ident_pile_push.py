"""
【フェーズ1：同定可能性】基準の土質から1つのパラメータだけをずらして、前方の決まった土の山を浅く削りながら押すエピソード（要 AGX_GRID_CONTROL）

山：開始時の刃先から 3 m の位置、長さ 2 m、高さ 0.3 m、幅 3.0 m（dataset_pile_push の範囲の中ほど）。深さ 2 cm、0.5 m/s、14 m。
山は loose_layer_rect（締固めの程度 1/膨張率 の緩い土の層）で作る。土質は「下限 = 上限」で固定し、点は ex_ident_flat_cut と同じ POINTS を使う。
深さのずれの 95% が 10 cm を超える記録は解析で除き、除いた分を回し足す（関門7 の基準）。
決定：notes の decisions/2026-11-17_flat_piecewiseとpile_pushの同定可能性用エピソード.md
エピソード名は ex_ident_pile_push_<点の名前>。
"""
from ..episode import Command, Episode, TerrainOp
from .ex_ident_flat_cut import BASE_SOIL, POINTS

PILE_START, PILE_LENGTH, PILE_HEIGHT, PILE_WIDTH = 3.0, 2.0, 0.3, 3.0   # m


class _IdentPilePush(Episode):
    """共通部分（name がないので一覧には出ない）"""
    REQUIRES_GRID_CONTROL = True
    DEPTH = 0.02          # 切削深さ [m]
    SPEED = 0.5           # 前進速度 [m/s]
    MAX_DISTANCE = 14.0   # 走行距離 [m]
    TIMEOUT = 70.0        # 走行時間の上限 [s]
    POINT = "base"

    def sample_params(self, rng):
        return {"pile_start": PILE_START, "pile_length": PILE_LENGTH, "pile_height": PILE_HEIGHT,
                "depth": self.DEPTH, "speed": self.SPEED, "max_distance": self.MAX_DISTANCE, "point": self.POINT}

    def terrain_ops(self):
        return [TerrainOp("loose_layer_rect", PILE_START, PILE_START + PILE_LENGTH,
                          -PILE_WIDTH / 2, PILE_WIDTH / 2, value=PILE_HEIGHT)]

    def operation(self, obs):
        return Command(speed=self.SPEED, depth=self.DEPTH)


def _make(key, change):
    soil = dict(BASE_SOIL)
    soil.update(change)
    desc = "、".join(f"{k}={v:g}" for k, v in change.items()) or "基準（dirt_1）"
    attrs = {
        "__module__": __name__,
        "__doc__": f"同定可能性の pile_push：{desc}",
        "name": f"ex_ident_pile_push_{key}",
        "description": f"【同定可能性】3 m 先の山（2 m × 0.3 m）を深さ 2 cm で押す（{desc}）",
        "SOIL_RANGES": {k: (v, v) for k, v in soil.items()},   # 下限 = 上限 で固定
        "POINT": key,
    }
    return type(f"IdentPilePush_{key}", (_IdentPilePush,), attrs)


for _key, _change in POINTS.items():
    _cls = _make(_key, _change)
    globals()[_cls.__name__] = _cls
