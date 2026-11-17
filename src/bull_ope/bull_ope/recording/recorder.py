"""
blade_state を受信するたびに、その時点の全データを CSV に1行書き出す

各トピックはすべて同じシミュレーションから来るので、blade_state(50 Hz)を基準とし、
他のトピックはその時点の最新値を使う（ゼロ次ホールド）

stop() は、エピソードの要約（episodes.jsonl に入る）として、削っている層の締固めの程度
（state_cut_compaction_mean）の running 中の集計を返す（CutCompactionSummary）
"""
import csv
import math
import threading

from .. import config as C


class CutCompactionSummary:
    """running 中の state_cut_compaction_mean（刃先の高さのボクセルの締固めの程度の、そのステップの平均）の集計。
    NaN（削っているマスがないステップ）は数えない。
      cut_compaction_steps        値があったステップの数
      cut_compaction_min / _max   そのステップの平均の最小・最大
      cut_compaction_below1_frac  1 を下回った（< 1 − TOL）ステップの割合
      cut_compaction_first_cross_t
          1 を初めてまたいだ時刻 [s]（記録の t。エピソードの記録の開始から）。
          「1 を下回っている（< 1 − TOL）か」が、最初に値があったステップと変わった最初のステップの時刻。
          地山（1.000）から 1 を下回った場合も、1 を超えていた土が 1 を下回った場合も、ここに入る。またがなければ NaN
    """
    TOL = 5e-4

    def __init__(self):
        self.n = 0
        self.lo = math.inf
        self.hi = -math.inf
        self.below = 0
        self.below0 = None      # 最初に値があったステップで 1 を下回っていたか
        self.cross_t = math.nan

    def add(self, v, t):
        if not math.isfinite(v):
            return
        self.n += 1
        self.lo, self.hi = min(self.lo, v), max(self.hi, v)
        below = v < 1 - self.TOL
        self.below += below
        if self.below0 is None:
            self.below0 = below
        elif below != self.below0 and not math.isfinite(self.cross_t):
            self.cross_t = t

    def result(self):
        nan = math.nan
        return {"cut_compaction_steps": self.n,
                "cut_compaction_min": self.lo if self.n else nan,
                "cut_compaction_max": self.hi if self.n else nan,
                "cut_compaction_below1_frac": self.below / self.n if self.n else nan,
                "cut_compaction_first_cross_t": self.cross_t}


class Recorder:
    def __init__(self, iface):
        self.iface = iface
        self.lock = threading.Lock()
        self.active = False
        self.phase = ""
        self.target_depth = float("nan")   # runner が設定する、制限後の目標深さ [m]（排土板を上げるときは −RAISE_HEIGHT）
        self.depth_clipped = False         # 目標深さを制限したか
        iface.blade_listeners.append(self._on_blade)

    def start(self, path, ground_h0, origin_xy, labels, meta):
        with self.lock:
            self.path = path
            self.file = open(path, "w", newline="")
            self.writer = None
            self.ground_h0 = ground_h0
            self.x0, self.y0 = origin_xy
            self.labels = labels
            self.meta = meta
            self.t0 = None
            self.prev_t = None
            self.cut_volume = 0.0
            self.rows = 0
            self.cut_compaction = CutCompactionSummary()
            self.active = True

    def stop(self):
        with self.lock:
            if not self.active:
                return {"rows": 0}
            self.active = False
            self.file.close()
            return {"rows": self.rows, "path": self.path, **self.cut_compaction.result()}

    def _on_blade(self, blade):
        if not self.active:
            return
        with self.lock:
            if not self.active:
                return
            joints = self.iface.joints or {}
            pose = self.iface.pose or {}
            sim_time = blade.get("sim_time", float("nan"))
            if self.t0 is None:
                self.t0 = sim_time
            dt = 0.0 if self.prev_t is None else max(0.0, sim_time - self.prev_t)
            self.prev_t = sim_time

            # ----- 派生量 -----
            edge_z = blade.get("edge_z", float("nan"))
            depth = self.ground_h0 - edge_z
            speed = math.hypot(pose.get("vx", 0.0), pose.get("vy", 0.0))   # 速さ（向きなし）
            v_forward = pose.get("v_forward", 0.0)                         # 前進で正、後退で負
            distance = math.hypot(pose.get("x", self.x0) - self.x0, pose.get("y", self.y0) - self.y0)
            width = blade.get("blade_width", float("nan"))
            if self.phase == "running" and depth > 0 and math.isfinite(width):
                # 前進しているときだけ積算する（後退中の切削を数えない）
                self.cut_volume += width * depth * max(v_forward, 0.0) * dt
            slip = float("nan")
            if C.SPROCKET_RADIUS:
                w = [abs(joints.get(f"{j}_vel", 0.0)) for j in C.TRACK_JOINTS]
                v_track = sum(w) / len(w) * C.SPROCKET_RADIUS
                if v_track > 1e-3:
                    slip = 1.0 - speed / v_track

            row = {}
            row.update(self.meta)
            row["phase"] = self.phase
            row["target_depth"] = self.target_depth
            row["depth_clipped"] = int(self.depth_clipped)
            row["t"] = sim_time - self.t0
            if self.phase == "running":
                self.cut_compaction.add(blade.get("state_cut_compaction_mean", math.nan), row["t"])
            row.update(blade)
            row.update(joints)
            row.update(pose)
            row.update(cmd_vx=self.iface.cmd_vx, cmd_wz=self.iface.cmd_wz, cmd_lift=self.iface.cmd_lift)
            row.update(ground_h0=self.ground_h0, depth=depth, speed=speed, distance=distance,
                       cut_volume=self.cut_volume, slip_ratio=slip)
            row.update(self.labels)

            if self.writer is None:
                self.writer = csv.DictWriter(self.file, fieldnames=list(row.keys()),
                                             extrasaction="ignore", restval="")
                self.writer.writeheader()
            self.writer.writerow(row)
            self.rows += 1