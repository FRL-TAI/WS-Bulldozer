# bull_ope：土質パラメータ推定用データ収集パッケージ（ROS2）

ブルドーザのシミュレーション（OperaSim-AGX）を ROS2 から自動で動かし、土質パラメータ（粘着力 c、内部摩擦角 φ、密度 ρ）を推定するニューラルネットワーク（PINN を含む）の学習データを集めるパッケージ。

| 項目 | 内容 |
| --- | --- |
| パッケージ名 | `bull_ope`（ROS2 Python パッケージ、ament_python） |
| 対象 | OperaSim-AGX のブルドーザ `d37pxi_24`（Unity のシーン `DataCollectionScene`） |
| 対になる Unity 側 | `OperaSim-AGX-TAI` リポジトリの `BladeStatePublisher`、`SimEpisodeManager`、`SceneReloader`、`EpisodeStatusOverlay` |
| 動作確認した環境 | Unity 2022.3.16f1、AGX Dynamics 2.37.3.0（AGXUnity 5.0.1）、ROS2 Humble（Dev Container「ROS2-Humble-Env for OperaSim」） |

目次

1. [パッケージの概要](#1-パッケージの概要)
2. [データ収集の本番スクリプト](#2-データ収集の本番スクリプト)
3. [収集データ](#3-収集データ)
4. [その他のドキュメント](#4-その他のドキュメント)


## 1. パッケージの概要
### 1.1 目的
1回の試行（エピソード）では、Unity のシーンを読み込み直して機体・地形・AGX の状態を初期状態に戻し、土質パラメータを設定し、決められた操作でブルドーザを走らせながら、排土板が土から受ける力や車体・関節の状態を 50 Hz で記録する。これを、土質と操作を変えながら自動で繰り返す。

記録の仕組みとシミュレーションの妥当性は、関門1〜7の検証で確かめてある（[検証のドキュメント](validation/README.md)）。

### 1.2 ファイルの構成
```
ws-bulldozer/
├ src/bull_ope/
│  ├ bull_ope/              ROS2 のノード（ビルドしてインストールされる）
│  │  ├ apps/               collect_data.py（収集）、test_episode.py（試走と点検）
│  │  ├ core/               runner.py（1エピソードの手順、指令の確認、安全の確認）
│  │  ├ ros/                sim_interface.py（トピックの送受信、シーンの読み込み直し、速度の計算）
│  │  ├ recording/          recorder.py（CSV への記録）、compaction_recorder.py（締固めの記録）、
│  │  │                     json_utils.py（JSON に書く前の型の変換）
│  │  ├ episodes/
│  │  │  ├ episode.py       エピソードの基底クラスとデータ構造
│  │  │  ├ dataset/         本番の収集で使う学習データ用（名前は dataset_*）
│  │  │  ├ sandbox/         試作・旧版・自由度のサンプル集（名前は ex_*）
│  │  │  └ validation/
│  │  │     ├ data_check/   検証用（val_*、val_sens_*）
│  │  │     └ stress/       不具合探し用（stress_*）
│  │  └ config.py           設定値
│  ├ scripts/               運用のためのスクリプト（インストールされない）
│  │  └ run_production.sh   本番の収集
│  └ resource/bull_ope      ament のパッケージの目印（中身は空）
├ analysis/                 解析・点検のスクリプト（インストールされない。一覧は analysis/README.md）
│  ├ production/            本番の収集の点検（run_production.sh が使う）
│  ├ validation/            データ検証の関門1〜7
│  └ phase0/                フェーズ0（締固め・沈下・較正曲線）
└ data/                     出力データ（Git の管理外。.gitkeep のみ）

docs/bull_ope/              このドキュメント
├ README.md                 この文書（概要、本番の収集、収集データ）
├ episodes.md               エピソード（1エピソードの流れ、定義と実装、一覧）
├ scripts.md                test_episode・collect_data の使い方
├ output_data.md            出力データ（フォルダの構成、episodes.jsonl）
├ config.md                 設定（config.py）
├ troubleshooting.md        トラブルシューティング
└ validation/               検証の道具と、関門1〜7のレポート
```


## 2. データ収集の本番スクリプト
### 2.1 採用したエピソード
学習データには、次のエピソードを使う（`bull_ope/episodes/dataset/flat_cut.py`、`pile_push.py`）。設計は関門1〜7の結果に基づく。

| エピソード | 動き | 用途 |
| --- | --- | --- |
| `dataset_flat_cut` | 平らな地形を、一定の深さ・一定の速度で 14 m 削りながら直進する | 主なデータ。関門5・6で調べた関係（土の量と力、土質と力）がそのまま当てはまる |
| `dataset_flat_piecewise` | 14 m を3つの区間（約 4.7 m ずつ）に分け、区間ごとに深さと速度を変えて削る | 主なデータ。条件が途中で変わる場合も推定器が扱えるようにする |
| `dataset_pile_push` | 前方 2〜4 m に緩い土の山（長さ 1〜2.5 m、高さ 0.2〜0.4 m、幅 3.0 m）を積み、浅く削り（深さ 0〜4 cm）ながら押して 14 m 進む | 追加のデータ。主なデータとは別のフォルダに集め、学習に使うかを後で選ぶ |

各エピソードの流れ（読み込み直し → 土質の設定 → 排土板を下げる → 走る → 上げる）は [episodes.md](episodes.md#1-1エピソードの流れ) を参照。

**操作と土質の範囲**

| 項目 | 範囲 | 根拠 |
| --- | --- | --- |
| 粘着力 c | 0〜30 kPa | 関門6で調べた範囲 |
| 内部摩擦角 φ | 25〜50° | 同上 |
| 密度 ρ | 1,200〜1,900 kg/m³ | 同上（AGX の Maximum Density 2,000 kg/m³ 未満） |
| 膨張率・ヤング率 | 変えない（1.28、6.5 MPa） | 関門6で調べていない |
| 土質の決め方 | ラテン超方格法（範囲内に偏りなく配置） | 関門7で、範囲を5等分したどの区間にも偏りなく入ることを確認 |
| 深さ | `dataset_flat_cut`・`dataset_flat_piecewise`：6〜12 cm、`dataset_pile_push`：0〜4 cm | 関門5で確かめた範囲。`dataset_pile_push` は関門7で潜りにくい範囲に狭めた |
| 速度 | 0.3〜0.8 m/s | 関門6：頭打ちの前後の力が速度にほぼ比例するので、速度を変える |
| 距離 | 14 m | 深さ 6 cm でも削った体積が約 2.5 m³ になり、頭打ちの特徴が取れる（関門5・6） |
| 入れない動き | 後退しながら排土板を当てる動き | 関門3：AGX ではこの動きで土も力もほとんど生じない |

### 2.2 スクリプトの実行方法
本番の収集は `src/bull_ope/scripts/run_production.sh` で行う。1つの区切り（チャンク）で各エピソードを決まった件数だけ集め、区切りが終わるたびに点検する。

**事前の準備**

1. ROS-TCP-Endpoint を起動する（`ros2 run ros_tcp_endpoint default_server_endpoint`）。
2. Unity で `DataCollectionScene` を開いて Play し、画面右下に「データ収集」の枠が出ることを確かめる。
3. PC のスリープを切る。Unity のウィンドウを最小化しない。

**実行**

```
cd /workspaces/ws-bulldozer
# 主なデータ：区切り 1〜12（1区切り = dataset_flat_cut 60 件 + dataset_flat_piecewise 30 件、約 55 分）
bash src/bull_ope/scripts/run_production.sh 1 12

# 追加のデータ（dataset_pile_push）：別の出力先に集める
N_CUT=0 N_PW=0 N_PILE=30 OUT=data/production_pile \
    bash src/bull_ope/scripts/run_production.sh 1 3
```

| 引数・環境変数 | 既定値 | 内容 |
| --- | --- | --- |
| 1つ目の引数 | — | 最初の区切りの番号 |
| 2つ目の引数 | — | 最後の区切りの番号 |
| `N_CUT` | 60 | 1区切りの `dataset_flat_cut` の件数 |
| `N_PW` | 30 | 1区切りの `dataset_flat_piecewise` の件数 |
| `N_PILE` | 0 | 1区切りの `dataset_pile_push` の件数 |
| `OUT` | `data/production` | 出力先 |
| `SEED_BASE` | 1000 | 区切り k の乱数のシードは `SEED_BASE + 10k`（`dataset_flat_cut`）、`+1`（`dataset_flat_piecewise`）、`+2`（`dataset_pile_push`） |

- 区切りごとにシードが決まっているので、途中で止まった区切りは、同じ番号で実行し直せば同じ計画が再現される。
- 区切りが終わるたびに `check_collection.py` と `check_dataset.py` が実行され、要約が `<OUT>/production.log` に追記される。「想定外・要確認の項目 : 0 件」が並んでいれば正常。
- どのフォルダから実行してもよい（スクリプトの場所からワークスペースの場所を求める）。

**所要時間と容量の目安（関門7）**

| 項目 | 値 |
| --- | --- |
| 1エピソードの実時間 | 約 36 秒（走行 約 26 秒） |
| CSV の大きさ | 約 2.3 MB / エピソード |
| 1,000 件 | 約 10 時間、約 2.3 GB |

**長時間の収集の注意**

| 注意 | 理由 |
| --- | --- |
| 数区切りごとに、ROS-TCP-Endpoint との接続の数と Unity の Console を確かめる | 関門1で直した接続の漏れが再発していないか。確かめ方は [troubleshooting.md](troubleshooting.md) |
| 止めるときは、区切りが終わってから止める | 途中で止めた区切りは、同じ番号でやり直す |
| Unity を再起動する前に Editor.log をコピーする | 問題があったときの調査に使う |


## 3. 収集データ
### 3.1 通信するトピック
| トピック | 型 | 向き | 内容 |
| --- | --- | --- | --- |
| `/d37pxi_24/blade_state` | `std_msgs/Float64MultiArray` | 受信 | 排土板の力、刃先の位置、地面の高さなど（50 Hz、AGX の各ステップの後）。値の名前は `layout.dim[0].label` にカンマ区切りで入る |
| `/d37pxi_24/joint_states` | `sensor_msgs/JointState` | 受信 | 関節（lift / tilt / angle / 左右の履帯）の位置・速度・力（約 39 Hz） |
| `/d37pxi_24/global_pose` | `nav_msgs/Odometry` | 受信 | 車体の位置・姿勢（約 38 Hz）。速度の欄は OperaSim では 0 のままなので、速度は `bull_ope` が位置の変化から計算する |
| `/sim/episode_status` | `std_msgs/String`（JSON） | 受信 | Unity の状態（5 Hz と、指令の処理直後）。AGX から読み戻した土質など |
| `/sim/compaction_probe` | `std_msgs/String`（JSON） | 受信 | 締固めの記録（`RECORD_COMPACTION` のエピソードだけ。[3.3](#33-締固めの記録_compactioncsv)） |
| `/d37pxi_24/cmd_vel` | `geometry_msgs/Twist` | 送信 | 前進・後退の速度（`linear.x`）と旋回の角速度（`angular.z`） |
| `/d37pxi_24/blade_cmd` | `com3_msgs/JointCmd` | 送信 | 排土板の速度指令（`control_type = 1`）。OperaSim は配列の順番 [0] lift、[1] tilt、[2] angle で読むので、必ず3要素で送る |
| `/sim/episode_cmd` | `std_msgs/String`（JSON） | 送信 | Unity への指令（下の表） |
| `/clock` | `rosgraph_msgs/Clock` | 受信 | シミュレーション時刻（ノードは `use_sim_time = True`） |

**`/sim/episode_cmd` で送る指令**

| `command` | 内容 | 完了の確かめ方 |
| --- | --- | --- |
| `reload` | シーンを読み込み直す | `/sim/episode_status` の `boot_id` が変わる |
| `setup` | 土質の設定 → 粒子の削除 → 地形のリセット → 地形の加工 | `/sim/episode_status` の `request_id` が送った値になる。失敗した場合も同じ `request_id` で `error` に内容が入る |
| `phase` | 画面右下の表示用の進行状況だけを更新する | なし |

```json
{"command": "reload"}

{"command": "setup", "request_id": 12, "episode_name": "dataset_pile_push", "episode_index": 3, "total_episodes": 30,
 "phase": "setup",
 "soil": {"cohesion": 15000, "friction_angle_deg": 35, "density": 1600, "swell_factor": -1, "youngs_modulus": -1},
 "terrain_ops": [{"type": "loose_layer_rect", "x_start": 2.5, "x_end": 4.5, "y_min": -1.5, "y_max": 1.5,
                  "value": 0.3, "depth": 0.0}]}

{"command": "phase", "phase": "running"}
```

- `soil` の負の値は「変更しない」（Unity 側の材料の値のまま）。
- `terrain_ops` の座標は、設定時の刃先の中点を原点とし、x が前方、y が左方 [m]。`loose_layer_rect` は範囲内に厚さ `value` [m] の緩い土の層を積み、`compaction_rect` は範囲内の締固めの程度を `value` にする（深さ `depth` [m] まで）。どちらも Unity 側で `AGX_GRID_CONTROL` が有効なときだけ使える（このプロジェクトでは有効）。
- `setup` は、届いたことが確かめられるまで1秒ごとに再送する（Unity 側は同じ `request_id` を無視する）。

**`/sim/episode_status` の例**

```json
{"boot_id": 1733042, "request_id": 12, "episode_name": "dataset_pile_push", "episode_index": 3, "total_episodes": 30,
 "phase": "running", "cohesion": 15000.0, "friction_angle_deg": 35.0, "density": 1600.0, "swell_factor": 1.28,
 "youngs_modulus": 6500000.0, "ops_requested": 1, "ops_applied": true, "ops_cells": 60,
 "grid_control_enabled": true, "reset_count": 1, "sim_time": 123.4, "error": ""}
```

`cohesion`〜`youngs_modulus` は AGX 本体から読み戻した値で、学習データのラベルになる。詳細は Unity 側の `docs/feature/SimEpisodeManager.md`。

### 3.2 収集データ（時系列データ ep*.csv の列）
`/d37pxi_24/blade_state` が届くたび（シミュレーション時刻で 20 ms ごと）に1行を書く。ほかのトピックの値は、その時点で届いている最新の値を使う。記録するのは「排土板を下げる → 走る → 上げる」の間で、学習には `phase == "running"` の行を使う。全 118 列。

**座標系：** 力・トルク（`F_*`、`T_*`）は車体（`base_link`）に固定した座標で、x：前方、y：左方、z：上方。4つの力の内訳はいずれも「排土板が土から受ける力」の向き（押土中は `F_total_x` が負、`F_total_z` も負＝下向き）。位置と地面の高さはワールド座標（高さは Unity のワールド y と同じ）。

| 種類 | 列 | 内容 |
| --- | --- | --- |
| エピソード | `episode_index`、`episode_name`、`seed` | エピソードの番号・名前・乱数のシード |
| 進行状況 | `phase` | `lowering`（下げる）、`running`（走る）、`raising`（上げる） |
| 指令（bull_ope） | `target_depth`、`depth_clipped` | その時点の目標の深さ [m]（`DEPTH_MIN`〜`DEPTH_MAX` に制限した後）と、制限したか（1/0）。上げる区間は −`RAISE_HEIGHT` |
| 時刻 | `t`、`sim_time` | 記録開始からの時間 [s]、シミュレーション時刻 [s] |
| 排土板の力（blade_state） | `F_total_x/y/z` | 排土板が土から受ける力の合計 [N] |
| | `F_pen_x/y/z` | 貫入抵抗 [N]。粘着力 c にほぼ比例する（関門6：`F_pen` ≒ 0.93 + 0.65 × c [kPa] kN） |
| | `F_sep_x/y/z` | 分離抵抗 [N]。排土板の前の土の塊から受ける力。押土中に支配的 |
| | `F_def_x/y/z`、`F_con_x/y/z` | 変形抵抗・通常の接触力 [N]。このシミュレーションでは常に 0（関門3） |
| | `T_pen_x/y/z` | 貫入抵抗のトルク [N·m]（参考値。ほぼ 0） |
| 排土板の形（blade_state） | `edge_x/y/z` | 刃先の中点の位置 [m]。`edge_z` が刃先の高さ |
| | `blade_width`、`blade_alpha_deg` | 排土板の幅（2.96 m）、排土板の角度 [deg]（刃先から上端へのベクトルと、後ろ向きの水平のなす角。下げると約 71°） |
| 地面の高さ（blade_state） | `ground_below` | 刃先の真下の地面の高さ [m]。削っている間は、まだ切り取られていない土と土の山の表面になる（削った後の地面ではない） |
| | `ground_behind` | 刃先から 0.3 m 後ろの地面の高さ [m]。削った後の地面（刃先の高さとほぼ同じ） |
| | `ground_ahead`、`ground_profile_025cm`〜`200cm` | 刃先から 0.5 m 前方、および 25 cm ごとに 8 点の前方の地形の高さ [m]（Unity の TerrainData。粒子を含まず、1ステップ遅れる）。`ground_ahead` は `ground_profile_050cm` と同じ値。平らな地面では刃先の前 1.0〜1.25 m より先が `ground_h0` のまま一定になるのは正常 |
| | `ground_terrain_*`、`ground_vis_*`、`ground_ptop_*`（025cm〜200cm） | 同じ 8 点の、AGX から直接読んだ地形の高さ、粒子を含む高さ（地形の経路・模擬 LiDAR に使う）、確かめ用の粒子の上端 [m]（T23。中身と注意は output_data.md の「前方の地面の高さの列」。足す前の記録にはない） |
| 土の状態（blade_state） | `state_compaction_mean/std/n` | 刃先の前 1 m・排土板の幅の範囲の、地表の締固めの程度の平均・標準偏差・マスの数 |
| | `front_soil_mass`、`front_soil_mass_deform`、`front_dynamic_mass`、`front_inner_volume`、`front_dead_load_fraction`、`excavated_volume_step` | 排土板の前の土塊・動く土の質量 [kg]、inner shape の体積と埋まっている割合、直前のステップの掘削体積 [m³]（AGX の API。中身と注意は output_data.md の「排土板の前の土の質量・掘削体積の列」。足す前の記録では NaN） |
| | `pile_*`、`dyn_*`、`bal_*` | 土の山の体積 V_pile（地形の高さ ＋ 粒子 ÷ (ρ/s)）とその内訳・感度用の範囲、地形全体の動く土、収支の確認用の窓の体積（T15。中身は output_data.md の「土の山の体積の列」） |
| 関節（joint_states） | `lift_joint_pos/vel/effort` など | 排土板の上げ下げ・チルト・アングル、左右の履帯の位置・速度・力。履帯の力は N·m（起動輪の半径 約 0.352 m で割ると駆動力 [N]）。`lift_joint_effort` は上下の力 `F_total_z` と相関 0.98 |
| 車体（global_pose） | `x`、`y`、`z`、`roll`、`pitch`、`yaw`、`pose_stamp` | 車体の位置 [m]・姿勢 [rad]、位置が更新された時刻 [s] |
| 車体の速度（bull_ope が計算） | `vx`、`vy`、`vz`、`wz`、`v_forward`、`v_lateral` | 位置の変化を 0.1 秒の幅で求めた速度。`v_forward` は前方向（後退で負） |
| 指令（bull_ope） | `cmd_vx`、`cmd_wz`、`cmd_lift` | 送った最新の指令（前進速度、旋回の角速度、排土板の速度） |
| 派生量（bull_ope） | `ground_h0` | 開始時に刃先の 0.5 m 前で 0.5 秒間測った地面の高さの中央値 [m]。切削深さの基準 |
| | `depth` | 切削深さ [m] = `ground_h0` − `edge_z`（正で元の地面より下） |
| | `speed`、`distance` | 水平の速さ [m/s]（向きなし）、開始位置からの距離 [m] |
| | `cut_volume` | それまでに地山を削った体積 [m³]（`blade_width` × `depth` × 前進速度 × Δt の積算）。`dataset_pile_push` で積んだ山の量は含まない |
| | `slip_ratio` | 履帯のスリップ率（`SPROCKET_RADIUS` が未設定なので NaN） |
| ラベル（episode_status） | `label_c`、`label_phi`、`label_rho0`、`label_swell`、`label_E0` | AGX から読み戻した土質（推定の正解） |
| | `label_KE`、`label_NE` | AGX から読み戻した硬化の係数・指数（締固めのしやすさの設定） |
| | `label_maxDensity` | AGX から読み戻した締固めの上限の密度 [kg/m³]。(2000/1474)·ρ（上限の程度はどの ρ でも約 1.357）。この列を足す前の記録にはない（2,000 で一定） |

**学習に使うときの注意**

| 注意 | 内容 |
| --- | --- |
| 値の時刻のずれ | `blade_state` の値に対し、`joint_states` は 20 ms、`global_pose` はふつう 20 ms（最大 100 ms）、計算した速度は約 60 ms 遅れる。同じ値が最大 5〜6 行続くことがある（関門2・4） |
| 地形のマスによる揺れ | 地形は 0.3125 m のマスでできていて、刃先が1マス進むごとに力・深さが揺れる（0.5 m/s で周期 約 0.6 秒）（関門3） |
| 深さの揺れ | 平均では目標どおりだが、速いほど揺れが大きい（95% の幅：0.5 m/s で約 2 cm、0.75 m/s で最大 7 cm）。学習には実際の `depth` を使う（関門3・7） |
| 力の頭打ち | 前後の力は削った土の量に比例して増え（傾き ≒ ρ g tanφ）、約 1.5〜2 m³ 以上で頭打ちになる（関門5） |
| 記録の最初 | 記録の最初の `depth` は約 13 cm（シーンの初期状態で排土板が地面にめり込んでいるため）。下げる区間は学習に使わない（関門3） |
| 潜ったエピソード | `dataset_pile_push` では約 5% のエピソードで、排土板が目標より大きく潜る（深さのずれの 95% が 10 cm 超）。学習から除く条件を決めて使う（関門7） |

出力のフォルダの構成と `episodes.jsonl` の列は [output_data.md](output_data.md) を参照。

### 3.3 締固めの記録（*_compaction.csv）
クラス属性 `RECORD_COMPACTION` が True のエピソード（現在は `ex_compaction_passes`・`ex_compaction_bands`・`ex_compaction_then_cut`・`ex_compaction_patterns`・`ex_compaction_levels`）では、Unity の `CompactionProbe` が、地形のマスの高さと締固めの程度を `/sim/compaction_probe` に送る。`bull_ope` の `CompactionRecorder`（`recording/compaction_recorder.py`）がそれを受け取り、時系列データの CSV の隣に `<時系列データの名前>_compaction.csv` として保存する。

| 項目 | 内容 |
| --- | --- |
| 送る条件 | `setup` の指令で `record_compaction` が true のエピソードの、phase が `lowering` になってから `done` になるまで |
| 送る間隔 | シミュレーション時刻で 1 秒ごと（Unity 側の `sampleInterval`）。最後に phase が `done` になった時点の記録を `final: true` で送る |
| メッセージ | `{"request_id": …, "episode_name": …, "final": false, "header": "sim_time,phase,…", "rows": "…\n…\n"}`。`rows` は1回分の記録（CSV の行） |
| 混ざらない仕組み | `setup` の `request_id` と一致するメッセージだけを保存する（前のエピソードの記録は捨てる） |
| 閉じ方 | phase を `done` にした後、`final` の記録を最大 3 秒待ってから閉じる。届かなければ注意を表示する。エラーや Ctrl+C で止まったときは待たずに閉じる |

**記録する場所（列）**

開始時（phase が `lowering` になった時点）の `body_link` の位置を原点、前方を x、左方を y とした座標で、前後 −1〜12 m の範囲のマスを記録する。

| 列の名前（`lane`） | 場所 |
| --- | --- |
| `track_L±0.00`、`track_R±0.00` | 左右の履帯の走路。履帯の幅（0.6 m）の中に中心が入るマスをすべて記録し、履帯の中心線からのマスの中心の横の位置 [m] を名前に付ける |
| `center` | 機体の中心線上のマス |
| `control` | 対照（走路の外、左方 3.5 m）のマス |

**CSV の列**（1行 = 1回の記録の1マス）

| 列 | 内容 |
| --- | --- |
| `sim_time`、`phase` | 記録した時刻 [s]、そのときの進行状況 |
| `machine_x` | 機体（`body_link`）の前後の位置 [m]（上の座標） |
| `lane`、`lane_y`、`x` | 列の名前、マスの中心の横の位置 [m]、前後の位置 [m] |
| `unity_ix`、`unity_iy` | Unity の地形のマスの番号 |
| `height` | 地表の高さ [m]（ワールド座標） |
| `c_surface` | 地表の締固めの程度（AGX の `getSurfaceCompaction`） |
| `surface_z` | 地表のボクセルの深さ方向の番号 |
| `c_z0`〜`c_z5` | 地表のボクセル（`c_z0`）から下へ6つのボクセルの締固めの程度 |

解析は `analysis/phase0/` のスクリプト（`check_compaction.py`、`check_track_settlement.py` など）で行う（[analysis/README.md](../../analysis/README.md)）。


## 4. その他のドキュメント
- **[エピソード](episodes.md)**
  - 1エピソードの流れ（読み込み直し、設定、排土板の制御、指令の確認、安全の確認、失敗の扱い）
  - エピソードの定義と実装方法（`Episode` クラス、データ構造、新しいエピソードの書き方）
  - エピソードの一覧（学習データ用、サンプル集、検証用 `val_*`・`val_sens_*`、不具合探し用 `stress_*`）
- **[スクリプトの使い方](scripts.md)**
  - `test_episode`：1エピソードの試走と点検、排土板の向きの較正
  - `collect_data`：複数のエピソードの収集
- **[出力データ](output_data.md)**：フォルダの構成、`config.json`、`episodes.jsonl` / `episodes.csv` の列、本番の収集のログ
- **[解析のスクリプト](../../analysis/README.md)**：`analysis/` のフォルダごとのスクリプトの一覧と用途
- **[設定（config.py）](config.md)**：各設定値の意味と、その値にした理由
- **[検証](validation/README.md)**
  - 検証の道具（`check_*.py` などの点検のスクリプト）の解説
  - 関門1〜7で何を確かめ、何が分かったか（各レポートへのリンク）
- **[トラブルシューティング](troubleshooting.md)**
