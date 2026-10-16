from ...episode import Command
from ..base import StressEpisode


class StressHeavyPush(StressEpisode):
    """硬く重い土（粘着力・密度を大きく）を深く削る。前に進めなくなる・粒子が大量に出る状況。

    確かめること：進めなくても TIMEOUT で終わるか、粒子が多くても次の読み込み直しが正常か、
    反力や姿勢に極端な値・NaN が出ないか
    """
    name = "stress_heavy_push"
    description = "【試験】粘着力 30 kPa・密度 1950 kg/m³ の土を 20 cm の深さで押す"
    SOIL_RANGES = {"cohesion": (30000.0, 30000.0), "friction_angle_deg": (45.0, 45.0),
                   "density": (1950.0, 1950.0)}
    TIMEOUT = 40.0

    def operation(self, obs):
        return Command(speed=0.8, depth=0.20)
