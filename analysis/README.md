# analysis：解析・点検のスクリプト

`bull_ope` が記録したデータ（`data/`）を解析・点検するスクリプト。ROS2 のパッケージとしてはインストールされないので、ビルドせずにワークスペース直下から `python3` や `bash` で実行する。

```
cd /workspaces/ws-bulldozer
python3 analysis/<フォルダ>/<スクリプト> --help
```

スクリプトは、使った場面ごとにフォルダを分けている。中身の共通化はしていない（関門ごとに書き、検証を終えたスクリプトのため）。新しいフェーズの解析は `analysis/phaseN/` に置く。

| フォルダ | 場面 |
| --- | --- |
| [production/](#production本番の収集の点検) | 本番の収集の点検（`src/bull_ope/scripts/run_production.sh` が使う） |
| [validation/](#validationデータ検証の関門17) | データ検証の関門1〜7 |
| [phase0/](#phase0フェーズ0締固め沈下較正曲線) | 卒研のフェーズ0（締固め・沈下・較正曲線） |


## production/：本番の収集の点検
| スクリプト | 用途 | 関門 |
| --- | --- | --- |
| `check_collection.py` | `collect_data` の1回分の出力フォルダを点検する（結果の内訳、開始位置のばらつき、ラベルと要求した土質の一致、行数・NaN）。`run_production.sh` が区切りごとに実行する | 1〜7、本番 |
| `check_dataset.py` | 学習データとしての使いやすさ（土質の広がり、関門5・6の関係）と、本番の収集の見積もりを出す。`run_production.sh` が区切りごとに実行する | 7、本番 |

`check_dataset.py` は `validation/check_sensitivity.py`（とそれが使う `validation/check_physics.py`）の関数を使う。`analysis/validation/` を `sys.path` に加えて読み込むので、フォルダの構成を変えるときは合わせて直す。


## validation/：データ検証の関門1〜7
各関門のレポートは [docs/bull_ope/validation/](../docs/bull_ope/validation/README.md)。

| スクリプト | 用途 | 関門 |
| --- | --- | --- |
| `run_stress_tests.sh` | 関門1の段階A〜D（`stress_*`）をまとめて実行し、点検まで行う。結果は `data/validation/stress/<実行日時>/` | 1 |
| `dryrun_stress.py` | Unity を使わずに、疑似の機体で各エピソードを `runner.py` に通し、例外の種類と記録の流れを確かめる | 1 |
| `check_recording.py` | 1つのエピソードの CSV が、きちんと記録されているかを確かめる（周期、時刻の逆戻り、NaN、一定の列、ラベル、進行状況の順番） | 1〜3、7 |
| `check_gate2.py` | 記録の健全さの追加の点検（列の構成、行数・メタ情報の一致、時刻の整合、トピックの更新） | 2〜7 |
| `check_units.py` | 単位・座標・符号の点検 | 3、7 |
| `inspect_depth.py` | 深さの追従・刃先と地面・記録の最初の状態の WARN を調べる | 3 |
| `check_timing.py` | トピックの間の時刻のずれと、指令から応答までの遅れを測る | 4、7 |
| `check_physics.py` | AGX の反力を、土の力学の式（FEE）や力のつり合いと比べる | 5 |
| `check_sensitivity.py` | `val_sens_*` の結果から、再現性（繰り返しのばらつき）と識別可能性（土質・速度を変えたときの変化）を比べる。`check_physics.py` の関数を使う | 6 |


## phase0/：フェーズ0（締固め・沈下・較正曲線）
締固めを、履帯で踏んだときの追加の沈下（地形の経路）から推定できるかを調べた。結論と経緯は notes の `docs/phase0.md`。入力は `test_episode` の CSV と、締固めの記録（`*_compaction.csv`、[docs/bull_ope/README.md の 3.3](../docs/bull_ope/README.md#33-締固めの記録_compactioncsv)）。データは `data/compaction/` に置いている。

| スクリプト | 用途 | 実験 |
| --- | --- | --- |
| `check_compaction.py` | 締固めの記録を読み、履帯による締固めの起き方（通過ごとの締固めの程度・沈下量、深さ方向・前後方向の分布）を要約する | 実験A（`ex_compaction_passes`） |
| `check_cut_bands.py` | 締固めの程度ごとの帯で切削抵抗を比べる（力の経路。締固めの推定には使わないと結論した） | 実験B1〜B3（`ex_compaction_bands`、`ex_compaction_then_cut`、`ex_compaction_patterns`、`ex_compaction_levels`） |
| `check_track_settlement.py` | 削った後の地面を履帯が踏んだときの追加の沈下と、その地面の締固めの程度の関係を調べる。`--out` でマスごとの値（`cells.csv`）を保存する | 実験B1・B3 の締固めの記録 |
| `calibrate_settlement.py` | `cells.csv` から、追加の沈下 → 締固めの程度の較正曲線を作り、記録ごとの交差検証で精度を評価する | 同上（関門0） |

実行例（フェーズ0 の較正曲線）：

```
python3 analysis/phase0/check_track_settlement.py \
    data/compaction/compaction_*_ex_compaction_{bands,patterns,levels}.csv \
    --out data/compaction/settlement --plot
python3 analysis/phase0/calibrate_settlement.py data/compaction/settlement/cells.csv \
    --seg 0.5 1 2 --out data/compaction/calibration --plot
```
