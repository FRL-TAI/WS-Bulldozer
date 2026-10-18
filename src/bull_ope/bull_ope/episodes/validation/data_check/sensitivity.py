"""
関門6（再現性と識別可能性）の検証用エピソード。

置き場所: bull_ope/episodes/validation/data_check/sensitivity.py

深さ 9 cm・10 m を、土質（c、φ、ρ）と速度を1つずつ変えて削る。基準は dirt_1（c = 2100 Pa、φ = 39.98°、ρ = 1474 kg/m³）、0.5 m/s。
深さ 9 cm なら、10 m で削った体積が約 2.7 m³ になり、関門5で分かった「直線の領域（1 m³ 未満）」と
「頭打ちの領域（2 m³ 以上）」の両方を1回で記録できる。

名前は val_sens_<条件>。条件は CONDITIONS を参照。
val_sens_rho1900_phi33・val_sens_rho1200_phi46 は、密度と摩擦角を、ρ × tanφ が基準と同じになるように
組み合わせたもの（関門5で、前後の力の増え方が ρ g tanφ で決まることが分かったため、ρ と φ を区別できるかを確かめる）。
"""
import math

from ...episode import Command
from ..base import VALIDATION_SOIL, ValidationEpisode

BASE_SPEED = 0.5
_rho_tan = VALIDATION_SOIL["density"] * math.tan(math.radians(VALIDATION_SOIL["friction_angle_deg"]))


def _phi_for(rho):
    """ρ × tanφ が基準と同じになる φ [deg]"""
    return round(math.degrees(math.atan(_rho_tan / rho)), 2)


# 条件名 → 基準から変えるもの（soil のフィールド名、または speed）
CONDITIONS = {
    "base": {},
    "c0": {"cohesion": 0.0},
    "c10k": {"cohesion": 10000.0},
    "c30k": {"cohesion": 30000.0},
    "phi25": {"friction_angle_deg": 25.0},
    "phi50": {"friction_angle_deg": 50.0},
    "rho1200": {"density": 1200.0},
    "rho1900": {"density": 1900.0},
    "rho1900_phi33": {"density": 1900.0, "friction_angle_deg": _phi_for(1900.0)},
    "rho1200_phi46": {"density": 1200.0, "friction_angle_deg": _phi_for(1200.0)},
    "v03": {"speed": 0.3},
    "v08": {"speed": 0.8},
}


class _Sensitivity(ValidationEpisode):
    """関門6の検証用エピソードの共通部分（name がないので一覧には出ない）"""
    DEPTH = 0.09             # m
    SPEED = BASE_SPEED       # m/s
    MAX_DISTANCE = 10.0      # m
    TIMEOUT = 90.0           # 0.3 m/s で 10 m 走るのに約 34 秒かかるため、余裕を持たせる
    PARAM_NAMES = ("DEPTH", "SPEED", "MAX_DISTANCE")

    def operation(self, obs):
        return Command(speed=self.SPEED, depth=self.DEPTH)


def _make(key, change):
    soil = dict(VALIDATION_SOIL)
    soil.update({k: v for k, v in change.items() if k != "speed"})
    speed = change.get("speed", BASE_SPEED)
    desc = "、".join(f"{k}={v:g}" for k, v in change.items()) or "基準（dirt_1、0.5 m/s）"
    attrs = {
        "__module__": __name__,
        "__doc__": f"関門6：{desc}",
        "name": f"val_sens_{key}",
        "description": f"【検証・関門6】深さ 9 cm で 10 m 削る（{desc}）",
        "SOIL_RANGES": {k: (v, v) for k, v in soil.items()},   # 下限 = 上限 で固定
        "SPEED": speed,
    }
    return type(f"ValSens_{key}", (_Sensitivity,), attrs)


for _key, _change in CONDITIONS.items():
    _cls = _make(_key, _change)
    globals()[_cls.__name__] = _cls