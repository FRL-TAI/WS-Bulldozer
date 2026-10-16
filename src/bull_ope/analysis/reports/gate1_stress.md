# 関門1：スクリプトの不具合探し

- 実行日：2026/10/16
- Unity 側のコミット：d2ec69c7d4a2fe2989b77450bf59416611c90aa7
- bull_ope 側のコミット：7d8a346fae8d0fb76ca4ba45d69590a636ee8bee
- 結果のフォルダ：`data/validation/stress/<実行日時>/`

## 段階A：1つずつ実行（目で確認）

| エピソード | ターミナルの結果 | 機体の動き（Unity の画面） | Unity の Console の新しいエラー | 判定 |
| --- | --- | --- | --- | --- |
| stress_instant_done | | 走行を始めた瞬間に終わる | なし | |
| stress_error_midrun | | 3 秒走った後、エピソードのコードでエラー | なし | |
| stress_none_command | | 2 秒走った後、機体が止まる| なし | |
| stress_runaway | | フィールドの端より手前で止まった| なし | |
| stress_depth_limits | | 機体が転倒したり、しなかったりする | なし | |
| stress_spin | | 予想通り、地面を引きずりながら旋回していた| なし | |
| stress_heavy_push | | 進めなくなり、40 秒の時間切れで終了 | なし | |
| stress_nan_depth | | 2秒後もブレードはそのままの位置を保ったまま進む | なし | |

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
