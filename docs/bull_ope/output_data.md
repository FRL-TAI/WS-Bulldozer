# 出力データ
[← bull_ope のドキュメントの入口](README.md)

時系列データ（`ep*.csv`）の各列の意味は [README の 3.2](README.md#32-収集データ時系列データ-epcsv-の列) を参照。この文書では、フォルダの構成と、エピソードごとの情報（`episodes.jsonl`）をまとめる。

## 1. フォルダの構成
保存先の既定は `src/bull_ope/data/`（`config.py` の `DATA_DIR`。環境変数 `SOIL_DATA_DIR` で変えられる）。`data/` 以下は Git の管理外（`.gitignore` で `.gitkeep` だけを管理する）。

```
data/
├ test/                                   test_episode の出力
│  └ <日時>_dataset_flat_cut.csv
├ production/                             本番の収集（run_production.sh）
│  ├ production.log                       区切りごとの開始・終了と点検の要約
│  ├ chunk001_cut.log、chunk001_pw.log     区切りごとのターミナルの出力
│  ├ chunk001_check_dataset.md            区切りごとの check_dataset.py の結果
│  ├ run_<日時>_chunk001_cut/       collect_data の出力（下）
│  └ run_<日時>_chunk001_pw/
├ production_pile/                        追加のデータ（dataset_pile_push。OUT で指定）
├ pilot/                                  関門7（試験的な収集）
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
└ check_collection.md など  点検の結果（run_production.sh や点検のスクリプトが作る）
```

- `episodes.jsonl` は途中で止まっても残る。`episodes.csv` は最後まで終わったときだけ作られ、エピソードの種類ごとに異なる列（操作のパラメータ）の和集合になる。
- フォルダの中の `ep*.csv` を点検のスクリプトにまとめて渡すときは、`episodes.csv` が混ざらないよう `ep[0-9]*.csv` と指定する。


## 2. episodes.jsonl / episodes.csv の列
| 列 | 内容 |
| --- | --- |
| `episode_index`、`file` | エピソード番号と時系列データのファイル名 |
| `episode_name`、`seed` | エピソード名と乱数のシード |
| `soil_cohesion`、`soil_friction_angle_deg`、`soil_density`、`soil_swell_factor`、`soil_youngs_modulus` | 要求した土質（指定しなかったものは `null`） |
| `param_*` | 操作のパラメータ（エピソードの種類による。例：`dataset_flat_cut` は `param_depth`・`param_speed`、`dataset_flat_piecewise` は `param_depths`・`param_speeds`（3区間のリスト）、`dataset_pile_push` は `param_pile_start`・`param_pile_length`・`param_pile_height`・`param_depth`・`param_speed`） |
| `n_terrain_ops` | 地形の加工の件数 |
| `ground_h0` | 切削深さの基準とした地面の高さ [m] |
| `label_c`、`label_phi`、`label_rho0`、`label_swell`、`label_E0` | AGX から読み戻した土質（ラベル） |
| `start_x`、`start_y`、`start_yaw_deg` | 開始時の車体の位置 [m] と向き [deg]（毎回同じ状態から始まっているかの確認用） |
| `run_time`、`run_distance` | 走行時間 [s] と走行距離 [m] |
| `raise_depth_over_max` | 上げる区間で実際の深さが `MAX_ACTUAL_DEPTH` を超えた場合の最大値 [m]。超えなければ `null` |
| `rows`、`path` | 時系列データの行数とパス |
| `status` | `ok`、`skipped: 理由`、`error: 内容` |

- エラーやスキップで止まったエピソードは、止まった時点までに決まっている列（エピソードの情報と `status`）だけが入る。
- NumPy の型や NaN・無限大は、書き出す前に普通の型（NaN・無限大は `null`）に変換する（`recording/json_utils.py`）。

**`dataset_pile_push` の山の体積**は、`param_pile_length` × 3.0 m × `param_pile_height`（緩い状態の体積）で計算できる。時系列データの `cut_volume` は地山を削った分だけで、山の量は含まない。


## 3. 大きさの目安（関門7）
| 項目 | 値 |
| --- | --- |
| 時系列データ 1 ファイル | 約 2.3 MB（約 1,500 行 × 89 列） |
| 1,000 エピソード | 約 2.3 GB |
