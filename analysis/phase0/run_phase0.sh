#!/usr/bin/env bash
# フェーズ0 の全実験を test_episode で順に記録する（計画は RECOLLECT_PLAN.md）。
#
# 使い方（コンテナの中、ワークスペース直下。ROS-TCP-Endpoint を起動し、Unity を Play しておく）：
#   bash analysis/phase0/run_phase0.sh               # 全実験
#   bash analysis/phase0/run_phase0.sh B2_then_cut   # 実験を選ぶ（複数可）
#
# 出力：data/phase0/<実験名>/<日時>_<エピソード>.csv（と _compaction.csv）
# 失敗したエピソードは data/phase0/run_log.txt に FAIL として残し、次へ進む（後で同じ seed で取り直す）。
# 注意：ROS の setup.bash は未定義の変数を参照するので set -u は使わない。

WS=/workspaces/ws-bulldozer
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
cd "$WS"

OUT=data/phase0
LOG=$OUT/run_log.txt
mkdir -p "$OUT"

run() {  # run <実験名> <エピソード> <seed> [test_episode のオプション...]
    local exp=$1 ep=$2 seed=$3; shift 3
    mkdir -p "$OUT/$exp"
    echo "=== $exp $ep seed=$seed $*"
    local before after csv status=OK
    before=$(ls "$OUT/$exp"/*_"$ep".csv 2>/dev/null | wc -l)
    # test_episode は SkipEpisode（実行できない）のとき終了コード 0 で終わるので、出力の記録の有無でも判定する
    ros2 run bull_ope test_episode "$ep" --seed "$seed" --out "$OUT/$exp" "$@" || status=FAIL
    after=$(ls "$OUT/$exp"/*_"$ep".csv 2>/dev/null | wc -l)
    csv=$(ls -t "$OUT/$exp"/*_"$ep".csv 2>/dev/null | head -1)
    if [ "$after" -le "$before" ]; then
        status=FAIL; csv="(記録なし)"
    elif [ ! -s "${csv%.csv}_compaction.csv" ]; then
        status=FAIL; csv="$csv（締固めの記録なし）"
    fi
    echo "$(date '+%F %T') $status $exp $ep seed=$seed $* -> $(basename "$csv")" >> "$LOG"
}

A_passes()    { for s in 0 1;               do run A_passes    ex_compaction_passes   $s; done; }
B1_bands()    { for s in 0 1 2 3;           do run B1_bands    ex_compaction_bands    $s; done; }
B2_then_cut() { for s in 0 1 2 3;           do run B2_then_cut ex_compaction_then_cut $s; done; }
B3_patterns() { for s in 0 1 2 3 4 5 6 7;   do run B3_patterns ex_compaction_patterns $s; done; }
B3_levels()   { for s in 0 1 2 3 4 5 6 7;   do run B3_levels   ex_compaction_levels   $s; done; }

hardening() {  # hardening <条件名> <KE> <NE>
    local exp=hardening_$1 ke=$2 ne=$3
    for s in 0 1 2 3; do run "$exp" ex_compaction_levels $s --ke "$ke" --ne "$ne"; done
    for s in 0 1 2 3; do run "$exp" ex_compaction_bands  $s --ke "$ke" --ne "$ne"; done
}
hardening_baseline() { hardening baseline 1.0 0.0833; }
hardening_NE1()      { hardening NE1      1.0 1.0; }
hardening_KE0()      { hardening KE0      0.0 0.0833; }

ALL=(A_passes B1_bands B2_then_cut B3_patterns B3_levels hardening_baseline hardening_NE1 hardening_KE0)
targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=("${ALL[@]}")
for t in "${targets[@]}"; do
    if declare -F "$t" > /dev/null; then "$t"; else echo "不明な実験: $t（${ALL[*]}）"; exit 1; fi
done
echo "完了。失敗の有無は $LOG を確認する。"
grep FAIL "$LOG" 2>/dev/null || true
