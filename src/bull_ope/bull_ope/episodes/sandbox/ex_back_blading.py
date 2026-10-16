"""【動き：後退しながら削る】排土板を上げて前進した後、排土板を下ろして後退する（バックブレード）。

後退中は切削方向と逆向きに土を動かすので、反力は主に F_def（変形抵抗）に現れる。
最後は開始位置に戻って終わるので、その後の自動の後退はほぼ行われない。
"""
from ..episode import Command, Episode


class ExBackBlading(Episode):
    name = "ex_back_blading"
    description = "【動き】排土板を上げて 6 m 前進し、排土板を地面に当てて後退で戻る"
    LENGTH = 6.0
    TIMEOUT = 120.0

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.stage = "forward"

    def operation(self, obs):
        if self.stage == "forward" and obs.distance >= self.LENGTH:
            self.stage = "backward"
        if self.stage == "forward":
            return Command(speed=0.6, depth=None)      # 排土板を上げて前進
        return Command(speed=-0.4, depth=0.02)          # 排土板を下ろして後退

    def is_done(self, obs):
        return (self.stage == "backward" and obs.distance <= 0.3) or obs.t >= self.TIMEOUT
