#!/usr/bin/env bash
# 本番の収集を、区切り（チャンク）ごとに実行する。
#
# 置き場所: src/bull_ope/analysis/scripts/run_production.sh
# 使い方:
#   cd /workspaces/ws-bulldozer
#   bash src/bull_ope/analysis/scripts/run_production.sh <最初の区切りの番号> <最後の区切りの番号>
#   例：bash src/bull_ope/analysis/scripts/run_production.sh 1 3    # 区切り 1〜3 を続けて実行
#
# 1つの区切り = flat_cut N_CUT 件 + flat_piecewise N_PW 件（既定 60 + 30 = 90 件、約 55 分）。
# 区切りごとに --seed を変えるので、同じ区切りを実行し直しても同じ計画が再現される。
# 区切りの間で止めても、それまでの区切りのデータは残る。途中で止まった区切りは、同じ番号で実行し直す。
# 区切りが終わるごとに、check_collection.py と check_dataset.py で点検し、結果を保存する。
set -u

FIRST=${1:?最初の区切りの番号を指定してください}
LAST=${2:?最後の区切りの番号を指定してください}
N_CUT=${N_CUT:-60}
N_PW=${N_PW:-30}
OUT=${OUT:-src/bull_ope/data/production}
CHECKS=src/bull_ope/analysis/checks
SEED_BASE=${SEED_BASE:-1000}     # 区切り k の seed は SEED_BASE + 10 k（flat_cut）と +1（flat_piecewise）

source install/setup.bash
mkdir -p "$OUT"
LOG="$OUT/production.log"

for k in $(seq "$FIRST" "$LAST"); do
  tag=$(printf "chunk%03d" "$k")
  echo "===== $(date '+%F %T') 区切り $tag 開始" | tee -a "$LOG"

  ros2 run bull_ope collect_data --episodes flat_cut --num "$N_CUT" --seed $((SEED_BASE + 10 * k)) \
      --run-name "${tag}_cut" --out "$OUT" 2>&1 | tee -a "$OUT/${tag}_cut.log"
  ros2 run bull_ope collect_data --episodes flat_piecewise --num "$N_PW" --seed $((SEED_BASE + 10 * k + 1)) \
      --run-name "${tag}_pw" --out "$OUT" 2>&1 | tee -a "$OUT/${tag}_pw.log"

  # この区切りのフォルダ（最新のもの）を点検する
  dc=$(ls -dt "$OUT"/run_*_"${tag}"_cut | head -1)
  dp=$(ls -dt "$OUT"/run_*_"${tag}"_pw | head -1)
  for d in "$dc" "$dp"; do
    python3 "$CHECKS/check_collection.py" "$d" --report "$d/check_collection.md" > /dev/null
    grep -E "想定外・要確認" "$d/check_collection.md" | sed "s|^|  $(basename "$d")：|" | tee -a "$LOG"
  done
  python3 "$CHECKS/check_dataset.py" "$dc" "$dp" --report "$OUT/${tag}_check_dataset.md" > /dev/null
  grep -E "エピソード .* 件：" "$OUT/${tag}_check_dataset.md" | sed "s|^|  |" | tee -a "$LOG"
  echo "===== $(date '+%F %T') 区切り $tag 終了" | tee -a "$LOG"
done