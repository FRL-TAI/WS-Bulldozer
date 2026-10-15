"""
blade_state を受信するたびに、その時点の全データを CSV に1行書き出す

各トピックはすべて同じシミュレーションから来るので、blade_state(50 Hz)を基準とし、
他のトピックはその時点の最新値を使う（ゼロ次ホールド）
"""
import csv
import math
import threading

from .. import config as C


class Recorder:
    def __init__(self, iface):
        self.iface = iface
        self.lock = threading.Lock()
        self.active = False
        self.phase = ""
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
            self.active = True

    def stop(self):
        with self.lock:
            if not self.active:
                return {"rows": 0}
            self.active = False
            self.file.close()
            return {"rows": self.rows, "path": self.path}

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
            speed = math.hypot(pose.get("vx", 0.0), pose.get("vy", 0.0))
            distance = math.hypot(pose.get("x", self.x0) - self.x0, pose.get("y", self.y0) - self.y0)
            width = blade.get("blade_width", float("nan"))
            if self.phase == "running" and depth > 0 and math.isfinite(width):
                self.cut_volume += width * depth * speed * dt
            slip = float("nan")
            if C.SPROCKET_RADIUS:
                w = [abs(joints.get(f"{j}_vel", 0.0)) for j in C.TRACK_JOINTS]
                v_track = sum(w) / len(w) * C.SPROCKET_RADIUS
                if v_track > 1e-3:
                    slip = 1.0 - speed / v_track

            row = {}
            row.update(self.meta)
            row["phase"] = self.phase
            row["t"] = sim_time - self.t0
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
