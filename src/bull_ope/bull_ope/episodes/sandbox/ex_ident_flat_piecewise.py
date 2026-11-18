"""
【フェーズ1：同定可能性】基準の土質から1つのパラメータだけをずらして、14 m を3区間に分け、深さを 12 → 6 → 9 cm と変えて削るエピソード

速度は 0.5 m/s で固定。区間の長さは約 4.67 m（14 m ÷ 3）。土質は「下限 = 上限」で固定し、点は ex_ident_flat_cut と同じ POINTS を使う。
深い区間で土の山を作ってから浅くし、「大きな山・浅い切削」の区間を作る（切り崩しの項 c と土の山の項 ρ の効き方をずらす）。
決定：notes の decisions/2026-11-17_flat_piecewiseとpile_pushの同定可能性用エピソード.md
エピソード名は ex_ident_flat_piecewise_<点の名前>。
"""
from ..episode import Command, Episode
from .ex_ident_flat_cut import BASE_SOIL, POINTS


class _IdentFlatPiecewise(Episode):
    """共通部分（name がないので一覧には出ない）"""
    RECORD_COMPACTION = True  # T31：締固めの記録（*_compaction.csv）を取る（decisions/2026-11-18_同定用のエピソードで締固めの記録を取る.md）
    DEPTHS = (0.12, 0.06, 0.09)   # 区間ごとの切削深さ [m]
    SPEED = 0.5                   # 前進速度 [m/s]
    MAX_DISTANCE = 14.0           # 走行距離 [m]
    TIMEOUT = 70.0                # 走行時間の上限 [s]
    POINT = "base"

    def sample_params(self, rng):
        return {"depths": list(self.DEPTHS), "speed": self.SPEED, "max_distance": self.MAX_DISTANCE, "point": self.POINT}

    def operation(self, obs):
        seg_len = self.MAX_DISTANCE / len(self.DEPTHS)
        i = min(int(max(obs.distance, 0.0) / seg_len), len(self.DEPTHS) - 1)
        return Command(speed=self.SPEED, depth=self.DEPTHS[i])


def _make(key, change):
    soil = dict(BASE_SOIL)
    soil.update(change)
    desc = "、".join(f"{k}={v:g}" for k, v in change.items()) or "基準（dirt_1）"
    attrs = {
        "__module__": __name__,
        "__doc__": f"同定可能性の flat_piecewise：{desc}",
        "name": f"ex_ident_flat_piecewise_{key}",
        "description": f"【同定可能性】14 m を深さ 12→6→9 cm で削る（{desc}）",
        "SOIL_RANGES": {k: (v, v) for k, v in soil.items()},   # 下限 = 上限 で固定
        "POINT": key,
    }
    return type(f"IdentFlatPiecewise_{key}", (_IdentFlatPiecewise,), attrs)


for _key, _change in POINTS.items():
    _cls = _make(_key, _change)
    globals()[_cls.__name__] = _cls


# ---- T31：膨張率の範囲の両端（ex_swell_flat_cut_s110・s140、ex_swell_pile_push_s110・s140 と同じ形）。
# 締固めの記録で、履帯が踏む時点の K3 の s による動きを確かめる（decisions/2026-11-18_同定用のエピソードで締固めの記録を取る.md）
class SwellFlatPiecewise110(_IdentFlatPiecewise):
    name = "ex_swell_flat_piecewise_s110"
    description = "【T31】膨張率 1.10（ほかは dirt_1）で、14 m を深さ 12→6→9 cm で削る"
    SOIL_RANGES = {k: (v, v) for k, v in {**BASE_SOIL, "swell_factor": 1.10}.items()}
    POINT = "swell_110"


class SwellFlatPiecewise140(_IdentFlatPiecewise):
    name = "ex_swell_flat_piecewise_s140"
    description = "【T31】膨張率 1.40（ほかは dirt_1）で、14 m を深さ 12→6→9 cm で削る"
    SOIL_RANGES = {k: (v, v) for k, v in {**BASE_SOIL, "swell_factor": 1.40}.items()}
    POINT = "swell_140"
