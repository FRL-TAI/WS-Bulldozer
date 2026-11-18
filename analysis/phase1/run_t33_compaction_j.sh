#!/usr/bin/env bash
# T33：締固めの列の J（案A）の試し。flat_cut で、初期の地面の締固めの程度を 0.94・1.06 にした点と基準を各 3 本、締固めの記録つきで取る。
# notes decisions/2026-11-18_締固めの列のJは締固めを動かす取り直しで作る.md
#
# 使い方（コンテナの中、ワークスペース直下。ROS-TCP-Endpoint を起動し、Unity を Play しておく。AGX_GRID_CONTROL が必要）：
#   bash analysis/phase1/run_t33_compaction_j.sh
#   python3 analysis/phase1/check_compaction_j.py --report data/phase1/compaction_j/report.md
# 出力：data/phase1/compaction_j/run_*_t33_trial（collect_data）
# 注意：ROS の setup.bash は未定義の変数を参照するので set -u は使わない。

WS=/workspaces/ws-bulldozer
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
cd "$WS"
OUT=data/phase1/compaction_j

ros2 run bull_ope collect_data \
    --episodes ex_ident_flat_cut_k_m0p06 ex_ident_flat_cut_base ex_ident_flat_cut_k_p0p06 \
    --num 3 --seed 71 --out $OUT --run-name t33_trial
