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

### 常に NaN の列
時系列データの `front_soil_mass`（排土板の前の土の質量）と `excavated_volume_step`（そのステップの掘削体積）は、**常に NaN** で、使えない。

- 理由：Unity の `BladeStatePublisher.cs` で、この2列を求める処理が `#if AGX_EXTRA_TERRAIN_API` の中にあり、このシンボルを定義していない。定義しても、`Terrain.getSoilParticleAggregate(shovel)` は AGX 2.37 の C# にはない（2.37 では TerrainToolCollection の側にある）のでコンパイルが通らない。`Terrain.getLastExcavatedVolume` は 2.37 にもある。
- 本番データの再取得の前に、AGX の体積・質量の API（`getSoilAggregateMass`・`getInnerVolume` など）で取れるようにする予定（notes の decisions/2026-11-17_土の山の項の摩擦角と体積の入力.md）。
- それまでは、土の山の量の代わりに `cut_volume`（地山を削った体積の積算。頭打ちの前だけ）を使う。

## 3. 大きさの目安（関門7）
| 項目 | 値 |
| --- | --- |
| 時系列データ 1 ファイル | 約 2.3 MB（約 1,500 行 × 89 列。関門7 の時点。現在は 91 列） |
| 1,000 エピソード | 約 2.3 GB |
