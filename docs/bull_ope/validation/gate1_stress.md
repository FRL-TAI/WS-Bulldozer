# 関門1：スクリプトの不具合探し
[← 検証のドキュメント](README.md)

| 項目 | 内容 |
| --- | --- |
| 前提 | なし（最初の関門） |
| 使うエピソード | `stress_*`（[一覧](../episodes.md#33-検証用validation)） |
| 主な道具 | `run_stress_tests.sh`、`check_collection.py`、`check_recording.py`、Unity の Editor.log |
| 結果の保存先 | `data/validation/stress/<実行日時>/` |
| 所要時間の目安 | 段階A 約 10 分、段階B2〜D 約 30 分 |
| 検証した環境 | Unity 2022.3.16f1、AGX Dynamics 2.37.3.0（AGXUnity 5.0.1）、ROS2 Humble |


## 1. 目的
学習データを何百回も自動で集める前に、収集のスクリプトそのものに不具合がないかを確かめる。具体的には次の3点。

1. エピソードが失敗しても（例外、不正な指令、安全停止）、収集が止まらず、次のエピソードが正常に始まるか
2. おかしな値（NaN、制限を超える深さ）が OperaSim に送られたり、記録されたりしないか
3. シーンの読み込み直しを何十回も繰り返しても、時間・メモリ・速さが劣化しないか


## 2. 手段
わざと失敗しやすい条件を作るエピソード（`stress_*`、[一覧](../episodes.md#33-検証用validation)）を、4つの段階で実行した。段階A〜D は `run_stress_tests.sh` でまとめて実行し、同じ Play の中で続けて行った（読み込み直し 84 回）。

| 段階 | 内容 | 確かめること |
| --- | --- | --- |
| A | `stress_*` 8 種類を `test_episode` で1つずつ実行し、Unity の画面を見る | 失敗の種類が想定どおりか、機体の動き、Console のエラー |
| B2 | `stress_numpy_params` を `collect_data` で実行 | NumPy の型を含むパラメータで記録が止まらないか |
| B | 失敗するエピソードと普通のエピソードを混ぜて 15 件連続で実行 | 失敗の直後のエピソードが正常に始まるか |
| C | `stress_soil_extremes` を 10 回 | 土質が毎回正しく入れ替わるか |
| D | `stress_short`（2 秒だけ走る）を 50 回 | 読み込み直しの耐久性 |

```
cd /workspaces/ws-bulldozer
bash analysis/validation/run_stress_tests.sh A          # 段階A（Unity の画面を見ながら）
bash analysis/validation/run_stress_tests.sh B2 B C D   # 段階B2〜D（約30分）

# 段階A の CSV の点検
R=data/validation/stress/<段階A の実行日時>
python3 analysis/validation/check_recording.py $R/A/*.csv --report $R/check_A_recording.md
python3 analysis/validation/check_recording.py $R/A/*stress_heavy_push.csv --c 30000 --phi 45 --rho 1950

# 段階D の間、別のターミナルで ROS-TCP-Endpoint との接続の数を見張る
while true; do echo "$(date +%T)  接続数: $(awk '$2 ~ /:2710$/ && $4 == "01"' /proc/net/tcp /proc/net/tcp6 | wc -l)"; sleep 5; done
```

`run_stress_tests.sh` は、各段階の後に `check_collection.py` で結果が想定どおりかを点検し、段階D の前後で `/clock` の周波数を測る。段階D の後は、Unity の Editor.log から、読み込み直しの時間、画面の更新の速さ（`RealTimeTracker` の行のフレーム番号の差 ÷ ゲーム時間の差）、メモリを読み取った。


## 3. 結果
### 段階A：1つずつ実行
| エピソード | ターミナルの結果 | 機体の動き | 判定 |
| --- | --- | --- | --- |
| `stress_instant_done` | 正常終了 | 排土板を下げてすぐ上げる。走らない | OK |
| `stress_error_midrun` | 約 3 秒で `ValueError` | 機体と排土板がその場で止まる | OK |
| `stress_none_command` | 約 2 秒で `InvalidCommand: … NoneType を返しました` | 機体が止まる | OK |
| `stress_runaway` | `SafetyStop: … 開始位置から 20.x m 離れた` | フィールドの端より手前で止まる | OK |
| `stress_depth_limits` | 正常終了。目標の深さの制限 546 行 | 転倒しない。走り終えて止まるときに前に傾く | OK（注1） |
| `stress_spin` | 正常終了 | 地面を引きずりながら旋回。転倒・跳ねなし | OK |
| `stress_heavy_push` | 約 3 秒で `SafetyStop: 排土板が深く入り込んだ`（37.7 cm） | 前に傾いて止まる | OK（注2） |
| `stress_nan_depth` | 約 2 秒で `InvalidCommand: … depth が不正な値です: nan` | 排土板が急に動かず、機体が止まる | OK |

- CSV の点検：8 件とも記録の周期 20.0 ms、50 ms を超える間隔 0 回、時刻の逆戻り・重複 0 回、想定外の NaN なし、指令の NaN 0 行（OK 41 / WARN 14 / NG 1。NG は `stress_heavy_push` のラベルを dirt_1 と比べたためで、土質を指定し直すと OK）
- 注1：最大深さ 79.3 cm は走行中ではなく上げる区間で、走り終えて急に止まるときに機体が前に倒れ込んだため。上げる区間では深さで止めず `raise_depth_over_max` に記録する設計どおり
- 注2：安全装置は想定どおり働いた。そのため「進めなくても時間切れで終わるか」の経路は、このエピソードでは試されない

### 段階B2・B・C
| 段階 | 結果 |
| --- | --- |
| B2 | ok。`param_n_segments` は整数、`param_depths` は数値のリストとして記録された |
| B | 15 件すべて想定どおり（error になるべき 9 件は error、残り 6 件は ok）。error の直後のエピソードもすべて ok。開始位置のばらつき 0.09 cm |
| C | 10 件すべて ok。AGX から読み戻した土質と要求の不一致 0 件 |

### 段階D：読み込み直しの耐久試験（不具合 1〜10 を直した後）
| 項目 | 最初 | 最後 |
| --- | --- | --- |
| 結果 | — | 50 件すべて ok |
| 1エピソードの実時間 | 11.9〜13.1 秒 | 11.9〜13.1 秒 |
| 読み込み直しの時間 | 1.08〜1.33 秒 | 1.13〜1.17 秒 |
| メモリ | 約 390 MB | 380〜470 MB を上下（増え続けない） |
| ROS-TCP-Endpoint との接続の数 | 1 | 1 |
| `Some objects were not cleaned up` | 0 件 | 0 件 |
| 画面の更新の速さ（HUD の修正前） | 約 108 フレーム/ゲーム秒（Play 開始直後） | 約 37（84 回目） |

### 見つかった不具合と対応
| # | 不具合 | 見つかった段階 | 対応（直したファイル） |
| --- | --- | --- | --- |
| 1 | 目標の深さが NaN のとき、NaN の指令が OperaSim に送られる | A | 指令を確認し、NaN・無限大・Command 以外なら `InvalidCommand` で止める。送る直前にも確認（`runner.py`、`sim_interface.py`） |
| 2 | 力の内訳の符号がそろっていない（分離抵抗などが逆向き） | A | 4つの力を「排土板が土から受ける力」にそろえる（Unity：`BladeStatePublisher.cs`） |
| 3 | global_pose の速度の欄が 0 のまま | A | 位置と向きの変化から速度を計算する（`sim_interface.py`） |
| 4 | 記録の周期が 50 Hz になっていない | A | `blade_state` を基準に毎回1行書く（`recorder.py`）。Unity 側の配信の判定に半ステップの余裕を入れる |
| 5 | 深すぎる目標で転倒する。上げる区間が深さの上限で途中で止まる | A | 目標の深さを −0.5〜0.20 m に制限し、傾き・実際の深さの上限で `SafetyStop`。上げる区間は深さで止めず記録する（`runner.py`、`config.py`） |
| 6 | NumPy の型を含むパラメータで、JSON の変換に失敗して収集全体が止まる | B2 | 書き出す前に普通の型に変換し、失敗しても収集を止めない（`json_utils.py`、`collect_data.py`） |
| 7 | シーンを閉じるときに `AGXUnity.Simulation` が作り直され、次のシーンで設定が反映されない可能性があった | A（Console の `Some objects were not cleaned up`） | `Simulation.HasInstance` を確かめてから登録を外す（Unity：`ImuSensor.cs`） |
| 8 | 新しいプロセスの最初の `reload` が Unity に届かず、時間切れになることがあった | A | `/sim/episode_cmd` の購読者がいることを確かめてから進む（`sim_interface.py` の `wait_ready`） |
| 9 | 読み込み直しのたびに ROS-TCP-Endpoint との古い接続が残る（10 回で 7 本、Play 停止後も残る）。まれに ROS → Unity の指令が十数秒止まり、設定が時間切れになる（段階D の 50 回中 1 回） | D | 読み込み直しの前に `ROSConnection.Disconnect()` を呼ぶ（Unity：`SceneReloader.cs`）。修正後は 84 回で接続は常に 1 本 |
| 10 | Unity 側の `setup` の失敗が ROS 側では単なる時間切れに見える | D（9 の調査中） | `setup` の失敗も `request_id` を付けて返す（Unity：`SimEpisodeManager.cs`）。`SETUP_TIMEOUT` を 10 → 30 秒（`config.py`） |
| 11 | 画面左上の HUD 表示（ROS2 IP）が読み込み直しのたびに積み重なり、画面の更新の速さが下がり続ける | D | 読み込み直しの前に、ROS-TCP-Connector の HUD の見出しの一覧を空にする（Unity：`SceneReloader.cs`）。修正後は、global_pose などの届く頻度が収集の間ずっと一定（関門2） |


## 4. 考察
- **失敗が次に影響しない仕組みは、シーンの読み込み直しで成り立っている。** 失敗の直後でも開始位置のばらつきは 0.1 cm 程度で、AGX の内部状態も含めて毎回同じ状態から始まる。
- **不具合の多くは「失敗したとき」と「繰り返したとき」に表れた。** 1回だけ動かす試験では見つからない不具合（接続の漏れ、HUD の積み重なり、最初の `reload` が届かない）が、段階D の耐久試験で見つかった。本番の数百回の収集の前に、この段階を通したことに意味があった。
- **接続の漏れ（不具合 9）は原因の特定に時間がかかった。** Unity 側にも ROS 側にもエラーが出ず、「ROS → Unity の方向だけが十数秒止まる」という症状だけだった。ROS-TCP-Endpoint のログの `Connection`／`Disconnected` の数の食い違いと、`/proc/net/tcp` で数えた接続の数から、ROS-TCP-Connector の `ROSConnection` が破棄のときに接続を閉じないことが分かった。
- **画面の更新の速さの低下（不具合 11）は、シミュレーションの速さには影響していなかった。** 1エピソードの実時間とシミュレーション時刻は一定で、物理のステップは実時間に追いついていた。ただし本番の数百回では、指令の遅れなどにつながるおそれがあったため直した。


## 5. 判定
| 合格の条件 | 結果 |
| --- | --- |
| 段階A〜D のすべての結果が想定どおりか、理由を説明できる | 満たす |
| 見つかった不具合がすべて修正され、修正後の再試験で直ったことを確かめた | 満たす（不具合 1〜11） |
| 読み込み直しを繰り返しても、時間・メモリ・シミュレーションの速さが劣化しない | 満たす |

**合格**。
