# エピソード
[← bull_ope のドキュメントの入口](README.md)

1回の試行（土質を設定し、決められた操作で走らせて記録する）を「エピソード」と呼ぶ。この文書では、1エピソードがどう進むか、エピソードをどう定義・実装するか、どんなエピソードが用意されているかをまとめる。

1. [1エピソードの流れ](#1-1エピソードの流れ)
2. [エピソードの定義と実装方法](#2-エピソードの定義と実装方法)
3. [エピソードの一覧](#3-エピソードの一覧)


## 1. 1エピソードの流れ
`core/runner.py` の `EpisodeRunner.run()` が、各エピソードを次の順に実行する。「進行状況」は、Unity の画面右下の表示と CSV の `phase` 列に出る値。

| 順番 | 処理 | 進行状況 | 記録 |
| --- | --- | --- | --- |
| 0 | 実行できる条件か確かめる（締固めの操作が必要なエピソードで、Unity 側の `AGX_GRID_CONTROL` が無効ならスキップ） | — | しない |
| 1 | Unity にシーンの読み込み直し（`reload`）を依頼し、`boot_id` が変わって新しいシーンのトピックがそろうまで待つ（最大 `RELOAD_TIMEOUT`）。その後 `RELOAD_SETTLE`（1 秒）待つ | reloading | しない |
| 2 | Unity にエピソードの設定（`setup`：土質、粒子の削除、地形のリセット、地形の加工）を依頼する。AGX から読み戻した土質が要求と一致するか確かめる | setup | しない |
| 3 | `SETTLE_TIME`（2 秒）待つ（機体が着地して落ち着くのを待つ） | setup | しない |
| 4 | 刃先の 0.5 m 前の地面の高さを 0.5 秒間測り、その中央値を切削深さの基準 `ground_h0` とする。車体の位置・向き・傾きを開始時の基準として記憶する | setup | しない |
| 5 | 停止したまま、排土板を最初の目標深さまで下げる（最大 `LOWER_TIMEOUT` 秒、誤差 `LOWER_TOLERANCE` 以内で終了） | lowering | する |
| 6 | エピソードの `operation()` に従って走る。終了条件（既定は走行距離 `MAX_DISTANCE` か時間 `TIMEOUT`）を満たすまで | running | する |
| 7 | 停止し、排土板を元の地面から `RAISE_HEIGHT`（0.3 m）の高さまで上げる（`RAISE_TIME` 秒） | raising | する |
| 8 | 記録を終了する（エラーで止まった場合も必ず実行する） | — | — |
| 9 | 完了 | done | — |

エピソードの最後に開始位置へ戻ることはしない。次のエピソードの最初にシーンを読み込み直すので、機体・地形・AGX の内部状態はすべて初期状態に戻る（開始位置のばらつきは 0.2 cm 以内。関門1〜7）。

### 1.1 排土板の制御
刃先の高さ（`blade_state` の `edge_z`）を目標の高さに近づける P 制御で、`lift_joint` に速度指令を送る。

```
目標の高さ  = ground_h0 − 目標の深さ
速度指令    = LIFT_SIGN × clip( LIFT_KP × (目標の高さ − edge_z), −LIFT_VMAX, LIFT_VMAX )
```

`LIFT_SIGN` = −1、`LIFT_KP` = 3.0、`LIFT_VMAX` = 0.1。`LIFT_KP` は関門3で 1.0 から 3.0 に上げた（深さの揺れの標準偏差が約 2 cm → 約 1 cm）。

### 1.2 指令の確認
エピソードの `operation()` が返した値は、送る前に毎回確かめる。

| 確かめること | 不正なとき |
| --- | --- |
| `Command` を返したか（`None` などでないか） | `InvalidCommand` で止める（指令は送らない） |
| `speed`、`yaw_rate` が有限の数か | 同上 |
| `depth` が有限の数か、`None`（排土板を上げる）か | 同上。NaN・無限大は送らない |
| `depth` が `DEPTH_MIN`〜`DEPTH_MAX`（−0.5〜0.20 m）の範囲か | 範囲に収めて実行し、`depth_clipped = 1` を記録する |

`sim_interface.py` でも、送る直前に値が有限でなければ例外にする（二重の確認）。

### 1.3 安全の確認
制御周期（0.05 秒）ごとに、開始時の基準と比べて次を確かめる。超えたら機体を止め、`SafetyStop` でエピソードを終える。

| 確かめること | 上限 |
| --- | --- |
| 開始位置からの距離 | `SAFE_RADIUS`（20 m） |
| ピッチ・ロールの変化 | `MAX_TILT_DEG`（20°） |
| 実際の切削深さ（`ground_h0` − `edge_z`） | `MAX_ACTUAL_DEPTH`（0.35 m） |

排土板を上げる区間では、深さの上限で止めない（深く入っていても上げ続けるほうが安全なため）。代わりに、上限を超えた深さの最大値を `raise_depth_over_max` として記録する。

### 1.4 失敗・スキップの扱い
| 状況 | 扱い |
| --- | --- |
| `AGX_GRID_CONTROL` が無効なのに、締固めの操作が必要なエピソード | スキップ |
| 地形の加工を要求したが、Unity で適用されなかった | スキップ |
| AGX から読み戻した土質が要求と一致しない | エラー |
| 読み込み直しが `RELOAD_TIMEOUT` 以内に終わらない | エラー |
| `setup` の応答が `SETUP_TIMEOUT` 以内に返らない | エラー（Unity 側の失敗なら「Unity でエラー: 内容」） |
| 指令が不正、安全の上限を超えた、エピソードのコードで例外 | エラー |

`collect_data` では、失敗・スキップしても機体を止めて次のエピソードに進む。次のエピソードは読み込み直しから始まるので、失敗の影響は残らない（関門1で確認）。


## 2. エピソードの定義と実装方法
### 2.1 Episode クラス（`episodes/episode.py`）
1つのエピソードは、`Episode` を継承したクラスで定義する。

| 要素 | 定義する場所 | 内容 |
| --- | --- | --- |
| 名前 | クラス属性 `name` | コマンドで指定する名前。重複するとエラー |
| 説明 | クラス属性 `description` | `--list` で表示される説明 |
| 土質 | クラス属性 `SOIL_RANGES` | 乱数で決めるときの範囲（フィールド名 → (下限, 上限)）。下限 = 上限で固定値になる |
| 操作のパラメータ | `sample_params(rng)` | 深さや速度など、エピソードごとに乱数で決める値。`episodes.jsonl` に `param_*` として記録される。NumPy の型でもよい（書き出すときに変換する） |
| 地形の加工 | `terrain_ops()` | 地形の加工のリスト。既定は空（平らな地形のまま） |
| 操作 | `operation(obs)` | 各時刻の観測から、速度・目標の深さ・旋回の角速度を返す |
| 終了条件 | `is_done(obs)` | 既定は走行距離 `MAX_DISTANCE`（10 m）または時間 `TIMEOUT`（60 秒） |
| 締固めの操作の要否 | クラス属性 `REQUIRES_GRID_CONTROL` | True なら Unity 側の `AGX_GRID_CONTROL` が必要 |

| データ構造 | 内容 |
| --- | --- |
| `SoilParams` | 土質。`cohesion` [Pa]、`friction_angle_deg` [deg]、`density` [kg/m³]、`swell_factor` [−]、`youngs_modulus` [Pa]。後の2つは None なら Unity 側の値のまま |
| `TerrainOp` | 地形の加工。`type`（`compaction_rect` / `loose_layer_rect`）、範囲（`x_start`, `x_end`, `y_min`, `y_max`）、`value`、`depth`。座標は開始時の刃先の中点が原点、x が前方、y が左方 [m] |
| `Observation` | `operation()` に渡す観測。`t`（走り出してからの時間）、`distance`（開始位置からの距離）、`speed`（前方向の速度。後退で負）、`edge_z`、`ground_h0`、`depth`、`blade`（`blade_state` の最新値の辞書） |
| `Command` | `operation()` が返す操作。`speed` [m/s]（負で後退）、`depth` [m]（None で排土板を上げる）、`yaw_rate` [rad/s]（正で左旋回、既定 0） |

エピソードは乱数のシードから作られ、同じシードなら同じ土質・同じ操作のパラメータになる。

### 2.2 新しいエピソードの書き方
`bull_ope/episodes/` の下のフォルダ（学習データ用なら `dataset/`）に、`Episode` を継承したクラスを書いたファイルを置くと、`collect_data` と `test_episode` が自動で見つける（`episodes/__init__.py` の `available_episodes()`）。置いたフォルダがグループ名になる。

```python
from ..episode import Command, Episode


class MyEpisode(Episode):
    name = "my_episode"
    description = "説明"
    SOIL_RANGES = {"cohesion": (0, 10000), "friction_angle_deg": (30, 40), "density": (1400, 1700)}
    MAX_DISTANCE = 12.0

    def sample_params(self, rng):          # 操作のパラメータ
        return {"depth": float(rng.uniform(0.05, 0.08)), "speed": 0.5}

    def operation(self, obs):              # 観測から速度と目標の深さを決める
        return Command(speed=self.params["speed"], depth=self.params["depth"])
```

| 注意 | 理由 |
| --- | --- |
| `operation()` は必ず `Command` を返す | `None` を返すと `InvalidCommand` で止まる |
| 深さは 12 cm 程度まで、土の山は高さ 0.4 m 程度までにする | 深すぎる・大きすぎると機体が前に傾き、排土板が潜って安全停止する（関門1・7） |
| 地形の加工は刃先の 1.5 m 以上前から始める | 切削深さの基準 `ground_h0` は刃先の 0.5 m 前で測るため |
| 後退しながら排土板を当てる動きは、学習データに入れない | AGX ではこの動きで土も力もほとんど生じない（関門3） |
| 新しいエピソードは、`test_episode` で1回試してから集める | 動きと記録を確かめる |

`--symlink-install` でビルドしていれば、ファイルを追加した後の再ビルドは不要。


## 3. エピソードの一覧
`ros2 run bull_ope test_episode --list` で一覧を表示できる。

### 3.1 学習データ用（`dataset/`）
| 名前 | 内容 | 状態 |
| --- | --- | --- |
| `flat_cut` | 平らな地形を、一定の深さ（6〜12 cm）・速度（0.3〜0.8 m/s）で 14 m 削る | **本番で使う**（[README の 2.1](README.md#21-採用したエピソード)） |
| `flat_piecewise` | 14 m を3区間に分け、区間ごとに深さ（6〜12 cm）と速度（0.3〜0.8 m/s）を変えて削る | **本番で使う** |
| `pile_push` | 前方 2〜4 m に緩い土の山（長さ 1〜2.5 m、高さ 0.2〜0.4 m）を積み、深さ 0〜4 cm で押しながら 14 m 進む（要 `AGX_GRID_CONTROL`） | **本番で使う（追加のデータ）** |
| `flat_constant` | 平らな地形を、一定の深さ（3〜12 cm）・速度（0.3〜1.0 m/s）で 10 m 削る | 旧版。`flat_cut` に置き換えた（10 m では頭打ちまで届かないことが多い） |
| `compacted_strips` | 地山・踏み固め・緩みの帯を横切って一定の深さで削る（要 `AGX_GRID_CONTROL`） | 未検証（`compaction_rect` は関門で確かめていない） |
| `shuttle_3x5m` | 特定の土質で、5 m の区間を3往復する | 土質が固定なので学習データには使わない |

### 3.2 サンプル集（`sandbox/`、`ex_*`）
ROS 側で変えられる自由度（動き・土質・地形）を一通り示すもの。`test_episode` で試す。

| 名前 | 内容 |
| --- | --- |
| `ex_speed_profile` | 0.2 → 1.2 m/s に加速し、一定で走った後、0.2 m/s まで減速しながら削る |
| `ex_stop_and_go` | 3 秒前進・2 秒停止を 20 秒間くり返しながら削る（関門4で使用） |
| `ex_blade_profile` | 排土板の高さを 削る → なでる → 浮かせる → 上げる → 削る と 2 m ごとに変える |
| `ex_load_control` | 前方の力が 15 kN になるよう、深さを自動で調整しながら削る |
| `ex_back_blading` | 排土板を上げて 6 m 前進し、排土板を地面に当てて後退で戻る（関門3で使用。後退中は力がほぼ生じない） |
| `ex_turning` | S 字に曲がりながら 12 秒削り、同じ軌跡を後退でたどって戻る（関門3で使用） |
| `ex_soil_all_params` | 5つの土質パラメータを固定値で指定して 10 m 削る |
| `ex_soil_random_all` | 5つの土質パラメータをすべて乱数で決めて 10 m 削る |
| `ex_terrain_compaction_map` | パッチごとに締固めの程度を変えて削る（要 `AGX_GRID_CONTROL`） |
| `ex_terrain_loose_pile` | 前方 2〜4 m に厚さ 50 cm の緩い土の山を積み、押し広げる（要 `AGX_GRID_CONTROL`） |

### 3.3 検証用（`validation/`）
検証用のエピソードは、学習データには使わない。どの関門で使ったかは [検証のドキュメント](validation/README.md) を参照。

**データの確認用（`validation/data_check/`、`val_*`、`val_sens_*`）**

`validation/base.py` の `ValidationEpisode` を継承し、土質を OperaSim の `dirt_1`（c = 2,100 Pa、φ = 39.98°、ρ = 1,474 kg/m³）に固定する。クラス属性 `PARAM_NAMES` に書いた値を、乱数を使わずにそのまま記録する。

| 名前 | 内容 | 使った関門 |
| --- | --- | --- |
| `val_static` | 排土板を上げたまま 10 秒静止する | 2・3・4 |
| `val_air_run` | 排土板を上げたまま 0.5 m/s で 10 m 直進する | 2・3・4・5 |
| `val_constant_depth` | 深さ 6 cm・0.5 m/s で 10 m 削る | 2〜5 |
| `val_constant_depth_3cm`・`9cm`・`12cm` | 深さだけを 3・9・12 cm に変えたもの | 5 |
| `val_depth_step` | 深さを 3 → 6 → 9 cm と 3 m ごとに変えて削る | 2〜5 |
| `val_sens_*`（12 条件） | 深さ 9 cm・10 m で、土質（c・φ・ρ）と速度を1つずつ変えて削る（`sensitivity.py` でまとめて定義） | 6 |

**不具合探し用（`validation/stress/`、`stress_*`）**

わざと失敗しやすい条件を作り、「失敗しても次のエピソードが正常に始まるか」「おかしな値が記録されないか」を確かめる（関門1）。

| 名前 | 内容 | 想定の結果 |
| --- | --- | --- |
| `stress_instant_done` | 走り出した瞬間に終了する | ok |
| `stress_error_midrun` | 走り出して 3 秒後に例外を起こす | error |
| `stress_none_command` | 2 秒後から `operation()` が None を返す | error（InvalidCommand） |
| `stress_nan_depth` | 2 秒後から目標の深さに NaN を返す | error（InvalidCommand） |
| `stress_runaway` | 外へ向かって 100 m 走ろうとする | error（SafetyStop） |
| `stress_depth_limits` | 制限を超える目標の深さ（0.5 m、−1.0 m）を与える | ok、または傾きで SafetyStop |
| `stress_spin` | 排土板を地面に当てたまま 15 秒旋回する | ok |
| `stress_heavy_push` | c 30 kPa・ρ 1,950 kg/m³ の土を深さ 20 cm で押す | SafetyStop（深さ） |
| `stress_numpy_params` | `sample_params` が NumPy の型を返す | ok |
| `stress_soil_extremes` | 土質を極端な範囲で決めて削る | ok |
| `stress_short` | 2 秒だけ走る（読み込み直しの耐久試験用） | ok |
