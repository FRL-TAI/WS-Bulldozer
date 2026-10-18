# スクリプトの使い方
[← bull_ope のドキュメントの入口](README.md)

ROS2 のコマンドとして使えるスクリプトは次の2つ。本番の収集の `run_production.sh` は [README の 2.2](README.md#22-スクリプトの実行方法)、検証の道具は [検証のドキュメント](validation/README.md) を参照。

| コマンド | 用途 |
| --- | --- |
| `ros2 run bull_ope test_episode` | 1つのエピソードを1回試走し、記録したデータを点検する。排土板の向きの較正にも使う |
| `ros2 run bull_ope collect_data` | 複数のエピソードを順に実行し、データを集める |

**事前の準備（どちらも共通）**

```
cd /workspaces/ws-bulldozer
colcon build --packages-select bull_ope --symlink-install   # 初回、または新しいファイルを追加したとき
source install/setup.bash
```

1. ROS-TCP-Endpoint を起動する（`ros2 run ros_tcp_endpoint default_server_endpoint`）。
2. Unity で `DataCollectionScene` を開いて Play する。
3. 次のトピックが届いていることを確かめる（届いていなければ、スクリプトが「受信待ち」と表示して待ち続ける）。

    ```
    ros2 topic echo /sim/episode_status --once
    ros2 topic echo /d37pxi_24/blade_state --once
    ```


## 1. test_episode：試走と点検
```
ros2 run bull_ope test_episode [エピソード名] [オプション]
```

| オプション | 既定値 | 内容 |
| --- | --- | --- |
| `--list` | — | 使えるエピソードの一覧を表示して終了する |
| `--calibrate` | — | 排土板の上げ下げの向きを確かめる（`lift_joint` に +0.05 を 2 秒送り、刃先の高さの変化と、`LIFT_SIGN` に設定すべき値を表示する） |
| `--seed` | 0 | 乱数のシード（土質・操作のパラメータが決まる） |
| `--c`、`--phi`、`--rho` | 乱数 | 粘着力 [Pa]、内部摩擦角 [deg]、密度 [kg/m³]。指定しなかったものは `--seed` から決まる乱数 |
| `--swell` | Unity 側の値 | 膨張率 [−] |
| `--no-record` | — | CSV に記録しない |
| `--out` | `<DATA_DIR>/test` | 保存先 |

**使用例**

```
ros2 run bull_ope test_episode --list
ros2 run bull_ope test_episode --calibrate                              # 初回に一度（LIFT_SIGN の確認）
ros2 run bull_ope test_episode dataset_flat_cut --seed 0
ros2 run bull_ope test_episode dataset_flat_cut --c 30000 --phi 50 --rho 1900   # 最も重い土で試す
ros2 run bull_ope test_episode val_constant_depth --out src/bull_ope/data/validation/gate3/kp3
```

**走行中の表示**（0.5 秒ごと）

```
t=  3.5s  dist= 1.62m  v=0.48m/s  depth=  7.9cm (目標   8.0)  Fx= -12.35kN  Fz= -10.10kN
```

**終了後の点検**

正常に終わった場合、記録した CSV を読み込み、行数（全体と走行中）、記録の周期（平均と最大。50 Hz なら 20 ms）、主な列と「未取得（すべて NaN）」「一定」と判定された列の欠損数・最小・平均・最大、走行中の切削深さの平均と標準偏差を表示する。統計は走行中（`phase == "running"`）の行で計算する。

エラー（`InvalidCommand`、`SafetyStop`、エピソードの例外など）で止まった場合は、トレースバックを表示して終了コード 1 で終わる。CSV はそこまでの分が保存されるので、`analysis/checks/check_recording.py` で点検できる。


## 2. collect_data：収集
```
ros2 run bull_ope collect_data [オプション]
```

| オプション | 既定値 | 内容 |
| --- | --- | --- |
| `--list` | — | 使えるエピソードの一覧を表示して終了する |
| `--episodes` | `all` | 実行するエピソード名（スペース区切りで複数）。`all` は検証用も含むので、通常は名前を指定する |
| `--num` | 5 | エピソードの種類ごとの実行回数 |
| `--seed` | 0 | 実行計画全体の乱数のシード |
| `--sampling` | `lhs` | 土質の決め方。`lhs`：ラテン超方格法、`uniform`：各エピソードのシードからの一様乱数 |
| `--out` | `DATA_DIR` | 保存先 |
| `--run-name` | なし | 実行名（保存フォルダ名の末尾に付く） |

**使用例**

```
# 検証用：4種類を3回ずつ（関門2）
ros2 run bull_ope collect_data --episodes val_static val_air_run val_constant_depth val_depth_step \
    --num 3 --seed 0 --run-name gate2 --out src/bull_ope/data/validation/gate2

# 試験的な収集（関門7）
ros2 run bull_ope collect_data --episodes dataset_flat_cut --num 20 --seed 100 \
    --run-name pilot_cut --out src/bull_ope/data/pilot
```

**動作**

- 実行計画を作った後、エピソードの種類が偏らないよう順番を混ぜる。
- 各エピソードのシードは `--seed` から決まる乱数で割り当てる。同じ `--seed` と同じオプションなら、同じ計画が再現される。
- エピソードが1つ終わるごとに、`episodes.jsonl` に1行追記し、経過時間と残り時間の目安をログに出す。
- 失敗・スキップしても次のエピソードに進む（[episodes.md の 1.4](episodes.md#14-失敗スキップの扱い)）。
- 1エピソードには、走行時間に加えて約 10 秒（読み込み直し 約 1.2 秒、待ち時間、地面の高さの計測、排土板の上げ下げ）かかる。

出力の内容は [output_data.md](output_data.md) を参照。
