"""
【フェーズ1：同定可能性】基準の土質から1つのパラメータだけをずらして、平らな地面を一定の深さで削るエピソード

深さ 9 cm・0.5 m/s・10 m（関門6 の val_sens_base と同じ操作）。土質は「下限 = 上限」で固定する。
基準は dirt_1（c 2100 Pa、φ 39.98°、ρ 1474 kg/m³、膨張率 1.28）。
ヤコビ行列を差分で求めるために、パラメータごとの点（基準からのずれ）を POINTS に並べる。
エピソード名は ex_ident_flat_cut_<点の名前>（例：ex_ident_flat_cut_base、ex_ident_flat_cut_phi_m5）。

点を足すときは POINTS に1行足す（例：c の片側差分 "c_p1500": {"cohesion": 3600.0}）。
刻みの決め方は notes の decisions/2026-11-17_差分の刻みと基準の点.md、docs/phase1.md §5。
"""
from ..episode import Command, Episode

# 基準の土質（OperaSim の TerrainMaterial（dirt_1）の設定値。膨張率はシーンの asset の値）
BASE_SOIL = {"cohesion": 2100.0, "friction_angle_deg": 39.98, "density": 1474.0, "swell_factor": 1.28}

# 点の名前 → 基準から変えるもの（SoilParams のフィールド名 → 値）
POINTS = {
    "base": {},
    "phi_m5": {"friction_angle_deg": 34.98},      # φ − 5°（範囲の幅 25° の −20%）
    "phi_p5": {"friction_angle_deg": 44.98},      # φ + 5°
    "phi_p2p5": {"friction_angle_deg": 42.48},    # φ + 2.5°（線形性の確認）
    # 本番の設計（decisions/2026-11-17_φの刻みを±10°にする.md。phi_p5 は ±10° の線形性の点として使う）
    "phi_m10": {"friction_angle_deg": 29.98},     # φ − 10°（範囲の幅 25° の −40%）
    "phi_p10": {"friction_angle_deg": 49.98},     # φ + 10°
    "c_m1p5": {"cohesion": 600.0},                # c − 1.5 kPa（範囲の幅 30 kPa の −5%。中心差分。decisions/2026-11-17_cは中心差分±1.5kPaにする.md）
    "c_p1p5": {"cohesion": 3600.0},               # c + 1.5 kPa（中心差分）
    "c_p3": {"cohesion": 5100.0},                 # c + 3.0 kPa（片側の傾きの参考。T7 の2次の片側差分で使った点）
    "rho_m70": {"density": 1404.0},               # ρ − 70（範囲の幅 700 の −10%）
    "rho_p70": {"density": 1544.0},               # ρ + 70
    "rho_p35": {"density": 1509.0},               # ρ + 35（線形性の確認）
    # 膨張率（decisions/2026-11-17_膨張率の範囲は1.10〜1.40.md。範囲の幅 0.30、中心差分 ±0.03 = 幅の ±10%）
    "s_m0p03": {"swell_factor": 1.25},            # s − 0.03
    "s_p0p03": {"swell_factor": 1.31},            # s + 0.03
    "s_p0p015": {"swell_factor": 1.295},          # s + 0.015（T17 の線形性の確認。±0.06 にした後は判定に使わない）
    # 本番の設計（decisions/2026-11-17_膨張率の刻みを±0.06にする.md。±0.03 の点は線形性の確認に使う）
    "s_m0p06": {"swell_factor": 1.22},            # s − 0.06（範囲の幅 0.30 の −20%）
    "s_p0p06": {"swell_factor": 1.34},            # s + 0.06
    # s = 1.10 の flat_cut は、T12 の ex_swell_flat_cut_s110（ex_maxdensity.py。操作は同じ）を使う
}


class _IdentFlatCut(Episode):
    """共通部分（name がないので一覧には出ない）"""
    DEPTH = 0.09          # 切削深さ [m]
    SPEED = 0.5           # 前進速度 [m/s]
    MAX_DISTANCE = 10.0   # 走行距離 [m]
    TIMEOUT = 90.0        # 走行時間の上限 [s]
    POINT = "base"

    def sample_params(self, rng):
        return {"depth": self.DEPTH, "speed": self.SPEED, "max_distance": self.MAX_DISTANCE, "point": self.POINT}

    def operation(self, obs):
        return Command(speed=self.SPEED, depth=self.DEPTH)


def _make(key, change):
    soil = dict(BASE_SOIL)
    soil.update(change)
    desc = "、".join(f"{k}={v:g}" for k, v in change.items()) or "基準（dirt_1）"
    attrs = {
        "__module__": __name__,
        "__doc__": f"同定可能性の flat_cut：{desc}",
        "name": f"ex_ident_flat_cut_{key}",
        "description": f"【同定可能性】深さ 9 cm で 10 m 削る（{desc}）",
        "SOIL_RANGES": {k: (v, v) for k, v in soil.items()},   # 下限 = 上限 で固定
        "POINT": key,
    }
    return type(f"IdentFlatCut_{key}", (_IdentFlatCut,), attrs)


for _key, _change in POINTS.items():
    _cls = _make(_key, _change)
    globals()[_cls.__name__] = _cls
