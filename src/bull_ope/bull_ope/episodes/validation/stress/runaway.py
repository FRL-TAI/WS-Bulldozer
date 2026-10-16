from ...episode import Command
from ..base import ValidationEpisode


class StressRunaway(ValidationEpisode):
    """排土板を上げて、止まらずに 100 m 走ろうとする（フィールドの外へ向かう）。

    確かめること：SAFE_RADIUS を超えたところで止まり、エラーとして記録されるか。
    次のエピソードが開始位置から正常に始まるか
    """
    name = "stress_runaway"
    description = "【試験】フィールドの外へ向かって 100 m 走ろうとする（SAFE_RADIUS で止まるはず）"
    MAX_DISTANCE = 100.0
    TIMEOUT = 200.0

    def operation(self, obs):
        return Command(speed=1.5, depth=None)
