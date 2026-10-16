from ...episode import Command
from ..base import ValidationEpisode


class StressErrorMidrun(ValidationEpisode):
    """走行の途中（3 秒後）で、エピソードのコードがエラーを起こす。

    確かめること：機体が止まり、CSV が閉じられ、エラーとして記録されるか。
    次のエピソードが（走行中の状態を引きずらず）正常に始まるか
    """
    name = "stress_error_midrun"
    description = "【試験】走行中の 3 秒後にエピソードのコードで例外を起こす"

    def operation(self, obs):
        if obs.t > 3.0:
            raise ValueError("試験用のエラー（走行中に発生）")
        return Command(speed=0.8, depth=0.05)
