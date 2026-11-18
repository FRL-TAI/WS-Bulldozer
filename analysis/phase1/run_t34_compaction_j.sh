#!/usr/bin/env bash
# T34：締固めの列の J を折れ目の両側で3作業について求めるための記録（締固めの記録つき、compaction_rect で設定）。
# notes decisions/2026-11-18_締固めの列は折れ目の両側で別々に判定する.md
#   flat_cut：0.94・1.06 を各 5 本（T33 の各 3 本と合わせて各 8 本）、0.97・1.03 を各 5 本
#   flat_piecewise・pile_push：0.94・1.06 を各 8 本
#
# 使い方（コンテナの中、ワークスペース直下。ROS-TCP-Endpoint を起動し、Unity を Play しておく。AGX_GRID_CONTROL が必要）：
#   bash analysis/phase1/run_t34_compaction_j.sh                  # すべて
#   bash analysis/phase1/run_t34_compaction_j.sh flat_cut pile_push   # 作業を選ぶ
# 出力：data/phase1/compaction_j/run_*_t34_*（flat_cut）、data/phase1/compaction_j_<作業>/run_*_t34（ほかの2作業）
# 注意：ROS の setup.bash は未定義の変数を参照するので set -u は使わない。

WS=/workspaces/ws-bulldozer
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
cd "$WS"
C="ros2 run bull_ope collect_data"

flat_cut() {
    $C --episodes ex_ident_flat_cut_k_m0p06 ex_ident_flat_cut_k_p0p06 ex_ident_flat_cut_k_m0p03 ex_ident_flat_cut_k_p0p03 \
       --num 5 --seed 81 --out data/phase1/compaction_j --run-name t34_flat_cut
}
flat_piecewise() {
    $C --episodes ex_ident_flat_piecewise_k_m0p06 ex_ident_flat_piecewise_k_p0p06 \
       --num 8 --seed 82 --out data/phase1/compaction_j_flat_piecewise --run-name t34
}
pile_push() {
    $C --episodes ex_ident_pile_push_k_m0p06 ex_ident_pile_push_k_p0p06 \
       --num 8 --seed 83 --out data/phase1/compaction_j_pile_push --run-name t34
}

if [ $# -eq 0 ]; then set -- flat_cut flat_piecewise pile_push; fi
for t in "$@"; do "$t"; done
