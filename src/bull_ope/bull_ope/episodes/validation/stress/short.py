from ...episode import Command
from ..base import ValidationEpisode


class StressShort(ValidationEpisode):
    """2 秒だけ走る。シーンの読み込み直しを短い間隔で何度も繰り返すための試験。

    確かめること：読み込み直しを何十回も続けても、かかる時間・メモリ・シミュレーションの速さが変わらないか
    """
    name = "stress_short"
    description = "【試験】2 秒だけ走る（読み込み直しを繰り返す耐久試験用）"

    def operation(self, obs):
        return Command(speed=0.5, depth=0.03)

    def is_done(self, obs):
        return obs.t >= 2.0
