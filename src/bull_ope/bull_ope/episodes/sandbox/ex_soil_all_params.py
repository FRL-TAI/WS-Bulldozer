"""【土質】Unity に送れる5つの土質パラメータをすべて固定値で指定する。"""
from ..episode import Command, Episode

SOIL = {
    "cohesion": 8000.0,             # 粘着力 c [Pa]
    "friction_angle_deg": 32.0,     # 内部摩擦角 φ [deg]
    "density": 1600.0,              # 密度 ρ0 [kg/m^3]（Maximum Density 2000 未満）
    "swell_factor": 1.15,           # 膨張率 [-]（掘り起こした土が何倍に膨らむか）
    "youngs_modulus": 4.0e6,        # ヤング率 E0 [Pa]（土の剛性）
}


class ExSoilAllParams(Episode):
    name = "ex_soil_all_params"
    description = "【土質】c・φ・ρ・膨張率・ヤング率の5つを固定値で指定して 10 m 削る"
    SOIL_RANGES = {k: (v, v) for k, v in SOIL.items()}   # 下限 = 上限 で固定

    def operation(self, obs):
        return Command(speed=0.5, depth=0.06)
