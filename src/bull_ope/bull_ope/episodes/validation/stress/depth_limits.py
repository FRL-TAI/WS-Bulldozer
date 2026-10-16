from ...episode import Command
from ..base import StressEpisode


class StressDepthLimits(StressEpisode):
    """OperaSim の排土板の高さの制限（地面から −0.38〜+0.8 m）を超える目標を与える。

    2 m ごとに、深すぎる（0.5 m）→ 普通（0.05 m）→ 高すぎる（−1.0 m = 地面から 1 m 上）→ 普通 と変える。
    確かめること：下げる区間の時間切れのあと先へ進むか、制限で止まった後に普通の目標に戻れるか
    """
    name = "stress_depth_limits"
    description = "【試験】排土板の高さの制限を超える目標深さ（0.5 m、−1.0 m）を与える"
    PROFILE = [0.5, 0.05, -1.0, 0.05]
    MAX_DISTANCE = 8.0

    def operation(self, obs):
        i = min(int(obs.distance // 2.0), len(self.PROFILE) - 1)
        return Command(speed=0.4, depth=self.PROFILE[i])
