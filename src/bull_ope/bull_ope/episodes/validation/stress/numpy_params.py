from ...episode import Command
from ..base import StressEpisode


class StressNumpyParams(StressEpisode):
    """操作のパラメータに NumPy の型（int64、配列）をそのまま入れる。

    確かめること：collect_data が episodes.jsonl に書き込むとき（json.dumps）にエラーで止まらないか
    """
    name = "stress_numpy_params"
    description = "【試験】sample_params が NumPy の整数・配列を返す（記録の JSON 変換の試験）"

    def sample_params(self, rng):
        return {"n_segments": rng.integers(2, 5), "depths": rng.uniform(0.02, 0.06, size=3)}

    def operation(self, obs):
        return Command(speed=0.5, depth=float(self.params["depths"][0]))

    def is_done(self, obs):
        return obs.t >= 4.0
