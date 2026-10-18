# 関門4：時間のずれ
[← 検証のドキュメント](README.md)

| 項目 | 内容 |
| --- | --- |
| 実行日 | 2026/10/18 |
| Unity 側のコミット | f6d7143b7645c8960ae5b8f8ff046186843241b2 |
| bull_ope 側のコミット | 9d8ff4fc3b5edb51068bc6d828f53961d1ac859c（`check_timing.py` を追加） |
| 結果のフォルダ | 関門3の正式な結果：`data/validation/gate3/run_20261018_145751_gate3/`、走り出しと止まりの繰り返し：`data/validation/gate4/run_20261018_151706_gate4/` |


## 1. 目的
同じ行に並んでいる値が、本当に同じ時刻の値なのか、どのくらいずれているのかを測る。あわせて、指令を送ってから機体が応答するまでの遅れを測る。

関門1〜3と違い、合否で切り分けるのではなく、ずれの大きさを把握して、学習の前処理（値をずらしてそろえるか、推定器が見る時間窓をどのくらいにするか）を決める材料をそろえるのが目的。


## 2. 手段
記録は `blade_state` が届くたびに1行を書くので、`blade_state` の値（力・刃先・地面）は同じステップの値で、ずれはない。ほかの値が `blade_state` に対してどれだけ遅れているかを、`check_timing.py` で5つの方法で測った。

| 測り方 | 内容 |
| --- | --- |
| T1 | `sim_time` − `pose_stamp`（`global_pose` の位置が何 ms 前の値か） |
| T2 | `global_pose`・`joint_states` の値が変わる間隔 |
| T3 | 速度の指令が変わってから、`v_forward` が変化量の 10%・63%・90% に達するまでの時間 |
| T4 | 排土板の速度指令 `cmd_lift` と、刃先の上下の速度（`edge_z` の微分）の相互相関が最大になる遅れ |
| T5 | 同じ物理量を別のトピックで見たときの相互相関が最大になる遅れ：上下の力 `F_total_z`（blade_state）と排土板を支える力 `lift_joint_effort`（joint_states）、`v_forward`（global_pose から計算）と履帯の回転速度（joint_states） |

T5 が、時刻の列を持たない `joint_states` のずれを測る方法。上下の力と排土板を支える力は、物理的にはほぼ同じ瞬間に変わるはずなので、相互相関の山の位置が遅れの目安になる。

関門3のデータは一定の速さで走る区間ばかりなので、速度が大きく変わるデータとして `ex_stop_and_go`（3 秒前進・2 秒停止を 20 秒間、0.6 m/s。1回で走り出しと止まりが4回ずつ）を3回記録した。

```
cd /workspaces/ws-bulldozer/src/bull_ope
G3=data/validation/gate3/run_20261018_145751_gate3
python3 analysis/checks/check_timing.py $G3 --report $G3/check_timing.md

cd /workspaces/ws-bulldozer
ros2 run bull_ope collect_data --episodes ex_stop_and_go --num 3 --seed 0 \
    --run-name gate4 --out src/bull_ope/data/validation/gate4
cd src/bull_ope
G4=data/validation/gate4/run_20261018_151706_gate4
python3 analysis/checks/check_gate2.py $G4 --report $G4/check_gate2.md
python3 analysis/checks/check_timing.py $G4 --report $G4/check_timing.md
```


## 3. 結果
| 項目 | 関門3のデータ（val_* × 12） | ex_stop_and_go × 3 |
| --- | --- | --- |
| T1 global_pose の遅れ（中央値） | 20 ms（12 件とも） | 20 ms（3 件とも） |
| T1 global_pose の遅れ（最大） | 60〜100 ms | 60〜80 ms |
| T2 届く間隔（中央値） | global_pose 20 ms、joint_states 20 ms | 同じ |
| T3 速度の指令 → 速度 10% | 60 ms（40〜100 ms、18 件） | 70 ms（40〜120 ms、24 件） |
| T3 速度の指令 → 速度 63% | 120 ms（100〜160 ms） | 140 ms（100〜180 ms） |
| T3 速度の指令 → 速度 90% | — | 140〜240 ms |
| T4 排土板の指令 → 刃先の動き | 60 ms（20〜60 ms） | 60 ms（3 件とも、相関 −0.66〜−0.73） |
| T5 F_total_z → lift_joint_effort | 20 ms（6 件とも） | 20 ms（3 件とも、相関 +0.76〜+0.78） |
| T5 v_forward → 履帯の回転速度 | 0 ms（−40〜0 ms） | **−40 ms**（3 件とも、相関 +0.88〜+0.89） |

- `ex_stop_and_go` の記録は健全（`check_gate2.py`：NG 0 件、WARN 3 件は G5 で関門2と同じ理由、繰り返しの差 0.3%）。
- T3 は、走り出し（0 → 0.6 m/s）と止まり（0.6 → 0 m/s）で大きな違いはない。
- T5 の v_forward → 履帯の回転速度は、関門3のデータでは速度の変化が小さく相関の山がはっきりしなかった。速度が大きく変わる `ex_stop_and_go` で、はっきりした相関（+0.88）で −40 ms が出たので、こちらを採る。
- T2 の最大（約 2 秒）は、点検の道具が停止中の行を除いて数えたためで、実際の届く間隔ではない。


## 4. 考察
**各値の、`blade_state` に対する遅れ**

| 値 | 遅れ | 根拠 |
| --- | --- | --- |
| `blade_state` の値（力、刃先、地面） | 0 ms（基準） | 同じステップの値 |
| `joint_states` の値（関節、履帯） | 20 ms（1 行） | T5：F_total_z → lift_joint_effort が毎回 20 ms |
| `global_pose` の位置・姿勢 | ふつう 20 ms、まれに 60〜100 ms | T1 |
| 計算した速度（`vx`、`v_forward` など） | 約 60 ms（3 行） | T5：履帯の回転速度（20 ms 遅れ）より、さらに 40 ms 遅れる。位置の変化を 0.1 秒の幅で求めていることによる遅れ |

- **遅れは小さく、毎回同じ。** `global_pose`・`joint_states` の遅れは、すべての繰り返しで中央値がまったく同じだった。
- **指令から応答まで：** 排土板の指令から刃先が動き出すまで 60 ms（指令が ROS から Unity に届く時間と関節の応答）。速度の指令から車体の速度が 63% に達するまで 120〜140 ms だが、`v_forward` 自体に約 60 ms の遅れがあるので、車体の実際の応答は 60〜80 ms 程度。

**決めたこと**

| 決めること | 結論 | 理由 |
| --- | --- | --- |
| 値をずらしてそろえるか | ずらさない | 遅れは最大 3 行（60 ms）で毎回同じ。時間窓に比べて十分短い。ずらすと、まれな遅れ（最大 100 ms）の行で逆にずれる |
| 計算した速度の遅れ | 記録の仕組みは変えず、遅れ（約 60 ms）を記録しておく | `VEL_WINDOW` を短くすると遅れは減るが、速度の揺れが大きくなる |
| 時間窓の長さの下限 | 1.2 秒以上 | 関門3の地形のマスによる約 0.6 秒の変動を2周期以上含む。遅れや応答時間（最大 240 ms）より十分長い |
| 指令が変わった直後 | 速度の指令が変わってから約 0.3 秒は応答の途中として扱う | 90% に達するまで最大 240 ms |


## 5. 判定
| 合格の条件 | 結果 |
| --- | --- |
| T1〜T5 が測れていて、繰り返しで値がそろっている | 満たす |
| 値をそろえる方法と、時間窓の長さの下限を決められる | 満たす（ずらさない、時間窓 1.2 秒以上） |

**合格**。
