# 検証
[← bull_ope のドキュメントの入口](../README.md)

学習データを集める前に、「記録の仕組みが壊れていないか」から「土質を反力から区別できるか」までを、7つの関門で順に確かめた。前の関門を通ったものだけを、次の関門で使う。

1. [関門の一覧と結論](#1-関門の一覧と結論)
2. [検証の道具](#2-検証の道具)


## 1. 関門の一覧と結論
| 関門 | 確かめたこと | 使ったエピソード | 主な結論 | レポート |
| --- | --- | --- | --- | --- |
| 1 | スクリプトの不具合（失敗しても次に影響しないか、おかしな値が送られないか、長く続けても劣化しないか） | `stress_*` | 10 件の不具合を見つけて修正した（NaN の指令、力の符号、ROS の接続の漏れ、HUD の積み重なりなど）。修正後、読み込み直し 84 回で劣化なし | [gate1_stress.md](gate1_stress.md) |
| 2 | 記録の健全さ（抜け・食い違いがないか） | `val_*` | 記録は健全。global_pose・joint_states は約 38 Hz で届き、最大 6 行同じ値が続く | [gate2_recording.md](gate2_recording.md) |
| 3 | 単位・座標・符号 | `val_*`、`ex_back_blading`、`ex_turning` | 誤りなし。`ground_below` は削った後の地面ではないので `ground_behind` を追加。`LIFT_KP` を 3.0 に。`F_def`・`F_con` が 0 の理由を特定 | [gate3_units_frames.md](gate3_units_frames.md) |
| 4 | 時間のずれ | `val_*`、`ex_stop_and_go` | joint_states・global_pose は 20 ms、計算した速度は約 60 ms 遅れる。値はずらさず、時間窓を 1.2 秒以上にする | [gate4_timing.md](gate4_timing.md) |
| 5 | 物理的な妥当性（土の力学の式・力のつり合い） | `val_constant_depth_*` | 前後の力 ≒ 小さな切り崩しの抵抗 ＋ 土の山の質量 × g × tanφ（傾き 1.05 倍）。約 20 kN で頭打ち。FEE のくさびの抵抗は主な成分ではない | [gate5_physics.md](gate5_physics.md) |
| 6 | 再現性と識別可能性（土質を変えると区別できるほど反力が変わるか） | `val_sens_*` | c は貫入抵抗、ρ は頭打ちの上下の力で区別できる。φ は感度が低い（1エピソードで約 9°）。速度が頭打ちの前後の力に大きく効く | [gate6_sensitivity.md](gate6_sensitivity.md) |
| 7 | 試験的な収集（本番と同じやり方で問題がないか） | `flat_cut`、`flat_piecewise`、`pile_push` | 30 件すべて ok。関門5・6の関係が、土質・速度を同時に変えても成り立つ（決定係数 0.95〜0.99）。`pile_push` は範囲を狭めて追加のデータとする | [gate7_pilot.md](gate7_pilot.md) |

各レポートは「目的 → 手段（実行したコマンド） → 結果 → 考察 → 判定」の順に書いている。結果のデータは `src/bull_ope/data/validation/`（関門1〜6）と `src/bull_ope/data/pilot/`（関門7）にある（Git の管理外）。


## 2. 検証の道具
`src/bull_ope/analysis/` 以下にある。ROS2 のパッケージとしてはインストールされないので、ビルドせずに `python3` や `bash` で実行する。点検のスクリプトは、どれも `collect_data` の出力フォルダ（または CSV）を引数にとり、`--report 結果.md` で結果を Markdown に保存できる。

```
cd /workspaces/ws-bulldozer/src/bull_ope
python3 analysis/checks/<スクリプト> <出力フォルダ> --report <出力フォルダ>/<結果>.md
```

### 2.1 点検のスクリプト（`analysis/checks/`）
| スクリプト | 使った関門 | 調べること | 判定 |
| --- | --- | --- | --- |
| `check_collection.py` | 1〜7 | エピソードの結果（ok / error / skipped）が想定どおりか、開始位置・向きのばらつき（許容 2 cm、0.5°）、ラベルと要求した土質の一致、時系列データの行数・NaN | 想定外・要確認の件数 |
| `check_recording.py` | 1〜3、7 | CSV ごとに、記録の周期（50 Hz）、時刻の逆戻り・重複、想定外の NaN、走行中に一定の列、ラベル（既定で dirt_1 と比べる。`--no-label` で飛ばす）、進行状況の順番、走行時間 | OK / WARN / NG |
| `check_gate2.py` | 2〜7 | G1 列の構成、G2 行数の一致、G3 メタ情報の一致、G4 時刻の整合、G5 トピックの更新（同じ値の連続・遅れ）、G6 区間の長さ、G7 繰り返しの差 | OK / WARN / NG |
| `check_units.py` | 3、7 | U1 空中の力、U2 押土の力の向き、U3 深さの追従、U4 刃先と削った後の地面、U5 速度と距離、U6 座標の整合、U7 値の範囲、U8 力の内訳（参考）、U9 記録の最初の状態（参考） | OK / WARN / NG / 参考 |
| `inspect_depth.py` | 3 | 深さのずれの揺れ方（周期、ピッチとの相関）、刃先と地面の高さの関係、下げる区間。`--plot` で図を保存 | 判定なし |
| `check_timing.py` | 4、7 | T1 global_pose の遅れ、T2 届く間隔、T3 速度の指令 → 車体の速度、T4 排土板の指令 → 刃先の動き、T5 トピックの間の遅れ（相互相関） | 判定なし |
| `check_physics.py` | 5 | P1 削った体積と前後の力、P2・P3 削り始めの力と FEE、P4 上下と前後の力の比、P5 履帯の駆動力のつり合い、P6 排土板を支える力。1つの土質のデータが前提。`--plot` で図を保存 | 判定なし |
| `check_sensitivity.py` | 6 | 条件ごとの特徴量（`Fpen`、`Fx_sat`、`Fz_sat` など）、基準の繰り返しのばらつき、基準との差 z | \|z\| ≥ 3 を区別できるとみなす |
| `check_dataset.py` | 7、本番 | D1 結果の内訳、D2 土質の広がり、D3 関門5・6の関係（`flat_cut` を対象に回帰）、D4 本番の見積もり（`--target` で件数を指定） | 判定なし |

`check_physics.py`・`check_sensitivity.py`・`check_dataset.py` は互いの関数を使うので、同じフォルダに置いたまま使う。

### 2.2 実行のスクリプト（`analysis/scripts/`）
| スクリプト | 内容 |
| --- | --- |
| `run_stress_tests.sh` | 関門1の段階A〜D（`stress_*`）をまとめて実行し、点検まで行う。`bash src/bull_ope/analysis/scripts/run_stress_tests.sh [A B B2 C D]`。`PAUSE=1` で段階A を1件ずつ止める。結果は `data/validation/stress/<実行日時>/` |
| `dryrun_stress.py` | Unity を使わずに、疑似の機体で各エピソードを `runner.py` に通し、例外の種類と記録の流れを数秒で確かめる。物理は再現しない。`runner.py` などを変えたときに、Unity で試す前に使う |

### 2.3 Unity 側での確認
| 確認 | 方法 | 使った関門 |
| --- | --- | --- |
| Console の `Some objects were not cleaned up` | Console の検索欄に `cleaned up` と入れる | 1 |
| ROS-TCP-Endpoint との接続の数 | コンテナ内で `awk '$2 ~ /:2710$/ && $4 == "01"' /proc/net/tcp /proc/net/tcp6 \| wc -l`（常に 1 が正常） | 1、7 |
| 画面の更新の速さ・読み込み直しの時間・メモリ | Editor.log（`%LOCALAPPDATA%\Unity\Editor\Editor.log`）の `RealTimeTracker`・`SceneReloader`・`Memory consumption` の行 | 1 |
| 排土板と地形の接触点 | `AGXUnity.Rendering.DebugRenderManager` の Render contacts をオンにして Scene ビューで見る（確認後に `git restore` でシーンを戻す） | 3 |
