"""
検証用エピソードの共通設定
"""

from ..episode import Episode

# 検証では土質を固定する（OperaSim の TerrainMaterial（dirt_1）の設定値）
VALIDATION_SOIL = {"cohesion": 2100.0, "friction_angle_deg": 39.98, "density": 1474.0}


class ValidationEpisode(Episode):
    """検証用エピソードの基底クラス。name を設定しないので、一覧には出ない。"""
    SOIL_RANGES = {k: (v, v) for k, v in VALIDATION_SOIL.items()}   # 下限 = 上限 で固定

    def sample_params(self, rng):
        # 乱数は使わず、クラスに書いた操作の条件をそのまま記録用に返す
        return {k.lower(): getattr(self, k) for k in self.PARAM_NAMES}

    PARAM_NAMES = ()   # 記録したいクラス属性の名前（サブクラスで指定）