# bull_ope：土質パラメータ推定用データ収集パッケージ（ROS2）

## 1. 概要
| 項目 | 内容 |
| --- | --- |
| パッケージ名 | `bull_ope` |
| 種類 | ROS2 Python パッケージ（ament_python） |
| 対象 | OperaSim-AGX のブルドーザ `d37pxi_24`（シーン `DataCollectionScene`） |
| 対になる Unity 側の機能 | `BladeStatePublisher`, `SimEpisodeManager`, `EpisodeStatusOverlay`, `SceneReloader`（`docs/research/README.md` を参照） |

### 目的
土質パラメータ（粘着力 c、内部摩擦角 φ、密度 ρ など）を推定するニューラルネットワークの学習データを、シミュレーションで自動的に大量に集める。

1回の試行（エピソード）では、Unity のシーンを読み込み直して機体・地形・AGX の状態をすべて初期状態に戻し、土質パラメータを設定し、決められた操作でブルドーザを走らせ、その間の排土板の反力や車体の状態を時系列で記録する。これを、土質と操作を変えながら自動で繰り返す。

### 使えるスクリプト
| コマンド | 用途 |
| --- | --- |
| `ros2 run bull_ope test_episode` | 特定のエピソードを1回テスト走行し、取得したデータを点検する。排土板の向きの較正にも使う |
| `ros2 run bull_ope collect_data` | 複数のエピソードを順に実行し、学習用データを収集する |

検証用の道具（`analysis/` 以下。ROS2 のパッケージとしてはインストールされない）は「9. 検証用の道具」を参照。

### ファイルの構成
```
src/bull_ope/
├ bull_ope/
│  ├ apps/          collect_data.py（収集）、test_episode.py（試走と点検）
│  ├ core/          runner.py（1エピソードの手順、指令の確認、安全の確認）
│  ├ ros/           sim_interface.py（トピックの送受信、シーンの読み込み直し）
│  ├ recording/     recorder.py（CSV への記録）、json_utils.py（JSON に書く前の型の変換）
│  ├ episodes/
│  │  ├ episode.py  エピソードの抽象クラスとデータ構造
│  │  ├ dataset/    学習データ用
│  │  ├ sandbox/    ROS 側で変えられる自由度のサンプル集（ex_*）
│  │  └ validation/
│  │     ├ data_check/  データの確認用（val_*）
│  │     └ stress/      不具合探し用（stress_*）
│  └ config.py      設定値
├ analysis/         検証用の道具（インストールされない）
│  ├ checks/        check_collection.py、check_recording.py
│  ├ scripts/       run_stress_tests.sh、dryrun_stress.py
│  └ reports/       gate1_stress.md（関門ごとの結果）
├ data/             出力データ（Git の管理外。.gitkeep のみ）
└ test/             ament の標準の試験（copyright、flake8、pep257）
```


## 2. データの流れ
### 2.1 通信するトピック
| トピック | 型 | 向き | 内容 |
| --- | --- | --- | --- |
| `/d37pxi_24/blade_state` | `std_msgs/Float64MultiArray` | 受信 | 排土板の反力、刃先位置、地面の高さなど（50 Hz、AGX の各ステップの後）。値の名前は `layout.dim[0].label` にカンマ区切りで入る |
| `/d37pxi_24/joint_states` | `sensor_msgs/JointState` | 受信 | 関節（lift / tilt / angle / 左右の履帯）の位置・速度・力 |
| `/d37pxi_24/global_pose` | `nav_msgs/Odometry` | 受信 | 車体の位置・姿勢。**速度の欄（twist）は OperaSim では 0 のまま**なので、速度は `bull_ope` が位置の変化から計算する |
| `/sim/episode_status` | `std_msgs/String`（JSON） | 受信 | Unity の状態（既定 5 Hz と、指令の処理直後）。AGX から読み戻した土質パラメータ、`request_id`、`boot_id` など |
| `/d37pxi_24/cmd_vel` | `geometry_msgs/Twist` | 送信 | 前進・後退の速度（`linear.x`）と旋回の角速度（`angular.z`） |
| `/d37pxi_24/blade_cmd` | `com3_msgs/JointCmd` | 送信 | 排土板の速度指令（`control_type = 1`）。OperaSim は `joint_name` を見ずに配列の順番 [0]=lift、[1]=tilt、[2]=angle で読むため、必ず3要素で送る（tilt と angle は 0） |
| `/sim/episode_cmd` | `std_msgs/String`（JSON） | 送信 | Unity への指令（下の表） |
| `/clock` | `rosgraph_msgs/Clock` | 受信 | シミュレーション時刻（ノードは `use_sim_time = True` で動く） |

`/sim/episode_cmd` で送る指令は次の3種類。

| `command` | 内容 | 完了の確かめ方 |
| --- | --- | --- |
| `reload` | シーンを読み込み直す（`SceneReloader`） | `/sim/episode_status` の `boot_id` が変わる（シーンが立ち上がるたびに新しい番号になる） |
| `setup` | 土質の設定 → 粒子の削除 → 地形の高さ（と締固め）のリセット → 地形の加工 | `/sim/episode_status` の `request_id` が送った値と一致する。失敗した場合も同じ `request_id` で `error` に内容が入る |
| `phase` | 画面右下の表示用の進行状況だけを更新する | なし |

`setup` は、届いたことが確認できるまで1秒ごとに再送する（Unity 側は同じ `request_id` の再送を無視する）。

### 2.2 収集データ
`bull_ope` が出力する時系列データ（`data/test/*.csv`、`<出力先>/run_*/ep*.csv`）の各カラムの収集元と内容。1行 = `/d37pxi_24/blade_state` を1回受信した時点（50 Hz）。他のトピックの値は、その時点で受信済みの最新値を使う（ゼロ次ホールド）。

記録するのはエピソードの「排土板を下げる → 走る → 上げる」の間（`phase` が `lowering` / `running` / `raising`）だけで、学習には `phase == "running"` の行を使う。

#### 収集元の凡例
| 収集元 | 意味 |
| --- | --- |
| bull_ope（エピソード） | 実行中のエピソードの情報。`bull_ope` 内で決まる |
| bull_ope（計算） | `bull_ope`（`recorder.py`、`sim_interface.py`）が他の値から計算する |
| bull_ope（指令） | `bull_ope`（`runner.py`、`sim_interface.py`）が決めた・最後に送った指令の値 |
| blade_state / AGX API | 自作の `BladeStatePublisher.cs` が AGX Dynamics の API で取得し、`/d37pxi_24/blade_state` で配信 |
| blade_state / AGXUnity | 同スクリプトが AGXUnity の Shovel の設定（刃先・上端の位置）から計算して配信 |
| blade_state / Unity | 同スクリプトが Unity の機能（`Terrain.SampleHeight` など）で取得して配信 |
| joint_states | OperaSim 本体が `/d37pxi_24/joint_states` で配信 |
| global_pose | OperaSim 本体が `/d37pxi_24/global_pose` で配信 |
| episode_status / AGX API | 自作の `SimEpisodeManager.cs` が AGX の地形材料から読み戻し、`/sim/episode_status` で配信。エピソード開始時に1回だけ受け取り、全行に同じ値を書く |

#### 座標系の約束
- **力・トルク（`F_*`、`T_*`）：** 車体（`base_link`）に固定した座標。x：前方、y：左方、z：上方。4つの内訳はいずれも「排土板が土から受ける力」の向きにそろえてある。
- **位置（`edge_*`、`x`、`y`、`z`）・高さ（`ground_*`）：** ワールド座標。高さは Unity のワールド y と同じ値。

#### カラム一覧（CSV の列の順）
| 収集元 | カラム名 | 内容 |
| --- | --- | --- |
| bull_ope（エピソード） | `episode_index` | エピソード番号（`test_episode` では常に 0） |
| bull_ope（エピソード） | `episode_name` | エピソード名（例：`val_constant_depth`） |
| bull_ope（エピソード） | `seed` | エピソードの乱数のシード |
| bull_ope（エピソード） | `phase` | 進行状況。`lowering`（排土板を下げる）、`running`（走行）、`raising`（排土板を上げる） |
| bull_ope（指令） | `target_depth` | その時点の目標切削深さ [m]（`DEPTH_MIN`〜`DEPTH_MAX` に制限した後の値）。排土板を上げるときは −`RAISE_HEIGHT` |
| bull_ope（指令） | `depth_clipped` | エピソードが返した目標深さを制限したか（1：制限した、0：そのまま） |
| bull_ope（計算） | `t` | 記録開始からの経過時間 [s]（`sim_time` − 最初の `sim_time`） |
| blade_state / Unity | `sim_time` | シミュレーション時刻 [s]（Unity の `Time.fixedTimeAsDouble`） |
| blade_state / AGX API | `F_total_x`, `F_total_y`, `F_total_z` | 排土板が土から受ける力の合力 [N]（下の4つの力の和）。土を押して前進中は `F_total_x` が負 |
| blade_state / AGX API | `F_pen_x`, `F_pen_y`, `F_pen_z` | 貫入抵抗 [N]。刃先が削られていない地面に食い込むときの抵抗（`Terrain.getPenetrationForce`） |
| blade_state / AGX API | `F_sep_x`, `F_sep_y`, `F_sep_z` | 分離抵抗 [N]。前方へ切削・押土するとき、排土板の前の土塊から受ける力（`Terrain.getSeparationContactForce`）。前進時に支配的 |
| blade_state / AGX API | `F_def_x`, `F_def_y`, `F_def_z` | 変形抵抗 [N]。後退や横方向など、切削方向以外に土を押しのけるときの力（`Terrain.getDeformationContactForce`） |
| blade_state / AGX API | `F_con_x`, `F_con_y`, `F_con_z` | 通常の接触力 [N]。排土板の面が削られていない地面に押し付けられたときの力（`Terrain.getContactForce`） |
| blade_state / AGX API | `T_pen_x`, `T_pen_y`, `T_pen_z` | 貫入抵抗のトルク [N·m]（参考値） |
| blade_state / AGXUnity | `edge_x`, `edge_y`, `edge_z` | 刃先（Cutting Edge）の中点の位置 [m]。`edge_z` が刃先の高さ |
| blade_state / AGXUnity | `blade_width` | 刃先の両端の距離 = 排土板の幅 [m]（d37pxi_24 では 2.96 m） |
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
| bull_ope（計算） | `vx`, `vy`, `vz` | 車体の速度 [m/s]。`global_pose` の位置を、`VEL_WINDOW`（0.1 s）ほど前の値と比べて計算する |
| bull_ope（計算） | `wz` | 車体の旋回の角速度 [rad/s]。向き（`yaw`）の変化から同様に計算する（角度の折り返しを考慮） |
| bull_ope（計算） | `v_forward` | 車体の前方向の速度 [m/s]。前進で正、後退で負 |
| bull_ope（計算） | `v_lateral` | 車体の左方向の速度 [m/s] |
| global_pose | `pose_stamp` | `global_pose` のヘッダの時刻 [s]。位置が更新された時刻（`sim_time` とは一致しないことがある） |
| bull_ope（指令） | `cmd_vx` | 送った前進速度の指令 [m/s]（`/d37pxi_24/cmd_vel` の `linear.x`） |
| bull_ope（指令） | `cmd_wz` | 送った旋回の角速度の指令 [rad/s]（`/d37pxi_24/cmd_vel` の `angular.z`） |
| bull_ope（指令） | `cmd_lift` | 送った `lift_joint` の速度指令（`/d37pxi_24/blade_cmd` の `velocity[0]`） |
| bull_ope（計算） | `ground_h0` | エピソード開始時に 0.5 秒間測った `ground_ahead` の中央値 [m]。切削深さの基準 |
| bull_ope（計算） | `depth` | 切削深さ [m] = `ground_h0` − `edge_z`。正で元の地面より下。平らな地形が前提 |
| bull_ope（計算） | `speed` | 水平面内の速さ [m/s] = √(`vx`² + `vy`²)。向きを持たない（後退中も正） |
| bull_ope（計算） | `distance` | 開始位置からの水平の直線距離 [m] |
| bull_ope（計算） | `cut_volume` | 累積切削体積 [m³]。`blade_width` × `depth` × max(`v_forward`, 0) × Δt を、走行中かつ `depth` > 0 の間だけ積算（後退中の切削は数えない）。前方土量の推定値 |
| bull_ope（計算） | `slip_ratio` | 履帯のスリップ率 [-] = 1 − `speed` ÷（左右の履帯の回転速度の平均 × 起動輪の半径）。`config.py` の `SPROCKET_RADIUS` を設定したときのみ（未設定時は NaN） |
| episode_status / AGX API | `label_c` | 粘着力 c [Pa]（推定の正解） |
| episode_status / AGX API | `label_phi` | 内部摩擦角 φ [deg]（推定の正解） |
| episode_status / AGX API | `label_rho0` | 地山の密度 ρ0 [kg/m³]（推定の正解） |
| episode_status / AGX API | `label_swell` | 膨張率 [-] |
| episode_status / AGX API | `label_E0` | ヤング率 [Pa] |

#### 注意点
- 同じ行の値でも、トピックごとに受信の時刻が異なるため、厳密には同時刻の値ではない（数十ミリ秒以内のずれ）。時間のずれは関門4で確かめる。
- 関節の位置・速度・力の単位は、関節が回転か直動かで決まる（rad / rad/s / N·m、または m / m/s / N）。Unity のモデルで要確認。
- 排土板の前でこぼれた土の粒子からの力は、AGX の仕様上 `F_*` に含まれない（AGX マニュアル 23.19）。
- `F_def_*` と `F_con_*` は、これまでの試験（直進・旋回・後退を含む）では常に 0。使われていないのかは関門3で確かめる。
- 記録の最初（下げる区間の始め）の `depth` は、どのエピソードでも約 13 cm になる。シーンを読み込み直した直後の排土板の位置が、`ground_h0` より低いため。下げる区間は学習に使わないので影響はないが、深さ 0 の基準は関門3で確かめる。


## 3. 1エピソードの流れ
`core/runner.py` の `EpisodeRunner.run()` は、各エピソードを次の順に実行する。括弧内は、Unity の画面右下と CSV の `phase` 列に出る進行状況。

| 順番 | 処理 | 進行状況 | 記録 |
| --- | --- | --- | --- |
| 0 | 実行できる条件か確かめる（締固めの操作が必要なエピソードで、Unity 側の `AGX_GRID_CONTROL` が無効ならスキップ） | — | しない |
| 1 | Unity にシーンの読み込み直しを依頼し、`boot_id` が変わって新しいシーンのトピックがそろうまで待つ（最大 `RELOAD_TIMEOUT`）。その後 `RELOAD_SETTLE`（1 秒）待つ | reloading | しない |
| 2 | Unity にエピソードの設定を依頼する（土質の設定、粒子の削除、地形のリセット、地形の加工）。AGX から読み戻した土質が要求と一致するか確認する | setup | しない |
| 3 | `SETTLE_TIME`（2 秒）待つ（機体が着地して落ち着くのを待つ） | setup | しない |
| 4 | 刃先の前方の地面の高さを 0.5 秒間測り、その中央値を切削深さの基準 `ground_h0` とする。車体の位置・向き・傾きを、開始時の基準として記憶する | setup | しない |
| 5 | 停止したまま、排土板を最初の目標深さまで下げる（最大 `LOWER_TIMEOUT` 秒、誤差 `LOWER_TOLERANCE` 以内で終了） | lowering | する |
| 6 | エピソードの `operation()` に従って走行する。終了条件（既定は走行距離 10 m か 60 秒）を満たすまで | running | する |
| 7 | 停止し、排土板を地面から `RAISE_HEIGHT`（0.3 m）の高さまで上げる（`RAISE_TIME` 秒） | raising | する |
| 8 | 記録を終了する（エラーで止まった場合も必ず実行する） | — | — |
| 9 | 完了 | done | — |

エピソードの最後に開始位置へ戻ることはしない。次のエピソードの最初にシーンを読み込み直すので、機体・地形・AGX の内部状態はすべて初期状態に戻る。

### 3.1 排土板の制御
刃先の高さ（`blade_state` の `edge_z`）を目標の高さに近づける P 制御で、`lift_joint` に速度指令を送る。

```
目標の高さ  = ground_h0 − 目標切削深さ
速度指令    = LIFT_SIGN × clip( LIFT_KP × (目標の高さ − edge_z), −LIFT_VMAX, LIFT_VMAX )
```

`LIFT_SIGN` は、`lift_joint` に正の速度を送ったときに排土板が上がるか下がるかで決まる（`test_episode --calibrate` で確認する。d37pxi_24 では −1）。

### 3.2 指令の確認
エピソードの `operation()` が返した値は、送る前に毎回確かめる。

| 確かめること | 不正なとき |
| --- | --- |
| `Command` を返したか（`None` などでないか） | `InvalidCommand` で止める（指令は送らない） |
| `speed`、`yaw_rate` が有限の数か | 同上 |
| `depth` が有限の数か、`None`（排土板を上げる）か | 同上。NaN・無限大は送らない |
| `depth` が `DEPTH_MIN`〜`DEPTH_MAX` の範囲か | 範囲に収めて実行し、`depth_clipped = 1` を記録する |

`sim_interface.py` でも、`cmd_vel` と `blade_cmd` を送る直前に、値が有限でなければ例外にする（二重の確認）。

### 3.3 安全の確認
制御周期（0.05 秒）ごとに、開始時の基準と比べて次を確かめる。超えたら機体を止めて `SafetyStop` で止める。

| 確かめること | 上限 |
| --- | --- |
| 開始位置からの距離 | `SAFE_RADIUS`（20 m） |
| ピッチ・ロールの変化 | `MAX_TILT_DEG`（20°） |
| 実際の切削深さ（`ground_h0` − `edge_z`） | `MAX_ACTUAL_DEPTH`（0.35 m） |

排土板を上げる区間（raising）では、深さの上限で止めない（深く入っていても上げ続けるほうが安全なため）。代わりに、上限を超えた場合の最大値を `raise_depth_over_max` として `episodes.jsonl` に記録する。走り終えて急に止まるときに機体が前に倒れ込み、刃先が一時的に深くなることがあるため。

### 3.4 エピソードが失敗・スキップした場合
| 状況 | 扱い |
| --- | --- |
| Unity 側で `AGX_GRID_CONTROL` が無効なのに、締固めの操作が必要なエピソード | スキップ |
| 地形の加工を要求したが、Unity で適用されなかった | スキップ |
| AGX から読み戻した土質が要求と一致しない | エラー |
| シーンの読み込み直しが `RELOAD_TIMEOUT` 以内に終わらない | エラー |
| `setup` の応答が `SETUP_TIMEOUT` 以内に返らない | エラー（Unity 側の失敗なら、`Unity でエラー: 内容` になる） |
| 指令が不正（3.2）、安全の上限を超えた（3.3）、エピソードのコードで例外 | エラー |

`collect_data` では、1つのエピソードが失敗・スキップしても機体を止めて次のエピソードに進む。次のエピソードはシーンの読み込み直しから始まるので、失敗の影響は残らない（関門1の段階Bで確認）。


## 4. エピソード
### 4.1 エピソードの定義（`episodes/episode.py`）
1つのエピソードは、`Episode` クラスを継承したクラスで定義する。

| 要素 | 定義する場所 | 内容 |
| --- | --- | --- |
| 名前 | クラス属性 `name` | コマンドで指定する名前 |
| 説明 | クラス属性 `description` | `--list` で表示される説明 |
| 土質パラメータ | クラス属性 `SOIL_RANGES` | 乱数で決めるときの範囲（フィールド名 → (下限, 上限)）。既定は c：0〜20000 Pa、φ：25〜45°、ρ：1300〜1900 kg/m³。下限 = 上限にすれば固定値になる |
| 操作のパラメータ | `sample_params(rng)` | 切削深さや速度など、エピソードごとに乱数で決める値。`episodes.jsonl` に `param_*` として記録される |
| 地形データ | `terrain_ops()` | 地形の加工のリスト。既定は空（平らな地形のまま） |
| 操作 | `operation(obs)` | 各時刻の観測（`Observation`）から、車速・目標切削深さ・旋回の角速度（`Command`）を返す |
| 終了条件 | `is_done(obs)` | 既定は走行距離 `MAX_DISTANCE`（10 m）または時間 `TIMEOUT`（60 秒） |
| 締固め操作の要否 | クラス属性 `REQUIRES_GRID_CONTROL` | True なら Unity 側の `AGX_GRID_CONTROL` が必要 |

関連するデータ構造は次のとおり。

| クラス | 内容 |
| --- | --- |
| `SoilParams` | 土質パラメータ。`cohesion` [Pa]、`friction_angle_deg` [deg]、`density` [kg/m³]、`swell_factor` [−]、`youngs_modulus` [Pa]。後の2つは None なら Unity 側の値のまま |
| `TerrainOp` | 地形の加工。`type`（`compaction_rect` / `loose_layer_rect`）、範囲（`x_start`, `x_end`, `y_min`, `y_max`）、`value`、`depth`。座標は開始時の刃先の中点を原点とし、x が前方、y が左方 [m] |
| `Observation` | `operation()` に渡す観測。`t`（走行開始からの時間 [s]）、`distance`（開始位置からの距離 [m]）、`speed`（前方向の速度 [m/s]。後退で負）、`edge_z`、`ground_h0`、`depth`、`blade`（`blade_state` の最新値） |
| `Command` | `operation()` が返す操作。`speed` [m/s]（負で後退）、`depth` [m]（None なら排土板を上げる）、`yaw_rate` [rad/s]（正で左旋回、既定 0） |

エピソードのインスタンスは乱数のシード（`seed`）から作られ、同じシードなら同じ土質・同じ操作パラメータになる。

操作のパラメータに NumPy の型（`np.int64`、配列など）を入れても構わない。`episodes.jsonl` に書く直前に `recording/json_utils.py` の `to_jsonable()` で普通の型に変換する（NaN・無限大は `null` になる）。

### 4.2 エピソードのグループ
エピソードは、置いたフォルダでグループ分けされる（`episodes/__init__.py` の `episode_group()`）。

| フォルダ | 名前の付け方 | 用途 |
| --- | --- | --- |
| `dataset/` | 自由 | 学習データ用 |
| `sandbox/` | `ex_*` | ROS 側で変えられる自由度（動き・土質・地形）を一通り示すサンプル集。`test_episode` で試す |
| `validation/data_check/` | `val_*` | データの確認用（関門2〜6）。土質は OperaSim の `dirt_1` の値に固定 |
| `validation/stress/` | `stress_*` | 不具合探し用（関門1）。学習データには使わない |

`validation/` のエピソードは `validation/base.py` の `ValidationEpisode` を継承する。土質を c = 2100 Pa、φ = 39.98°、ρ = 1474 kg/m³（`dirt_1`）に固定し、クラス属性 `PARAM_NAMES` に書いた名前の値を、乱数を使わずにそのまま記録用のパラメータにする。

### 4.3 用意しているエピソード
**dataset（学習データ用）**

| 名前 | 内容 | 操作のパラメータ（乱数の範囲） | 備考 |
| --- | --- | --- | --- |
| `flat_constant` | 平らな地形を、一定の切削深さ・一定の速度で直進する | 深さ 3〜12 cm、速度 0.3〜1.0 m/s | 基本条件 |
| `compacted_strips` | 地山・踏み固め・緩みの帯が交互に並んだ地形を、一定深さで削る | 深さ 5〜10 cm、速度 0.3〜1.0 m/s、帯の長さ 1.0〜2.5 m、踏み固めの締固めの程度 1.05〜1.25 | 作業中に変化する土の状態を含むデータ用。**要 `AGX_GRID_CONTROL`** |
| `shuttle_3x5m` | 5 m の区間を、前進して削り・排土板を上げて後退で戻る、を3往復する | 深さ 5 cm、速度 0.5 m/s（固定） | 土質は `dirt_1` に固定。走行時間の上限 300 秒 |

`compacted_strips` の踏み固めの締固めの程度は、密度が Maximum Density（2000 kg/m³）を超えないよう、`0.98 × 2000 ÷ 密度` 以下に制限している。緩みの帯は `1 ÷ 膨張率`（膨張率を指定しなければ 1.28）。

**sandbox（サンプル集）**

| 名前 | 内容 |
| --- | --- |
| `ex_speed_profile` | 0.2→1.2 m/s に加速し、一定で走った後、0.2 m/s まで減速しながら削る |
| `ex_stop_and_go` | 3 秒前進・2 秒停止を 20 秒間くり返しながら削る（時間で制御） |
| `ex_blade_profile` | 排土板の高さを 削る→なでる→浮かせる→上げる→削る と 2 m ごとに変える |
| `ex_load_control` | 前方の反力が 15 kN になるよう、切削深さを自動で調整しながら削る |
| `ex_back_blading` | 排土板を上げて 6 m 前進し、排土板を地面に当てて後退で戻る |
| `ex_turning` | S 字に曲がりながら 12 秒削り、同じ軌跡を後退でたどって戻る |
| `ex_soil_all_params` | c・φ・ρ・膨張率・ヤング率の5つを固定値で指定して 10 m 削る |
| `ex_soil_random_all` | 5つの土質パラメータをすべて範囲内の乱数で決めて 10 m 削る |
| `ex_terrain_compaction_map` | 前後 2 m × 左右 2 分割のパッチごとに締固めの程度を変えて削る（要 `AGX_GRID_CONTROL`） |
| `ex_terrain_loose_pile` | 前方 2〜4 m に厚さ 50 cm の緩い土の山を積み、地面の高さで押し広げる（要 `AGX_GRID_CONTROL`） |

**validation/data_check（データの確認用）**

| 名前 | 内容 | 主に確かめること |
| --- | --- | --- |
| `val_static` | 排土板を上げたまま静止する（10 秒） | 静止時の値のばらつき、力が 0 か |
| `val_air_run` | 排土板を上げたまま 0.5 m/s で 10 m 直進する | 走行中も力が 0 のままか、速度の追従、距離の整合性 |
| `val_constant_depth` | 深さ 6 cm・速度 0.5 m/s で 10 m 削る | 力の符号、深さの追従、再現性 |
| `val_depth_step` | 深さを 3→6→9 cm と 3 m ごとに変えて削る | 深さと力の関係、深さが変わってからの時間のずれ |

**validation/stress（不具合探し用）**

| 名前 | 内容 | 想定の結果 |
| --- | --- | --- |
| `stress_instant_done` | 走行を始めた瞬間に終了する | ok（走行 0 行） |
| `stress_error_midrun` | 走行中の 3 秒後にエピソードのコードで例外を起こす | error |
| `stress_none_command` | 走行の 2 秒後から `operation()` が None を返す | error（`InvalidCommand`） |
| `stress_nan_depth` | 走行の 2 秒後から目標深さに NaN を返す | error（`InvalidCommand`） |
| `stress_runaway` | フィールドの外へ向かって 100 m 走ろうとする | error（`SafetyStop`、`SAFE_RADIUS`） |
| `stress_depth_limits` | 排土板の高さの制限を超える目標深さ（0.5 m、−1.0 m）を与える | ok、または傾きで `SafetyStop`（実行ごとにばらつく） |
| `stress_spin` | 排土板を地面に当てたまま、その場で 15 秒旋回する | ok |
| `stress_heavy_push` | 粘着力 30 kPa・密度 1950 kg/m³ の土を 20 cm の深さで押す | 深さの上限で `SafetyStop` |
| `stress_numpy_params` | `sample_params` が NumPy の整数・配列を返す | ok（記録が止まらない） |
| `stress_soil_extremes` | 土質を極端な範囲（c 0〜40 kPa、φ 15〜50°、ρ 1100〜1980 など）で決めて削る | ok（ラベルの不一致 0） |
| `stress_short` | 2 秒だけ走る（読み込み直しを繰り返す耐久試験用） | ok |

### 4.4 エピソードの追加
`bull_ope/episodes/` の下のフォルダ（学習データ用なら `dataset/`）に、`Episode` を継承したクラスを書いたファイルを置くと、`collect_data` と `test_episode` が自動で見つける（`episodes/__init__.py` の `available_episodes()`）。名前（`name`）が重複するとエラーになる。

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

`operation()` は必ず `Command` を返す（条件分岐の書き忘れで `None` を返すと `InvalidCommand` になる）。排土板を上げたいときは `depth=None` にする。

`--symlink-install` でビルドしていれば、ファイルを追加した後に再ビルドは不要。


## 5. 導入
### 5.1 ビルド
```
cd /workspaces/ws-bulldozer
colcon build --packages-select bull_ope --symlink-install
source install/setup.bash
```

`config.py` を変えたときも、`--symlink-install` でビルドしていれば再ビルドは不要。新しいファイルを `bull_ope/` の下に追加したときは、念のため再ビルドする。

### 5.2 事前の確認
1. Unity 側で `DataCollection` オブジェクトに `BladeStatePublisher`、`SimEpisodeManager`、`EpisodeStatusOverlay`、`SceneReloader` が付いていること。
2. コンテナ内で ROS-TCP-Endpoint を起動していること（`ros2 run ros_tcp_endpoint default_server_endpoint`）。
3. Unity で `DataCollectionScene` を開いて Play し、ROS-TCP の接続が確立していること。
4. 次のトピックが届いていること。

    ```
    ros2 topic echo /sim/episode_status --once
    ros2 topic echo /d37pxi_24/blade_state --once
    ```
5. `config.py` の `SAFE_RADIUS` が設定されていること（`None` だと、開始位置からの距離で止まらない）。
6. ブルドーザの前方に、10 m 以上の平らな地面があること（切削深さを「元の地面の高さ − 刃先の高さ」で計算するため）。


## 6. 使い方
### 6.1 test_episode：テスト走行と点検
```
ros2 run bull_ope test_episode [エピソード名] [オプション]
```

| オプション | 既定値 | 内容 |
| --- | --- | --- |
| `--list` | — | 使えるエピソードの一覧を表示して終了 |
| `--calibrate` | — | 排土板の上げ下げの向きを確認する（`lift_joint` に +0.05 を2秒送り、刃先の高さの変化と、`LIFT_SIGN` に設定すべき値を表示） |
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
ros2 run bull_ope test_episode flat_constant --c 15000 --phi 30 --rho 1600
```

**走行中の表示**（0.5 秒ごと）

```
t=  3.5s  dist= 1.62m  v=0.48m/s  depth=  7.9cm (目標   8.0)  Fx= -12.35kN  Fz=  20.10kN
```

**終了後の点検**

正常に終了した場合、記録した CSV を読み込み、次を表示する。

- 行数（全体と走行中）、サンプリング周期（平均と最大。50 Hz なら 20 ms）
- 主な列と「未取得（すべて NaN）」「一定」と判定された列の、欠損数・最小・平均・最大
- 走行中の切削深さの平均と標準偏差

統計は走行中（`phase == "running"`）の行で計算する。各特徴量が取れているか、値の大きさが妥当かの確認に使う。

エラー（`InvalidCommand`、`SafetyStop`、エピソードの例外など）で止まった場合は、トレースバックを表示して終了コード 1 で終わり、点検の表示は出ない。CSV はそこまでの分が保存されるので、`analysis/checks/check_recording.py` で点検できる。

### 6.2 collect_data：データ収集
```
ros2 run bull_ope collect_data [オプション]
```

| オプション | 既定値 | 内容 |
| --- | --- | --- |
| `--list` | — | 使えるエピソードの一覧を表示して終了 |
| `--episodes` | `all` | 実行するエピソード名（スペース区切りで複数。`all` で全種類。sandbox・validation も含まれるので、通常は名前を指定する） |
| `--num` | 5 | エピソードの種類ごとの実行回数 |
| `--seed` | 0 | 実行計画全体の乱数のシード |
| `--sampling` | `lhs` | 土質パラメータの決め方。`lhs`：ラテン超方格法（範囲内に偏りなく配置）、`uniform`：各エピソードのシードからの一様乱数 |
| `--out` | `DATA_DIR` | 保存先 |
| `--run-name` | なし | 実行名（保存フォルダ名の末尾に付く） |

**使用例**

```
# 学習用の2種類を20回ずつ（計40エピソード）
ros2 run bull_ope collect_data --episodes flat_constant compacted_strips --num 20 --run-name v1

# 試験的に5回ずつ、別のフォルダに
ros2 run bull_ope collect_data --episodes flat_constant --num 5 --run-name pilot \
    --out src/bull_ope/data/pilot
```

**動作**

- 実行計画を作った後、エピソードの種類が偏らないよう順番を混ぜる。
- 各エピソードのシードは、`--seed` から決まる乱数で割り当てる。同じ `--seed` と同じオプションなら、同じ計画が再現される。
- エピソードが1つ終わるごとに、`episodes.jsonl` に1行追記し、経過時間と残り時間の目安をログに出す。
- 1エピソードには、走行時間に加えて約 10 秒（読み込み直し 約 1.2 秒、待ち時間、地面の高さの計測、排土板の上げ下げ）かかる。シミュレーションはほぼ実時間で進む（関門1の段階Dで、2 秒だけ走るエピソードが実時間 12〜13 秒）。
- 1つのエピソードが失敗・スキップしても、次のエピソードに進む（3.4）。


## 7. 出力データ
### 7.1 保存先の構成
```
<DATA_DIR>/
├ test/                                 test_episode の出力
│  └ 20261009_101500_flat_constant.csv
└ run_20261009_103000_v1/               collect_data の出力（実行ごとに1フォルダ）
   ├ config.json                        実行時のオプションと config.py の設定値
   ├ episodes.jsonl                     エピソードごとの条件・結果（1件終わるごとに追記、UTF-8）
   ├ episodes.csv                       同じ内容の表（全エピソード終了時に作成）
   ├ ep0000_flat_constant.csv           時系列データ（1エピソード1ファイル）
   └ ep0001_compacted_strips.csv
```

`episodes.jsonl` は途中で止まっても残る。`episodes.csv` はエピソードの種類ごとに異なる列（操作のパラメータ）の和集合で作る。

### 7.2 episodes.csv / episodes.jsonl の列
| 列 | 内容 |
| --- | --- |
| `episode_index`, `file` | エピソード番号と時系列データのファイル名 |
| `episode_name`, `seed` | エピソード名とシード |
| `soil_cohesion`, `soil_friction_angle_deg`, `soil_density`, `soil_swell_factor`, `soil_youngs_modulus` | 要求した土質パラメータ（指定しなかったものは `null`） |
| `param_*` | 操作のパラメータ（エピソードの種類による） |
| `n_terrain_ops` | 地形の加工の件数 |
| `ground_h0` | 切削深さの基準とした地面の高さ [m] |
| `label_c`, `label_phi`, `label_rho0`, `label_swell`, `label_E0` | AGX から読み戻した土質パラメータ（ラベル） |
| `start_x`, `start_y`, `start_yaw_deg` | 開始時の車体の位置 [m] と向き [deg]（毎回同じ状態から始まっているかの確認用） |
| `run_time`, `run_distance` | 走行時間 [s] と走行距離 [m] |
| `raise_depth_over_max` | 上げる区間で実際の深さが `MAX_ACTUAL_DEPTH` を超えた場合の最大値 [m]。超えなければ `null` |
| `rows`, `path` | 時系列データの行数とパス |
| `status` | `ok`、`skipped: 理由`、`error: 内容` |

エラーやスキップで止まったエピソードは、止まった時点までに決まっている列（エピソードの情報と `status`）だけが入る。記録に失敗した場合は、最小限の情報と `status: record_error: 内容` を書き、収集は止めない。

### 7.3 時系列データ（ep*.csv）の列
列の順と各列の内容は「2.2 収集データ」のカラム一覧のとおり。種類ごとにまとめると次のようになる。

| 種類 | 列 | 取得元 |
| --- | --- | --- |
| メタ情報 | `episode_index`, `episode_name`, `seed`, `phase`, `target_depth`, `depth_clipped`, `t` | bull_ope |
| 排土板の状態 | `sim_time`, `F_total_*`, `F_pen_*`, `F_sep_*`, `F_def_*`, `F_con_*`, `T_pen_*`, `edge_*`, `blade_width`, `blade_alpha_deg`, `ground_below`, `ground_ahead`, `ground_profile_025cm`〜`ground_profile_200cm`, `front_soil_mass`, `excavated_volume_step`, `state_compaction_mean/std/n` | `blade_state` |
| 関節 | `lift_joint_pos/vel/effort`, `tilt_joint_*`, `angle_joint_*`, `right_track_*`, `left_track_*` | `joint_states` |
| 車体 | `x`, `y`, `z`, `roll`, `pitch`, `yaw`, `vx`, `vy`, `vz`, `wz`, `v_forward`, `v_lateral`, `pose_stamp` | `global_pose`（速度は bull_ope が計算） |
| 指令 | `cmd_vx`, `cmd_wz`, `cmd_lift` | このノードが送った最新の指令 |
| 派生量 | `ground_h0`, `depth`, `speed`, `distance`, `cut_volume`, `slip_ratio` | このノードで計算 |
| ラベル | `label_c`, `label_phi`, `label_rho0`, `label_swell`, `label_E0` | `episode_status`（エピソード中は一定） |

学習には `phase == "running"` の行を使う。


## 8. 設定（config.py）
| 名前 | 既定値 | 内容 |
| --- | --- | --- |
| `NS` | `/d37pxi_24` | 機体のトピックの名前空間 |
| `TOPIC_*` | — | 各トピック名 |
| `DATA_DIR` | `/workspaces/ws-bulldozer/src/bull_ope/data` | 保存先。環境変数 `SOIL_DATA_DIR` で上書きできる |
| `LIFT_JOINT` | `lift_joint` | 上げ下げを制御する関節 |
| `LIFT_SIGN` | −1 | 上げ下げの向き。**`test_episode --calibrate` の結果に合わせる** |
| `LIFT_KP` | 1.0 | 刃先の高さの P 制御ゲイン |
| `LIFT_VMAX` | 0.1 | `lift_joint` への速度指令の上限 |
| `CONTROL_PERIOD` | 0.05 s | 制御周期（シミュレーション時刻） |
| `VEL_WINDOW` | 0.1 s | 位置の変化から速度を計算するときの時間幅（大きいほど揺れが少なく、遅れが大きい） |
| `SETUP_TIMEOUT` | 30 s | Unity から `setup` の完了の応答を待つ時間（実時間） |
| `SETTLE_TIME` | 2 s | 地形リセット後に待つ時間 |
| `LOWER_TIMEOUT` / `LOWER_TOLERANCE` | 5 s / 0.01 m | 排土板を下げる時間の上限と、下げ終わりとみなす誤差 |
| `RAISE_HEIGHT` / `RAISE_TIME` | 0.3 m / 3 s | 走行後に排土板を上げる高さ（元の地面から）と時間 |
| `TRACK_JOINTS` | `right_track`, `left_track` | スリップ率の計算に使う関節 |
| `SPROCKET_RADIUS` | None | 起動輪の半径 [m]。設定するとスリップ率を計算する |
| `RELOAD_TIMEOUT` | 60 s | シーンの読み込み直しを待つ時間の上限（実時間） |
| `RELOAD_SETTLE` | 1 s | 読み込み直しの後、設定を送る前に待つ時間（AGX の初期化を待つ） |
| `SAFE_RADIUS` | 20 m | 開始位置からこの距離を超えたら止める。「開始位置からフィールドの一番近い端までの距離」より小さくする。None で確認しない |
| `DEPTH_MIN` / `DEPTH_MAX` | −0.5 m / 0.20 m | 目標深さの範囲。範囲外の指示は範囲に収める（負は地面より上） |
| `MAX_TILT_DEG` | 20° | 開始時からのピッチ・ロールの変化の上限。超えたら止める |
| `MAX_ACTUAL_DEPTH` | 0.35 m | 実際の切削深さの上限。超えたら止める（転倒の兆候）。上げる区間では止めずに記録する |


## 9. 検証用の道具（analysis/）
`analysis/` は ROS2 のパッケージとしてインストールされない。ビルドせずに、そのまま `python3` や `bash` で実行する。検証の進め方（関門1〜6）と結果は `analysis/reports/` に関門ごとに残す。

| ファイル | 用途 |
| --- | --- |
| `checks/check_collection.py` | `collect_data` の1回分の実行結果をまとめて点検する |
| `checks/check_recording.py` | 1つ以上の時系列データ（CSV）の記録の健全さを点検する |
| `scripts/run_stress_tests.sh` | 関門1の段階A〜D（`stress_*` エピソード）をまとめて実行する |
| `scripts/dryrun_stress.py` | Unity を使わずに、`runner.py` の流れと記録を疑似の機体で通す |
| `reports/gate1_stress.md` | 関門1（スクリプトの不具合探し）の結果 |

### 9.1 check_collection.py
```
python3 analysis/checks/check_collection.py <collect_data の出力フォルダ> [--report 結果.md]
```

| 項目 | 確かめること |
| --- | --- |
| 1. 結果 | 各エピソードの結果（ok / error / skipped）が想定どおりか。想定は `EXPECTED_STATUS` に書く（ここにないエピソードは ok を想定） |
| 2. 開始位置・向き | ok のエピソードが毎回同じ位置・向きから始まっているか（許容 2 cm、0.5°） |
| 3. ラベル | AGX から読み戻した土質が、要求した土質と一致しているか |
| 4. 時系列データ | 行数、`sim_time` の逆戻り・重複、主な列と指令（`cmd_vx`、`cmd_lift`）の NaN |

最後に「想定外・要確認の項目：○件」を表示する。学習用の収集の後の点検にもそのまま使える。

### 9.2 check_recording.py
```
python3 analysis/checks/check_recording.py <CSV> [<CSV> …] [--c 粘着力 --phi 摩擦角 --rho 密度] [--report 結果.md]
```

各 CSV について、記録の周期（50 Hz）、時刻の単調性・重複、欠損（想定外の NaN）、一定の列（走行中）、ラベル、進行状況の順番、走行時間を、OK / WARN / NG で表示する。ラベルの確認は、既定で検証用の土質（c = 2100、φ = 39.98、ρ = 1474）と比べるので、土質が違うエピソードは `--c`、`--phi`、`--rho` で指定する。エラーで途中終了したエピソードの CSV も点検できる。

### 9.3 run_stress_tests.sh
```
bash src/bull_ope/analysis/scripts/run_stress_tests.sh            # 段階 A〜D をすべて実行
bash src/bull_ope/analysis/scripts/run_stress_tests.sh A B        # 指定した段階だけ実行
PAUSE=1 bash src/bull_ope/analysis/scripts/run_stress_tests.sh A  # 段階A で1つ終わるごとに Enter を待つ
```

| 段階 | 内容 | 所要時間の目安 |
| --- | --- | --- |
| A | `stress_*` を1つずつ `test_episode` で実行（Unity の画面を見ながら確かめる） | 約 10 分 |
| B | 失敗するエピソードと普通のエピソードを混ぜて、各3回を `collect_data` で連続実行 | 約 5 分 |
| B2 | `stress_numpy_params` を `collect_data` で実行（記録の JSON 変換の確認） | 1 分未満 |
| C | `stress_soil_extremes` を 10 回（土質の入れ替わりの確認） | 約 5 分 |
| D | `stress_short` を 50 回。前後で `/clock` の周波数を 10 秒ずつ測る（読み込み直しの耐久試験） | 約 12 分 |

結果は `src/bull_ope/data/validation/stress/<実行日時>/` に、CSV、各段階のターミナルの出力（`.log`）、点検結果（`check_*.md`）、全体のまとめ（`summary.log`）として保存される。

### 9.4 dryrun_stress.py
```
cd /workspaces/ws-bulldozer/src/bull_ope
python3 analysis/scripts/dryrun_stress.py                   # stress_* をすべて
python3 analysis/scripts/dryrun_stress.py stress_nan_depth  # 指定したものだけ
```

指令どおりに動くだけの疑似の機体で、各エピソードを `runner.py` に通す。例外の種類と記録の流れ（CSV が閉じる、`episodes.jsonl` に書ける、指令に NaN が入らない）を数秒で確かめられる。物理（反力・転倒）は再現しない。結果のフォルダは最後に表示されるので、`check_collection.py` もそのまま試せる。`runner.py` などを変えたときに、Unity で試す前に使う。


## 10. トラブルシューティング
| 症状 | 確認事項 |
| --- | --- |
| `トピックが届きません: [...]` で止まる（30 秒） | Unity が Play 中か。ROS-TCP-Endpoint が動いているか。`DataCollection` のコンポーネントが有効か。`ros2 topic list` に該当のトピックがあるか |
| `受信待ち: … episode_cmd の購読（Unity 側）` が続く | Unity の `SimEpisodeManager` が `/sim/episode_cmd` を購読していない。Unity の Play と ROS-TCP の接続を確認する |
| `シーンの読み込み直しが完了しません` | `SimEpisodeManager` が `reload` を受け取っているか、`SceneReloader` が付いているか。Unity の Console に「シーン … を読み込み直します」が出ているか |
| `Unity から設定完了の応答がありません` | `SimEpisodeManager` が動いているか（`ros2 topic echo /sim/episode_status`）。ROS-TCP-Endpoint との接続が増え続けていないか（下の行） |
| `Unity でエラー: …` | Unity 側の `setup` の処理で例外が出ている。Unity の Console のエラーの全文を確認する |
| `… が反映されていません（要求 …, AGX …）` | Unity 側で土質パラメータの設定に失敗している。Unity の Console と画面右下の表示を確認する |
| `InvalidCommand: …` | エピソードの `operation()` が `Command` 以外（`None` など）や NaN を返している。エピソードのコードを確認する |
| `SafetyStop: 安全のため停止しました：…` | 理由（開始位置からの距離・傾き・深さ）を確認する。学習用のエピソードで頻繁に出るなら、操作のパラメータ（深さ・速度）の範囲を見直す |
| 排土板が下がらず上がっていく | `LIFT_SIGN` の向きが逆。`test_episode --calibrate` で確認して `config.py` を直す |
| 排土板が目標の深さで振動する、追従が遅い | `LIFT_KP`、`LIFT_VMAX` を調整する |
| 走行中に止まったまま進まない | Unity の Play が一時停止していると、シミュレーション時刻が進まず待ち続ける |
| `ground_ahead が取得できません` | `BladeStatePublisher` が `ground_ahead` を配信しているか |
| `compacted_strips` などがスキップされる | Unity 側で `AGX_GRID_CONTROL` が無効（既定）。2.37 で API を確認してから有効にする |
| Unity の Console に `Some objects were not cleaned up when closing the scene` | `OnDestroy` / `OnDisable` の中で `Simulation.Instance` を確かめずに使っているスクリプトがある（関門1では `ImuSensor.cs` を修正）。`Simulation.HasInstance` で確かめてから使う |
| ROS-TCP-Endpoint との接続が増え続ける | コンテナ内で `awk '$2 ~ /:2710$/ && $4 == "01"' /proc/net/tcp /proc/net/tcp6 \| wc -l` で数える。常に 1 が正常。増える場合は、`SceneReloader.Reload()` で読み込み直しの前に `ROSConnection.Disconnect()` を呼んでいるか確認する |
| 読み込み直しを重ねると Unity の画面の更新が遅くなり、`/clock` の周波数が 50 Hz を下回る | HUD 表示（画面左上の「ROS2 IP」）が読み込み直しのたびに積み重なっている（「11. 注意点」を参照） |


## 11. 注意点
- 切削深さ `depth` は、開始時の前方の地面の高さを基準にしている。平らな地形での実験が前提で、`loose_layer_rect` で地面を盛った場合は基準とずれる。
- 時系列データの各列は、`blade_state` の受信時点での各トピックの最新値（ゼロ次ホールド）であり、厳密に同じ時刻の値ではない。どのトピックも同じシミュレーションから配信されるため、ずれは数十ミリ秒以内。
- エラーや安全停止で止まったエピソードは、上げる区間（raising）がない。機体と排土板はその場で止め、次のエピソードの読み込み直しで初期状態に戻す。
- 深く沈んだ状態からは、上げる区間（`RAISE_TIME` = 3 秒）で刃先を地面の上まで上げきれないことがある。次のエピソードは読み込み直しから始まるので、収集には影響しない。
- Unity の `ROSConnectionPrefab(Clone)` はシーンの一部として作られ、読み込み直しのたびに作り直される。そのたびに ROS-TCP-Connector の HUD 表示の見出しが static の一覧に登録されて消えないため、画面の更新の速さが読み込み直し1回あたり約 0.85 フレーム/ゲーム秒ずつ下がる（84 回で約 108 → 約 37）。シミュレーションの速さとデータには今のところ影響しないが、本番の収集（数百回の読み込み直し）の前に対応する（`SceneReloader` で見出しの一覧を空にするか、Robotics → ROS Settings の Show HUD を外す）。
- 収集データ（`data/` 以下の CSV）は大きくなるので Git の管理対象から外す（`.gitignore` に `src/bull_ope/data/*` と `!src/bull_ope/data/.gitkeep`）。


## 12. 動作確認の状況
| 項目 | 状況 |
| --- | --- |
| エピソードの定義（`episodes/`）の単体での動作 | 確認済み（シミュレータなし） |
| `colcon build` | 確認済み |
| `test_episode --calibrate` | 確認済み（`LIFT_SIGN = -1`） |
| `test_episode` によるテスト走行と点検 | 確認済み |
| `collect_data` による収集 | 確認済み |
| 関門1：スクリプトの不具合探し（`stress_*`） | 合格（`analysis/reports/gate1_stress.md`）。HUD 表示の積み重なりは持ち越し |
| 関門2：記録の健全さ（`val_*`） | 未実施 |
| 関門3：単位・座標・符号 | 未実施（力の符号・速度は関門1の段階A で個別に修正・確認済み） |
| 関門4：時間のずれ | 未実施 |
| 関門5：物理的な妥当性（FEE との比較） | 未実施 |
| 関門6：再現性と識別可能性 | 未実施 |