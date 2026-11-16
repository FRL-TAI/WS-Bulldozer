"""
Unity なしで、runner.py の流れ（正常終了・エラー・安全停止）と記録を通してみる（疑似実行）

置き場所: src/bull_ope/analysis/scripts/dryrun_stress.py
使い方:
  cd /workspaces/ws-bulldozer/src/bull_ope
  python3 analysis/scripts/dryrun_stress.py                  # stress_* をすべて
  python3 analysis/scripts/dryrun_stress.py stress_nan_depth  # 指定したものだけ

疑似の SimInterface は「指令どおりに動くだけの機体」で、物理（反力・転倒）は再現しない。
確かめられるのは、例外の種類と記録の流れ（CSV が閉じる、episodes.jsonl に1行ずつ書ける、
指令に NaN が入らない、点検スクリプトが最後まで動く）まで。結果は一時フォルダに保存し、
最後にその場所を表示するので、check_collection.py / check_recording.py をそのまま試せる。
"""
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from bull_ope import config as C                                  # noqa: E402
from bull_ope.core.runner import EpisodeRunner, SkipEpisode       # noqa: E402
from bull_ope.episodes import available_episodes                  # noqa: E402
from bull_ope.recording.json_utils import to_jsonable             # noqa: E402

DT = 0.02   # blade_state の周期（50 Hz）


class FakeIface:
    """SimInterface の代わり。指令どおりに位置と刃先の高さを動かし、50 Hz で blade_state を配る"""

    def __init__(self):
        self.t = 100.0
        self.blade_listeners = []
        self.cmd_vx = self.cmd_wz = self.cmd_lift = 0.0
        self.sent_nonfinite = 0                    # NaN・無限大が送られようとした回数
        self.status = {"boot_id": 1, "grid_control_enabled": True}
        self._reset()

    def _reset(self):
        self.x, self.y, self.yaw, self.edge = -10.0, 7.0, 0.0, 0.3
        self._publish()

    def _publish(self):
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        self.pose = dict(x=self.x, y=self.y, z=0.0, roll=0.0, pitch=0.0, yaw=self.yaw,
                         vx=self.cmd_vx * c, vy=self.cmd_vx * s, vz=0.0, wz=self.cmd_wz,
                         v_forward=self.cmd_vx, v_lateral=0.0, pose_stamp=self.t)
        self.joints = {"lift_joint_pos": 0.0, "lift_joint_vel": self.cmd_lift, "lift_joint_effort": 0.0}
        self.blade = {"sim_time": self.t, "edge_z": self.edge, "ground_ahead": 0.0, "blade_width": 2.96,
                      "F_total_x": 0.0, "F_total_z": 0.0}
        for cb in list(self.blade_listeners):
            cb(self.blade)

    # ---- 時間 ----
    def now(self):
        return self.t

    def sleep_sim(self, sec):
        for _ in range(max(1, round(sec / DT))):
            self.t += DT
            self.x += self.cmd_vx * math.cos(self.yaw) * DT
            self.y += self.cmd_vx * math.sin(self.yaw) * DT
            self.yaw += self.cmd_wz * DT
            self.edge += C.LIFT_SIGN * self.cmd_lift * DT   # LIFT_SIGN をかけた指令で刃先が上がる向きに合わせる
            self._publish()

    # ---- 送信（本物と同じく、有限でない値は送る前に例外）----
    def _check_finite(self, *values):
        for v in values:
            if not math.isfinite(v):
                self.sent_nonfinite += 1
                raise ValueError(f"有限でない値を送ろうとしました: {values}")

    def send_vel(self, v, w=0.0):
        self._check_finite(float(v), float(w))
        self.cmd_vx, self.cmd_wz = float(v), float(w)

    def send_lift_velocity(self, u):
        self._check_finite(float(u))
        self.cmd_lift = float(u)

    def stop_all(self):
        self.send_vel(0.0)
        self.send_lift_velocity(0.0)

    # ---- Unity とのやり取り ----
    def setup_episode(self, episode, index, total):
        s = episode.soil.to_msg_dict()
        return {"cohesion": s["cohesion"], "friction_angle_deg": s["friction_angle_deg"], "density": s["density"],
                "swell_factor": s["swell_factor"] if s["swell_factor"] >= 0 else 1.2,
                "youngs_modulus": s["youngs_modulus"] if s["youngs_modulus"] >= 0 else 5.0e6,
                "ops_applied": True}

    def reload_scene(self):
        self.status["boot_id"] += 1
        self.cmd_vx = self.cmd_wz = self.cmd_lift = 0.0
        self._reset()

    def set_phase(self, phase):
        pass


def main():
    registry = available_episodes()
    names = sys.argv[1:] or [n for n in registry if n.startswith("stress_")]
    out = tempfile.mkdtemp(prefix="dryrun_")
    run_dir = os.path.join(out, "run_dryrun")
    os.makedirs(run_dir)
    iface = FakeIface()
    runner = EpisodeRunner(iface)

    print(f"{'エピソード':24s}{'行数':>6s}  結果")
    for i, name in enumerate(names):
        ep = registry[name](seed=i)
        fname = f"ep{i:04d}_{name}.csv"
        row = {"episode_index": i, "file": fname, **ep.metadata()}
        try:
            row.update(runner.run(ep, i, len(names), csv_path=os.path.join(run_dir, fname)), status="ok")
        except SkipEpisode as e:
            row.update(status=f"skipped: {e}")
        except Exception as e:   # collect_data と同じく、1つの失敗で止めない
            row.update(status=f"error: {type(e).__name__}: {e}")
            iface.stop_all()
        line = json.dumps(to_jsonable(row), ensure_ascii=False, allow_nan=False)
        with open(os.path.join(run_dir, "episodes.jsonl"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(f"{name:24s}{row.get('rows', '-'):>6}  {row['status'][:100]}")

    print(f"\nNaN・無限大を送ろうとした回数: {iface.sent_nonfinite}（0 が正常）")
    print(f"結果のフォルダ: {run_dir}")


if __name__ == "__main__":
    main()