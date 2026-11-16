"""
削った後の地面を履帯が踏んだときの「追加の沈下」と、その地面の締固めの程度の関係を調べる。

CompactionProbe の CSV（compaction_*.csv。ex_compaction_bands / patterns / levels / then_cut）を読む。
排土板の刃先は機体の基準点（body_link）の約 2.8 m 前、履帯はその後ろ（基準点から前後 ±1.1 m）にあるので、
地面の各マスは「排土板が通る → しばらくそのまま → 履帯が通る」の順で変化する。

マスごとに次の3つの時点の値を取る（機体の位置 machine_x で判定する）：
  開始時   ：削り始める直前の記録（往復してから削るエピソードでは、最後に前進を始めた時点）
  削った後 ：排土板は通り過ぎたが、履帯はまだ来ていない記録（machine_x が x − 刃先の位置 + 余裕 〜 x − 履帯の前端 − 余裕）
  最後     ：最後の記録（履帯が通り過ぎた後）
  追加の沈下 = 最後の高さ − 削った後の高さ（下がると負）

履帯の位置の列（track_L・track_R）のマスだけを使い、履帯がマスの上を通り切ったマスに限る。

使い方：
  python3 check_track_settlement.py <compaction_*.csv> [...] [オプション]
  例）python3 analysis/phase0/check_track_settlement.py \\
          data/compaction/compaction_*_ex_compaction_{bands,patterns,levels}.csv \\
          --out data/compaction/settlement --plot

オプション：
  --blade-offset  機体の基準点から刃先までの前方の距離 [m]（既定 2.8。実験B1 の記録から求めた値）
  --track-front   機体の基準点から履帯の前端までの距離 [m]（既定 1.1。後端は −この値とする）
  --margin        判定の余裕 [m]（既定 0.3）
  --group-step    開始時の締固めの程度をまとめる幅（既定 0.02）
  --seg           逆算の誤差を区間平均でも評価するときの区間の長さ [m]（既定 1.0）
  --out DIR、--plot

出力：
  1. 記録ごとの要約（使えたマスの数、削る前に締め固まっていたマスの範囲）
  2. 開始時の締固めの程度ごとの表：削った後の締固めの程度、削った厚さ、追加の沈下（平均・標準偏差）
  3. 追加の沈下 S [mm] と締固めの程度 c の関係の当てはめ：S = H × (1 − c / c_sat)
     （履帯で踏むと締固めの程度が c_sat まで上がり、影響する厚さ H の土の質量が保存されるとした単純なモデル）
     と、その逆算 ĉ = c_sat × (1 − S / H) で締固めの程度を推定したときの誤差（マスごと、区間平均）
"""
import argparse
import csv
import math
import os
import re
from collections import defaultdict

import numpy as np

BASE_LANE = re.compile(r"^(track_L|track_R|center|control)")


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return math.nan


def load(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cols = sorted([c for c in rows[0] if re.fullmatch(r"c_z\d+", c)], key=lambda c: int(c[3:]))
    for r in rows:
        r["_t"] = to_float(r["sim_time"])
        r["_mx"] = to_float(r["machine_x"])
        r["_x"] = to_float(r["x"])
        r["_h"] = to_float(r["height"])
        r["_c"] = to_float(r["c_surface"])
        r["_cz"] = [to_float(r[c]) for c in cols]
        m = BASE_LANE.match(r["lane"])
        r["_group"] = m.group(1) if m else r["lane"]
    return rows


def cut_start_time(rows):
    """最後に前進を始めた時刻（往復してから削るエピソード用）。後退がなければ最初の記録の時刻"""
    snaps = sorted({(r["_t"], r["_mx"]) for r in rows})
    start = snaps[0][0]
    for (t0, x0), (t1, x1) in zip(snaps[:-1], snaps[1:]):
        if x1 - x0 < -0.05:          # 後退している
            start = t1
    # 後退の最後の記録から、機体の位置が最も小さい記録を開始時とする
    after = [(t, x) for t, x in snaps if t >= start]
    return min(after, key=lambda p: p[1])[0] if after else start


def analyze_file(path, a):
    rows = load(path)
    t0 = cut_start_time(rows)
    run = [r for r in rows if r["_t"] >= t0]
    mx_final = max(r["_mx"] for r in run)

    cells = defaultdict(list)
    for r in run:
        if r["_group"] in ("track_L", "track_R"):
            cells[(r["lane"], r["unity_ix"], r["unity_iy"])].append(r)

    out, not_passed = [], 0
    for key, rs in cells.items():
        rs.sort(key=lambda r: r["_t"])
        x = rs[0]["_x"]
        if mx_final < x + a.track_front + a.margin:        # 履帯の後端がまだマスを通り切っていない
            if rs[0]["_c"] > 1.005 or rs[0]["_c"] < 0.995:
                not_passed += 1
            continue
        lo, hi = x - a.blade_offset + a.margin, x - a.track_front - a.margin
        mid = [r for r in rs if lo <= r["_mx"] <= hi]
        if not mid:
            continue
        r_start, r_cut, r_end = rs[0], mid[-1], rs[-1]
        cz = [v for v in r_cut["_cz"][:3] if math.isfinite(v)]
        out.append({
            "file": os.path.basename(path), "lane": key[0], "group": r_start["_group"], "x": x,
            "c_start": r_start["_c"], "c_cut": r_cut["_c"], "c_cut_col3": float(np.mean(cz)) if cz else math.nan,
            "c_end": r_end["_c"],
            "cut_mm": (r_start["_h"] - r_cut["_h"]) * 1000.0,          # 削った厚さ（正）
            "extra_mm": (r_end["_h"] - r_cut["_h"]) * 1000.0,          # 追加の沈下（下がると負）
        })
    return rows, t0, mx_final, out, not_passed


def fit_model(c, S):
    """S = H × (1 − c / c_sat) = H − (H / c_sat) × c を最小二乗で当てはめる。戻り値 (H, c_sat)"""
    if len(c) < 3 or np.std(c) < 1e-6:
        return math.nan, math.nan
    b, a0 = np.polyfit(c, S, 1)          # S = a0 + b c
    if b >= 0:
        return math.nan, math.nan
    return a0, -a0 / b


def main():
    ap = argparse.ArgumentParser(description="削った後の地面を履帯が踏んだときの追加の沈下を調べる")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--blade-offset", type=float, default=2.8)
    ap.add_argument("--track-front", type=float, default=1.1)
    ap.add_argument("--margin", type=float, default=0.3)
    ap.add_argument("--group-step", type=float, default=0.02)
    ap.add_argument("--seg", type=float, default=1.0, help="逆算の誤差を区間平均で評価するときの区間の長さ [m]")
    ap.add_argument("--out")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    allc = []
    print("=" * 78)
    print("1. 記録ごとの要約")
    print("=" * 78)
    for path in a.csv:
        rows, t0, mx_final, cells, not_passed = analyze_file(path, a)
        pre = [c for c in cells if c["c_start"] > 1.005 or c["c_start"] < 0.995]
        print(f"{os.path.basename(path)}: 削り始め t = {t0:.1f} s、機体の最終位置 {mx_final:.2f} m、"
              f"使えたマス {len(cells)}（削る前に締固めの程度が 1 でなかったマス {len(pre)}）")
        if not_passed:
            print(f"    注意：締固めの程度が 1 でないのに、履帯が通り切っていないため使えなかったマス {not_passed}"
                  f"（走行距離を延ばすと使える）")
        allc += cells
    if not allc:
        raise SystemExit("使えるマスがありません（--blade-offset・--track-front を確認）")

    # ---- 2. 開始時の締固めの程度ごと ----
    print("\n" + "=" * 78)
    print("2. 開始時の締固めの程度ごとの表（履帯の位置のマス。追加の沈下は下がると負）")
    print("=" * 78)
    groups = defaultdict(list)
    for c in allc:
        groups[round(round(c["c_start"] / a.group_step) * a.group_step, 4)].append(c)
    print(f"{'開始時の c':>10s} {'マス数':>6s} {'削った後の c':>12s} {'削った後 z0-2':>13s} {'削った厚さmm':>12s} "
          f"{'追加の沈下mm':>14s} {'最後の c':>9s}")
    table = []
    for g in sorted(groups):
        cs = groups[g]
        e = np.array([c["extra_mm"] for c in cs])
        row = {"c_start": g, "n": len(cs),
               "c_cut": float(np.nanmean([c["c_cut"] for c in cs])),
               "c_cut_col3": float(np.nanmean([c["c_cut_col3"] for c in cs])),
               "cut_mm": float(np.nanmean([c["cut_mm"] for c in cs])),
               "extra_mm": float(e.mean()), "extra_sd": float(e.std()),
               "c_end": float(np.nanmean([c["c_end"] for c in cs]))}
        table.append(row)
        print(f"{g:10.2f} {row['n']:6d} {row['c_cut']:12.4f} {row['c_cut_col3']:13.4f} {row['cut_mm']:12.1f} "
              f"{row['extra_mm']:8.1f} ± {row['extra_sd']:4.1f} {row['c_end']:9.4f}")

    # ---- 3. モデルの当てはめと逆算 ----
    print("\n" + "=" * 78)
    print("3. 追加の沈下 S = −追加の沈下 [mm] と締固めの程度 c の関係：S = H × (1 − c / c_sat)")
    print("=" * 78)
    S = np.array([-c["extra_mm"] for c in allc])
    fits = []
    for key, name in (("c_start", "開始時の c（地形の加工で設定した値など）"),
                      ("c_cut", "削った後の地表の c"),
                      ("c_cut_col3", "削った後の z0〜z2 の平均")):
        cv = np.array([c[key] for c in allc])
        ok = np.isfinite(cv) & np.isfinite(S)
        H, csat = fit_model(cv[ok], S[ok])
        if not math.isfinite(H):
            print(f"  {name}: 当てはめられません")
            continue
        S_hat = H * (1 - cv[ok] / csat)
        c_hat = np.clip(csat * (1 - S[ok] / H), 0.5, csat)
        r = float(np.corrcoef(cv[ok], S[ok])[0, 1])
        print(f"  {name}:")
        print(f"     H = {H:.1f} mm、c_sat = {csat:.4f}、相関 {r:+.3f}、"
              f"S の当てはめの RMSE {math.sqrt(np.mean((S_hat - S[ok]) ** 2)):.1f} mm")
        # 逆算の誤差（c_sat を超える c のマスは逆算できないので除く）
        m = cv[ok] < csat
        if m.sum() > 2:
            err = c_hat[m] - cv[ok][m]
            print(f"     逆算 ĉ = c_sat × (1 − S / H) の誤差（c < c_sat のマス {int(m.sum())} 個）："
                  f"平均 {err.mean():+.4f}、RMSE {math.sqrt(np.mean(err ** 2)):.4f}")
        # 前後 --seg [m] ごとに平均してから逆算したときの誤差（マス単位のばらつきを均す）
        seg = defaultdict(list)
        for c in allc:
            if math.isfinite(c[key]):
                seg[(c["file"], c["group"], math.floor(c["x"] / a.seg))].append(c)
        cs_, Ss_ = [], []
        for v in seg.values():
            if len(v) >= 2:
                cs_.append(np.mean([c[key] for c in v]))
                Ss_.append(np.mean([-c["extra_mm"] for c in v]))
        cs_, Ss_ = np.array(cs_), np.array(Ss_)
        mm = cs_ < csat
        if mm.sum() > 2:
            err = np.clip(csat * (1 - Ss_[mm] / H), 0.5, csat) - cs_[mm]
            print(f"     前後 {a.seg} m ごと・履帯ごとに平均してから逆算した誤差（{int(mm.sum())} 区間）："
                  f"平均 {err.mean():+.4f}、RMSE {math.sqrt(np.mean(err ** 2)):.4f}")
        fits.append({"x": key, "H_mm": H, "c_sat": csat, "corr": r})

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        for name, tab in (("cells.csv", allc), ("by_level.csv", table), ("fit.csv", fits)):
            if tab:
                with open(os.path.join(a.out, name), "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=list(tab[0].keys()))
                    w.writeheader()
                    w.writerows(tab)
                print(f"保存: {os.path.join(a.out, name)}")
        if a.plot:
            plot(a.out, allc, fits)
    elif a.plot:
        print("--plot には --out が必要です")


def plot(out, allc, fits):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib がないため、図は作りません（pip install matplotlib）")
        return
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    S = np.array([-c["extra_mm"] for c in allc])
    for ax, key, label in ((axes[0], "c_start", "compaction before cutting [-]"),
                           (axes[1], "c_cut", "surface compaction after cutting [-]")):
        cv = np.array([c[key] for c in allc])
        ax.scatter(cv, S, s=8, alpha=0.5)
        f = next((f for f in fits if f["x"] == key), None)
        if f:
            xs = np.linspace(np.nanmin(cv), f["c_sat"], 50)
            ax.plot(xs, f["H_mm"] * (1 - xs / f["c_sat"]), color="tab:red",
                    label=f"S = {f['H_mm']:.0f}(1 - c/{f['c_sat']:.3f})")
            ax.legend()
        ax.set_xlabel(label)
        ax.set_ylabel("extra settlement by tracks [mm]")
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p = os.path.join(out, "settlement_vs_compaction.png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    print(f"保存: {p}")


if __name__ == "__main__":
    main()