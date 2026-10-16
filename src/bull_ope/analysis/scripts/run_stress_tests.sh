#!/usr/bin/env bash
# =============================================================================
# 関門1：スクリプトの不具合探し（stress_* エピソードの一括実行）
#
# 使い方（ワークスペースのどこからでも可）:
#   bash src/bull_ope/analysis/scripts/run_stress_tests.sh            # 段階 A〜D をすべて実行
#   bash src/bull_ope/analysis/scripts/run_stress_tests.sh A B        # 指定した段階だけ実行
#   PAUSE=1 bash src/bull_ope/analysis/scripts/run_stress_tests.sh A  # 段階A で1つ終わるごとに Enter を待つ
#
# 段階:
#   A  : stress_* を1つずつ test_episode で実行（Unity の画面を見ながら確かめる）
#   B  : 失敗するエピソードと普通のエピソードを混ぜて collect_data で連続実行
#   B2 : stress_numpy_params を collect_data で実行（記録の JSON 変換の不具合の確認。止まるのが想定）
#   C  : 土質を極端な範囲で変えて連続実行（ラベルの入れ替わりの確認）
#   D  : 2 秒のエピソードを 50 回（シーンの読み込み直しの耐久試験）
#
# 結果: src/bull_ope/data/validation/stress/<実行日時>/ に、CSV・ログ・点検結果をまとめて保存する
# 前提: Unity が Play 中であること。config.py の SAFE_RADIUS が設定されていること
# =============================================================================
set -u

WS=/workspaces/ws-bulldozer
PKG=$WS/src/bull_ope
CHECK=$PKG/analysis/checks/check_collection.py
STAMP=$(date +%Y%m%d_%H%M%S)
OUT=$PKG/data/validation/stress/$STAMP
mkdir -p "$OUT"

cd "$WS"

set +u
# shellcheck disable=SC1091
source install/setup.bash
set -u

STAGES=("$@")
[ ${#STAGES[@]} -eq 0 ] && STAGES=(A B B2 C D)

log() { echo -e "\n===== $* =====" | tee -a "$OUT/summary.log"; }

# collect_data を実行し、できたフォルダを点検する
collect_and_check() {   # $1: 実行名, $2: 回数, 残り: エピソード名
    local name=$1 num=$2; shift 2
    log "collect_data: $name（$* を各 $num 回）"
    ros2 run bull_ope collect_data --episodes "$@" --num "$num" --run-name "$name" --out "$OUT" \
        2>&1 | tee "$OUT/${name}.log"
    echo "終了コード: ${PIPESTATUS[0]}" | tee -a "$OUT/summary.log"
    local dir
    dir=$(ls -d "$OUT"/run_*_"$name" 2>/dev/null | tail -1)
    if [ -n "$dir" ] && [ -f "$dir/episodes.jsonl" ]; then
        python3 "$CHECK" "$dir" --report "$OUT/check_${name}.md" | tee -a "$OUT/summary.log"
    else
        echo "episodes.jsonl がありません（収集が途中で止まった可能性）" | tee -a "$OUT/summary.log"
    fi
}

clock_rate() {   # シミュレーションの速さ（/clock の周波数）を 10 秒測る
    log "/clock の周波数（$1）"
    timeout 10 ros2 topic hz /clock 2>&1 | tail -3 | tee -a "$OUT/summary.log"
}

for stage in "${STAGES[@]}"; do
    case "$stage" in
    A)
        # 危険の少ないものから順に
        for ep in stress_instant_done stress_error_midrun stress_none_command stress_runaway \
                  stress_depth_limits stress_spin stress_heavy_push stress_nan_depth; do
            log "段階A: test_episode $ep"
            ros2 run bull_ope test_episode "$ep" --out "$OUT/A" 2>&1 | tee "$OUT/A_${ep}.log"
            echo "終了コード: ${PIPESTATUS[0]}" | tee -a "$OUT/summary.log"
            if [ "${PAUSE:-0}" = "1" ]; then
                read -r -p "Unity の画面と Console を確認したら Enter を押してください… "
            fi
        done
        ;;
    B)
        collect_and_check stress_mix 3 \
            val_constant_depth stress_error_midrun stress_none_command stress_runaway stress_instant_done
        ;;
    B2)
        collect_and_check stress_numpy 1 stress_numpy_params
        ;;
    C)
        collect_and_check stress_soil 10 stress_soil_extremes
        ;;
    D)
        clock_rate "耐久試験の前"
        collect_and_check stress_endurance 50 stress_short
        clock_rate "耐久試験の後"
        ;;
    *)
        echo "不明な段階: $stage（A, B, B2, C, D のいずれか）"
        ;;
    esac
done

log "完了。結果: $OUT"
