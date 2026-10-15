"""【動き：時間】時間で操作を決める（3 秒進んで 2 秒止まる、を繰り返す）。終了条件も時間。"""
from ..episode import Command, Episode


class ExStopAndGo(Episode):
    name = "ex_stop_and_go"
    description = "【動き】3 秒前進・2 秒停止を 20 秒間くり返しながら削る（時間で制御）"
    GO, STOP, DURATION = 3.0, 2.0, 20.0

    def operation(self, obs):
        moving = (obs.t % (self.GO + self.STOP)) < self.GO
        return Command(speed=0.6 if moving else 0.0, depth=0.05)

    def is_done(self, obs):
        return obs.t >= self.DURATION or obs.distance >= 12.0   # 距離は安全のための上限
