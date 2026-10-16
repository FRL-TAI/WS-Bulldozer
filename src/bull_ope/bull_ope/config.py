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
    "SOIL_DATA_DIR", "/workspaces/ws-bulldozer/src/bull_ope/data")

# ---------------- 排土板の制御 ----------------
LIFT_JOINT = "lift_joint"
LIFT_SIGN = -1         # `test_episode --calibrate` の結果に合わせて 1 か -1 にする
LIFT_KP = 1.0          # 刃先高さの P 制御ゲイン
LIFT_VMAX = 0.1        # lift_joint に送る速度指令の上限
CONTROL_PERIOD = 0.05  # 制御周期 [s]（シミュレーション時刻）
VEL_WINDOW = 0.1         # 位置の変化から速度を計算するときの時間幅 [s]（大きいほど揺れが少なく、遅れが大きい）

# ---------------- エピソードの進行 ----------------
SETUP_TIMEOUT = 10.0     # Unity から設定完了の応答を待つ時間 [s]（実時間）
SETTLE_TIME = 2.0        # 地形リセット後に待つ時間 [s]
LOWER_TIMEOUT = 5.0      # 排土板を初期深さまで下げる時間の上限 [s]
LOWER_TOLERANCE = 0.01   # 下げ終わりとみなす刃先高さの誤差 [m]
RAISE_HEIGHT = 0.3       # 走行後に排土板を上げる高さ（元の地面から）[m]
RAISE_TIME = 3.0

# ---------------- 派生量の計算 ----------------
TRACK_JOINTS = ("right_track", "left_track")
SPROCKET_RADIUS = None   # 起動輪の半径 [m]。分かったら設定するとスリップ率を計算する

# ---------------- シーンの読み込み直し ----------------
RELOAD_TIMEOUT = 60.0    # シーンの読み込み直しを待つ時間の上限 [s]（実時間）
RELOAD_SETTLE = 1.0      # 読み込み直しの後、設定を送る前に待つ時間 [s]（AGX の初期化を待つ）

# ---------------- 安全範囲 ----------------
# 走行中に開始位置からこの距離 [m] を超えたら、機体を止めてそのエピソードを中止する。
# 「開始位置からフィールドの一番近い端までの距離」より小さくする。None で確認しない
SAFE_RADIUS = 20.0