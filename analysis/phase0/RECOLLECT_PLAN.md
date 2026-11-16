# フェーズ0 の記録の取り直しの計画

notes の decisions/2026-11-17_フェーズ0のデータを取り直す.md に基づき、フェーズ0 の記録を消して同じ条件で取り直す。取り直した記録は `data/phase0/` にまとめ、図と本文の数値はそこから作る。

## 1. 今の記録（取り直す前の調査、2026-11-17）

記録はすべて 2026-11-11 に取ったもの（`data/test/` の 20261116_* はリファクタリングの確認用）。当時は Unity の CompactionProbe がエピソード名（`ex_compaction` で始まる）で締固めの記録を判定し、`compaction_<日時>_<エピソード>.csv` を書いていた。硬化の設定は Unity の CompactionParamOverride で変えていた（記録の CSV に KE・NE の列はない）。今はどちらも ROS 側から指定する（`RECORD_COMPACTION`、`test_episode --ke/--ne`）。

| 実験 | エピソード | 記録（時系列 / 締固め） | seed | KE・NE | 解析とオプション | 使った図・値 |
|---|---|---|---|---|---|---|
| A | ex_compaction_passes | 時系列 3（`data/test/` 045536・051314・060227）/ 締固め 4（`data/compaction/` 045543・051320・060234・060815） | 0 | 既定（1・0.0833） | `check_compaction.py`（既定 x0 0.5・x1 7.5・cell 0.3125） | 図2〜4。使ったのは 060234・060815 の2つ（本文の値と合うものを後から選んだ）。045543 は通過を判定できず、051320 は履帯ごとに1列 |
| B1 | ex_compaction_bands | 時系列 **なし**（070412・070446・070520・070554 を解析した出力だけ `expB1/` に残る）/ 締固め 4（070419〜070600） | 0〜3 | 既定 | `check_cut_bands.py`（既定 trim 0.5） | 図6(b) の 0.78・1.08・1.16（`expB3_levels/`） |
| B2 | ex_compaction_then_cut | 時系列 **なし** / 締固め **なし**（`expB2/compare.csv` だけ） | 不明（偶数＝踏み固めあり、奇数＝対照） | 既定 | `check_cut_bands.py`（既定 bin 0.5） | 図5 の B2（比 0.69）。§3.3 の「地表 1.132、深さ方向の平均 1.055 に対して 1.108」は出どころの記録がない |
| B3 範囲 | ex_compaction_patterns | 時系列 **なし**（073005〜073358 の出力だけ `expB3_patterns/`）/ 締固め 8（073011〜073404） | 0〜7 | 既定 | `check_cut_bands.py` | 図5 |
| B3 程度 | ex_compaction_levels | 時系列 **なし**（073436〜073618 の出力だけ `expB3_levels/`）/ 締固め 4（073444〜073625） | 0〜3 | 既定 | `check_cut_bands.py` | 図6(b)、§3.3 の表の切削抵抗の比 |
| 較正 | ex_compaction_levels・ex_compaction_bands | 締固め 12（`data/compaction/a/`：levels 075448〜075925、bands 080010〜080209） | levels 0〜7、bands 0〜3（帯の程度から推定） | 既定 | `check_track_settlement.py --out …/settlement2` → `calibrate_settlement.py --seg 0.5 1` | 図6(a)・図7、§3.3 の表の追加の沈下、RMSE |
| 硬化（3条件） | ex_compaction_levels・ex_compaction_bands | 条件ごとに時系列 8・締固め 8（`data/hardening/{baseline,NE1,KE0}/`） | levels 0〜3、bands 0〜3 | baseline 1・0.0833、NE1 1・1.0、KE0 0・0.0833 | `check_cut_bands.py --out …/cut_bands`、`check_track_settlement.py --out …/settlement` | 図9〜11、§3.4 |

`data/compaction/settlement/`（16 記録・1 記録 100 マス）は、走行距離を直す前の記録（docs/history.md §7）。

## 2. 取り直しの条件

上の表の条件をそのまま使う。土質はエピソードで固定（c 2100 Pa・φ 39.98°・ρ 1474 kg/m³）。

| 出力（`data/phase0/`） | エピソード | seed | KE・NE | 記録の数 | 締固めの記録 |
|---|---|---|---|---|---|
| `A_passes/` | ex_compaction_passes | 0、1 | 既定 | 2 | 要 |
| `B1_bands/` | ex_compaction_bands | 0〜3 | 既定 | 4 | 要 |
| `B2_then_cut/` | ex_compaction_then_cut | 0〜3（0・2 踏み固めあり、1・3 対照） | 既定 | 4 | 要（図8） |
| `B3_patterns/` | ex_compaction_patterns | 0〜7 | 既定 | 8 | 要（較正には使わないが、元と同じく記録する） |
| `B3_levels/` | ex_compaction_levels | 0〜7 | 既定 | 8 | 要 |
| `hardening_baseline/` | levels 0〜3、bands 0〜3 | — | 1・0.0833 | 8 | 要 |
| `hardening_NE1/` | 同上 | — | 1・1.0 | 8 | 要 |
| `hardening_KE0/` | 同上 | — | 0・0.0833 | 8 | 要 |

計 50 エピソード。

- 実験A：エピソードに乱数はないので seed は記録の区別のためだけ（0・1）。
- 較正は、元と同じく levels 0〜7 と bands 0〜3 の 12 記録で作る。元は図6(b) 用（B1・B3 程度 seed 0〜3）と較正用（`a/`）を別に取っていたが、条件が同じなので `B1_bands/`・`B3_levels/` を両方に使う。
- 硬化の baseline は既定の設定と同じだが、元と同じく別に記録する（3条件を同じ手順・同じ時期の記録で比べるため）。既定の設定の記録も `--ke 1 --ne 0.0833` を明示する。

## 3. 実行

```bash
# コンテナの中で ROS-TCP-Endpoint を起動し、Unity の DataCollectionScene を Play したうえで
bash analysis/phase0/run_phase0.sh                 # 全部
bash analysis/phase0/run_phase0.sh B2_then_cut     # 実験を選ぶ
```

失敗・スキップしたエピソードは同じ seed で取り直す。取り直した場合も、すべての記録を MANIFEST.md に載せ、図に使う記録を後から選び直さない（使わない記録は理由を書く）。

## 4. 解析（出力は各実験のフォルダの下）

```bash
python3 analysis/phase0/check_compaction.py data/phase0/A_passes/<各記録>_compaction.csv --out data/phase0/A_passes/report_<日時>
python3 analysis/phase0/check_cut_bands.py data/phase0/B1_bands/*_ex_compaction_bands.csv data/phase0/B3_levels/*_ex_compaction_levels.csv --out data/phase0/analysis/cut_levels
python3 analysis/phase0/check_cut_bands.py data/phase0/B3_patterns/*_ex_compaction_patterns.csv --out data/phase0/analysis/cut_patterns
python3 analysis/phase0/check_cut_bands.py data/phase0/B2_then_cut/*_ex_compaction_then_cut.csv --out data/phase0/analysis/cut_then_cut
python3 analysis/phase0/check_track_settlement.py data/phase0/{B1_bands,B3_levels}/*_compaction.csv --out data/phase0/analysis/settlement
python3 analysis/phase0/calibrate_settlement.py data/phase0/analysis/settlement/cells.csv --seg 0.5 1 --out data/phase0/analysis/calibration
# 硬化の3条件（<cond> = baseline / NE1 / KE0）
python3 analysis/phase0/check_cut_bands.py data/phase0/hardening_<cond>/*_ex_compaction_{levels,bands}.csv --out data/phase0/hardening_<cond>/cut_bands
python3 analysis/phase0/check_track_settlement.py data/phase0/hardening_<cond>/*_compaction.csv --out data/phase0/hardening_<cond>/settlement
```

## 5. 取り直しの前に直したこと

- **締固めの記録の有無**：リファクタリングの後のコードでは `RECORD_COMPACTION = True` が `ex_compaction_bands` だけだった（2026-11-11 は Unity 側がエピソード名で判定していたので、`ex_compaction_*` はすべて記録された）。同じ条件で取り直すため、ユーザーの確認を取って `ex_compaction_passes`・`ex_compaction_then_cut`・`ex_compaction_patterns`（`ex_compaction_levels` を含む共通の基底クラス）にも `RECORD_COMPACTION = True` を付けた。記録のカラムは変わらない。
