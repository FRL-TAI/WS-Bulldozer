"""【動き：排土板】排土板の高さを区間ごとに変える。

depth > 0 : 地面より下（削る）
depth = 0 : 地面と同じ高さ（表面をなでる）
depth < 0 : 地面より上（浮かせる。押してきた土を広げる敷き均しの動き）
None      : 地面から RAISE_HEIGHT（0.3 m）上げる
OperaSim の制限で、刃先は地面から −0.38 m〜+0.8 m の範囲しか動かない。
"""
from ..episode import Command, Episode


class ExBladeProfile(Episode):
    name = "ex_blade_profile"
    description = "【動き】排土板の高さを 削る→なでる→浮かせる→上げる→削る と 2 m ごとに変える"
    PROFILE = [0.08, 0.0, -0.05, None, 0.04]     # 2 m ごとの目標深さ [m]
    SEGMENT = 2.0

    def operation(self, obs):
        i = min(int(obs.distance // self.SEGMENT), len(self.PROFILE) - 1)
        return Command(speed=0.5, depth=self.PROFILE[i])
