# 関門1：スクリプトの不具合探し
- 実行日：2026/10/16
- Unity 側のコミット ： 23891164333da770191d783ff69f759c74d22073
- bull_ope 側のコミット ： 791505cd44ac2d58aed7344306a5492c7c312ed9
- 結果のフォルダ：`data/validation/stress/<実行日時>/`


## 段階A：1つずつ実行（目で確認）
| エピソード | ターミナルの結果 | 機体の動き（Unity の画面） | Unity の Console の新しいエラー | 判定 |
| --- | --- | --- | --- | --- |
| stress_instant_done | `結果: {…}` が出て正常終了 | 排土板を下げてすぐ上げる。走行しない | なし | |
| stress_error_midrun | 約3秒で `ValueError: 試験用のエラー` | 機体と排土板がその場で止まる | なし | |
| stress_none_command | 約2秒で `InvalidCommand: … NoneType を返しました` | 機体が止まる| なし | |
| stress_runaway | `SafetyStop: … 開始位置から 20.x m 離れた` | フィールドの端より手前で止まった| なし | |
| stress_depth_limits | `SafetyStop: 機体が傾いた` | 機体が転倒しない | なし | |
| stress_spin | `結果: {…}` が出て正常終了 | 予想通り、地面を引きずりながら旋回していた。転倒・跳ねがない | なし | |
| stress_heavy_push | `SafetyStop: 排土板が深く入り込んだ` | 機体が止まり終了 | なし | |
| stress_nan_depth | 約2秒で `InvalidCommand: … depth が不正な値です: nan` | 排土板が急に動かず、機体が止まる | なし | |


## 段階B：混在の連続実行
- 点検結果：`check_stress_mix.md`
- 失敗の直後のエピソードも ok になったか：
- 開始位置のばらつき：


## 段階B2：NumPy の型の記録
- 収集が止まったか：
- エラーの内容：


## 段階C：土質の入れ替わり
- 点検結果：`check_stress_soil.md`
- ラベルの不一致：


## 段階D：耐久試験
| 項目 | 最初 | 最後 |
| --- | --- | --- |
| 読み込み直しの時間（Unity の Console） | | |
| Unity のメモリ使用量（タスクマネージャー） | | |
| /clock の周波数 | | |

- Console のメッセージの変化（RealTimeTracker、HUDPanel など）：