"""【動き：速度】走行距離に応じて速度を変える（加速 → 一定 → 減速）。"""
from ..episode import Command, Episode


class ExSpeedProfile(Episode):
    name = "ex_speed_profile"
    description = "【動き】0.2→1.2 m/s に加速し、一定で走った後、0.2 m/s まで減速しながら削る"
    V_MIN, V_MAX = 0.2, 1.2      # m/s（OperaSim の上限は約 2.36 m/s = 8.5 km/h）
    RAMP = 3.0                   # 加速・減速にかける距離 [m]

    def operation(self, obs):
        s, L = obs.distance, self.MAX_DISTANCE
        if s < self.RAMP:                          # 加速
            v = self.V_MIN + (self.V_MAX - self.V_MIN) * s / self.RAMP
        elif s > L - self.RAMP:                    # 減速
            v = self.V_MIN + (self.V_MAX - self.V_MIN) * (L - s) / self.RAMP
        else:                                      # 一定
            v = self.V_MAX
        return Command(speed=v, depth=0.05)
