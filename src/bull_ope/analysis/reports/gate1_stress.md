# 関門1：スクリプトの不具合探し
- 実行日：2026/10/16
- Unity 側のコミット ： 23891164333da770191d783ff69f759c74d22073
- bull_ope 側のコミット ： 791505cd44ac2d58aed7344306a5492c7c312ed9
- 結果のフォルダ：
  - 段階A：`data/validation/stress/20261016_194312/`
  - 段階B2・B・C・D：`data/validation/stress/20261016_194616/`
- 上の2つのコミットで、段階A〜D をすべて同じ Play の中で実行した（読み込み直し 84 回）


## 段階A：1つずつ実行（目で確認）
| エピソード | ターミナルの結果 | 機体の動き（Unity の画面） | Unity の Console の新しいエラー | 判定 |
| --- | --- | --- | --- | --- |
| stress_instant_done | `結果: {…}` が出て正常終了 | 排土板を下げてすぐ上げる。走行しない | なし | OK |
| stress_error_midrun | 約3秒で `ValueError: 試験用のエラー` | 機体と排土板がその場で止まる | なし | OK |
| stress_none_command | 約2秒で `InvalidCommand: … NoneType を返しました` | 機体が止まる | なし | OK |
| stress_runaway | `SafetyStop: … 開始位置から 20.x m 離れた` | フィールドの端より手前で止まった | なし | OK |
| stress_depth_limits | `結果: {…}` が出て正常終了（`raise_depth_over_max` が記録される） | 機体が転倒しない。走り終えて止まるときに前に傾く | なし | OK（注1） |
| stress_spin | `結果: {…}` が出て正常終了 | 予想通り、地面を引きずりながら旋回していた。転倒・跳ねがない | なし | OK |
| stress_heavy_push | `SafetyStop: 排土板が深く入り込んだ` | 約3秒で機体が止まり終了 | なし | OK（注2） |
| stress_nan_depth | 約2秒で `InvalidCommand: … depth が不正な値です: nan` | 排土板が急に動かず、機体が止まる | なし | OK |

「Console の新しいエラー：なし」は、読み込み直しの直後に毎回出る既知のメッセージ
（`Constraint.Initialize`、`UrdfInertial` / `UrdfJointRevolute`、`Removed 2 disabled shovels`、
`HUDPanel`、`RealTimeTracker`、`Critical Timing Problem`）以外に出ていないことを指す。
`Some objects were not cleaned up` は 84 回の読み込み直しで 0 件。段階A の読み込み直しの時間は 1.21〜1.42 秒。

### CSV の点検（`check_A_recording.md`）
- 記録の周期：8件とも平均 20.0 ms、最大 20.0 ms、50 ms を超える間隔 0 回
- 時刻の逆戻り・重複：0 回。想定外の NaN：なし。指令（cmd_vx、cmd_wz、cmd_lift）の NaN：8件とも 0 行
- 上げる区間：正常終了したエピソードで 151〜153 行（約3秒）
- エラー・安全停止のエピソードは上げる区間が 0 行（その場で止め、次の読み込み直しで戻す設計どおり）
- 走行時間：error_midrun 3.0 s、none_command・nan_depth 2.0 s、spin 15.1 s で、設計どおり
- stress_depth_limits：目標深さの制限 546 行（0.5 m → 0.20 m の区間と、−1.0 m → −0.5 m の区間の両方）
- ラベル：stress_heavy_push の NG は点検の既定値（検証用の土質）と比べたため。
  土質を指定し直すと OK（c = 30000、φ = 45、ρ = 1950）
- 力の向き・速度：check_force_sign.py ○○、check_velocity.py ○○
- WARN（合計 14 件）はすべて説明できる
  - 一定の列：F_def・F_con が常に 0（関門3 で確認する）。ground_profile の遠い位置と ground_ahead は、
    手を付けていない平らな地面を見ているため一定。cmd_vx・cmd_wz はエピソードの設計どおり一定。
    stress_runaway は排土板を上げて空中を走るため、力と cut_volume が一定
  - 進行状況の順番：エラー・安全停止のエピソードは raising がなく、instant_done は running がない（設計どおり）

### 注
1. stress_depth_limits：走行中の深さは制限どおり（最大 20 cm 程度、35 cm 未満）。最大深さ 79.3 cm は上げる区間で、
   走り終えて止まるときに機体が前に倒れ込んだため（不具合5 と同じ現象。上げる区間では深さで止めず、
   raise_depth_over_max に記録する設計どおり）。上げる区間の終わりでも刃先が元の地面より約 50 cm 下に残っており、
   深く沈んだ状態からは RAISE_TIME（3 秒）では上げきれない。次のエピソードは読み込み直しから始まるため、関門1 には影響しない。
   なお、修正前の実行（16:24）では、同じエピソードが走行中に傾きの上限で止まっており、止まり方は実行ごとにばらつく。
2. stress_heavy_push：0.8 m/s で硬く重い土を押すと、約3秒で前傾して刃先が沈み、深さの上限（35 cm）で止まる（最大 37.7 cm）。
   安全装置は想定どおり働いた。安全の制限を入れたため、「進めなくても時間切れ（40 秒）で終わるか」の経路は
   このエピソードでは試されない。
3. 記録の最初の深さが、どのエピソードでも約 13 cm ある（シーンの読み込み直し直後の排土板の位置が、
   基準の地面の高さ ground_h0 より低い）。下げる区間は学習に使わないので関門1 には影響しない。
   深さ 0 の基準の確認として関門3 に引き継ぐ。


## 段階B：混在の連続実行
- 点検結果：`check_stress_mix.md`（想定外・要確認の項目：0 件）
- 実行したエピソード：val_constant_depth、stress_error_midrun、stress_none_command、stress_runaway、stress_instant_done を各3回、順番を混ぜて 15 件
- 結果：error になるべき9件（error_midrun・none_command・runaway）はすべて error、残りの6件はすべて ok
- 失敗の直後のエピソードも ok になったか：なった（番号 2→3、4→5、8→9、10→11 など、error の直後もすべて ok）
- 開始位置のばらつき：最大 0.09 cm、向き 0.037°（許容 2 cm、0.5°）
- ラベルと要求した土質の一致：不一致 0 件
- 時系列データ：15 件とも問題なし（sim_time の逆戻り・主な列と指令の NaN なし）
- episodes.jsonl：15 行。status の日本語のエラーメッセージ（「試験用のエラー（走行中に発生）」など）がそのまま読める


## 段階B2：NumPy の型の記録
- 収集が止まったか：止まらない（修正後。修正前は `TypeError: Object of type int64 is not JSON serializable` で収集全体が止まっていた）
- エラーの内容：なし（結果 ok、想定外・要確認の項目 0 件）
- 記録のされ方：`"param_n_segments": 4`（整数）、`"param_depths": [0.0596…, 0.0230…, 0.0593…]`（数値のリスト）
- episodes.jsonl：1 行


## 段階C：土質の入れ替わり
- 点検結果：`check_stress_soil.md`（想定外・要確認の項目：0 件）
- 実行したエピソード：stress_soil_extremes を 10 回（c 134〜39430 Pa、φ 17.4〜47.0°、ρ 1120〜1970 kg/m³、
  膨張率 1.003〜1.567、ヤング率 2.8〜20.0 MPa）
- ラベルの不一致：0 件（AGX から読み戻した値が、要求した値と浮動小数点の誤差の範囲で一致）
- 結果：10 件とも ok（約 20 秒で 10 m を走行）
- 開始位置のばらつき：最大 0.17 cm、向き 0.062°


## 段階D：耐久試験
stress_short（2 秒だけ走る）を 50 回。この時点で、同じ Play の中の読み込み直しは通算 35〜84 回目。

| 項目 | 最初 | 最後 |
| --- | --- | --- |
| 1エピソードの実時間（stress_endurance.log の開始時刻の差） | 11.9〜13.1 秒 | 11.9〜13.1 秒 |
| 1エピソードのシミュレーション時刻（sim_time 開始の差） | 約 10.4 秒 | 約 10.5 秒 |
| 読み込み直しの時間（Editor.log） | 1.08〜1.33 秒 | 1.13〜1.17 秒 |
| Unity のメモリ使用量（Editor.log の Memory consumption） | 約 390 MB（Play 開始直後） | 380〜470 MB を上下（増え続けてはいない） |
| /clock の周波数 | 46.9 Hz | 36.1 Hz |
| 画面の更新の速さ（Editor.log、ゲーム1秒あたりのフレーム数） | 約 53（35 回目）※Play 開始直後は約 108 | 約 37（84 回目） |
| ROS-TCP-Endpoint との接続の数（/proc/net/tcp） | 1 | 1 |

- 結果：50 件すべて ok。点検結果 `check_stress_endurance.md` の想定外・要確認の項目 0 件
- 開始位置のばらつき：最大 0.10 cm、向き 0.074°
- Console のメッセージの変化：
  - `Some objects were not cleaned up` は 0 件のまま
  - `RealTimeTracker` / `Critical Timing Problem` は読み込み直しのたびに同じ内容で出る（変化なし）
  - `HUDPanel … Registering at index N` の N が読み込み直しのたびに1ずつ増え、84 回目で 84。
    画面左上の「ROS2 IP」の表示も同じ数だけ重なる
- 判断：
  - シミュレーションの速さは保たれている（1エピソードの実時間・シミュレーション時刻とも一定）。記録したデータは
    シミュレーション時刻で 50 Hz、取りこぼし 0 回で、データへの影響はない
  - /clock の低下は、画面の更新の速さが 50 回/秒を下回ったことによるもの（/clock は画面の更新1回につき最大1回送られる）
  - 画面の更新の速さは、読み込み直し1回あたり約 0.85 ずつ下がり続ける。原因は HUD 表示（ROS2 IP）の積み重なりと
    考えられ、本番の収集（数百回の読み込み直し）の前に対応する（「持ち越す問題」を参照）


## 見つかった不具合と対応
| # | 不具合 | 見つかった段階 | 対応 | 修正のコミット |
| --- | --- | --- | --- | --- |
| 1 | 目標深さが NaN のとき、NaN の指令が OperaSim に送られる | A | runner.py で指令を確認し、NaN・無限大・Command 以外なら InvalidCommand で止める。sim_interface.py でも送る前に確認する | bull_ope：○○ |
| 2 | 力の内訳の符号がそろっていない（分離抵抗などが逆向き） | A | BladeStatePublisher.cs で、4つの力を「排土板が土から受ける力」にそろえる | Unity：○○ |
| 3 | global_pose の速度の欄が 0 のまま | A | 位置と向きの変化から速度を計算する（sim_interface.py） | bull_ope：○○ |
| 4 | 記録の周期が 50 Hz になっていない | A | blade_state を基準に毎回1行書く（recorder.py） | bull_ope：○○ |
| 5 | 深すぎる目標で転倒する。上げる区間が深さの上限で途中で止まる | A | 目標深さを −0.5〜0.20 m に制限し、傾き・実際の深さの上限で SafetyStop。上げる区間は深さで止めず raise_depth_over_max に記録する | bull_ope：○○ |
| 6 | NumPy の型を含むエピソードで、collect_data が JSON の変換で止まる | B2 | 記録の前に to_jsonable() で普通の型に変換し、変換できなくても収集を止めない | bull_ope：○○ |
| 7 | シーンの読み込み直し・Play の停止で AGXUnity.Simulation が作り直され、次のシーンで SolverSettings が反映されない可能性があった（ImuSensor.OnDisable が Simulation.HasInstance を確かめていなかった） | A（Console の `Some objects were not cleaned up`） | Simulation.HasInstance で確かめてから登録を外す | Unity：○○ |
| 8 | 新しいプロセスの最初の reload が Unity に届かず、読み込み直しが TimeoutError になることがあった（/sim/episode_cmd の送信者がつながる前に1回だけ送っていた） | A（stress_none_command） | wait_ready で episode_cmd の購読者がいることを確かめてから進む | bull_ope：○○ |
| 9 | 読み込み直しのたびに ROS-TCP-Endpoint との古い接続が閉じられずに残る（10 回で 7 本、Play 停止後も残る）。そのため、まれに ROS → Unity の指令が十数秒止まり、設定が時間切れになる（段階D の 50 回中 1 回） | D | SceneReloader.Reload() で、読み込み直しの前に ROSConnection.Disconnect() を呼ぶ。20 回・84 回の読み込み直しで接続は常に1本 | Unity：○○ |
| 10 | Unity 側の setup の失敗が ROS 側では単なる時間切れに見え、エラーの内容が分からない | D（9 の調査中） | setup の失敗も request_id を付けて状態を返す（SimEpisodeManager.cs）。あわせて SETUP_TIMEOUT を 10 秒から 30 秒に延ばす（config.py） | Unity：○○、bull_ope：○○ |

### 9 の調査の記録
- 失敗した回（通算 54 回目の読み込み直しの後）は、Unity 側に例外がなく、ROS-TCP-Endpoint のログでも
  新しい接続と /sim/episode_cmd の登録は 0.03 秒で正常に終わっていた。その後の約 17 秒間、ROS → Unity の方向だけが止まり
  （設定の指令 11 回が届かず、次の読み込み直しの指令も約 5 秒遅れた）、その後に自然に戻った
- ROSConnectionPrefab(Clone) はシーンの一部として作られ、読み込み直しのたびに破棄・再作成される。
  ROS-TCP-Connector の ROSConnection には OnDestroy がなく、Disconnect() は OnApplicationQuit でしか呼ばれない。
  接続を管理するスレッドは GameObject とは別に動いているため、破棄されても止まらず、接続も開いたまま残っていた
- 確認：ROS-TCP-Endpoint のログで Connection 50 回に対し Disconnected 約 23 回。/proc/net/tcp で数えた接続は
  10 回の読み込み直しで 1 → 7 本に増え、Play を止めても 6 本残った。修正後は常に 1 本、Play 停止後 0 本


## 持ち越す問題（関門1 の範囲外、または後で対応）
| 問題 | 影響 | 引き継ぎ先 |
| --- | --- | --- |
| HUD 表示（ROS2 IP）が読み込み直しのたびに積み重なり、画面の更新の速さが下がり続ける（Play 開始直後 約 108 → 84 回目 約 37 フレーム/ゲーム秒） | 今はシミュレーションの速さ・データに影響なし。本番の数百回では、指令の遅れや、シミュレーションの遅れにつながるおそれ | 段階7（試験的な収集）の前に対応する。まず Robotics → ROS Settings の Show HUD を外して確かめる |
| 記録の最初の深さが約 13 cm（読み込み直し直後の排土板の位置が ground_h0 より低い） | 下げる区間は学習に使わないので影響なし | 関門3（深さ 0 の基準） |
| F_def・F_con が常に 0 | 4つの力の内訳のうち2つが使われていない可能性 | 関門3（力の向き・内訳） |
| 深く沈んだ状態からは、上げる区間（RAISE_TIME = 3 秒）で刃先を地面の上まで上げきれない | 次のエピソードは読み込み直しから始まるため、今は影響なし | 必要になれば RAISE_TIME を見直す |
| stress_heavy_push で「時間切れで終わる」経路が試されない | 安全の制限が先に働くため | 必要になれば、浅い深さ・低い速度の試験用エピソードを追加する |
| ParticleEmitter.cs の OnDestroy にも、不具合 7 と同じ書き方（Simulation.HasInstance を確かめない）がある | DataCollectionScene では使われていないので影響なし | 粒子の放出を使うシーンを作るときに直す |
| check_recording.py のラベルの確認が、既定で検証用の土質と比べる | 土質を変えるエピソードでは NG と出る（今回は stress_heavy_push） | 必要になれば、episodes.jsonl や CSV の要求値と比べるように直す |


## 修正前の実行（参考。正式な結果には使わない）
| 実行 | 結果のフォルダ | 内容 |
| --- | --- | --- |
| 段階A（16:24） | `20261016_162439/` | ターミナルの結果は最終版と同じ。ただし読み込み直し 8 回のうち 3 回と Play の停止時に `Some objects were not cleaned up`（不具合 7）が起きていた |
| 段階A（17:47） | （中断） | stress_none_command で読み込み直しの指令が届かず TimeoutError（不具合 8）。途中で中断 |
| 段階A（18:00） | `20261016_180045/` | 不具合 7・8 の修正後。最終版と同じ結果 |
| 段階B2・B・C・D（18:17） | `20261016_181726/` | B2・B・C は合格。D で 50 回中 1 回、設定の応答が時間切れ（不具合 9）。読み込み直し 76 回で画面の更新の速さが 約 105 → 約 58 に低下 |


## 関門1 の判定
| 合格の条件 | 結果 |
| --- | --- |
| 1. 段階A〜D のすべての結果が、想定どおりか、想定と違う理由を説明できる | 満たす（段階A の注1〜3 を含め、すべて説明できる） |
| 2. 見つかった不具合がすべて修正され、修正後の再試験で直ったことを確認した | 満たす（不具合 1〜10 を修正し、上記のコミットで段階A〜D を通しで再実行） |
| 3. 段階D で、読み込み直しを 50 回繰り返しても、時間・メモリ・シミュレーションの速さに劣化がない | 時間・メモリ・シミュレーションの速さは劣化なし。画面の更新の速さは低下する（持ち越す問題として記録） |

判定：**合格**。ただし、HUD 表示の積み重なりによる画面の更新の速さの低下は、段階7（試験的な収集）の前に対応する。
次は関門2（`val_*` による記録の健全さ）に進む。