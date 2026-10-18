#!/usr/bin/env bash
# 本番の収集を、区切り（チャンク）ごとに実行する。
#
# 置き場所: src/bull_ope/scripts/run_production.sh
# 使い方（どのフォルダから実行してもよい）:
#   bash src/bull_ope/scripts/run_production.sh <最初の区切りの番号> <最後の区切りの番号>
#   例：bash src/bull_ope/scripts/run_production.sh 1 3    # 区切り 1〜3 を続けて実行
#
# 1つの区切り = dataset_flat_cut N_CUT 件 + dataset_flat_piecewise N_PW 件 + dataset_pile_push N_PILE 件
#   （既定 60 + 30 + 0 = 90 件、約 55 分）。件数は環境変数で変えられる：
#   N_PILE=20 bash src/bull_ope/scripts/run_production.sh 1 1
# 区切りごとに --seed を変えるので、同じ区切りを実行し直しても同じ計画が再現される。
# 区切りの間で止めても、それまでの区切りのデータは残る。途中で止まった区切りは、同じ番号で実行し直す。
# 区切りが終わるごとに、check_collection.py と check_dataset.py で点検し、結果を保存する。
set -u

FIRST=${1:?最初の区切りの番号を指定してください}
LAST=${2:?最後の区切りの番号を指定してください}
N_CUT=${N_CUT:-60}
N_PW=${N_PW:-30}
N_PILE=${N_PILE:-0}
SEED_BASE=${SEED_BASE:-1000}     # 区切り k の seed は SEED_BASE + 10 k（+0：dataset_flat_cut、+1：dataset_flat_piecewise、+2：dataset_pile_push）

# このスクリプトの場所から、パッケージとワークスペースの場所を求める（どこから実行してもよいように）
PKG=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)      # .../src/bull_ope
WS=$(cd "$PKG/../.." && pwd)                               # .../ws-bulldozer
CHECKS=$PKG/analysis/checks
OUT=${OUT:-$PKG/data/production}

cd "$WS"
set +u                 # ROS2 の setup.bash は未定義の変数を使うので、読み込む間だけ外す
source install/setup.bash
set -u
mkdir -p "$OUT"
LOG="$OUT/production.log"

run_one() {   # $1 エピソード名、$2 件数、$3 seed、$4 区切りの名前
  [ "$2" -gt 0 ] || return 0
  ros2 run bull_ope collect_data --episodes "$1" --num "$2" --seed "$3" \
      --run-name "$4" --out "$OUT" 2>&1 | tee -a "$OUT/$4.log"
  local d
  d=$(ls -dt "$OUT"/run_*_"$4" | head -1)
  python3 "$CHECKS/check_collection.py" "$d" --report "$d/check_collection.md" > /dev/null
  grep -E "想定外・要確認" "$d/check_collection.md" | sed "s|^|  $(basename "$d")：|" | tee -a "$LOG"
  DIRS+=("$d")
}

for k in $(seq "$FIRST" "$LAST"); do
  tag=$(printf "chunk%03d" "$k")
  echo "===== $(date '+%F %T') 区切り $tag 開始" | tee -a "$LOG"
  DIRS=()
  run_one dataset_flat_cut "$N_CUT" $((SEED_BASE + 10 * k)) "${tag}_cut"
  run_one dataset_flat_piecewise "$N_PW" $((SEED_BASE + 10 * k + 1)) "${tag}_pw"
  run_one dataset_pile_push "$N_PILE" $((SEED_BASE + 10 * k + 2)) "${tag}_pile"
  python3 "$CHECKS/check_dataset.py" "${DIRS[@]}" --report "$OUT/${tag}_check_dataset.md" > /dev/null
  grep -E "エピソード .* 件：" "$OUT/${tag}_check_dataset.md" | sed "s|^|  |" | tee -a "$LOG"
  echo "===== $(date '+%F %T') 区切り $tag 終了" | tee -a "$LOG"
done
