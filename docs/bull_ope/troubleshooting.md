# トラブルシューティング
[← bull_ope のドキュメントの入口](README.md)

## 起動・通信
| 症状 | 確かめること |
| --- | --- |
| 「受信待ち: […]」が続く | Unity が Play 中か。ROS-TCP-Endpoint が動いているか。`DataCollection` のコンポーネントが有効か。`ros2 topic list` に該当のトピックがあるか |
| 「受信待ち: … episode_cmd の購読（Unity 側）」が続く | Unity の `SimEpisodeManager` が `/sim/episode_cmd` を購読していない。Play と ROS-TCP の接続を確かめる |
| 「シーンの読み込み直しが完了しません」 | `SimEpisodeManager` が `reload` を受け取っているか、`SceneReloader` が付いているか。Unity の Console に「シーン … を読み込み直します」が出ているか |
| 「Unity から設定完了の応答がありません」 | `SimEpisodeManager` が動いているか（`ros2 topic echo /sim/episode_status`）。ROS-TCP-Endpoint との接続が増え続けていないか（下の行） |
| 「Unity でエラー: …」 | Unity 側の `setup` の処理で例外が出ている。Unity の Console のエラーの全文を見る |
| 「… が反映されていません（要求 …, AGX …）」 | Unity 側で土質の設定に失敗している。Unity の Console と画面右下の表示を見る |
| ROS-TCP-Endpoint との接続が増え続ける | コンテナ内で `awk '$2 ~ /:2710$/ && $4 == "01"' /proc/net/tcp /proc/net/tcp6 \| wc -l`（`ss` がない環境用）。常に 1 が正常。増える場合は Unity 側の `SceneReloader` で読み込み直しの前に `ROSConnection.Disconnect()` を呼んでいるか（関門1） |
| 読み込み直しを重ねると Unity の画面の更新が遅くなる | HUD 表示（画面左上の「ROS2 IP」）が積み重なっている。Unity 側の `SceneReloader` で HUD の見出しを空にしているか（関門1） |
| Unity の Console に `Some objects were not cleaned up when closing the scene` | 破棄のときに `Simulation.Instance` を確かめずに使っているスクリプトがある（関門1で `ImuSensor.cs` を修正）。Unity 側の `docs/tips/simulation_recreated_on_destroy.md` |

## エピソードの実行
| 症状 | 確かめること |
| --- | --- |
| `InvalidCommand: …` | エピソードの `operation()` が `Command` 以外（`None` など）や NaN を返している |
| `SafetyStop: … 開始位置から … 離れた` | `SAFE_RADIUS`（20 m）を超えた。エピソードの走行距離を見直す |
| `SafetyStop: 排土板が深く入り込んだ` | 深すぎる目標、または大きな土の山に速く当たって機体が前に傾いた（関門1・7）。深さや土の山の大きさの範囲を見直す |
| `SafetyStop: 機体が傾いた` | 同上 |
| 排土板が下がらず上がっていく | `LIFT_SIGN` の向きが逆。`test_episode --calibrate` で確かめる |
| 排土板が目標の深さで振動する、追従が遅い | `LIFT_KP`、`LIFT_VMAX` を調整する。速い速度（0.7 m/s 以上）では深さの揺れが大きくなるのは既知の性質（関門7） |
| 走行中に止まったまま進まない | Unity の Play が一時停止していると、シミュレーション時刻が進まず待ち続ける |
| 締固めの操作が必要なエピソード（`pile_push` など）がスキップされる | Unity 側で `AGX_GRID_CONTROL` が無効。Player Settings の Scripting Define Symbols を確かめる |
| 速度が指令より遅い | 履帯の関節の力には約 60,000 N·m の上限がある。重い土・深い・速いの組み合わせで上限に張り付いていないか（関門7では速度の比 0.99 以上で問題なし） |

## 点検・データ
| 症状 | 確かめること |
| --- | --- |
| 点検のスクリプトが `KeyError: 'sim_time'` で止まる | `ep*.csv` の指定に `episodes.csv` が含まれている。`ep[0-9]*.csv` と指定する |
| `check_recording.py` のラベルが NG になる | 既定で dirt_1 の土質と比べるため。土質が毎回違うデータでは `--no-label` を付ける（ラベルは `check_collection.py` で確かめる） |
| `check_gate2.py` の G7（繰り返しの差）が WARN | 速度がエピソードごとに違うデータでは当てはまらない（同じ条件の繰り返しを前提にした点検） |
| `check_physics.py` の P1〜P4 の値がおかしい | 1つの土質を前提にした計算なので、土質が混ざったデータには使えない。`check_dataset.py` の D3 を使う |
| `F_def_*`、`F_con_*` が常に 0 | このシミュレーションの性質（関門3）。前に削る動きの力は `F_pen` と `F_sep` で表される |
| 記録の最初の `depth` が約 13 cm | シーンの初期状態で排土板が地面にめり込んでいるため（関門3）。下げる区間は学習に使わない |

## 既知の制約
- 使っている AGX Dynamics 2.37.3.0 には、締固めの程度に応じたダイレイタンシー角の計算に不具合がある可能性がある（2.38.0.0 で修正）。削る・押すうちに締固めの程度が変わるので、反力に影響している可能性がある。特に `pile_push`（緩い土の山）は影響を受けやすいと考えられる。
- 地形は 0.3125 m のマスでできていて、前後方向に 31 cm より細かい変化は表せない。
- 履帯の転がり抵抗が大きい（係数 約 0.29。実機は土の上で 0.1 前後）。駆動力から排土板の力を推定する場合は補正が必要（関門5）。
