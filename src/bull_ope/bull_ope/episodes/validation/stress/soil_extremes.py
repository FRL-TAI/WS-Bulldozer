from ...episode import Command, Episode


class StressSoilExtremes(Episode):
    """土質を範囲の両端（とても柔らかい／とても硬い）を含む広い範囲で決める。

    collect_data で続けて実行すると、前のエピソードの土質が次に残っていないか
    （読み込み直しで材料が初期値に戻り、setup で正しく設定されるか）を確かめられる
    """
    name = "stress_soil_extremes"
    description = "【試験】土質を極端な範囲（c 0〜40 kPa、φ 15〜50°、ρ 1100〜1980）で決めて削る"
    SOIL_RANGES = {"cohesion": (0.0, 40000.0), "friction_angle_deg": (15.0, 50.0),
                   "density": (1100.0, 1980.0), "swell_factor": (1.0, 1.6),
                   "youngs_modulus": (1.0e6, 2.0e7)}

    def operation(self, obs):
        return Command(speed=0.5, depth=0.06)
