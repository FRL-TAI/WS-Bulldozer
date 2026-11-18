"""
【実験B2：締固めと切削抵抗（現実的な条件）】履帯で踏み固めた後、同じ経路を一定の深さで削るエピソード

シードの偶奇で2通りに分ける（同じ経路・同じ深さで削り、踏み固めの有無だけを変える）。
  seed が偶数（踏み固めあり）：
    1. 排土板を上げたまま、開始位置から PASS_LENGTH [m] の区間を ROUND_TRIPS 回往復して、履帯で地面を踏み固める
    2. 開始位置に戻ったら、止まったまま排土板を DEPTH まで下げる
    3. 一定の深さ・速さで CUT_LENGTH [m] まで前進して削る
  seed が奇数（対照、踏み固めなし）：
    2 と 3 だけを行う

削る経路の前半は、踏み固めありのときだけ履帯で踏み固めた地面（排土板の幅のうち、左右の履帯の幅の部分）になる。
押土では前方の土塊が育つにつれて切削抵抗が増えるので、同じ記録の中で前半と後半を比べると
土塊の影響と締固めの影響が混ざる。そこで解析（check_cut_bands.py）では、同じ刃先の位置どうしで
「踏み固めあり」と「対照」の記録を比べる。

注意：踏み固めた部分は約 4〜5 cm 沈下しているので、目標の深さ（開始時の地面が基準）で削ると、
     その部分は実際には浅く削ることになる。実機で起きることと同じ条件である。

名前が "ex_compaction" で始まるので、Unity 側の CompactionProbe も地形の高さと締固めの程度を記録する。
"""
from ..episode import Command, Episode
from ..turnaround import ProgressTracker

SOIL = {"cohesion": 2100.0, "friction_angle_deg": 39.98, "density": 1474.0}


class CompactionThenCut(Episode):
    name = "ex_compaction_then_cut"
    description = "【実験B2】履帯で往復して踏み固めた後（奇数のシードは踏み固めなし）、同じ経路を一定の深さで削る"
    SOIL_RANGES = {k: (v, v) for k, v in SOIL.items()}
    RECORD_COMPACTION = True

    PASS_LENGTH = 5.0       # 踏み固める区間の長さ [m]（機体の移動距離）
    ROUND_TRIPS = 2         # 踏み固めありのときの往復の回数（走路の上を通る回数は 2 倍。実験A では 4 回で約 95%）
    PASS_SPEED = 0.5        # 踏み固めるときの速さ [m/s]
    DEPTH = 0.10            # 切削深さ [m]（開始時の地面が基準）
    CUT_SPEED = 0.5         # 削るときの速さ [m/s]
    CUT_LENGTH = 10.0       # 削り終わる位置 [m]（開始位置からの距離）
    LOWER_TOLERANCE = 0.015 # 下げ終わりとみなす深さの誤差 [m]
    LOWER_TIMEOUT = 8.0     # 下げるのを待つ時間の上限 [s]
    TIMEOUT = 600.0

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.count = 0                # 終わった往復の数
        self.t_lower = None
        # 踏み固めありなら往復から、対照なら排土板を下げるところから始める
        self.state = "pass_forward" if self.params["round_trips"] > 0 else "lower"

    def sample_params(self, rng):
        trips = self.ROUND_TRIPS if self.seed % 2 == 0 else 0
        return {"round_trips": trips, "compacted": trips > 0, "pass_length": self.PASS_LENGTH,
                "depth": self.DEPTH, "cut_speed": self.CUT_SPEED, "cut_length": self.CUT_LENGTH}

    def operation(self, obs):
        if self.state == "pass_forward" and obs.distance >= self.PASS_LENGTH:
            self.state = "pass_backward"
        elif self.state == "pass_backward" and obs.distance <= 0.2:
            self.count += 1
            self.state = "lower" if self.count >= self.params["round_trips"] else "pass_forward"
        if self.state == "lower":
            if self.t_lower is None:
                self.t_lower = obs.t
            if abs(obs.depth - self.DEPTH) < self.LOWER_TOLERANCE or obs.t - self.t_lower > self.LOWER_TIMEOUT:
                self.state = "cut"

        if self.state == "pass_forward":
            return Command(speed=self.PASS_SPEED, depth=None)
        if self.state == "pass_backward":
            return Command(speed=-self.PASS_SPEED, depth=None)
        if self.state == "lower":
            return Command(speed=0.0, depth=self.DEPTH)
        return Command(speed=self.CUT_SPEED, depth=self.DEPTH)

    def is_done(self, obs):
        return (self.state == "cut" and obs.distance >= self.CUT_LENGTH) or obs.t >= self.TIMEOUT

# ---- T31：踏み固めの往復の折り返しを「開始時の向きへの進み」で判定する別名版
# （decisions/2026-11-18_折り返しは進みの判定の別名版と失敗の検出で直す.md）。上のクラスの動きは変えない。
# 削り終わりの判定（obs.distance ≥ CUT_LENGTH）はそのまま
class CompactionThenCutV2(CompactionThenCut):
    name = "ex_compaction_then_cut_v2"
    description = "【実験B2】ex_compaction_then_cut と同じ。踏み固めの往復の折り返しを刃先の開始時の向きへの進みで判定する"
    RETURN_TOL = 0.2   # 開始位置に戻ったとみなす進み [m]

    def __init__(self, seed, soil=None):
        super().__init__(seed, soil)
        self.tracker = ProgressTracker()

    def operation(self, obs):
        p = self.tracker.progress(obs)
        if self.state == "pass_forward" and p >= self.PASS_LENGTH:
            self.state = "pass_backward"
        elif self.state == "pass_backward" and p <= self.RETURN_TOL:
            self.count += 1
            self.state = "lower" if self.count >= self.params["round_trips"] else "pass_forward"
        # ここから下は CompactionThenCut.operation と同じ（折り返しの判定を2回しないよう、super は呼ばない）
        if self.state == "lower":
            if self.t_lower is None:
                self.t_lower = obs.t
            if abs(obs.depth - self.DEPTH) < self.LOWER_TOLERANCE or obs.t - self.t_lower > self.LOWER_TIMEOUT:
                self.state = "cut"
        if self.state == "pass_forward":
            return Command(speed=self.PASS_SPEED, depth=None)
        if self.state == "pass_backward":
            return Command(speed=-self.PASS_SPEED, depth=None)
        if self.state == "lower":
            return Command(speed=0.0, depth=self.DEPTH)
        return Command(speed=self.CUT_SPEED, depth=self.DEPTH)
