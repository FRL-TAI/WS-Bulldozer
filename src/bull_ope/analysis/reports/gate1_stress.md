# 関門1：スクリプトの不具合探し

- 実行日：
- Unity 側のコミット：
- bull_ope 側のコミット：
- 結果のフォルダ：`data/validation/stress/<実行日時>/`

## 段階A：1つずつ実行（目で確認）

| エピソード | ターミナルの結果 | 機体の動き（Unity の画面） | Unity の Console の新しいエラー | 判定 |
| --- | --- | --- | --- | --- |
| stress_instant_done | | | | |
| stress_error_midrun | | | | |
| stress_none_command | | | | |
| stress_runaway | | | | |
| stress_depth_limits | | | | |
| stress_spin | | | | |
| stress_heavy_push | | | | |
| stress_nan_depth | | | | |

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

## 見つかった不具合と対応

| # | 不具合 | 見つかった段階 | 対応 | 修正のコミット |
| --- | --- | --- | --- | --- |
| 1 | | | | |
