"""
【フェーズ1：貫入抵抗の段差の確認】削り始める位置だけを ±2 m ずらして、flat_cut の基準と同じ操作で削るエピソード

貫入抵抗の段差（刃先が開始から約 6.9 m、edge_x ≈ −0.26 m を通るときに約2倍になる）が、
ワールドの位置で決まるのか、削り始めからの距離で決まるのかを確かめる（notes の docs/phase1.md §4.3）。

機体の開始位置はシーンの読み込み直しで決まり、ROS 側からは変えられない。そこで、排土板を少し上げたまま
前進（+2 m）または後退（−2 m）してから止まり、排土板を 9 cm まで下げて、0.5 m/s で 10 m 削る。
止まってから下げて走り出す手順は、ふだんのエピソード（runner の lowering → running）と同じにしている。

  - ex_step_shift_p2：+2 m 前進してから削る（削り始めの edge_x ≈ −5.2 m）
  - ex_step_shift_m2：−2 m 後退してから削る（削り始めの edge_x ≈ −9.2 m）

段差が位置で決まるなら、削り始めからの距離で p2 は約 4.9 m、m2 は約 8.9 m に段差が動く。
距離で決まるなら、どちらも約 6.9 m のまま。m2 では、機体の走った道のり（後退 2 m を含む）で決まる場合とも区別できる。

移動の判定にはワールドの刃先の位置 blade["edge_x"]（ROS の座標で前方が正）を使う。
obs.distance は開始位置からの直線距離なので、後退してから前進する m2 では単調にならず、使えない。
土質・深さ・速さは ex_ident_flat_cut の基準（dirt_1、9 cm、0.5 m/s、10 m）と同じ。
"""
from ..episode import Command, Episode
from .ex_ident_flat_cut import BASE_SOIL


class _StepShift(Episode):
    """共通部分（name がないので一覧には出ない）"""
    SHIFT = 0.0             # 削り始める位置のずれ [m]（前方が正）
    DEPTH = 0.09            # 切削深さ [m]
    SPEED = 0.5             # 削るときの前進速度 [m/s]
    MOVE_SPEED = 0.5        # 位置を移すときの速さ [m/s]
    CUT_LENGTH = 10.0       # 削る距離 [m]
    LIFT = 0.05             # 位置を移すときの排土板の高さ（元の地面から）[m]
    STOP_SPEED = 0.02       # 止まったとみなす速さ [m/s]
    DEPTH_TOL = 0.005       # 下げ終わったとみなす深さの誤差 [m]
    HOLD = 1.0              # 止まって下げ終わってから走り出すまでの待ち時間 [s]
    TIMEOUT = 90.0
    SOIL_RANGES = {k: (v, v) for k, v in BASE_SOIL.items()}   # 下限 = 上限 で固定

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.state = "move"     # move（移す）→ lower（止まって下げる）→ cut（削る）
        self.x_start = None     # 開始時の刃先の位置 edge_x [m]
        self.x_cut = None       # 削り始めの刃先の位置 edge_x [m]
        self.t_ready = None     # 止まって下げ終わった時刻 [s]

    def sample_params(self, rng):
        return {"shift": self.SHIFT, "depth": self.DEPTH, "speed": self.SPEED,
                "cut_length": self.CUT_LENGTH, "lift": self.LIFT}

    def operation(self, obs):
        x = obs.blade["edge_x"]
        if self.x_start is None:
            self.x_start = x
        if self.state == "move":
            reached = (x - self.x_start >= self.SHIFT) if self.SHIFT >= 0 else (x - self.x_start <= self.SHIFT)
            if not reached:
                sign = 1.0 if self.SHIFT >= 0 else -1.0
                return Command(speed=sign * self.MOVE_SPEED, depth=-self.LIFT)
            self.state = "lower"
        if self.state == "lower":
            ready = abs(obs.speed) < self.STOP_SPEED and abs(obs.depth - self.DEPTH) < self.DEPTH_TOL
            if not ready:
                self.t_ready = None
                return Command(speed=0.0, depth=self.DEPTH)
            if self.t_ready is None:
                self.t_ready = obs.t
            if obs.t - self.t_ready < self.HOLD:
                return Command(speed=0.0, depth=self.DEPTH)
            self.state = "cut"
            self.x_cut = x
        return Command(speed=self.SPEED, depth=self.DEPTH)

    def is_done(self, obs):
        if obs.t >= self.TIMEOUT:
            return True
        return self.state == "cut" and obs.blade["edge_x"] - self.x_cut >= self.CUT_LENGTH


class StepShiftP2(_StepShift):
    name = "ex_step_shift_p2"
    description = "【段差の確認】+2 m 前進してから、深さ 9 cm で 10 m 削る（dirt_1）"
    SHIFT = 2.0


class StepShiftM2(_StepShift):
    name = "ex_step_shift_m2"
    description = "【段差の確認】−2 m 後退してから、深さ 9 cm で 10 m 削る（dirt_1）"
    SHIFT = -2.0
