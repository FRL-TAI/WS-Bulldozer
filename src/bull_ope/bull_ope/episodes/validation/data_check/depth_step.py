from ...episode import Command
from ..base import ValidationEpisode


class ValidationDepthStep(ValidationEpisode):
    """深さを段階的に深くしながら削る（3 cm → 6 cm → 9 cm、各 3 m）。

    確かめること：深さと力の関係（深いほど力が大きいか、d と d² で近似できるか）、
    深さが変わってから刃先・力が追いつくまでの時間のずれ
    """
    name = "val_depth_step"
    description = "【検証】深さを 3→6→9 cm と 3 m ごとに変えて削る"
    DEPTHS = (0.03, 0.06, 0.09)   # 各区間の深さ [m]
    SEGMENT = 3.0                 # 1区間の長さ [m]
    SPEED = 0.5                   # m/s
    MAX_DISTANCE = 9.0            # 区間の長さ × 区間の数 [m]
    PARAM_NAMES = ("DEPTHS", "SEGMENT", "SPEED", "MAX_DISTANCE")

    def operation(self, obs):
        i = min(int(obs.distance // self.SEGMENT), len(self.DEPTHS) - 1)
        return Command(speed=self.SPEED, depth=self.DEPTHS[i])