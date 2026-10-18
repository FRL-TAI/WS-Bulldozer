# 関門7：試験的な収集
[← 検証のドキュメント](README.md)

| 項目 | 内容 |
| --- | --- |
| 前提 | 関門1〜6 |
| 使うエピソード | `flat_cut`、`flat_piecewise`、`pile_push` |
| 主な道具 | 関門1〜6の点検の道具、`check_dataset.py` |
| 結果の保存先 | `data/pilot/`（`run_<日時>_pilot_cut/`、`run_<日時>_pilot_pw/`、`run_<日時>_pilot_pile/`、`run_<日時>_pilot_pile2/`、まとめの `check_*.md`） |
| 所要時間の目安 | 約 1 時間 |
| 検証した環境 | Unity 2022.3.16f1、AGX Dynamics 2.37.3.0（AGXUnity 5.0.1）、ROS2 Humble |


## 1. 目的
本番と同じやり方（学習データ用のエピソード、土質・深さ・速度を同時にランダムに変える）で 30 エピソードほどを集め、関門1〜6の道具でまとめて点検する。確かめることは次の5つ。

1. 学習データ用のエピソードが、失敗せずに最後まで走るか
2. 記録は関門2〜4と同じように健全か
3. 土質が範囲全体に偏りなく散らばっているか
4. 関門5・6で分かった関係が、土質・速度を同時に変えても成り立つか
5. 本番には何時間・何 GB かかるか


## 2. 手段
### 2.1 学習データ用のエピソード
関門の結果を反映して、`flat_cut` と `flat_piecewise` を作った（`dataset/flat_cut.py`）。設計は [README の 2.1](../README.md#21-採用したエピソード)。あわせて、前方に緩い土の山を積んで押す `pile_push`（`dataset/pile_push.py`）も試した。

### 2.2 実行したこと
```
cd /workspaces/ws-bulldozer
# (a) 範囲の端（最も重い土）で1回ずつ試す
ros2 run bull_ope test_episode flat_cut --seed 0 --c 30000 --phi 50 --rho 1900
ros2 run bull_ope test_episode flat_piecewise --seed 1

# (b) 試験的に収集する
ros2 run bull_ope collect_data --episodes flat_cut --num 20 --seed 100 --run-name pilot_cut --out src/bull_ope/data/pilot
ros2 run bull_ope collect_data --episodes flat_piecewise --num 10 --seed 101 --run-name pilot_pw --out src/bull_ope/data/pilot

# (c) まとめて点検する
cd src/bull_ope
PC=data/pilot/run_<日時>_pilot_cut; PW=data/pilot/run_<日時>_pilot_pw
for d in $PC $PW; do
  python3 analysis/checks/check_collection.py $d --report $d/check_collection.md
  python3 analysis/checks/check_recording.py $d/ep[0-9]*.csv --no-label --report $d/check_recording.md
  python3 analysis/checks/check_gate2.py $d --report $d/check_gate2.md
  python3 analysis/checks/check_units.py $d --report $d/check_units.md
done
python3 analysis/checks/check_timing.py $PC $PW --report data/pilot/check_timing.md
python3 analysis/checks/check_physics.py $PC --report data/pilot/check_physics.md --plot data/pilot/check_physics.png
python3 analysis/checks/check_dataset.py $PC $PW --target 1000 --report data/pilot/check_dataset.md

# (d) pile_push：10 件試し、範囲を狭めて 20 件試す
cd /workspaces/ws-bulldozer
ros2 run bull_ope collect_data --episodes pile_push --num 10 --seed 102 --run-name pilot_pile --out src/bull_ope/data/pilot
#   （pile_push.py の範囲を狭めた後）
ros2 run bull_ope collect_data --episodes pile_push --num 20 --seed 103 --run-name pilot_pile2 --out src/bull_ope/data/pilot
```

この関門に合わせて、点検の道具を2か所直した。`check_units.py` は削るエピソードを名前ではなくデータで判断するように、`check_recording.py` は土質が毎回違うデータ用に `--no-label`（ラベルの確認を飛ばす）を追加した。`check_dataset.py` は、D1 結果の内訳、D2 土質の広がり、D3 関門5・6の関係の回帰、D4 本番の見積もりを出す。


## 3. 結果
### 3.1 範囲の端での試走
最も重い土（c 30 kPa、φ 50°、ρ 1,900、深さ 9.8 cm、0.43 m/s）でも安全停止せずに 14 m 走り切った。前後の力は平均 37.8 kN（瞬間的に 100 kN 超）、深さの標準偏差 1.1 cm、速度 0.42〜0.46 m/s。14 m 先まで前方の地面は平らなまま。貫入抵抗は 21.4 kN で、関門6の式（20.4 kN）と合った。履帯の関節の力は瞬間的に上限（約 60,000 N·m）に届いた。

### 3.2 flat_cut・flat_piecewise（30 件）
| 項目 | 結果 |
| --- | --- |
| 結果 | 30 件すべて ok |
| 土質の広がり（範囲を5等分した件数） | c 7/5/6/6/6、φ 7/5/6/6/6、ρ 6/6/6/5/7 |
| 記録の点検 | すべて NG 0 件（WARN は一定の列・G5・G7・U3） |
| 速度の追従 | 平均の速度と指令の比 0.991〜1.008 |
| 深さの追従（U3） | 平均のずれ −0.05〜+0.26 cm。95% の幅 2.0〜7.2 cm（大きいのは 0.6〜0.76 m/s のエピソード） |
| 時間のずれ | 関門4と同じ（global_pose 20 ms、joint_states 20 ms、速度の指令 → 63% 140 ms） |
| 駆動力のつり合い | 傾き 1.30、転がり抵抗 32.5 kN、相関 0.89。排土板を支える力と上下の力の相関 0.99 |

**関門5・6の関係（`flat_cut` 20 件をまとめて回帰）**

| 関係 | 関門7 | 関門6（1つずつ変えた実験） |
| --- | --- | --- |
| 貫入抵抗 | Fpen = 1.50 + **0.647** × c [kPa] kN（決定係数 0.99） | 0.93 + 0.65 × c |
| 頭打ちの上下の力 | Fz_sat = 2.43 + **5.89** × ρ [N/(kg/m³)] + 0.485 × c [kPa] kN（決定係数 0.97） | ρ に約 7.1 N/(kg/m³) |
| 頭打ちの前後の力 | Fx_sat = −5.95 + 5.25 × ρtanφ [t/m³] + 0.759 × c [kPa] + **38.7** × v [m/s] kN（決定係数 0.95） | 速度に約 27 kN/(m/s) |

**見積もり：** 1エピソードの実時間 36 秒（走行 26 秒）、CSV 平均 2.27 MB（1,527 行）、ok の割合 100%。1,000 件で約 10 時間、約 2.3 GB。

### 3.3 pile_push
| 試験 | 山の範囲 | 結果 |
| --- | --- | --- |
| 1回目（10 件） | 位置 1.5〜4 m、長さ 1〜3 m、高さ 0.2〜0.5 m、深さ 0〜6 cm | 9/10 件 ok。安全停止 1 件（山が最も近く大きい：開始から 1.52 m、長さ 2.46 m、高さ 0.44 m、0.67 m/s で深さ 37.9 cm）。ok だが深さのずれの 95% が 21 cm のもの 1 件 |
| 2回目（20 件） | 位置 2〜4 m、長さ 1〜2.5 m、高さ 0.2〜0.4 m、深さ 0〜4 cm | 20/20 件 ok。深さのずれの 95% は 19 件で 1.9〜3.6 cm、1 件で 16 cm |

- 記録の点検は NG 0 件。貫入抵抗と c の関係は、山を押していても成り立った（例：c 1.6 kPa で 2.23 kN、29.8 kPa で 21.6 kN）。
- 地山を削った体積 `cut_volume` がほとんど増えないため、頭打ちの特徴（`Fx_sat`・`Fz_sat`）は今の点検では求められなかった。


## 4. 考察
- **本番のやり方に問題はない。** 失敗 0 件、記録も関門2〜4と同じ水準で、土質も偏りなく散らばった。
- **関門6の関係は、土質・速度を同時に変えても成り立つ。** 3つの関係の決定係数は 0.95〜0.99。頭打ちの前後の力への寄与を比べると、このデータの範囲で速度が 12〜31 kN、c が 0〜23 kN、ρ tanφ が 3〜11 kN で、**φ に関わる部分が最も小さい**。関門6の「φ は推定が難しい」と合う。
- **速いほど深さが揺れる。** 0.75 m/s では刃先が地形のマスを通る周期が約 0.4 秒になり、排土板の制御（`LIFT_KP` = 3.0）が追いつきにくくなる。平均のずれは 0.3 cm 未満で、記録した深さは実際の値なので、学習には実際の深さを使う。
- **点検の道具の当てはまり方：** G7（繰り返しの差）は同じ条件の繰り返しを前提にしているので、速度がエピソードごとに違う学習データには当てはまらない。`check_physics.py` の P1〜P4 の要約は1つの土質を前提にした計算なので、土質が混ざったデータには使えず、その役割は `check_dataset.py` の D3 が担う。
- **pile_push は、大きな山に速く当たると排土板が潜る。** 排土板に大きな下向きの力がかかって機体が前に傾き、排土板の制御（上げる速さの上限 0.1 m/s）が追いつかない（関門1の `stress_heavy_push` と同じ現象）。範囲を狭めると 95% は問題なくなったが、約 5% のエピソードで目標と大きく違う深さを削る。積んだ山は「緩い土」で、関門5・6で調べた地山とは扱いが違うこと、AGX 2.37.3.0 では締固めの程度に応じたダイレイタンシー角の計算に不具合がある可能性（2.38.0.0 で修正）があることから、**主なデータとは別のフォルダに追加のデータとして集め、学習に使うかを後で選ぶ**ことにした。


## 5. 本番の設計
| 項目 | 決めたこと |
| --- | --- |
| エピソード | 主なデータ：`flat_cut` と `flat_piecewise` を 2:1（1区切り 60 件 + 30 件）。追加のデータ：`pile_push`（別の出力先） |
| 範囲 | 試験と同じ（`pile_push` は2回目の範囲） |
| 実行の仕方 | `src/bull_ope/scripts/run_production.sh` で区切りごとに実行し、区切りが終わるたびに点検する（[README の 2.2](../README.md#22-スクリプトの実行方法)） |
| 件数 | 学習に必要な数に合わせて決める（1,000 件で約 10 時間） |

**学習に使う条件を決める段階に持ち越すこと**

| 項目 | 内容 |
| --- | --- |
| 除くエピソード | 深さのずれの 95% が 10 cm を超えるもの（`pile_push` で約 5%） |
| 推定器の入力と時間窓 | `F_pen`・`F_z`・速度を含める。時間窓は 1.2 秒以上（関門4） |
| φ の扱い | 分解能が粗い（関門6）。目標の精度、ρ tanφ として推定するか |
| pile_push の土の量 | 山の量（`param_pile_*`）を含めた扱い |


## 6. 判定
| 合格の目安 | 結果 |
| --- | --- |
| ok の割合 95% 以上、失敗の理由を説明できる | 満たす（`flat_cut`・`flat_piecewise` 100%、`pile_push` 2回目 100%） |
| 記録の点検で NG 0 件、WARN は既知の理由 | 満たす |
| 土質が範囲全体に偏りなく散らばる | 満たす |
| 関門5・6の関係が成り立つ | 満たす（決定係数 0.95〜0.99） |
| 本番の所要時間と容量が現実的 | 満たす |

**合格**。本番の収集に進む。
