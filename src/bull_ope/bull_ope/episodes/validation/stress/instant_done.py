from ...episode import Command
from ..base import ValidationEpisode


class StressInstantDone(ValidationEpisode):
    """走行の最初から終了条件を満たす（走行の区間が 0 秒）。

    確かめること：走行の行が 0 行でもエラーにならず、記録とサマリーが正しく終わるか
    """
    name = "stress_instant_done"
    description = "【試験】走行を始めた瞬間に終了する"

    def operation(self, obs):
        return Command(speed=0.5, depth=0.05)

    def is_done(self, obs):
        return True
