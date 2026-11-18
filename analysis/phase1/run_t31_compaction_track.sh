#!/usr/bin/env bash
# T31：締固めの記録つきで同定用のエピソードを取り直す（3作業 × 35 本）と、折り返しの別名版（v2）の確かめ。
# decisions/2026-11-18_同定用のエピソードで締固めの記録を取る.md、decisions/2026-11-18_折り返しは進みの判定の別名版と失敗の検出で直す.md
#
# 使い方（コンテナの中、ワークスペース直下。ROS-TCP-Endpoint を起動し、Unity を Play しておく）：
#   bash analysis/phase1/run_t31_compaction_track.sh            # すべて
#   bash analysis/phase1/run_t31_compaction_track.sh v2         # v2 の確かめだけ
#   bash analysis/phase1/run_t31_compaction_track.sh flat_cut   # 作業を選ぶ（複数可）
#   bash analysis/phase1/run_t31_compaction_track.sh fp_rest pile_push   # 1回目の続き（Unity が固まった後）
#   bash analysis/phase1/run_t31_compaction_track.sh fill_flat_piecewise fill_pile_push   # 足りない本数だけ回し足す
# 出力：data/phase1/compaction_track/<作業>/run_*_t31_*（collect_data）、data/phase1/compaction_track/turnaround_v2/（test_episode）
# 注意：ROS の setup.bash は未定義の変数を参照するので set -u は使わない。

WS=/workspaces/ws-bulldozer
source /opt/ros/humble/setup.bash
source "$WS/install/setup.bash"
cd "$WS"
OUT=data/phase1/compaction_track
C="ros2 run bull_ope collect_data"

swell_name() {  # swell_name <作業> <110|140>：膨張率の端のエピソード名（T12・T31 の ex_swell_*）
    echo "ex_swell_$1_s$2"
}

task() {  # task <作業>
    local T=$1
    $C --episodes ex_ident_${T}_base --num 5 --seed 61 --out $OUT/$T --run-name t31_base
    $C --episodes ex_ident_${T}_s_m0p06 ex_ident_${T}_s_p0p06 "$(swell_name $T 110)" "$(swell_name $T 140)" \
                  ex_ident_${T}_phi_m10 ex_ident_${T}_phi_p10 ex_ident_${T}_c_m1p5 ex_ident_${T}_c_p1p5 \
                  ex_ident_${T}_rho_m70 ex_ident_${T}_rho_p70 \
       --num 3 --seed 62 --out $OUT/$T --run-name t31_points
}

fp_rest() {  # 1回目に Unity が固まって取れなかった flat_piecewise の3本（c ±1.5 kPa・φ +10° 各1本）
    $C --episodes ex_ident_flat_piecewise_c_m1p5 ex_ident_flat_piecewise_c_p1p5 ex_ident_flat_piecewise_phi_p10 \
       --num 1 --seed 63 --out $OUT/flat_piecewise --run-name t31_rest
}

fp_rest2() {  # 1回目で締固めの記録が届かなかった flat_piecewise の2本（φ −10°・ρ −70 各1本。compaction_rows 0）
    $C --episodes ex_ident_flat_piecewise_phi_m10 ex_ident_flat_piecewise_rho_m70 \
       --num 1 --seed 64 --out $OUT/flat_piecewise --run-name t31_rest2
}

missing() {  # missing <作業>：各エピソードの足りない本数を「名前 本数」の行で出す（status ok かつ締固めの記録が届いた回を数える）
    python3 - "$OUT/$1" "$1" <<'PY'
import glob, json, os, sys
d, t = sys.argv[1], sys.argv[2]
sw = {"flat_cut": "ex_swell_flat_cut", "flat_piecewise": "ex_swell_flat_piecewise", "pile_push": "ex_swell_pile_push"}[t]
want = {f"ex_ident_{t}_base": 5}
for pt in ("s_m0p06", "s_p0p06", "phi_m10", "phi_p10", "c_m1p5", "c_p1p5", "rho_m70", "rho_p70"):
    want[f"ex_ident_{t}_{pt}"] = 3
want[f"{sw}_s110"] = want[f"{sw}_s140"] = 3
have = {k: 0 for k in want}
for f in glob.glob(os.path.join(d, "run_*", "episodes.jsonl")):
    for line in open(f, encoding="utf-8"):
        r = json.loads(line)
        if r.get("status") == "ok" and r.get("compaction_rows", 0) > 0 and r.get("episode_name") in have:
            have[r["episode_name"]] += 1
for k, n in want.items():
    if n > have[k]:
        print(k, n - have[k])
PY
}

fill() {  # fill <作業>：足りない本数だけ回す（Unity が固まった・記録が届かなかった回の回し足し）
    local T=$1 seed=70
    missing $T | while read -r name n; do
        seed=$((seed + 1))
        $C --episodes $name --num $n --seed $seed --out $OUT/$T --run-name t31_fill
    done
    echo "足りない本数（$T）："; missing $T
}

v2() {
    local D=$OUT/turnaround_v2
    mkdir -p $D
    ros2 run bull_ope test_episode ex_compaction_passes_v2 --seed 0 --out $D
    ros2 run bull_ope test_episode ex_compaction_passes_v2_rho1900 --seed 0 --out $D
    ros2 run bull_ope test_episode ex_compaction_passes_v2_rho1900 --seed 1 --out $D
    ros2 run bull_ope test_episode ex_compaction_then_cut_v2 --seed 0 --out $D   # 偶数のシード = 踏み固めあり
}

targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=(v2 flat_cut flat_piecewise pile_push)
for t in "${targets[@]}"; do
    case $t in
        v2) v2 ;;
        fp_rest) fp_rest ;;
        fp_rest2) fp_rest2 ;;
        fill_flat_cut|fill_flat_piecewise|fill_pile_push) fill "${t#fill_}" ;;
        flat_cut|flat_piecewise|pile_push) task "$t" ;;
        *) echo "不明: $t"; exit 1 ;;
    esac
done
echo "完了"
