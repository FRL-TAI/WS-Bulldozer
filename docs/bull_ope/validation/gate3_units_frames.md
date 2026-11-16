# 関門3：単位・座標・符号
[← 検証のドキュメント](README.md)

| 項目 | 内容 |
| --- | --- |
| 前提 | 関門2（関門2のデータを最初の点検に使う） |
| 使うエピソード | `val_*`、`ex_back_blading`、`ex_turning` |
| 主な道具 | `check_units.py`、`inspect_depth.py`、`check_gate2.py`、Unity の DebugRenderManager |
| 結果の保存先 | `data/validation/gate3/`（正式な結果 `run_<日時>_gate3/`、制御のゲインの試験 `kp3/`、力の内訳の試験 `forces/`） |
| この関門で変えたもの | Unity：`BladeStatePublisher` に `ground_behind` を追加。bull_ope：`LIFT_KP` を 1.0 → 3.0 |
| 検証した環境 | Unity 2022.3.16f1、AGX Dynamics 2.37.3.0（AGXUnity 5.0.1）、ROS2 Humble |


## 1. 目的
記録された値が、**正しい向き・正しい単位・正しい座標系**になっているかを確かめる。あわせて、関門1・2から持ち越した2つの疑問に答える。

1. 力の内訳のうち `F_def`（変形抵抗）と `F_con`（通常の接触力）が、いつも 0 なのはなぜか
2. 記録の最初の切削深さが、いつも約 13 cm になるのはなぜか


## 2. 手段
### 2.1 関門2のデータで点検する
この関門のために `check_units.py`（U1〜U9）と `inspect_depth.py` を作り、関門2の 12 エピソードを点検した。

| 項目 | 確かめること | 基準（暫定） |
| --- | --- | --- |
| U1 空中の力 | 排土板を上げている間（`val_static`、`val_air_run`）、力がほぼ 0 か | 大きさの最大 100 N 未満 |
| U2 押土の力の向き | 削っている間、`F_total_x` が負か、`F_total_y` が小さいか | Fx < 0、\|Fy\|/\|Fx\| ≤ 0.2 |
| U3 深さの追従 | 深さが目標に追従しているか（走り出し・目標の変化から 1.5 秒を除く） | 平均のずれ 1 cm 未満、95% が 2 cm 以内 |
| U4 刃先と地面 | 削った後の地面の高さが刃先の高さとほぼ同じか | 差の中央値 2 cm 未満 |
| U5 速度と距離 | `v_forward` の積分と位置から求めた距離が一致するか | ずれ 3% 以内 |
| U6 座標の整合 | 刃先が車体の前方にあるか、直進中に向きがずれないか | 横のずれ 0.2 m 未満、向きの変化 2° 以内 |
| U7 値の範囲 | 排土板の幅・角度、ラベルの単位（φ が度、ρ が kg/m³ など） | 妥当な範囲 |
| U8・U9 | 力の内訳の最大、記録の最初の行の状態 | 参考 |

```
cd /workspaces/ws-bulldozer
G=data/validation/gate2/run_<日時>_gate2
python3 analysis/validation/check_units.py $G --report $G/check_units.md
python3 analysis/validation/inspect_depth.py $G/ep*_val_constant_depth.csv $G/ep*_val_depth_step.csv $G/ep*_val_static.csv --plot
```

### 2.2 わかったことを受けて試す・調べる
```
cd /workspaces/ws-bulldozer
# (a) 制御のゲイン LIFT_KP を 1.0 → 3.0 にして試す（config.py を書き換えて）
for i in 1 2; do ros2 run bull_ope test_episode val_constant_depth --seed $i --out data/validation/gate3/kp3; done
python3 analysis/validation/inspect_depth.py data/validation/gate3/kp3/*.csv --plot

# (b) F_def・F_con が出るはずの動き（後退、旋回）を試す
for ep in ex_back_blading ex_turning; do
  ros2 run bull_ope test_episode $ep --out data/validation/gate3/forces
done
python3 analysis/validation/check_units.py data/validation/gate3/forces/*.csv
```

(c) 後退中に排土板が土に当たっているかを、記録で調べた。後退中、刃先から 0.5 m 前方（`ground_ahead`）などは、排土板が少し前に通った場所なので、そこが削られているかを見る。

```
python3 - data/validation/gate3/forces/*_ex_back_blading.csv <<'PY'
import sys
import numpy as np
import pandas as pd
df = pd.read_csv(sys.argv[1])
r = df[(df["phase"] == "running") & (df["cmd_vx"] < 0) & (df["target_depth"] > 0)]
r = r[r["t"] > r["t"].iloc[0] + 1.5]
h0 = df["ground_h0"].iloc[0]
print(f"刃先の深さ 中央値 {r['depth'].median()*100:.1f} cm")
for col in ["ground_profile_025cm", "ground_profile_050cm", "ground_ahead", "ground_profile_100cm"]:
    d = (h0 - r[col]) * 100
    print(f"{col} の削られた深さ 中央値 {d.median():+.1f} cm")
f = np.sqrt(r["F_total_x"]**2 + r["F_total_y"]**2 + r["F_total_z"]**2)
print(f"力の大きさ 中央値 {f.median():.0f} N、最大 {f.max():.0f} N")
PY
```

(d) Unity 側では、`blade_link` の `DeformableTerrainShovel` の設定、`AGXUnity.CollisionGroupsManager` の衝突させない組み合わせ、`Terrain` の設定を見た。さらに、`AGXUnity.Rendering.DebugRenderManager` の Render contacts をオンにして、`ex_back_blading` の後退中に排土板と地面の接触点が出るかを Scene ビューで見た（確認後に `git restore` でシーンを戻した）。

### 2.3 最終の設定で記録し直す
`BladeStatePublisher` に `ground_behind`（刃先から 0.3 m 後ろの地面の高さ）を追加し、`LIFT_KP` = 3.0 にしたうえで、`val_*` を記録し直して点検した。

```
cd /workspaces/ws-bulldozer
ros2 run bull_ope collect_data --episodes val_static val_air_run val_constant_depth val_depth_step \
    --num 3 --seed 0 --run-name gate3 --out data/validation/gate3
G3=data/validation/gate3/run_<日時>_gate3
python3 analysis/validation/check_gate2.py $G3 --report $G3/check_gate2.md
python3 analysis/validation/check_units.py $G3 --report $G3/check_units.md
python3 analysis/validation/inspect_depth.py $G3/ep*_val_constant_depth.csv $G3/ep*_val_depth_step.csv --plot
```


## 3. 結果
### 3.1 単位・座標・符号（正式な結果）
| 項目 | 結果 | 判定 |
| --- | --- | --- |
| U1 空中の力 | 力の大きさの最大 0.0 N（6 件とも） | OK |
| U2 押土の力の向き | 平均 F_total = (−9.3〜−12.4, −0.0〜−0.2, −5.9〜−8.0) kN、\|Fy\|/\|Fx\| ≤ 0.01 | OK |
| U5 速度と距離 | ずれ 0.2〜0.4% | OK |
| U6 刃先の位置 | 車体の位置から前方 2.79 m（削っているとき）〜2.83 m（上げたとき）、左方 0.00 m | OK |
| U6 直進中の向き | +0.1〜+1.1°（毎回わずかに左） | OK |
| U7 値の範囲 | 排土板の幅 2.96 m、φ 39.98°、ρ 1,474 kg/m³、E 6.5 MPa、`ground_h0` −0.0001 m | OK |
| 点検の合計 | `check_units.py`：OK 62 / WARN 4 / NG 0、`check_gate2.py`：OK 68 / WARN 8 / NG 0（89 列にそろう） | — |

### 3.2 刃先と地面の高さ
| 比べたもの | 差（中央値） | 様子 |
| --- | --- | --- |
| 刃先の真下の地面 `ground_below` − 刃先 `edge_z` | +4.5〜+6.9 cm（最大 40 cm） | ゆっくり上がっては急に落ちる「のこぎり波」。歯の間隔は約 0.6 秒。走るほど振れ幅が大きくなる |
| 刃先の 0.3 m 後ろの地面 `ground_behind` − `edge_z`（追加後） | +0.1〜+0.3 cm | 削った後の地面が刃先とほぼ同じ高さ（U4 OK） |

### 3.3 深さの揺れと制御のゲイン
| 状態 | 深さのずれの標準偏差 | ピッチの変化との相関 | 揺れの周期 |
| --- | --- | --- | --- |
| `LIFT_KP` = 1.0（関門2のデータ） | 1.9〜2.3 cm | r = +0.45〜+0.53 | 1.7〜2.6 秒 |
| `LIFT_KP` = 3.0（正式な結果） | 0.9〜1.2 cm | r = +0.14〜+0.30 | 主に 0.58〜0.67 秒 |

正式な結果の U3 は、平均のずれ +0.06〜+0.25 cm、95% の幅 1.69〜2.23 cm（6 件中 4 件が基準の 2 cm をわずかに超えて WARN）。

### 3.4 F_def・F_con と、後退中の排土板
| 確認 | 結果 |
| --- | --- |
| `ex_turning`（曲がりながら削る） | `F_pen`・`F_sep` は出る（最大 7.4 kN、16.5 kN）。`F_def`・`F_con` は 0 |
| `ex_back_blading`（排土板を地面に当てて後退） | 刃先は元の地面より 2.1 cm 下（中央値）なのに、通った跡の地面は削られていない（削られた深さの中央値 0.0 cm）。力の大きさは中央値 0 N、最大 465 N |
| 接触点の表示 | 履帯には接触点が並ぶが、後退中の排土板には刃先の先にまれに1つ（前向き）出るだけ |
| Unity の設定 | `DeformableTerrainShovel` の Settings は None（AGX の既定値）。排土板の3つの形状（厚さ 4 cm の板）は Collisions Enabled。`CollisionGroupsManager` で排土板と地形の衝突は切られていない |
| 地形の設定 | `DeformableTerrain` の Element Size = 0.3125 m |

### 3.5 記録の最初の状態
記録の最初の行は、12 件とも `edge_z` = −0.13 m、`ground_below` = 0.00 m。`val_static` で排土板を上げても地面はへこまず（`ground_below` は 0 のまま）、力は最初の約 0.25 秒に最大 0.45 kN 出るだけだった。

### 3.6 そのほかの値
| 項目 | 値 |
| --- | --- |
| 押土中の上下と前後の力の比 \|Fz\|/\|Fx\| | 0.60〜0.70（上下の力は下向き） |
| 力の内訳 | `F_sep` が支配的。`F_pen` の最大 5.7〜7.5 kN |
| 速度の追従 | 指令 0.5 m/s に対し 0.503〜0.506 m/s（削っていても滑りはほとんどない） |
| 排土板の角度 | 下げると 71°、上げると 63° |


## 4. 考察
- **単位・座標・符号に誤りはない。** 空中では力がちょうど 0、押土中は前後の力が負で左右の力はほぼ 0、速度の積分と位置が一致し、刃先は車体の真正面にある。
- **`ground_below` は「削った後の地面」ではなかった。** 刃先の真下のマスには、まだ切り取られていない土と、排土板の前の土の山が乗っている。地形は 31 cm のマスでできているので、刃先が1マス進むごとに測る土が切り替わり、のこぎり波になる。削った後の地面は刃先の後ろで測る必要があり、`ground_behind` を追加して確かめた。`ground_behind` は「実際に削った深さ」として学習の特徴量にも使える。
- **深さの揺れは、車体のピッチの揺れと、制御の反応の遅さが原因だった。** `LIFT_KP` = 1.0 では、ずれ 1 cm に対して 0.01 m/s しか動かさず、周期 2〜3 秒のピッチの揺れを打ち消せなかった。3.0 にすると揺れは半分になり、残りの揺れの周期（約 0.6 秒）は、刃先が地形のマスを1つ通る時間（0.3125 m ÷ 0.5 m/s）と一致する。記録した `depth` は実際の刃先の深さなので、データとしては正しい。
- **`F_def`・`F_con` が 0 なのは、AGX の性質だった（疑問1の答え）。** 衝突の設定は切られていないのに、後退中は土も動かず力もほとんど出ない。前に削る動き（掘削のモデル）以外では、排土板が地形に入っても土はほとんど動かない。原因は、排土板の設定（Settings が None）で、後ろや横に押しのける動きが無効か、力を返さないことと考えられる。前に削る動きの力は `F_pen` と `F_sep` で表されるので、今の学習データには影響しない。後退しながら排土板を当てる動きは、学習データに入れない。
- **最初の深さ約 13 cm は、排土板の初期位置のめり込み（疑問2の答え）。** シーンの初期状態で、排土板が地面に約 13 cm めり込んでいる。5 と同じ理由で、上げても地面はへこまず、力もごく小さい。下げる区間は学習に使わないので、シーンは変えない。
- **関門5・段階8への材料：** 力・深さには地形のマスによる約 0.6 秒周期の変動が含まれる。`F_total_x` は鋭く揺れ、`F_total_z` のほうが滑らか。


## 5. 判定
| 合格の条件 | 結果 |
| --- | --- |
| U1〜U7 で NG が 0 件 | 満たす |
| WARN と参考の項目をすべて説明できる | 満たす（U3 は地形のマスによる揺れ、G5 は関門2と同じ） |
| 持ち越した疑問（F_def・F_con が 0、最初の深さ約 13 cm）に答えが出ている | 満たす |

**合格**。
