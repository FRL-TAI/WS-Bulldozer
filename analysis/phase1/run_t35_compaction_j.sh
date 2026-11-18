#!/usr/bin/env bash
# T35：緩い側の凸を 3作業の ±0.03 で確かめるための記録（締固めの記録つき、compaction_rect で設定）。
# notes decisions/2026-11-18_緩い側の凸を3作業の±0.03で確かめる.md
#   1. pile_push 0.97・1.03 を各 8 本
#   2. flat_piecewise 0.97・1.03 を各 8 本
#   3. pile_push 0.94 を 8 本（T34 の 8 本と合わせて 16 本）
#   4. flat_cut 0.97・1.03 を各 3 本（T34 の 5 本と合わせて 8 本）
#
# 使い方（コンテナの中、ワークスペース直下。ROS-TCP-Endpoint を起動し、Unity を Play しておく。AGX_GRID_CONTROL が必要）：
#   bash analysis/phase1/run_t35_compaction_j.sh                        # すべて（上の順）
#   bash analysis/phase1/run_t35_compaction_j.sh pp03 fp03 pp94 fc03   # 段階を選ぶ
#   bash analysis/phase1/run_t35_compaction_j.sh fill                  # 締固めの記録が届かなかった分の回し足し（すべての後に）
# 出力：data/phase1/compaction_j_pile_push/run_*_t35_*、data/phase1/compaction_j_flat_piecewise/run_*_t35、
#       data/phase1/compaction_j/run_*_t35_flat_cut
# 注意：ROS の setup.bash は未定義の変数を参照するので set -u は使わない。

WS=/workspaces/ws-bulldozer
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
cd "$WS"
C="ros2 run bull_ope collect_data --max-consecutive-errors 3"

# Unity が Play になるまで待つ（collect_data の wait_ready は約 30 秒で諦めるため、無人で始めるときに使う）
# （トピック名だけでは collect_data 自身の購読でも出るので、送り手〔Unity〕の数で見る）
until ros2 topic info /d37pxi_24/blade_state 2>/dev/null | grep -q 'Publisher count: [1-9]'; do sleep 10; done
echo "Unity の接続を確認：$(date)"

pp03() {
    $C --episodes ex_ident_pile_push_k_m0p03 ex_ident_pile_push_k_p0p03 \
       --num 8 --seed 91 --out data/phase1/compaction_j_pile_push --run-name t35_03
}
fp03() {
    $C --episodes ex_ident_flat_piecewise_k_m0p03 ex_ident_flat_piecewise_k_p0p03 \
       --num 8 --seed 92 --out data/phase1/compaction_j_flat_piecewise --run-name t35
}
pp94() {
    $C --episodes ex_ident_pile_push_k_m0p06 \
       --num 8 --seed 93 --out data/phase1/compaction_j_pile_push --run-name t35_m0p06
}
fc03() {
    $C --episodes ex_ident_flat_cut_k_m0p03 ex_ident_flat_cut_k_p0p03 \
       --num 3 --seed 94 --out data/phase1/compaction_j --run-name t35_flat_cut
}
# 締固めの記録が届かなかった分の回し足し（1回まで）：flat_piecewise の 1.03 で 8 本中 7 本が届かなかった
fill() {
    $C --episodes ex_ident_flat_piecewise_k_p0p03 \
       --num 7 --seed 95 --out data/phase1/compaction_j_flat_piecewise --run-name t35_fill
}

if [ $# -eq 0 ]; then set -- pp03 fp03 pp94 fc03; fi
for t in "$@"; do "$t"; done
