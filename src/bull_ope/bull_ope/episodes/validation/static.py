from ..episode import Command
from .base import ValidationEpisode


class ValidationStatic(ValidationEpisode):
    """排土板を空中に上げたまま止まっている。

    確かめること：力がほぼ 0 か、ノイズの大きさ、記録の周期、前方の地面の高さが平らか
    """
    name = "val_static"
    description = "【検証】排土板を上げたまま静止する（10 秒）"
    DURATION = 10.0          # 静止する時間 [s]
    PARAM_NAMES = ("DURATION",)

    def operation(self, obs):
        return Command(speed=0.0, depth=None)   # depth=None で排土板を上げる

    def is_done(self, obs):
        return obs.t >= self.DURATION