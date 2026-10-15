"""
1つのエピソードを実行する共通処理 ( collect_data, test_episode の両方から使う)

流れ：
0. シーンの読み込み直し(機体・地形・AGX の状態をすべて初期状態に戻す)
1. 設定（土質・地形の加工）
2. 地面高さの計測
3. 記録開始
4. 排土板を下げる
5. 走行
6. 排土板を上げる
7. 記録終了

開始位置への後退は行わない（次のエピソードの最初にシーンを読み込み直すため）。
"""
import math

import numpy as np

from .. import config as C
from ..episodes import Observation
from ..recording.recorder import Recorder


class SkipEpisode(Exception):
    """実行条件を満たさないため飛ばすエピソード"""


class EpisodeRunner:
    def __init__(self, iface):
        self.iface = iface
        self.recorder = Recorder(iface)

    # ----- 補助関数 -----
    def _phase(self, phase):
        self.recorder.phase = phase
        self.iface.set_phase(phase)

    def _lift_control(self, h_target):
        err = h_target - self.iface.blade["edge_z"]
        u = float(np.clip(C.LIFT_KP * err, -C.LIFT_VMAX, C.LIFT_VMAX))
        self.iface.send_lift_velocity(C.LIFT_SIGN * u)
        return err

    def _sleep(self, x0, y0):
        """制御周期だけ待つ。そのたびに、開始位置から離れすぎていないかを確認する"""
        r = math.hypot(self.iface.pose["x"] - x0, self.iface.pose["y"] - y0)
        if C.SAFE_RADIUS is not None and r > C.SAFE_RADIUS:
            self.iface.stop_all()
            raise RuntimeError(f"開始位置から {r:.1f} m 離れたため停止しました（SAFE_RADIUS = {C.SAFE_RADIUS} m）")
        self.iface.sleep_sim(C.CONTROL_PERIOD)

    def _measure_ground(self, duration=0.5):
        vals = []
        t0 = self.iface.now()
        while self.iface.now() - t0 < duration:
            vals.append(self.iface.blade.get("ground_ahead", float("nan")))
            self.iface.sleep_sim(0.02)
        h0 = float(np.nanmedian(vals)) if vals else float("nan")
        if not math.isfinite(h0):
            raise RuntimeError("ground_ahead が取得できません（BladeStatePublisher を確認）")
        return h0

    def _observe(self, t0, h0, x0, y0):
        b, p = self.iface.blade, self.iface.pose
        return Observation(
            t=self.iface.now() - t0,
            distance=math.hypot(p["x"] - x0, p["y"] - y0),
            speed=math.hypot(p["vx"], p["vy"]),
            edge_z=b["edge_z"], ground_h0=h0, depth=h0 - b["edge_z"], blade=dict(b))

    @staticmethod
    def _check_soil(episode, st):
        s = episode.soil
        checks = [("cohesion", s.cohesion, 1.0), ("friction_angle_deg", s.friction_angle_deg, 0.01),
                  ("density", s.density, 0.5)]
        if s.swell_factor is not None:
            checks.append(("swell_factor", s.swell_factor, 1e-3))
        if s.youngs_modulus is not None:
            checks.append(("youngs_modulus", s.youngs_modulus, 1.0))
        for key, want, tol in checks:
            got = st.get(key)
            if got is None or abs(got - want) > tol + 1e-6 * abs(want):
                raise RuntimeError(f"{key} が反映されていません（要求 {want}, AGX {got}）")

    # ----- 本体 -----
    def run(self, episode, index, total, csv_path=None, on_tick=None):
        iface = self.iface

        # 実行できる条件か確認（Unity に依頼する前に判定する）
        if episode.REQUIRES_GRID_CONTROL and not (iface.status or {}).get("grid_control_enabled"):
            raise SkipEpisode("Unity 側で AGX_GRID_CONTROL が無効です")

        # 0. シーンの読み込み直し（新しいシーンのトピックがそろうまで待つ）
        self._phase("reloading")
        iface.reload_scene()
        iface.sleep_sim(C.RELOAD_SETTLE)          # AGX の地形などの初期化を待つ

        # 1. 設定（土質・地形の加工）
        st = iface.setup_episode(episode, index, total)
        self._check_soil(episode, st)
        if episode.terrain_ops() and not st.get("ops_applied"):
            raise SkipEpisode(f"地形の加工が適用されませんでした（Unity のエラー: {st.get('error')}）")
        iface.sleep_sim(C.SETTLE_TIME)            # 機体が着地して落ち着くのを待つ

        # 2. 基準の地面高さと開始位置
        h0 = self._measure_ground()
        x0, y0 = iface.pose["x"], iface.pose["y"]
        labels = {
            "label_c": st.get("cohesion"),
            "label_phi": st.get("friction_angle_deg"),
            "label_rho0": st.get("density"),
            "label_swell": st.get("swell_factor"),
            "label_E0": st.get("youngs_modulus"),
        }
        meta = {"episode_index": index, "episode_name": episode.name, "seed": episode.seed}

        # 3. 記録開始
        if csv_path:
            self.recorder.start(csv_path, h0, (x0, y0), labels, meta)
        summary = {
            "ground_h0": h0, **labels,
            # 開始位置・向き（読み込み直しで毎回同じ状態から始まっているかの記録）
            "start_x": x0, "start_y": y0, "start_yaw_deg": math.degrees(iface.pose["yaw"]),
        }
        try:
            # 4. 停止したまま排土板を初期深さまで下げる
            self._phase("lowering")
            t0 = iface.now()
            first = episode.operation(self._observe(t0, h0, x0, y0))
            d0 = first.depth if first.depth is not None else -C.RAISE_HEIGHT
            while iface.now() - t0 < C.LOWER_TIMEOUT:
                if abs(self._lift_control(h0 - d0)) < C.LOWER_TOLERANCE:
                    break
                self._sleep(x0, y0)

            # 5. 走行
            self._phase("running")
            t0 = iface.now()
            while True:
                obs = self._observe(t0, h0, x0, y0)
                if episode.is_done(obs):
                    break
                cmd = episode.operation(obs)
                iface.send_vel(cmd.speed, cmd.yaw_rate)
                target = h0 - cmd.depth if cmd.depth is not None else h0 + C.RAISE_HEIGHT
                err = self._lift_control(target)
                if on_tick:
                    on_tick(obs, cmd, err)
                self._sleep(x0, y0)
            summary["run_time"] = obs.t
            summary["run_distance"] = obs.distance

            # 6. 停止して排土板を上げる
            self._phase("raising")
            iface.send_vel(0.0)
            t0 = iface.now()
            while iface.now() - t0 < C.RAISE_TIME:
                self._lift_control(h0 + C.RAISE_HEIGHT)
                self._sleep(x0, y0)
            iface.stop_all()
        finally:
            # 7. 記録終了（エラーや Ctrl+C で止まった場合も必ず実行する）
            summary.update(self.recorder.stop())
            iface.stop_all()

        self._phase("done")
        return summary