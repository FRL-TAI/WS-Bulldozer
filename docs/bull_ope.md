# bull_ope：土質パラメータ推定用データ収集パッケージ（ROS2）

## 1. 概要
| 項目 | 内容 |
| --- | --- |
| パッケージ名 | `bull_ope` |
| 種類 | ROS2 Python パッケージ（ament_python） |
| 対象 | OperaSim-AGX のブルドーザ `d37pxi_24` |
| 対になる Unity 側の機能 | `BladeStatePublisher`, `SimEpisodeManager`, `EpisodeStatusOverlay`（`docs/research/README.md` を参照） |

### 目的
土質パラメータ（粘着力 c、内部摩擦角 φ、密度 ρ など）を推定するニューラルネットワークの学習データを、シミュレーションで自動的に大量に集める。

1回の試行（エピソード）では、土質パラメータを設定して地形を初期状態に戻し、決められた操作でブルドーザを走らせ、その間の排土板の反力や車体の状態を時系列で記録する。これを、土質と操作を変えながら自動で繰り返す。

### 使えるスクリプト
| コマンド | 用途 |
| --- | --- |
| `ros2 run bull_ope test_episode` | 特定のエピソードを1回テスト走行し、取得したデータを点検する。排土板の向きの較正にも使う |
| `ros2 run bull_ope collect_data` | 複数のエピソードを順に実行し、学習用データを収集する |


## 2. データの流れ
### 2.1 通信するトピック
| トピック | 型 | 向き | 内容 |
| --- | --- | --- | --- |
| `/d37pxi_24/blade_state` | `std_msgs/Float64MultiArray` | 受信 | 排土板の反力、刃先位置、地面の高さなど（50 Hz）。値の名前は `layout.dim[0].label` にカンマ区切りで入る |
| `/d37pxi_24/joint_states` | `sensor_msgs/JointState` | 受信 | 関節（lift / tilt / angle / 左右の履帯）の位置・速度・力 |
| `/d37pxi_24/global_pose` | `nav_msgs/Odometry` | 受信 | 車体の位置・姿勢・速度 |
| `/sim/episode_status` | `std_msgs/String`（JSON） | 受信 | Unity の状態。AGX から読み戻した土質パラメータなど |
| `/d37pxi_24/cmd_vel` | `geometry_msgs/Twist` | 送信 | 前進・後退の速度指令（`linear.x`） |
| `/d37pxi_24/blade_cmd` | `com3_msgs/JointCmd` | 送信 | `lift_joint` への速度指令（`control_type = 1`） |
| `/sim/episode_cmd` | `std_msgs/String`（JSON） | 送信 | エピソードの設定（土質・地形の加工）、進行状況の更新 |
| `/clock` | — | 受信 | シミュレーション時刻（ノードは `use_sim_time = True` で動く） |

### 2.2 収集データ

`bull_ope` が出力する時系列データ（`data/test/*.csv`、`data/run_*/ep*.csv`）の各カラムの収集元と内容。1行 = `/d37pxi_24/blade_state` を1回受信した時点（50 Hz）。他のトピックの値は、その時点で受信済みの最新値を使う。

記録するのはエピソードの「排土板を下げる → 走る → 上げる」の間（`phase` が `lowering` / `running` / `raising`）だけで、学習には `phase == "running"` の行を使う。

#### 収集元の凡例
| 収集元 | 意味 |
| --- | --- |
| bull_ope（エピソード） | 実行中のエピソードの情報。`bull_ope` 内で決まる |
| bull_ope（計算） | `bull_ope`（`recorder.py`）が他の値から計算する |
| bull_ope（指令） | `bull_ope`（`sim_interface.py`）が最後に送った指令の値 |
| blade_state / AGX API | 自作の `BladeStatePublisher.cs` が AGX Dynamics の API で取得し、`/d37pxi_24/blade_state` で配信 |
| blade_state / AGXUnity | 同スクリプトが AGXUnity の Shovel の設定（刃先・上端の位置）から計算して配信 |
| blade_state / Unity | 同スクリプトが Unity の機能（`Terrain.SampleHeight` など）で取得して配信 |
| joint_states | OperaSim 本体が `/d37pxi_24/joint_states` で配信 |
| global_pose | OperaSim 本体が `/d37pxi_24/global_pose` で配信 |
| episode_status / AGX API | 自作の `SimEpisodeManager.cs` が AGX の地形材料から読み戻し、`/sim/episode_status` で配信。エピソード開始時に1回だけ受け取り、全行に同じ値を書く |

#### 座標系の約束
- **力・トルク（`F_*`、`T_*`）：** 車体（`base_link`）に固定した座標。x：前方、y：左方、z：上方。
- **位置（`edge_*`、`x`、`y`、`z`）・高さ（`ground_*`）：** ワールド座標。高さは Unity のワールド y と同じ値。

#### カラム一覧
| 収集元 | カラム名 | 内容 |
| --- | --- | --- |
| bull_ope（エピソード） | `episode_index` | エピソード番号（`test_episode` では常に 0） |
| bull_ope（エピソード） | `episode_name` | エピソード名（例：`val_constant_depth`） |
| bull_ope（エピソード） | `seed` | エピソードの乱数のシード |
| bull_ope（エピソード） | `phase` | 進行状況。`lowering`（排土板を下げる）、`running`（走行）、`raising`（排土板を上げる） |
| bull_ope（エピソード） | `leg` | エピソードが指定した区間名（`label` の仕組みを使っている場合のみ。例：`forward_1`） |
| bull_ope（計算） | `t` | 記録開始からの経過時間 [s]（`sim_time` − 最初の `sim_time`） |
| blade_state / Unity | `sim_time` | シミュレーション時刻 [s]（Unity の `Time.fixedTimeAsDouble`） |
| blade_state / AGX API | `F_total_x`, `F_total_y`, `F_total_z` | 排土板が土から受ける力の合力 [N]（下の4つの力の和）。土を押して前進中は `F_total_x` が負 |
| blade_state / AGX API | `F_pen_x`, `F_pen_y`, `F_pen_z` | 貫入抵抗 [N]。刃先が削られていない地面に食い込むときの抵抗（`Terrain.getPenetrationForce`） |
| blade_state / AGX API | `F_sep_x`, `F_sep_y`, `F_sep_z` | 分離抵抗 [N]。前方へ切削・押土するとき、排土板の前の土塊から受ける力（`Terrain.getSeparationContactForce`）。前進時に支配的 |
| blade_state / AGX API | `F_def_x`, `F_def_y`, `F_def_z` | 変形抵抗 [N]。後退や横方向など、切削方向以外に土を押しのけるときの力（`Terrain.getDeformationContactForce`）。直進時は 0 |
| blade_state / AGX API | `F_con_x`, `F_con_y`, `F_con_z` | 通常の接触力 [N]。排土板の面が削られていない地面に押し付けられたときの力（`Terrain.getContactForce`）。通常の前進時は 0 |
| blade_state / AGX API | `T_pen_x`, `T_pen_y`, `T_pen_z` | 貫入抵抗のトルク [N·m]（参考値） |
| blade_state / AGXUnity | `edge_x`, `edge_y`, `edge_z` | 刃先（Cutting Edge）の中点の位置 [m]。`edge_z` が刃先の高さ |
| blade_state / AGXUnity | `blade_width` | 刃先の両端の距離 = 排土板の幅 [m] |
| blade_state / AGXUnity | `blade_alpha_deg` | 排土板の角度 α [deg]。刃先から上端へのベクトルが、水平（車体の後ろ向き）となす角。90° で垂直 |
| blade_state / Unity | `ground_below` | 刃先の真下の地面の高さ [m]（削った後の地面） |
| blade_state / Unity | `ground_ahead` | 刃先から 0.5 m 前方の地面の高さ [m]。開始時の値が `ground_h0` になる |
| blade_state / Unity | `ground_profile_025cm` 〜 `ground_profile_200cm` | 刃先から前方 25 cm、50 cm、…、200 cm（25 cm ごとに 8 点）の地面の高さ [m] |
| blade_state / AGX API | `front_soil_mass` | 排土板の前の土塊の質量 [kg]。`AGX_EXTRA_TERRAIN_API` 有効時のみ（無効時は NaN） |
| blade_state / AGX API | `excavated_volume_step` | そのステップで掘り起こされた体積 [m³]。`AGX_EXTRA_TERRAIN_API` 有効時のみ（無効時は NaN） |
| blade_state / AGX API | `state_compaction_mean` | 刃先から前方 1 m・排土板の幅の範囲の、地表の締固めの程度の平均 [-]。`AGX_GRID_CONTROL` 有効時のみ（無効時は NaN） |
| blade_state / AGX API | `state_compaction_std` | 同じ範囲の締固めの程度の標準偏差 [-]（同上） |
| blade_state / AGX API | `state_compaction_n` | 平均に使った地形のマスの数（無効時は 0） |
| joint_states | `lift_joint_pos`, `lift_joint_vel`, `lift_joint_effort` | 排土板の上げ下げの関節の位置・速度・力。`effort` は排土板を支える力で、反力の上下成分と排土板・腕の重さを含む（実機のリフトシリンダ圧に相当） |
| joint_states | `tilt_joint_pos`, `tilt_joint_vel`, `tilt_joint_effort` | 排土板のチルト（前後の傾き）の関節の位置・速度・力 |
| joint_states | `angle_joint_pos`, `angle_joint_vel`, `angle_joint_effort` | 排土板のアングル（左右の振り）の関節の位置・速度・力。直進時は動かさない |
| joint_states | `right_track_pos`, `right_track_vel`, `right_track_effort` | 右履帯の回転位置・回転速度・駆動力（実機の走行モータのトルクに相当） |
| joint_states | `left_track_pos`, `left_track_vel`, `left_track_effort` | 左履帯の回転位置・回転速度・駆動力 |
| global_pose | `x`, `y`, `z` | 車体の位置 [m] |
| global_pose | `roll`, `pitch`, `yaw` | 車体の姿勢 [rad]。トピックのクォータニオンを `bull_ope` で変換。`pitch` は前後の傾き、`yaw` は向き |
| global_pose | `vx`, `vy`, `vz` | 車体の速度 [m/s] |
| global_pose | `wz` | 車体の旋回の角速度 [rad/s] |
| bull_ope（指令） | `cmd_vx` | 送った前進速度の指令 [m/s]（`/d37pxi_24/cmd_vel` の `linear.x`） |
| bull_ope（指令） | `cmd_wz` | 送った旋回の角速度の指令 [rad/s]（角速度の指令を追加している場合のみ） |
| bull_ope（指令） | `cmd_lift` | 送った `lift_joint` の速度指令（`/d37pxi_24/blade_cmd` の `velocity[0]`） |
| bull_ope（計算） | `ground_h0` | エピソード開始時に 0.5 秒間測った `ground_ahead` の中央値 [m]。切削深さの基準 |
| bull_ope（計算） | `depth` | 切削深さ [m] = `ground_h0` − `edge_z`。正で元の地面より下。平らな地形が前提 |
| bull_ope（計算） | `speed` | 水平面内の速さ [m/s] = √(`vx`² + `vy`²)。後退中も正 |
| bull_ope（計算） | `distance` | 開始位置からの水平の直線距離 [m] |
| bull_ope（計算） | `cut_volume` | 累積切削体積 [m³]。`blade_width` × `depth` × `speed` × Δt を、走行中かつ `depth` > 0 の間だけ積算。前方土量の推定値 |
| bull_ope（計算） | `slip_ratio` | 履帯のスリップ率 [-] = 1 − `speed` ÷（左右の履帯の回転速度の平均 × 起動輪の半径）。`config.py` の `SPROCKET_RADIUS` を設定したときのみ（未設定時は NaN） |
| episode_status / AGX API | `label_c` | 粘着力 c [Pa]（推定の正解） |
| episode_status / AGX API | `label_phi` | 内部摩擦角 φ [deg]（推定の正解） |
| episode_status / AGX API | `label_rho0` | 地山の密度 ρ0 [kg/m³]（推定の正解） |
| episode_status / AGX API | `label_swell` | 膨張率 [-] |
| episode_status / AGX API | `label_E0` | ヤング率 [Pa] |

#### 注意点
- 同じ行の値でも、トピックごとに受信の時刻が異なるため、厳密には同時刻の値ではない（数十ミリ秒以内のずれ）。
- 関節の位置・速度・力の単位は、関節が回転か直動かで決まる（rad / rad/s / N·m、または m / m/s / N）。Unity のモデルで要確認。
- 排土板の前でこぼれた土の粒子からの力は、AGX の仕様上 `F_*` に含まれない（AGX マニュアル 23.19）。
- `leg` と `cmd_wz` は、それぞれの仕組みを追加した場合にのみ存在する。


## 3. 1エピソードの流れ
`episode_runner.py` は、各エピソードを次の順に実行する。括弧内は、Unity の画面右下と CSV の `phase` 列に出る進行状況。

| 順番 | 処理 | 進行状況 | 記録 |
| --- | --- | --- | --- |
| 1 | Unity にエピソードの設定を依頼する（土質の設定、粒子の削除、地形のリセット、地形の加工）。AGX から読み戻した土質が要求と一致するか確認する | setup | しない |
| 2 | `SETTLE_TIME`（2 秒）待つ | setup | しない |
| 3 | 刃先の前方の地面の高さを 0.5 秒間測り、その中央値を切削深さの基準 `ground_h0` とする。車体の位置をスタート位置として記憶する | setup | しない |
| 4 | 停止したまま、排土板を最初の目標深さまで下げる（最大 `LOWER_TIMEOUT` 秒） | lowering | する |
| 5 | エピソードの `operation()` に従って走行する。終了条件（既定は走行距離 10 m か 60 秒）を満たすまで | running | する |
| 6 | 停止し、排土板を地面から `RAISE_HEIGHT`（0.3 m）上げる | raising | する |
| 7 | 記録を終了する | — | — |
| 8 | 排土板を上げたまま後退し、スタート位置へ戻る | returning | しない |
| 9 | 完了 | done | — |

### 排土板の制御
刃先の高さ（`blade_state` の `edge_z`）を目標の高さに近づける P 制御で、`lift_joint` に速度指令を送る。

```
目標の高さ  = ground_h0 − 目標切削深さ
速度指令    = LIFT_SIGN × clip( LIFT_KP × (目標の高さ − edge_z), −LIFT_VMAX, LIFT_VMAX )
```

`LIFT_SIGN` は、`lift_joint` に正の速度を送ったときに排土板が上がるか下がるかで決まる（`test_episode --calibrate` で確認する）。

### エピソードが実行されない場合
| 状況 | 扱い |
| --- | --- |
| AGX から読み戻した土質が要求と一致しない | エラー（そのエピソードは失敗として記録） |
| エピソードが締固めの操作を必要とするが、Unity 側で `AGX_GRID_CONTROL` が無効 | スキップ |
| 地形の加工を要求したが、Unity で適用されなかった | スキップ |

`collect_data` では、1つのエピソードが失敗・スキップしても、次のエピソードに進む。


## 4. エピソード
### 4.1 エピソードの定義（`episodes/episode.py`）
1つのエピソードは、`Episode` クラスを継承したクラスで定義する。

| 要素 | 定義する場所 | 内容 |
| --- | --- | --- |
| 名前 | クラス属性 `name` | コマンドで指定する名前 |
| 説明 | クラス属性 `description` | `--list` で表示される説明 |
| 土質パラメータ | クラス属性 `SOIL_RANGES` | 乱数で決めるときの範囲。既定は c：0〜20000 Pa、φ：25〜45°、ρ：1300〜1900 kg/m³ |
| 操作のパラメータ | `sample_params(rng)` | 切削深さや速度など、エピソードごとに乱数で決める値 |
| 地形データ | `terrain_ops()` | 地形の加工のリスト。既定は空（平らな地形のまま） |
| 操作 | `operation(obs)` | 各時刻の観測（`Observation`）から、車速と目標切削深さ（`Command`）を返す |
| 終了条件 | `is_done(obs)` | 既定は走行距離 `MAX_DISTANCE`（10 m）または時間 `TIMEOUT`（60 秒） |
| 締固め操作の要否 | クラス属性 `REQUIRES_GRID_CONTROL` | True なら Unity 側の `AGX_GRID_CONTROL` が必要 |

関連するデータ構造は次のとおり。

| クラス | 内容 |
| --- | --- |
| `SoilParams` | 土質パラメータ。`cohesion` [Pa]、`friction_angle_deg` [deg]、`density` [kg/m³]、`swell_factor` [−]、`youngs_modulus` [Pa]。後の2つは None なら Unity 側の値のまま |
| `TerrainOp` | 地形の加工。`type`（`compaction_rect` / `loose_layer_rect`）、範囲（`x_start`, `x_end`, `y_min`, `y_max`）、`value`、`depth`。座標は開始時の刃先の中点を原点とし、x が前方、y が左方 [m] |
| `Observation` | `operation()` に渡す観測。`t`（走行開始からの時間）、`distance`、`speed`、`edge_z`、`ground_h0`、`depth`、`blade`（`blade_state` の最新値） |
| `Command` | `operation()` が返す操作。`speed` [m/s] と `depth` [m]（None なら排土板を上げる） |

エピソードのインスタンスは乱数のシード（`seed`）から作られ、同じシードなら同じ土質・同じ操作パラメータになる。

### 4.2 用意しているエピソード
| 名前 | 内容 | 操作のパラメータ（乱数の範囲） | 備考 |
| --- | --- | --- | --- |
| `flat_constant` | 平らな地形を、一定の切削深さ・一定の速度で直進する | 深さ 3〜12 cm、速度 0.3〜1.0 m/s | 基本条件 |
| `flat_step` | 切削深さを一定区間ごとに浅い・深いと切り替えながら直進する | 平均深さ 5〜10 cm、振幅 1〜4 cm、切り替え間隔 1.5〜3.0 m、速度 0.3〜1.0 m/s | 深さへの依存性の違いから c と ρ を分離する狙い |
| `flat_sine` | 切削深さを正弦波状に変えながら直進する | 平均深さ 5〜10 cm、振幅 1〜4 cm、波長 2〜5 m、速度 0.3〜1.0 m/s | 同上（連続的な変化） |
| `compacted_strips` | 地山・踏み固め・緩みの帯が交互に並んだ地形を、一定深さで削る | 深さ 5〜10 cm、速度 0.3〜1.0 m/s、帯の長さ 1.0〜2.5 m、踏み固めの締固めの程度 1.05〜1.25 | 作業中に変化する土の状態を含むデータ用。**要 `AGX_GRID_CONTROL`** |

`compacted_strips` の踏み固めの締固めの程度は、密度が Maximum Density（2000 kg/m³）を超えないよう、`0.98 × 2000 ÷ 密度` 以下に制限している。緩みの帯は `1 ÷ 膨張率`（膨張率を指定しなければ 1.28）。

### 4.3 エピソードの追加
`bull_ope/episodes/specific/` に `Episode` を継承したクラスを書いたファイルを置くと、`collect_data` と `test_episode` が自動で見つける（`episodes/__init__.py` の `available_episodes()`）。名前（`name`）が重複するとエラーになる。

```python
from ..episode import Command, Episode


class MyEpisode(Episode):
    name = "my_episode"
    description = "説明"
    SOIL_RANGES = {"cohesion": (0, 10000), "friction_angle_deg": (30, 40), "density": (1400, 1700)}

    def sample_params(self, rng):          # 操作のパラメータ
        return {"depth": float(rng.uniform(0.05, 0.08)), "speed": 0.5}

    def terrain_ops(self):                 # 地形データ（省略すると平らな地形）
        return []

    def operation(self, obs):              # 操作：観測から車速と目標切削深さを決める
        return Command(speed=self.params["speed"], depth=self.params["depth"])
```

`--symlink-install` でビルドしていれば、ファイルを追加した後に再ビルドは不要。


## 5. 導入
### 5.1 ビルド
```
cd /workspaces/ws-bulldozer/src
# bull_ope/ をここに置く
cd ..
colcon build --symlink-inistall
source ~/.bashrc
```

### 5.2 事前の確認
1. Unity 側で `DataCollection` オブジェクトに `BladeStatePublisher`、`SimEpisodeManager`、`EpisodeStatusOverlay` が付いていること。
2. Unity で Play し、ROS-TCP の接続が確立していること。
3. 次のトピックが届いていること。

        ```
        ros2 topic echo /sim/episode_status --once
        ros2 topic echo /d37pxi_24/blade_state --once
        ```
4. ブルドーザの前方に、10 m 以上の平らな地面があること（切削深さを「元の地面の高さ − 刃先の高さ」で計算するため）。


## 6. 使い方
### 6.1 test_episode：テスト走行と点検
```
ros2 run bull_ope test_episode [エピソード名] [オプション]
```

| オプション | 既定値 | 内容 |
| --- | --- | --- |
| `--list` | — | 使えるエピソードの一覧を表示して終了 |
| `--calibrate` | — | 排土板の上げ下げの向きを確認する（`lift_joint` に +0.05 を2秒送り、刃先の高さの変化を表示） |
| `--seed` | 0 | 乱数のシード（土質・操作のパラメータが決まる） |
| `--c` | 乱数 | 粘着力 [Pa] |
| `--phi` | 乱数 | 内部摩擦角 [deg] |
| `--rho` | 乱数 | 密度 [kg/m³] |
| `--swell` | Unity 側の値 | 膨張率 [−] |
| `--no-record` | — | CSV に記録しない |
| `--out` | `<DATA_DIR>/test` | 保存先 |

`--c`、`--phi`、`--rho` のうち指定しなかったものは、`--seed` から決まる乱数の値になる。

**使用例**

```
# エピソードの一覧
ros2 run bull_ope test_episode --list

# 最初に一度：排土板の向きを確認し、config.py の LIFT_SIGN を合わせる
ros2 run bull_ope test_episode --calibrate

# テスト走行
ros2 run bull_ope test_episode flat_constant --seed 0

# 土質を指定してテスト走行
ros2 run bull_ope test_episode flat_step --c 15000 --phi 30 --rho 1600
```

**走行中の表示**（0.5 秒ごと）

```
t=  3.5s  dist= 1.62m  v=0.48m/s  depth=  7.9cm (目標   8.0)  Fx= -12.35kN  Fz=  20.10kN
```

**終了後の点検**

記録した CSV を読み込み、次を表示する。

- 行数（全体と走行中）、サンプリング周期（平均と最大。50 Hz なら 20 ms）
- 主な列と「未取得（すべて NaN）」「一定」と判定された列の、欠損数・最小・平均・最大
- 走行中の切削深さの平均と標準偏差

統計は走行中（`phase == "running"`）の行で計算する。各特徴量が取れているか、値の大きさが妥当かの確認に使う。

### 6.2 collect_data：データ収集
```
ros2 run bull_ope collect_data [オプション]
```

| オプション | 既定値 | 内容 |
| --- | --- | --- |
| `--list` | — | 使えるエピソードの一覧を表示して終了 |
| `--episodes` | `all` | 実行するエピソード名（スペース区切りで複数。`all` で全種類） |
| `--num` | 5 | エピソードの種類ごとの実行回数 |
| `--seed` | 0 | 実行計画全体の乱数のシード |
| `--sampling` | `lhs` | 土質パラメータの決め方。`lhs`：ラテン超方格法（範囲内に偏りなく配置）、`uniform`：一様乱数 |
| `--out` | `DATA_DIR` | 保存先 |
| `--run-name` | なし | 実行名（保存フォルダ名の末尾に付く） |

**使用例**

```
# 3種類を20回ずつ（計60エピソード）
ros2 run bull_ope collect_data --episodes flat_constant flat_step flat_sine --num 20 --run-name v1

# 全種類を5回ずつ試験的に
ros2 run bull_ope collect_data --num 5 --run-name pilot
```

**動作**

- 実行計画を作った後、エピソードの種類が偏らないよう順番を混ぜる。
- 各エピソードのシードは、`--seed` から決まる乱数で割り当てる。同じ `--seed` と同じオプションなら、同じ計画が再現される。
- エピソードが1つ終わるごとに、経過時間と残り時間の目安をログに出す。
- 1エピソードはおよそ1分（シミュレーションが実時間の約 0.7 倍の場合）。60 エピソードで約1時間が目安。


## 7. 出力データ
### 7.1 保存先の構成
```
<DATA_DIR>/
├ test/                                 test_episode の出力
│  └ 20261009_101500_flat_constant.csv
└ run_20261009_103000_v1/               collect_data の出力（実行ごとに1フォルダ）
   ├ config.json                        実行時のオプションと config.py の設定値
   ├ episodes.jsonl                     エピソードごとの条件・結果（1件終わるごとに追記）
   ├ episodes.csv                       同じ内容の表（全エピソード終了時に作成）
   ├ ep0000_flat_step.csv               時系列データ（1エピソード1ファイル）
   └ ep0001_flat_constant.csv
```

`episodes.jsonl` は途中で止まっても残る。`episodes.csv` はエピソードの種類ごとに異なる列（操作のパラメータ）の和集合で作る。

### 7.2 episodes.csv / episodes.jsonl の列
| 列 | 内容 |
| --- | --- |
| `episode_index`, `file` | エピソード番号と時系列データのファイル名 |
| `episode_name`, `seed` | エピソード名とシード |
| `soil_cohesion`, `soil_friction_angle_deg`, `soil_density`, `soil_swell_factor`, `soil_youngs_modulus` | 要求した土質パラメータ |
| `param_*` | 操作のパラメータ（エピソードの種類による） |
| `n_terrain_ops` | 地形の加工の件数 |
| `ground_h0` | 切削深さの基準とした地面の高さ [m] |
| `label_c`, `label_phi`, `label_rho0`, `label_swell`, `label_E0` | AGX から読み戻した土質パラメータ（ラベル） |
| `run_time`, `run_distance` | 走行時間 [s] と走行距離 [m] |
| `rows`, `path` | 時系列データの行数とパス |
| `status` | `ok`、`skipped: 理由`、`error: 内容` |

### 7.3 時系列データ（ep*.csv）の列
`blade_state` を受信するたび（50 Hz）に1行を書く。他のトピックの値は、その時点の最新値を使う。

| 種類 | 列 | 取得元 |
| --- | --- | --- |
| メタ情報 | `episode_index`, `episode_name`, `seed`, `phase`, `t`（記録開始からの時間 [s]） | — |
| 排土板の状態 | `sim_time`, `F_total_*`, `F_pen_*`, `F_sep_*`, `F_def_*`, `F_con_*`, `T_pen_*`, `edge_*`, `blade_width`, `blade_alpha_deg`, `ground_below`, `ground_ahead`, `ground_profile_025cm`〜`ground_profile_200cm`, `front_soil_mass`, `excavated_volume_step`, `state_compaction_mean/std/n` | `blade_state`（各値の定義は `BladeStatePublisher.md`） |
| 関節 | `lift_joint_pos/vel/effort`, `tilt_joint_*`, `angle_joint_*`, `right_track_*`, `left_track_*` | `joint_states` |
| 車体 | `x`, `y`, `z`, `roll`, `pitch`, `yaw`, `vx`, `vy`, `vz`, `wz` | `global_pose` |
| 指令 | `cmd_vx`, `cmd_lift` | このノードが送った最新の指令 |
| 派生量 | `ground_h0`, `depth`, `speed`, `distance`, `cut_volume`, `slip_ratio` | このノードで計算 |
| ラベル | `label_c`, `label_phi`, `label_rho0`, `label_swell`, `label_E0` | `episode_status`（エピソード中は一定） |

派生量の計算方法は次のとおり。

| 列 | 計算方法 |
| --- | --- |
| `depth` | `ground_h0 − edge_z`（平らな地形が前提） |
| `speed` | `√(vx² + vy²)` |
| `distance` | スタート位置からの水平距離 |
| `cut_volume` | `blade_width × depth × speed × Δt` を、走行中（`phase == "running"`）かつ `depth > 0` の間だけ積算 |
| `slip_ratio` | `1 − speed ÷ (左右の履帯の回転速度の平均 × SPROCKET_RADIUS)`。`SPROCKET_RADIUS` が未設定なら NaN |

学習には `phase == "running"` の行を使う。


## 8. 設定（config.py）
| 名前 | 既定値 | 内容 |
| --- | --- | --- |
| `NS` | `/d37pxi_24` | 機体のトピックの名前空間 |
| `TOPIC_*` | — | 各トピック名 |
| `DATA_DIR` | `/workspaces/ws-bulldozer/src/bull_ope/data` | 保存先。環境変数 `SOIL_DATA_DIR` で上書きできる |
| `LIFT_JOINT` | `lift_joint` | 上げ下げを制御する関節 |
| `LIFT_SIGN` | 1 | 上げ下げの向き。**`test_episode --calibrate` の結果に合わせる** |
| `LIFT_KP` | 1.0 | 刃先の高さの P 制御ゲイン |
| `LIFT_VMAX` | 0.1 | `lift_joint` への速度指令の上限 |
| `CONTROL_PERIOD` | 0.05 s | 制御周期（シミュレーション時刻） |
| `SETUP_TIMEOUT` | 10 s | Unity から設定完了の応答を待つ時間（実時間） |
| `SETTLE_TIME` | 2 s | 地形リセット後に待つ時間 |
| `LOWER_TIMEOUT` / `LOWER_TOLERANCE` | 5 s / 0.01 m | 排土板を下げる時間の上限と、下げ終わりとみなす誤差 |
| `RAISE_HEIGHT` / `RAISE_TIME` | 0.3 m / 3 s | 走行後に排土板を上げる高さと時間 |
| `RETURN_SPEED` / `RETURN_TOLERANCE` / `RETURN_TIMEOUT` | 1.0 m/s / 0.2 m / 120 s | スタート位置へ戻る速さ、戻り終わりとみなす距離、時間の上限 |
| `TRACK_JOINTS` | `right_track`, `left_track` | スリップ率の計算に使う関節 |
| `SPROCKET_RADIUS` | None | 起動輪の半径 [m]。設定するとスリップ率を計算する |


## 9. トラブルシューティング
| 症状 | 確認事項 |
| --- | --- |
| `トピックが届きません: [...]` で止まる（30 秒） | Unity が Play 中か。`DataCollection` のコンポーネントが有効か。`ros2 topic list` に該当のトピックがあるか |
| `Unity から設定完了の応答がありません` | `SimEpisodeManager` が動いているか（`ros2 topic echo /sim/episode_status`）。Unity の Console にエラーがないか |
| `… が反映されていません（要求 …, AGX …）` | Unity 側で土質パラメータの設定に失敗している。Unity の Console と画面右下の表示を確認する |
| 排土板が下がらず上がっていく | `LIFT_SIGN` の向きが逆。`test_episode --calibrate` で確認して `config.py` を直す |
| 排土板が目標の深さで振動する、追従が遅い | `LIFT_KP`、`LIFT_VMAX` を調整する |
| スタート位置に戻らない、戻りすぎる | 後退中に向きがずれている可能性。`RETURN_TOLERANCE` を大きくするか、スタート位置の周辺の地形を確認する |
| 走行中に止まったまま進まない | Unity の Play が一時停止していると、シミュレーション時刻が進まず待ち続ける |
| `ground_ahead が取得できません` | `BladeStatePublisher` が `ground_ahead` を配信しているか |
| `compacted_strips` がスキップされる | Unity 側で `AGX_GRID_CONTROL` が無効（既定）。2.37 で API を確認してから有効にする |


## 10. 注意点
- 切削深さ `depth` は、開始時の前方の地面の高さを基準にしている。平らな地形での実験が前提で、`loose_layer_rect` で地面を盛った場合は基準とずれる。
- 時系列データの各列は、`blade_state` の受信時点での各トピックの最新値（ゼロ次ホールド）であり、厳密に同じ時刻の値ではない。どのトピックも同じシミュレーションから配信されるため、ずれは数十ミリ秒以内。
- 収集データ（`data/` 以下の CSV）は大きくなるので Git の管理対象から外す（`.gitignore` に `data/*` と `!data/.gitkeep`）。


## 11. 動作確認の状況
| 項目 | 状況 |
| --- | --- |
| エピソードの定義（`episodes/`）の単体での動作 | 確認済み（シミュレータなし） |
| `colcon build` | 未確認 |
| `test_episode --calibrate` | 未確認 |
| `test_episode` によるテスト走行と点検 | 未確認 |
| `collect_data` による収集 | 未確認 |