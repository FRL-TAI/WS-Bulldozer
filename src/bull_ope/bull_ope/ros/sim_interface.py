"""
シミュレータ(OperaSim-AGX)との ROS2 通信をまとめたノード
"""

import json
import math
import time
from collections import deque

from com3_msgs.msg import JointCmd
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray, String

from .. import config as C


def quat_to_rpy(q):
    roll = math.atan2(2 * (q.w * q.x + q.y * q.z), 1 - 2 * (q.x ** 2 + q.y ** 2))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (q.w * q.y - q.z * q.x))))
    yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y ** 2 + q.z ** 2))
    return roll, pitch, yaw


class SimInterface(Node):
    def __init__(self):
        super().__init__("bull_ope", parameter_overrides=[Parameter("use_sim_time", value=True)])
        self.blade  = None  # blade_state    の最新値 {名前: 値}
        self.joints = None  # joint_states   の最新値 {"lift_joint_pos": …}
        self.pose   = None  # global_pose    の最新値 {"x": …}
        self.status = None  # episode_status の最新値（dict）

        self.cmd_vx = 0.0
        self.cmd_wz = 0.0
        self.cmd_lift = 0.0

        self.blade_listeners = []   # blade_state を受信するたびに呼ぶ関数（記録用）
        self.probe_listeners = []   # compaction_probe を受信するたびに呼ぶ関数（記録用。引数は JSON の文字列）
        self._pose_hist = deque(maxlen=200)   # 速度の計算用の (時刻, x, y, z, yaw) の履歴
        self._request_id = int(time.time()) % 100000

        self.create_subscription(Float64MultiArray, C.TOPIC_BLADE_STATE, self._on_blade, 50)
        self.create_subscription(JointState, C.TOPIC_JOINT_STATES, self._on_joints, 50)
        self.create_subscription(Odometry, C.TOPIC_POSE, self._on_pose, 50)
        self.create_subscription(String, C.TOPIC_EPISODE_STATUS, self._on_status, 10)
        self.create_subscription(String, C.TOPIC_COMPACTION_PROBE, self._on_probe, 10)
        self.pub_vel = self.create_publisher(Twist, C.TOPIC_CMD_VEL, 10)
        self.pub_blade = self.create_publisher(JointCmd, C.TOPIC_BLADE_CMD, 10)
        self.pub_episode = self.create_publisher(String, C.TOPIC_EPISODE_CMD, 10)


    # ----- 受信 -----
    def _on_blade(self, msg):
        if msg.layout.dim and msg.layout.dim[0].label:
            names = msg.layout.dim[0].label.split(",")
        else:
            names = [f"v{i}" for i in range(len(msg.data))]
        d = dict(zip(names, msg.data))
        self.blade = d
        for cb in list(self.blade_listeners):
            cb(d)

    def _on_joints(self, msg):
        d = {}
        for i, n in enumerate(msg.name):
            if i < len(msg.position):
                d[f"{n}_pos"] = msg.position[i]
            if i < len(msg.velocity):
                d[f"{n}_vel"] = msg.velocity[i]
            if i < len(msg.effort):
                d[f"{n}_effort"] = msg.effort[i]
        self.joints = d

    def _on_pose(self, msg):
        """global_pose を受信する。

        OperaSim の global_pose は速度の欄（twist）が 0 のままなので（関門1の段階Aで確認）、
        位置と向きの変化から速度を計算する。VEL_WINDOW 秒ほど前の値との差をとって、ノイズを抑える。
        """
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        roll, pitch, yaw = quat_to_rpy(q)
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9

        h = self._pose_hist
        if h and t < h[-1][0]:
            h.clear()                       # 時刻が戻った（シーンの読み込み直し）→ 履歴を捨てる
        if not h or t > h[-1][0]:
            h.append((t, p.x, p.y, p.z, yaw))

        # VEL_WINDOW 秒以上前の、いちばん新しい値を探す
        old = next((s for s in reversed(h) if t - s[0] >= C.VEL_WINDOW), None)
        vx = vy = vz = wz = 0.0
        if old is not None:
            dt = t - old[0]
            vx, vy, vz = (p.x - old[1]) / dt, (p.y - old[2]) / dt, (p.z - old[3]) / dt
            wz = math.atan2(math.sin(yaw - old[4]), math.cos(yaw - old[4])) / dt   # 角度の折り返しを考慮

        # 車体の前方向・左方向の成分（前進で正、後退で負）
        c, s = math.cos(yaw), math.sin(yaw)
        v_forward = vx * c + vy * s
        v_lateral = -vx * s + vy * c

        self.pose = dict(x=p.x, y=p.y, z=p.z, roll=roll, pitch=pitch, yaw=yaw,
                         vx=vx, vy=vy, vz=vz, wz=wz, v_forward=v_forward, v_lateral=v_lateral,
                         pose_stamp=t)

    def _on_status(self, msg):
        try:
            self.status = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warn(f"episode_status を解釈できません: {msg.data[:200]}")

    def _on_probe(self, msg):
        """CompactionProbe（Unity）の記録を受信し、記録用の関数に JSON の文字列のまま渡す。
        解釈と保存は CompactionRecorder が行う（request_id が一致するものだけを保存する）"""
        for cb in list(self.probe_listeners):
            cb(msg.data)


    # ----- 時間 -----
    def now(self):
        """シミュレーション時刻 [s]"""
        return self.get_clock().now().nanoseconds * 1e-9

    def sleep_sim(self, sec):
        t0 = self.now()
        while self.now() - t0 < sec:
            time.sleep(0.005)

    def wait_ready(self, timeout=30.0):
        """blade_state / joint_states / global_pose / episode_status が届き、
        /sim/episode_cmd の送信が Unity 側とつながるまで待つ"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            missing = [n for n, v in [("blade_state", self.blade), ("joint_states", self.joints),
                                      ("global_pose", self.pose), ("episode_status", self.status)]
                       if v is None]
            # 送信者が相手とつながる前に送ったメッセージは捨てられる（新しいプロセスの最初の reload が届かない）。
            # Unity 側（ROS-TCP-Endpoint）が /sim/episode_cmd を購読していることを確かめてから進む
            if self.pub_episode.get_subscription_count() == 0:
                missing.append("episode_cmd の購読（Unity 側）")
            if not missing:
                return
            self.get_logger().info(f"受信待ち: {', '.join(missing)}", throttle_duration_sec=2.0)
            time.sleep(0.1)
        raise TimeoutError(f"トピックが届きません: {missing}。Unity が Play 中か確認してください")


    # ----- 送信 -----
    @staticmethod
    def _check_finite(name, *values):
        """NaN・無限大の指令を OperaSim に送らない（送る前に例外にする）"""
        for v in values:
            if not math.isfinite(v):
                raise ValueError(f"{name} に有限でない値を送ろうとしました: {values}")

    def send_vel(self, v, w=0.0):
        self._check_finite("cmd_vel", float(v), float(w))
        self.cmd_vx = float(v)
        self.cmd_wz = float(w)
        msg = Twist()
        msg.linear.x = self.cmd_vx
        msg.angular.z = self.cmd_wz
        self.pub_vel.publish(msg)

    def send_lift_velocity(self, u):
        """lift_joint に速度指令を送る（tilt と angle は速度 0 で保持）。

        OperaSim の BulldozerInput.SetCommands() は joint_name を見ず、
        配列の [0]=lift, [1]=tilt, [2]=angle の順番で値を読むため、必ず3要素で送る。
        """
        self._check_finite("blade_cmd", float(u))
        self.cmd_lift = float(u)
        msg = JointCmd()
        msg.joint_name = ["lift_joint", "tilt_joint", "angle_joint"]   # 参考情報（OperaSim 側では未使用）
        msg.control_type = 1  # 0:position, 1:velocity, 2:effort
        msg.position = [0.0, 0.0, 0.0]
        msg.velocity = [self.cmd_lift, 0.0, 0.0]
        msg.effort = [0.0, 0.0, 0.0]
        self.pub_blade.publish(msg)

    def stop_all(self):
        """車体の速度とブレードの操作を停止させる"""
        self.send_vel(0.0)
        self.send_lift_velocity(0.0)

    def setup_episode(self, episode, index, total):
        """土質パラメータの設定・地形のリセット・地形の加工を Unity に依頼し、完了の応答を返す"""
        self._request_id += 1
        rid = self._request_id
        cmd = {
            "command": "setup",
            "request_id": rid,
            "episode_name": episode.name,
            "episode_index": int(index),
            "total_episodes": int(total),
            "phase": "setup",
            "soil": episode.soil.to_msg_dict(),
            "terrain_ops": [op.to_msg_dict() for op in episode.terrain_ops()],
            # Unity の CompactionProbe に、このエピソードの締固めを記録させるか
            "record_compaction": bool(getattr(episode, "RECORD_COMPACTION", False)),
        }
        msg = String(data=json.dumps(cmd))
        deadline = time.monotonic() + C.SETUP_TIMEOUT
        next_send = 0.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_send:   # 取りこぼし対策で1秒ごとに再送（Unity 側で重複は無視）
                self.pub_episode.publish(msg)
                next_send = time.monotonic() + 1.0
            st = self.status
            if st and st.get("request_id") == rid:
                if st.get("error"):
                    raise RuntimeError(f"Unity でエラー: {st['error']}")
                return st
            time.sleep(0.05)
        raise TimeoutError("Unity から設定完了の応答がありません（SimEpisodeManager を確認）")

    def reload_scene(self, timeout=None):
        """Unity にシーンの読み込み直しを依頼し、新しいシーンのトピックがそろうまで待つ。

        Unity の SimEpisodeManager は起動のたびに新しい boot_id を作って状態に含めるので、
        boot_id が変わったことで「新しいシーンが立ち上がった」と判断する。
        """
        timeout = C.RELOAD_TIMEOUT if timeout is None else timeout
        old = (self.status or {}).get("boot_id")
        if old is None:
            raise RuntimeError("episode_status に boot_id がありません（Unity の SimEpisodeManager を更新してください）")
        self.pub_episode.publish(String(data=json.dumps({"command": "reload"})))

        deadline = time.monotonic() + timeout
        while True:
            st = self.status
            if st and st.get("boot_id") not in (None, old):
                break
            if time.monotonic() > deadline:
                raise TimeoutError("シーンの読み込み直しが完了しません（Unity の Console を確認）")
            time.sleep(0.05)

        # 古いシーンの値を捨て、新しいシーンの値がそろうまで待つ
        self.blade = self.joints = self.pose = None
        self._pose_hist.clear()
        self.cmd_vx = self.cmd_wz = self.cmd_lift = 0.0
        self.wait_ready(timeout=max(1.0, deadline - time.monotonic()))

    def set_phase(self, phase):
        """Unity の表示ウィンドウに出す進行状況を更新する"""
        self.pub_episode.publish(String(data=json.dumps({"command": "phase", "phase": phase})))