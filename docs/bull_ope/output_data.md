# 出力データ
[← bull_ope のドキュメントの入口](README.md)

時系列データ（`ep*.csv`）の各列の意味は [README の 3.2](README.md#32-収集データ時系列データ-epcsv-の列) を参照。この文書では、フォルダの構成と、エピソードごとの情報（`episodes.jsonl`）をまとめる。

## 1. フォルダの構成
保存先の既定は `data/`（`config.py` の `DATA_DIR`。環境変数 `SOIL_DATA_DIR` で変えられる）。`data/` 以下は Git の管理外（`.gitignore` で `.gitkeep` だけを管理する）。

```
data/
├ test/                                   test_episode の出力
│  ├ <日時>_dataset_flat_cut.csv
│  └ <日時>_ex_compaction_bands_compaction.csv   締固めの記録（RECORD_COMPACTION のエピソードだけ。README の 3.3）
├ production/                             本番の収集（run_production.sh）
│  ├ production.log                       区切りごとの開始・終了と点検の要約
│  ├ chunk001_cut.log、chunk001_pw.log     区切りごとのターミナルの出力
│  ├ chunk001_check_dataset.md            区切りごとの check_dataset.py の結果
│  ├ run_<日時>_chunk001_cut/       collect_data の出力（下）
│  └ run_<日時>_chunk001_pw/
├ production_pile/                        追加のデータ（dataset_pile_push。OUT で指定）
├ pilot/                                  関門7（試験的な収集）
├ compaction/                             フェーズ0（締固め・沈下・較正曲線）の記録と解析結果
└ validation/                             関門1〜6（stress/、gate2/〜gate6/）
```

**collect_data の出力（実行ごとに1フォルダ）**

```
run_<日時>_<実行名>/
├ config.json              実行時のオプションと config.py の設定値
├ episodes.jsonl           エピソードごとの条件・結果（1件終わるごとに追記、UTF-8）
├ episodes.csv             同じ内容の表（全エピソードが終わったときに作成）
├ ep0000_dataset_flat_cut.csv   時系列データ（1エピソード1ファイル）
├ ep0001_dataset_flat_cut.csv
├ ep0002_<名前>_compaction.csv  締固めの記録（RECORD_COMPACTION のエピソードだけ）
└ check_collection.md など  点検の結果（run_production.sh や点検のスクリプトが作る）
```

- `episodes.jsonl` は途中で止まっても残る。`episodes.csv` は最後まで終わったときだけ作られ、エピソードの種類ごとに異なる列（操作のパラメータ）の和集合になる。
- フォルダの中の `ep*.csv` を点検のスクリプトにまとめて渡すときは、`episodes.csv` が混ざらないよう `ep[0-9]*.csv` と指定する。


## 2. episodes.jsonl / episodes.csv の列
| 列 | 内容 |
| --- | --- |
| `episode_index`、`file` | エピソード番号と時系列データのファイル名 |
| `episode_name`、`seed` | エピソード名と乱数のシード |
| `soil_cohesion`、`soil_friction_angle_deg`、`soil_density`、`soil_swell_factor`、`soil_youngs_modulus`、`soil_hardening_ke`、`soil_hardening_ne` | 要求した土質（指定しなかったものは `null`） |
| `param_*` | 操作のパラメータ（エピソードの種類による。例：`dataset_flat_cut` は `param_depth`・`param_speed`、`dataset_flat_piecewise` は `param_depths`・`param_speeds`（3区間のリスト）、`dataset_pile_push` は `param_pile_start`・`param_pile_length`・`param_pile_height`・`param_depth`・`param_speed`） |
| `n_terrain_ops` | 地形の加工の件数 |
| `record_compaction` | 締固めを記録するエピソードか（`RECORD_COMPACTION`） |
| `ground_h0` | 切削深さの基準とした地面の高さ [m] |
| `label_c`、`label_phi`、`label_rho0`、`label_swell`、`label_E0`、`label_KE`、`label_NE` | AGX から読み戻した土質（ラベル） |
| `label_maxDensity` | AGX から読み戻した締固めの上限の密度 maxDensity [kg/m³]。Unity は (2000/1474)·ρ にする（締固めの程度の上限はどの ρ でも約 1.357。`config.MAX_DENSITY_PER_DENSITY`）。この列を足す前の記録にはない（そのときの maxDensity は、上書きしたエピソードを除きシーンの 2,000 で一定） |
| `start_x`、`start_y`、`start_yaw_deg` | 開始時の車体の位置 [m] と向き [deg]（毎回同じ状態から始まっているかの確認用） |
| `run_time`、`run_distance` | 走行時間 [s] と走行距離 [m] |
| `raise_depth_over_max` | 上げる区間で実際の深さが `MAX_ACTUAL_DEPTH` を超えた場合の最大値 [m]。超えなければ `null` |
| `rows`、`path` | 時系列データの行数とパス |
| `cut_compaction_steps`、`cut_compaction_min`、`cut_compaction_max`、`cut_compaction_below1_frac`、`cut_compaction_first_cross_t` | 削っている層の締固めの程度（`state_cut_compaction_mean`）の、running 中の集計（下の「削っている層の締固め」） |
| `compaction_path`、`compaction_snapshots`、`compaction_rows`、`compaction_final` | 締固めの記録のパス、受け取った回数、行数、最後の記録が届いたか（`record_compaction` のエピソードだけ） |
| `status` | `ok`、`skipped: 理由`、`error: 内容` |

- `label_E0`：既定の硬化の設定（KE 1・NE 0.0833）では、削っている最中の地山の実際の剛性は E0 より小さい（notes の docs/phase0.md §3.4）。
- エラーやスキップで止まったエピソードは、止まった時点までに決まっている列（エピソードの情報と `status`）だけが入る。
- NumPy の型や NaN・無限大は、書き出す前に普通の型（NaN・無限大は `null`）に変換する（`recording/json_utils.py`）。

### 削っている層の締固め
時系列データには、地表の値（`state_compaction_*`）とは別に、刃先の高さの層の値を記録する（notes の decisions/2026-11-17_削っている層の締固めを案Aで記録する.md）。

| 時系列データの列 | 内容 |
| --- | --- |
| `state_cut_compaction_mean`、`_min`、`_max` | 刃先の前 0〜0.5 m・排土板の幅のマスについて、刃先の高さ（`edge_z`）に当たるボクセルの締固めの程度の平均・最小・最大。削っているマスがなければ NaN |
| `state_cut_compaction_n` | 読んだマスの数（刃先がそのマスの地面より下にあるマスだけ。削っていなければ 0） |

- ボクセルの決め方：地表のボクセル zs の中心の高さ y_c（AGX の `getGridElementPositionWorld`）から、刃先のボクセルを zs + floor((edge\_z − y_c) / e + 0.5) とする（e はボクセルの大きさ 0.3125 m）。刃先がちょうど境目にあるときは上のボクセル。刃先のボクセルが地表のボクセルより上になるマスも数えない。
- 地表の `state_compaction_mean` には刃の前の緩んだ土が混ざるので、地山の w の判定にはこちらを使う。
- 列は `state_compaction_n` の後に入る。それより前の記録にはこの列がない。

episodes.jsonl の要約（running 中に値があったステップだけで集計。値がなければ `null`）：

| 列 | 内容 |
| --- | --- |
| `cut_compaction_steps` | `state_cut_compaction_mean` に値があったステップの数 |
| `cut_compaction_min`、`cut_compaction_max` | そのステップの平均（`state_cut_compaction_mean`）の最小・最大 |
| `cut_compaction_below1_frac` | 1 を下回った（< 0.9995）ステップの割合 |
| `cut_compaction_first_cross_t` | 1 を初めてまたいだ時刻 [s]（時系列データの `t`）。「1 を下回っているか（< 0.9995）」が、最初に値があったステップと変わった最初のステップ。地山（1.000）から下回った場合も、1 を超えていた土が下回った場合も入る。またがなければ `null` |

**`dataset_pile_push` の山の体積**は、`param_pile_length` × 3.0 m × `param_pile_height`（緩い状態の体積）で計算できる。時系列データの `cut_volume` は地山を削った分だけで、山の量は含まない。

### 排土板の前の土の質量・掘削体積の列
時系列データの次の列は、Unity の `BladeStatePublisher.cs` が AGX 2.37 の Terrain の API（引数にショベルを取るもの。2.40 では Shovel 側に移り非推奨）で毎ステップ読む。この列を足す前の記録（本番データを含む）では、`front_soil_mass`・`excavated_volume_step` は常に NaN で、ほかの4列はない。

| 列 | AGX の API | 中身 |
| --- | --- | --- |
| `front_soil_mass` | `getSoilAggregateMass(shovel, PRIMARY)` | 土塊（soil aggregate）の質量 [kg]。破壊領域で押しのけようとしている土と、inner shape の中の動く土 |
| `front_soil_mass_deform` | `getSoilAggregateMass(shovel, DEFORM_BACK/RIGHT/LEFT)` の和 | 押しのけ・横への変形の土塊の質量 [kg]。このシーンの前進では常に 0 |
| `front_dynamic_mass` | `getDynamicMass(shovel)` | ショベルまわりの動く土（粒子と fluid mass）の質量 [kg]。inner shape の中だけではない：T15 の確認では、`front_inner_volume` × `front_dead_load_fraction` × 粒子の密度の 2.5〜2.8 倍で、排土板のすぐ前（上端〜刃先の前 0.5 m）の粒子の 0.78〜1.00 倍（中央値 約 0.92）、地形全体の動く土の 0.68〜0.89 倍だった |
| `front_inner_volume` | `getInnerVolume(shovel)` | inner shape の体積 [m³]。排土板の形で決まり、一定（0.301 m³） |
| `front_dead_load_fraction` | `getLastDeadLoadFraction(shovel)` | inner shape のうち動く土で埋まっている割合 [-] |
| `excavated_volume_step` | `getLastExcavatedVolume()` | 直前のステップに地形全体で掘削された体積 [m³] |

使うときの注意（dirt_1 の flat_cut・pile_push で確かめた）：
- **`front_soil_mass` は「排土板の前にたまった土の全体」ではない**。削り始めて約 2.5 m で 900〜1,000 kg 前後に頭打ちになり、`cut_volume` × ρ（10 m で約 3,900 kg）とは離れていく。前にたまった土のうち、地形に戻った分は含まれない。pile_push でも、山（約 2,070 kg）を押している間の値は 900〜1,000 kg 程度で、走り出す前（山に届く前）は 0 である。
- `front_soil_mass` ≥ `front_dynamic_mass` で、差が破壊領域の土（まだ地形の側の土）に当たる。排土板を上げると両者は等しくなる。
- `excavated_volume_step` は、ほとんどのステップで 0 で、ときどき大きな値が入る（積算は階段状）。積算は flat_cut で `cut_volume` の約 2 倍、pile_push で約 8 倍になる。地形に戻った土をもう一度掘削した分も数えるためと考えられ、削った地山の体積の代わりには使えない。
- 土の山の量としては、引き続き `cut_volume`（地山を削った体積の積算。頭打ちの前だけ）を使う。`front_soil_mass` を使うかは、notes の docs/phase1.md §4.1 で決める。

### 土の山の体積の列（T15）
時系列データの次の列は、Unity の `PileVolume.cs`（`BladeStatePublisher.cs` から毎ステップ呼ぶ）が求める。定義は notes の decisions/2026-11-17_土の山の体積の定義と入力の決め方.md。この列を足す前の記録にはない。

V_pile = Σ（範囲内のマス）max(h − h0, 0)·A ＋ M_dyn ÷ (ρ/s)

- h：AGX の地形の高さ（`Terrain.getHeight`）。h0：シーンを読み込んだ直後の高さ（エピソードごとに読み込み直すので、開始時の地表。pile_push の山を積む前）。
- 範囲：刃先の中点を原点に、水平の前方は「排土板の上端の水平位置（`pile_back_offset`、刃先の後ろ約 0.33 m）」から刃先の前 2.0 m まで、横は ±1.48 m。マス（0.3125 m）の中心が範囲に入るものを数える。
- M_dyn：範囲内のマスに位置がある粒子の質量。fluid mass は、2.37 にボクセルごとに種類を指定して読む関数がないため含めない（地形全体でも 0〜1.4 kg）。
- ρ/s：その時点の density ÷ swellFactor（dirt_1 で 1,151.6 kg/m³）。

| 列 | 中身 |
| --- | --- |
| `pile_volume` | V_pile [m³] |
| `pile_vol_terrain`、`pile_vol_dynamic` | その内訳：地形の分 Σ max(h − h0, 0)·A、動く土の分 M_dyn ÷ (ρ/s) [m³] |
| `pile_mass_particle` | 範囲内の粒子の質量 M_dyn [kg] |
| `pile_volume_front150`、`pile_volume_front250` | 前を 1.5 m・2.5 m にした V_pile [m³]（感度用） |
| `pile_volume_wide`、`pile_volume_ridge` | 横に1マスずつ広げた V_pile、広げた分（範囲の外側1マス＝横の畝）だけの体積 [m³] |
| `pile_vol_terrain_setup` | h0 の代わりに setup（地形の加工）の後の高さを使った地形の分 [m³]。pile_push で `pile_vol_terrain` との差が、まだ触れていない山の分 |
| `pile_back_offset` | 刃先から排土板の上端までの水平距離 [m]（範囲の後ろの端） |
| `pile_bulk_density` | 換算に使った ρ/s [kg/m³] |
| `dyn_mass_particle_near` | 上端〜刃先の前 0.5 m・±1.48 m の粒子の質量 [kg]（参考） |
| `dyn_mass_particle_total`、`dyn_mass_fluid_total`、`dyn_mass_total`、`dyn_num_particles` | 地形全体の粒子の質量、fluid mass（`calculateTotalFluidMass`）、動く土の合計（`calculateTotalDynamicMass`。粒子 ＋ fluid に一致）[kg]、粒子の数 |
| `bal_vol_pos`、`bal_vol_neg` | 刃先の後ろ 16 m〜前 3 m・±3 m の窓での Σ max(h − h0, 0)·A、Σ min(h − h0, 0)·A [m³]（収支の確認用） |
| `pile_volume_vis` | 粒子を含む高さ場から求める幾何学的な山の体積 [m³]（T24）。V_pile と同じ範囲のマスで Σ max(max(hB, h) − h0, 0)·A。hB は AGX の `Terrain.getSoilParticleBoundedHeightField()`（地形と同じ頂点・同じ基準）。粒子の質量を ρ/s で換算しないので、s にラベルの値を使わない。**地形の経路の観測（s の情報源）にはこの列を使う**（notes の decisions/2026-11-18_地形の経路の観測は粒子を含む高さ場から求める体積にする.md） |
| `pile_volume_vis_wide` | 同じ計算を、刃先の後ろ 1 m〜前 3 m・±2 m で求めた体積 [m³]（範囲の外にこぼれた土を含めるため） |
| `vis_net_pos`、`vis_net_neg`、`vis_net` | 道すじ全体の体積の出入り [m³]（T25）。収支の窓（`bal_*` と同じ、刃先の後ろ 16 m〜前 3 m・±3 m）で、粒子を含む高さ hB と h0'（シーンを読み込んだ直後の同じ粒子を含む高さ場）の差の、正の部分 Σ max(hB − h0', 0)·A・負の部分 Σ max(h0' − hB, 0)·A（正の値）・その差。ΔV_net ≈ (s − 1)·V_cut で、地形の経路の s の観測にする（notes の decisions/2026-11-18_sの判定は道すじ全体の体積の出入りで行う.md） |

- `bal_*` は 25 ステップ（0.5 s）ごとに求め、間は前の値を出す。地形全体の質量（`calculateTotalMass`）も一時は出していたが、1回に約 0.3 s かかって Unity が止まり、深さの制御が乱れた（深さのずれの 95% 点が 2〜4 cm → 9〜19 cm）ので外した。
- `pile_volume`（V_pile）の粒子の分は s のラベルの値で換算するので、V_pile が s で変わるのは計算の作りによる。V_pile は力の経路の入力としてだけ使い、地形の経路の s の観測には使わない。
- 粒子を含む高さ場が取れないか、解像度が地形と違うときは、`pile_volume_vis`・`pile_volume_vis_wide`・`vis_net_*` は NaN。これらの列を足す前の記録にはない。
- `vis_net_*` は 50 ステップ（1 s）ごとに求め、間は前の値を出す。ただし、進行状況が raising の間と進行状況が変わった回は毎回求めるので、エピソードの最後の行の値は新しい。h0' は TerrainData ではなく粒子を含む高さ場から読むので、0.46 mm の差は入らない。
- 解析は `analysis/phase1/check_pile_volume.py`（V_pile）、`analysis/phase1/check_pile_volume_vis.py`（`pile_volume_vis` と V_pile・膨張率の比較）、`analysis/phase1/check_vis_net.py`（`vis_net` と膨張率）。

### 前方の地面の高さの列（T23）
`ground_ahead`・`ground_profile_*` は Unity の TerrainData（AGX の地形の高さ場を毎ステップ書き戻したもの）を読むので、粒子（動く土）を含まず、1ステップ（20 ms）遅れる。地形の経路と模擬 LiDAR のために、同じ8点（刃先の中点から水平の前方 25 cm ごと、25〜200 cm）で次の列を足した（notes の decisions/2026-11-17_粒子を含む高さの列とground_profileの扱い.md）。Unity の `BladeStatePublisher.cs` が求める。この列を足す前の記録にはない。

| 列 | 中身 |
| --- | --- |
| `ground_profile_025cm`〜`200cm` | 地形の高さ場（Unity の TerrainData、`Terrain.SampleHeight`）[m]。粒子を含まない。1ステップ遅れる。これまでの記録と比べるために残す |
| `ground_ahead` | 刃先の前 0.5 m の地形の高さ [m]。**`ground_profile_050cm` と同じ点・同じ値**。本番データのカラムを作り直すとき（フェーズ2）に整理する |
| `ground_terrain_025cm`〜`200cm` | 同じ点の、AGX の地形の高さ場（`Terrain.getHeight`）を直接読んだ高さ [m]。4つの頂点の双一次補間。1ステップの遅れがない。粒子は含まない |
| `ground_vis_025cm`〜`200cm` | 同じ点の、粒子を含む高さ [m]。AGX の `Terrain.getSoilParticleBoundedHeightField()`（粒子を包む高さ場。地形と同じ 257×257 の頂点・同じ基準）を双一次補間し、`ground_terrain_*` との大きいほうを取る。**地形の経路・模擬 LiDAR にはこの列を使う** |
| `ground_ptop_025cm`〜`200cm` | 確かめ用。最寄りの頂点の地形の高さと、その頂点に割り当てた粒子の上端（中心の高さ ＋ 半径）の最大の、大きいほう [m]（`PileVolume.cs` の粒子の走査で求める） |

- 高さはすべてワールドの高さ。AGX の高さ ＋ Terrain の transform の高さがワールドの高さになる（再生中は transform を MaximumDepth だけ下げてあるため）。
- **平らな地面でも、AGX から読む列（`ground_terrain_*`・`ground_vis_*`・`ground_ptop_*`）は、TerrainData から読む列と `ground_h0` より 0.46 mm 低い**（TerrainData の高さの量子化によると考えられる。確かめていない）。`check_recording.py` は、走行中に一定な前方の高さの列を、`ground_h0` との差が 1 mm 以内なら正常とする。
- **前方の地面の高さが走行中に一定になるのは正常**。平らな地面を削る作業では、刃先の前 1.0〜1.25 m（山の大きい 12 cm でも 1.5 m）より先は手つかずの平らな地面なので、高さは `ground_h0` のまま変わらない（pile_push では山が前にある間は変わる）。
- 粒子は少数で大きい（基準の flat_cut・pile_push で 35〜42 個、1 個 平均 約 25 kg。Console に出た2個の半径は 0.066・0.104 m、平均の質量からは約 0.15 m）。すべて排土板の上端（刃先の後ろ 0.34 m）〜刃先の前 0.5 m にあるので、粒子で高くなるのは 25 cm と 50 cm の点だけである（25 cm の点で、走行中の 54〜70% の行で `ground_terrain_*` より 1 mm 以上高い。75 cm より先は `ground_terrain_*` と同じ）。土の山の本体（刃先の後ろ 0.34 m〜前 0.25 m）は8点の範囲の外にある。
- 確かめの解析は `analysis/phase1/check_forward_height.py`。
- 処理時間は、粒子を含む高さ場の読み出しと補間で平均 0.017 ms（最大 0.14 ms）、`BladeStatePublisher` の配信全体で平均 0.43〜0.62 ms（1ステップ 20 ms）。深さのずれの 95% 点（1.9〜2.2 cm）は変わらなかった。

## 3. 大きさの目安（関門7）
| 項目 | 値 |
| --- | --- |
| 時系列データ 1 ファイル | 約 2.3 MB（約 1,500 行 × 89 列。関門7 の時点。現在は 118 列） |
| 1,000 エピソード | 約 2.3 GB |
