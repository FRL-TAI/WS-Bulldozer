from ..episode import Command
from .base import ValidationEpisode


class ValidationAirRun(ValidationEpisode):
    """排土板を空中に上げたまま、一定速度で直進する。

    確かめること：走行中も力が 0 のままか、速度が指令に追従するか、
    速度の積分と位置から求めた距離が一致するか、指令から速度が立ち上がるまでの遅れ
    """
    name = "val_air_run"
    description = "【検証】排土板を上げたまま一定速度で 10 m 直進する"
    SPEED = 0.5              # m/s
    MAX_DISTANCE = 10.0      # m
    PARAM_NAMES = ("SPEED", "MAX_DISTANCE")

    def operation(self, obs):
        return Command(speed=self.SPEED, depth=None)