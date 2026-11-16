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
import numbers

import numpy as np

from .. import config as C
from ..episodes import Command, Observation
from ..recording.recorder import Recorder


class SkipEpisode(Exception):
    """実行条件を満たさないため飛ばすエピソード"""


class InvalidCommand(RuntimeError):
    """エピソードが不正な指令（Command 以外、NaN・無限大など）を返した"""


class SafetyStop(RuntimeError):
    """機体が危険な状態になった（開始位置から離れすぎ・大きく傾いた・深く入り込みすぎた）ため止めた"""


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

    @staticmethod
    def _validate_command(cmd, episode, t):
        """エピソードが返した指令を確かめる。不正なら InvalidCommand（機体を止めてから runner が送出する）"""
        where = f"{episode.name} の operation()（t = {t:.2f} s）"
        if not isinstance(cmd, Command):
            raise InvalidCommand(f"{where} が Command ではなく {type(cmd).__name__} を返しました")
        for field in ("speed", "yaw_rate"):
            v = getattr(cmd, field)
            if not isinstance(v, numbers.Real) or not math.isfinite(v):
                raise InvalidCommand(f"{where} の {field} が不正な値です: {v!r}")
        if cmd.depth is not None and (not isinstance(cmd.depth, numbers.Real) or not math.isfinite(cmd.depth)):
            raise InvalidCommand(f"{where} の depth が不正な値です: {cmd.depth!r}（排土板を上げるなら None）")
        return cmd

    def _clip_depth(self, depth):
        """目標深さを [DEPTH_MIN, DEPTH_MAX] に収める。None（排土板を上げる）はそのまま"""
        if depth is None:
            return None, False
        clipped = min(max(depth, C.DEPTH_MIN), C.DEPTH_MAX)
        return clipped, clipped != depth

    def _check_safety(self, stop_on_depth=True):
        """機体が危険な状態でないかを確かめる。危険なら機体を止めて SafetyStop を送出する。
        stop_on_depth=False のとき（排土板を上げる区間）は、深さの超過では止めずに最大値を記録する"""
        p, s = self.iface.pose, self._safety_ref
        reasons = []
        r = math.hypot(p["x"] - s["x"], p["y"] - s["y"])
        if C.SAFE_RADIUS is not None and r > C.SAFE_RADIUS:
            reasons.append(f"開始位置から {r:.1f} m 離れた（SAFE_RADIUS = {C.SAFE_RADIUS} m）")
        dpitch = math.degrees(abs(p["pitch"] - s["pitch"]))
        droll = math.degrees(abs(p["roll"] - s["roll"]))
        if C.MAX_TILT_DEG is not None and max(dpitch, droll) > C.MAX_TILT_DEG:
            reasons.append(f"機体が傾いた（ピッチ {dpitch:.1f}°、ロール {droll:.1f}°、上限 {C.MAX_TILT_DEG}°）")
        depth = s["h0"] - self.iface.blade["edge_z"]
        if C.MAX_ACTUAL_DEPTH is not None and depth > C.MAX_ACTUAL_DEPTH:
            if stop_on_depth:
                reasons.append(f"排土板が深く入り込んだ（{depth * 100:.1f} cm、上限 {C.MAX_ACTUAL_DEPTH * 100:.0f} cm）")
            else:
                prev = self._depth_over_max
                self._depth_over_max = depth if prev is None else max(prev, depth)
        if reasons:
            self.iface.stop_all()
            raise SafetyStop("安全のため停止しました：" + "、".join(reasons))

    def _sleep(self, stop_on_depth=True):
        """制御周期だけ待つ。そのたびに、機体が危険な状態でないかを確かめる"""
        self._check_safety(stop_on_depth)
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
            speed=p["v_forward"],          # 前進方向の速度（前進で正、後退で負）
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
        for key in ("hardening_ke", "hardening_ne"):
            want = getattr(s, key)
            if want is not None:
                checks.append((key, want, 1e-6))

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
        # 安全確認の基準（開始時の位置・傾き・地面の高さ）
        self._safety_ref = {"x": x0, "y": y0, "h0": h0,
                            "pitch": iface.pose["pitch"], "roll": iface.pose["roll"]}
        self._depth_over_max = None   # 上げる区間で深さの上限を超えた場合の最大値 [m]
        labels = {
            "label_c": st.get("cohesion"),
            "label_phi": st.get("friction_angle_deg"),
            "label_rho0": st.get("density"),
            "label_swell": st.get("swell_factor"),
            "label_E0": st.get("youngs_modulus"),
            "label_KE": st.get("hardening_ke"),
            "label_NE": st.get("hardening_ne"),
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
            first = self._validate_command(episode.operation(self._observe(t0, h0, x0, y0)), episode, 0.0)
            d0, clipped = self._clip_depth(first.depth)
            if d0 is None:
                d0 = -C.RAISE_HEIGHT
            self.recorder.target_depth, self.recorder.depth_clipped = d0, clipped
            while iface.now() - t0 < C.LOWER_TIMEOUT:
                if abs(self._lift_control(h0 - d0)) < C.LOWER_TOLERANCE:
                    break
                self._sleep()

            # 5. 走行
            self._phase("running")
            t0 = iface.now()
            while True:
                obs = self._observe(t0, h0, x0, y0)
                if episode.is_done(obs):
                    break
                cmd = self._validate_command(episode.operation(obs), episode, obs.t)
                iface.send_vel(cmd.speed, cmd.yaw_rate)
                depth, clipped = self._clip_depth(cmd.depth)
                if depth is None:
                    depth = -C.RAISE_HEIGHT          # 排土板を上げる = 地面から RAISE_HEIGHT 上
                self.recorder.target_depth, self.recorder.depth_clipped = depth, clipped
                target = h0 - depth
                err = self._lift_control(target)
                if on_tick:
                    on_tick(obs, cmd, err)
                self._sleep()
            summary["run_time"] = obs.t
            summary["run_distance"] = obs.distance

            # 6. 停止して排土板を上げる
            self._phase("raising")
            self.recorder.target_depth, self.recorder.depth_clipped = -C.RAISE_HEIGHT, False
            iface.send_vel(0.0)
            t0 = iface.now()
            while iface.now() - t0 < C.RAISE_TIME:
                self._lift_control(h0 + C.RAISE_HEIGHT)
                self._sleep(stop_on_depth=False)   # 深く入っていても上げ続けるほうが安全
            iface.stop_all()
            summary["raise_depth_over_max"] = self._depth_over_max
        finally:
            # 7. 記録終了（エラーや Ctrl+C で止まった場合も必ず実行する）
            summary.update(self.recorder.stop())
            iface.stop_all()

        self._phase("done")
        return summary