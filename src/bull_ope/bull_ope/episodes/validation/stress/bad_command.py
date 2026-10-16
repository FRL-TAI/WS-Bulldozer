import math

from ...episode import Command
from ..base import ValidationEpisode


class StressNanDepth(ValidationEpisode):
    """走行の途中から、目標深さに NaN を返す（反力が取れないときに計算が NaN になる状況を模擬）。

    確かめること：NaN の指令が OperaSim に送られてしまわないか。送られた場合、排土板がどう動くか
    """
    name = "stress_nan_depth"
    description = "【試験】走行の 2 秒後から目標深さに NaN を返す"

    def operation(self, obs):
        return Command(speed=0.5, depth=math.nan if obs.t > 2.0 else 0.05)

    def is_done(self, obs):
        return obs.t >= 6.0


class StressNoneCommand(ValidationEpisode):
    """走行の途中から、Command ではなく None を返す（条件分岐の書き忘れを模擬）。

    確かめること：エラーとして記録され、機体が止まるか
    """
    name = "stress_none_command"
    description = "【試験】走行の 2 秒後から operation() が None を返す"

    def operation(self, obs):
        if obs.t > 2.0:
            return None
        return Command(speed=0.5, depth=0.05)
