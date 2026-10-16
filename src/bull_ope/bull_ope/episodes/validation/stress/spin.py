from ...episode import Command
from ..base import ValidationEpisode


class StressSpin(ValidationEpisode):
    """排土板を下ろしたまま、その場で旋回し続ける。

    確かめること：機体が転倒・跳ねたりしないか、旋回中の反力（横方向）や姿勢の値が極端にならないか
    """
    name = "stress_spin"
    description = "【試験】排土板を地面に当てたまま、その場で 15 秒旋回する"

    def operation(self, obs):
        return Command(speed=0.0, depth=0.03, yaw_rate=0.5)

    def is_done(self, obs):
        return obs.t >= 15.0
