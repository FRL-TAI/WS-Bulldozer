"""パッケージ全体の設定値。環境に合わせてここを書き換える。"""
import os

# ---------------- トピック ----------------
NS = "/d37pxi_24"
TOPIC_BLADE_STATE = f"{NS}/blade_state"        # BladeStatePublisher.cs
TOPIC_JOINT_STATES = f"{NS}/joint_states"
TOPIC_POSE = f"{NS}/global_pose"
TOPIC_CMD_VEL = f"{NS}/cmd_vel"
TOPIC_BLADE_CMD = f"{NS}/blade_cmd"
TOPIC_EPISODE_CMD = "/sim/episode_cmd"          # SimEpisodeManager.cs が受信
TOPIC_EPISODE_STATUS = "/sim/episode_status"    # SimEpisodeManager.cs が送信

# ---------------- 保存先 ----------------
# 環境変数 SOIL_DATA_DIR で上書きできる。既定はパッケージのソース内の data/
DATA_DIR = os.environ.get(
    "SOIL_DATA_DIR", "/workspaces/ws-bulldozer/src/soil_data_collector/data")

# ---------------- 排土板の制御 ----------------
LIFT_JOINT = "lift_joint"
LIFT_SIGN = 1          # `test_episode --calibrate` の結果に合わせて 1 か -1 にする
LIFT_KP = 1.0          # 刃先高さの P 制御ゲイン
LIFT_VMAX = 0.1        # lift_joint に送る速度指令の上限
CONTROL_PERIOD = 0.05  # 制御周期 [s]（シミュレーション時刻）

# ---------------- エピソードの進行 ----------------
SETUP_TIMEOUT = 10.0     # Unity から設定完了の応答を待つ時間 [s]（実時間）
SETTLE_TIME = 2.0        # 地形リセット後に待つ時間 [s]
LOWER_TIMEOUT = 5.0      # 排土板を初期深さまで下げる時間の上限 [s]
LOWER_TOLERANCE = 0.01   # 下げ終わりとみなす刃先高さの誤差 [m]
RAISE_HEIGHT = 0.3       # 走行後に排土板を上げる高さ（元の地面から）[m]
RAISE_TIME = 3.0
RETURN_SPEED = 1.0       # スタート位置へ戻る速さ [m/s]
RETURN_TOLERANCE = 0.2   # 戻り終わりとみなす距離 [m]
RETURN_TIMEOUT = 120.0

# ---------------- 派生量の計算 ----------------
TRACK_JOINTS = ("right_track", "left_track")
SPROCKET_RADIUS = None   # 起動輪の半径 [m]。分かったら設定するとスリップ率を計算する
