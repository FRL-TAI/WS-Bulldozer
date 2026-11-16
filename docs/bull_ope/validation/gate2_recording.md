# 関門2：記録の健全さ
[← 検証のドキュメント](README.md)

| 項目 | 内容 |
| --- | --- |
| 前提 | 関門1 |
| 使うエピソード | `val_static`、`val_air_run`、`val_constant_depth`、`val_depth_step` |
| 主な道具 | `check_collection.py`、`check_recording.py`、`check_gate2.py` |
| 結果の保存先 | `data/validation/gate2/run_<日時>_gate2/`（目で見た確認は `data/validation/gate2/visual/`） |
| 所要時間の目安 | 約 10 分 |
| 検証した環境 | Unity 2022.3.16f1、AGX Dynamics 2.37.3.0（AGXUnity 5.0.1）、ROS2 Humble |


## 1. 目的
データが**抜けなく、食い違いなく**記録されているかを確かめる。値が物理的に正しいか（力の向き、深さの追従など）は関門3以降で扱い、ここでは「記録の仕組みとして正しいか」に絞る。

特に、記録は `blade_state` が届くたびに1行を書き、ほかのトピックはその時点の最新値を使う（ゼロ次ホールド）ので、ほかのトピックが途中で届かなくなっても NaN にならず、古い値が書かれ続ける。これは欠損の確認では見つからないので、別に確かめる。


## 2. 手段
検証用のエピソード `val_*`（土質は dirt_1 に固定）の4種類を、まず1回ずつ目で見て、次に3回ずつ記録して点検した。点検には、関門1から使っている `check_collection.py`・`check_recording.py` に加えて、この関門のために `check_gate2.py` を作った。

| エピソード | 動き |
| --- | --- |
| `val_static` | 排土板を上げたまま 10 秒静止 |
| `val_air_run` | 排土板を上げたまま 0.5 m/s で 10 m 直進 |
| `val_constant_depth` | 深さ 6 cm・0.5 m/s で 10 m 削る |
| `val_depth_step` | 深さを 3 → 6 → 9 cm と 3 m ごとに変えて削る |

```
cd /workspaces/ws-bulldozer
source install/setup.bash

# 目で見る確認
for ep in val_static val_air_run val_constant_depth val_depth_step; do
  ros2 run bull_ope test_episode $ep --out data/validation/gate2/visual
done

# 4種類 × 3回を記録
ros2 run bull_ope collect_data --episodes val_static val_air_run val_constant_depth val_depth_step \
    --num 3 --seed 0 --run-name gate2 --out data/validation/gate2

# 点検
G=data/validation/gate2/run_<日時>_gate2
python3 analysis/production/check_collection.py $G --report $G/check_collection.md
python3 analysis/validation/check_recording.py $G/ep[0-9]*.csv --report $G/check_recording.md
python3 analysis/validation/check_gate2.py $G --report $G/check_gate2.md
```

`check_gate2.py` で確かめる項目：

| 項目 | 内容 |
| --- | --- |
| G1 列の構成 | すべての CSV で列の名前と順番が同じか |
| G2 行数の一致 | `episodes.jsonl` の行数と CSV の行数が一致するか |
| G3 メタ情報の一致 | CSV のエピソード名・シード・ラベル・`ground_h0` が一定で、`episodes.jsonl` と一致するか |
| G4 時刻の整合 | `t` が 0 から始まり、`sim_time` と食い違わないか |
| G5 トピックの更新 | 走行中に `global_pose`・`joint_states` の同じ値が何行続くか（5 行以上で WARN、25 行以上で NG）、`global_pose` の遅れ（100 ms 超で WARN）。届く頻度は参考に表示 |
| G6 区間の長さ | 下げる区間が `LOWER_TIMEOUT` 以内か、上げる区間が約 3 秒あるか |
| G7 繰り返しの差 | 同じエピソードの繰り返しで、走行の行数・距離の差が平均の 5%（または 10 行・0.1 m）以内か |

G5 の判定の基準は、最初は「更新された行の割合が 90% 未満で WARN」としていたが、関門1のデータ（`stress_short` × 50）で試すと、記録に問題がなくても 52〜80% にしかならなかった。OperaSim の2つのトピックは記録より少ない回数しか届かないためで、割合では不具合と区別できない。そこで「同じ値の連続」と「遅れ」で判定するように直してから使った（直した後、関門1のデータで OK 301 / WARN 0 / NG 0）。


## 3. 結果
**目で見た確認：** 4種類とも想定どおりの動き（静止、空中を直進、土を排土板の前にためながら削る、3 m ごとに深くなる）。

| 点検 | OK | WARN | NG |
| --- | --- | --- | --- |
| `check_collection.py` | 想定外・要確認 0 件 | — | — |
| `check_recording.py` | 72 | 12 | 0 |
| `check_gate2.py` | 65 | 11 | 0 |

| 項目 | 結果 |
| --- | --- |
| 結果 | 12 件すべて ok |
| 記録の周期 | 12 件とも平均 20.0 ms、最大 20.0 ms、50 ms を超える間隔 0 回 |
| 時刻の逆戻り・重複、想定外の NaN | なし |
| 列の構成、行数、メタ情報、時刻 | 12 件とも 88 列で同じ、行数一致、メタ情報一致、`t` と `sim_time` の差 10⁻¹³ s 程度 |
| 開始位置のばらつき | 最大 0.13 cm、向き 0.059° |
| 繰り返しの差（G7） | 走行の行数 1.2% 以内、距離 0.4% 以内 |
| global_pose・joint_states の届く頻度 | 約 37〜40 Hz（記録の 73〜80% の行で更新）。12 エピソードを通して一定 |
| 同じ値の連続（最大） | 4〜6 行（0.08〜0.12 秒）。0.5 秒以上止まったことはない |
| global_pose の遅れ | 中央値 20 ms、最大 40〜120 ms |

WARN の内訳：

| WARN | 理由 |
| --- | --- |
| 一定の列：`F_def_*`、`F_con_*`（すべてのエピソード） | 常に 0（理由は関門3で特定） |
| 一定の列：`cmd_vx`、`cmd_wz` | 設計どおり一定の指令 |
| 一定の列：遠い位置の `ground_profile_*`（削るエピソード） | 排土板の前の土の山は 1〜1.25 m までで、その先は手を付けていない平らな地面 |
| 一定の列：力・地面の高さ・`cut_volume`（`val_static`、`val_air_run`） | 排土板を上げているので力は 0、地面も変わらない |
| G5（11 件） | 同じ値の連続 5〜6 行、または遅れ 100〜120 ms。基準をわずかに超えたもの |


## 4. 考察
- **記録の仕組みは健全。** 50 Hz の記録に抜けや重複はなく、列・行数・メタ情報・時刻も食い違いがない。シーンの読み込み直しで、繰り返しの差も 1% 程度と小さい。
- **global_pose と joint_states は、記録より少ない頻度（約 38 Hz）で届く。** 記録の行の 2〜3 割は直前の値で、位置・関節の値は 1〜数ステップ前のものになる。これは記録の不具合ではなく、OperaSim のトピックの届き方の性質。どのくらい遅れているかは関門4で詳しく測る。
- **HUD の積み重なりの修正（関門1の不具合 11）の効果が確かめられた。** 修正前の関門1の段階D では、届く割合が約 75% → 55〜60% に下がっていった（画面の更新の速さの低下とともに）。修正後のこの関門では、12 エピソードを通して一定だった。
- **学習データとして使うときの注意：** 位置・速度・関節の値は 1〜数ステップ遅れていて、同じ値が最大 6 行続く。前処理（時間窓の取り方など）は関門4と、学習に使う条件を決める段階で考慮する。


## 5. 判定
| 合格の条件 | 結果 |
| --- | --- |
| 12 エピソードがすべて ok で記録される | 満たす |
| 3つの点検で NG が 0 件 | 満たす |
| WARN をすべて説明できる | 満たす |

**合格**。この関門の 12 エピソードは、関門3の最初の確認にも使った。
