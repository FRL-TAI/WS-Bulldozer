"""
履帯で踏んだときの追加の沈下から締固めの程度を逆算する「較正曲線」を作り、その精度を交差検証で評価する。

入力は check_track_settlement.py が --out で保存した cells.csv（マスごとの値）。

手順：
  1. 区間にまとめる：記録・履帯（track_L / track_R）ごとに、前後 --seg [m] の区間でマスを平均する。
     区間の中で開始時の締固めの程度がそろっていない区間（帯の境目をまたぐ区間）は除く
  2. 較正曲線を作る：締固めの程度（--level-step ごとにまとめる）ごとに追加の沈下 S の平均を求め、
     「締固めの程度が大きいほど S が小さい」ように単調化する（重み付きの単調回帰）
  3. 逆算：S から、較正曲線を log S と c の折れ線とみなして補間し、締固めの程度 ĉ を求める。
     較正曲線の範囲を外れる S は端の値にし、「範囲外」として数える
  4. 交差検証：記録（ファイル）を1つずつ除いて較正曲線を作り、除いた記録の区間を逆算して誤差を求める
     （一度も見ていない作業の記録に使ったときの精度の見積もり）

使い方：
  python3 calibrate_settlement.py <cells.csv> [オプション]
  例）python3 src/bull_ope/analysis/checks/calibrate_settlement.py \\
          src/bull_ope/data/compaction/settlement/cells.csv \\
          --seg 0.5 1 2 --out src/bull_ope/data/compaction/calibration --plot

オプション：
  --target       逆算する締固めの程度の列（既定 c_start：削る前の値。c_cut_col3：削った後の z0〜z2 の平均）
  --seg          区間の長さ [m]（複数指定すると、区間の長さごとの精度を比べる。既定 1.0）
  --level-step   較正曲線で締固めの程度をまとめる幅（既定 0.02）
  --homog        区間の中の締固めの程度のばらつき（標準偏差）の上限（既定 0.01）
  --min-cells    区間に必要なマスの数（既定 2）
  --saturated    「十分に締め固まっている」とみなす締固めの程度（誤差の集計を分ける。既定 1.15）
  --out DIR、--plot
"""
import argparse
import csv
import math
import os
from collections import defaultdict

import numpy as np


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return math.nan


# ---------------------------------------------------------------- 読み込みと区間
def load_cells(path, target):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cells = []
    for r in rows:
        c, e, x = to_float(r.get(target)), to_float(r.get("extra_mm")), to_float(r.get("x"))
        if all(math.isfinite(v) for v in (c, e, x)):
            cells.append({"file": r["file"], "group": r["group"], "x": x, "c": c, "S": -e})
    if not cells:
        raise SystemExit(f"{path} に列 {target}・extra_mm・x がありません")
    return cells


def make_segments(cells, seg, homog, min_cells):
    groups = defaultdict(list)
    for c in cells:
        groups[(c["file"], c["group"], math.floor(c["x"] / seg))].append(c)
    out, dropped = [], 0
    for (f, g, k), cs in groups.items():
        cv = np.array([c["c"] for c in cs])
        if len(cs) < min_cells or cv.std() > homog:
            dropped += 1
            continue
        out.append({"file": f, "group": g, "x0": k * seg, "n": len(cs),
                    "c": float(cv.mean()), "S": float(np.mean([c["S"] for c in cs]))})
    return out, dropped


# ---------------------------------------------------------------- 較正曲線
def pav_decreasing(y, w):
    """重み付きの単調回帰（減少）。y は c の小さい順に並んでいるとする"""
    blocks = [[yi, wi, 1] for yi, wi in zip(y, w)]   # [値, 重み, 要素数]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] < blocks[i + 1][0]:          # 減少になっていない → まとめる
            v = (blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / (blocks[i][1] + blocks[i + 1][1])
            blocks[i] = [v, blocks[i][1] + blocks[i + 1][1], blocks[i][2] + blocks[i + 1][2]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for v, _, n in blocks:
        out += [v] * n
    return np.array(out)


def build_curve(segments, level_step):
    """[(締固めの程度, S の平均, S の標準偏差, 区間の数, 記録の数)]。S は単調化した値"""
    lv = defaultdict(list)
    for s in segments:
        lv[round(round(s["c"] / level_step) * level_step, 4)].append(s)
    levels = sorted(lv)
    if len(levels) < 2:
        return None
    c = np.array([np.mean([s["c"] for s in lv[k]]) for k in levels])
    S = np.array([np.mean([s["S"] for s in lv[k]]) for k in levels])
    sd = np.array([np.std([s["S"] for s in lv[k]]) for k in levels])
    n = np.array([len(lv[k]) for k in levels])
    nf = np.array([len({s["file"] for s in lv[k]}) for k in levels])
    S_mono = pav_decreasing(S, n)
    return {"c": c, "S_raw": S, "S": S_mono, "sd": sd, "n": n, "n_files": nf}


def invert(curve, S):
    """S から締固めの程度を逆算する（log S と c の折れ線で補間）。戻り値 (ĉ, 範囲外か)"""
    c, Sm = curve["c"], np.maximum(curve["S"], 0.1)       # log を取るため 0.1 mm を下限にする
    # 単調化で同じ値になった点をまとめる（補間の x を狭義単調増加にする）
    u = -np.log(Sm)
    xs, ys = [], []
    for ui, ci in zip(u, c):
        if xs and abs(ui - xs[-1]) < 1e-9:
            ys[-1] = 0.5 * (ys[-1] + ci)
        else:
            xs.append(ui)
            ys.append(ci)
    xs, ys = np.array(xs), np.array(ys)
    if len(xs) < 2:
        return math.nan, True
    v = -math.log(max(S, 0.1))
    out = v < xs[0] or v > xs[-1]
    return float(np.interp(v, xs, ys)), out


# ---------------------------------------------------------------- 交差検証
def cross_validate(segments, level_step):
    files = sorted({s["file"] for s in segments})
    res = []
    for f in files:
        train = [s for s in segments if s["file"] != f]
        test = [s for s in segments if s["file"] == f]
        curve = build_curve(train, level_step)
        if curve is None:
            continue
        lv_train = {round(round(s["c"] / level_step) * level_step, 4) for s in train}
        for s in test:
            c_hat, out = invert(curve, s["S"])
            level = round(round(s["c"] / level_step) * level_step, 4)
            res.append(dict(s, c_hat=c_hat, err=c_hat - s["c"], out_of_range=out,
                            level=level, level_in_train=level in lv_train))
    return res


def summarize(res, saturated):
    def stats(rs):
        e = np.array([r["err"] for r in rs if math.isfinite(r["err"])])
        if len(e) == 0:
            return None
        return {"n": len(e), "bias": float(e.mean()), "rmse": float(math.sqrt(np.mean(e ** 2))),
                "mae": float(np.mean(np.abs(e))), "out": sum(r["out_of_range"] for r in rs)}
    return {"全体": stats(res),
            f"c < {saturated}": stats([r for r in res if r["c"] < saturated]),
            f"c ≥ {saturated}": stats([r for r in res if r["c"] >= saturated])}


# ---------------------------------------------------------------- 本体
def main():
    ap = argparse.ArgumentParser(description="追加の沈下から締固めの程度を逆算する較正曲線と交差検証")
    ap.add_argument("cells")
    ap.add_argument("--target", default="c_start")
    ap.add_argument("--seg", type=float, nargs="+", default=[1.0])
    ap.add_argument("--level-step", type=float, default=0.02)
    ap.add_argument("--homog", type=float, default=0.01)
    ap.add_argument("--min-cells", type=int, default=2)
    ap.add_argument("--saturated", type=float, default=1.15)
    ap.add_argument("--out")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    cells = load_cells(a.cells, a.target)
    files = sorted({c["file"] for c in cells})
    print(f"マス {len(cells)}、記録 {len(files)}、逆算する値: {a.target}")

    all_seg_rows, all_cv_rows, curves = [], [], {}
    for seg in a.seg:
        segments, dropped = make_segments(cells, seg, a.homog, a.min_cells)
        print("\n" + "=" * 78)
        print(f"区間の長さ {seg} m：使った区間 {len(segments)}（締固めの程度がそろわない・マスが少ない区間 {dropped} を除外）")
        print("=" * 78)

        # ---- 1. 較正曲線（すべての記録から） ----
        curve = build_curve(segments, a.level_step)
        if curve is None:
            print("締固めの程度が1種類しかないため、較正曲線を作れません")
            continue
        curves[seg] = curve
        print("\n1. 較正曲線（すべての記録から）")
        print(f"{'c':>7s} {'S 平均mm':>9s} {'単調化mm':>9s} {'区間SDmm':>9s} {'区間数':>6s} {'記録数':>6s} "
              f"{'感度 mm/0.01':>12s}")
        for i in range(len(curve["c"])):
            if 0 < i < len(curve["c"]) - 1:
                sens = (curve["S"][i - 1] - curve["S"][i + 1]) / (curve["c"][i + 1] - curve["c"][i - 1]) * 0.01
            else:
                sens = math.nan
            print(f"{curve['c'][i]:7.3f} {curve['S_raw'][i]:9.1f} {curve['S'][i]:9.1f} {curve['sd'][i]:9.1f} "
                  f"{curve['n'][i]:6d} {curve['n_files'][i]:6d} {sens:12.2f}")
        print("    感度 = 締固めの程度が 0.01 違うときの S の違い。区間 SD ÷ 感度 × 0.01 がおおよその逆算の誤差")

        # ---- 2. 交差検証 ----
        res = cross_validate(segments, a.level_step)
        summ = summarize(res, a.saturated)
        print("\n2. 交差検証（記録を1つずつ除いて較正し、除いた記録を逆算）")
        print(f"{'範囲':>10s} {'区間数':>6s} {'平均誤差':>9s} {'RMSE':>8s} {'MAE':>8s} {'範囲外':>6s}")
        for k, v in summ.items():
            if v:
                print(f"{k:>10s} {v['n']:6d} {v['bias']:+9.4f} {v['rmse']:8.4f} {v['mae']:8.4f} {v['out']:6d}")
        print("\n   締固めの程度ごと（較正に同じ程度の記録がなかった区間には * を付ける）")
        print(f"{'c':>7s} {'区間数':>6s} {'ĉ 平均':>8s} {'平均誤差':>9s} {'RMSE':>8s}")
        bylv = defaultdict(list)
        for r in res:
            bylv[r["level"]].append(r)
        for lv in sorted(bylv):
            rs = bylv[lv]
            e = np.array([r["err"] for r in rs])
            mark = "" if all(r["level_in_train"] for r in rs) else " *"
            print(f"{lv:7.2f} {len(rs):6d} {np.mean([r['c_hat'] for r in rs]):8.4f} {e.mean():+9.4f} "
                  f"{math.sqrt(np.mean(e ** 2)):8.4f}{mark}")

        for i in range(len(curve["c"])):
            all_seg_rows.append({"seg_m": seg, "c": curve["c"][i], "S_raw_mm": curve["S_raw"][i],
                                 "S_mm": curve["S"][i], "S_sd_mm": curve["sd"][i],
                                 "n_segments": int(curve["n"][i]), "n_files": int(curve["n_files"][i])})
        all_cv_rows += [dict(seg_m=seg, **{k: v for k, v in r.items()}) for r in res]

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        for name, tab in (("curve.csv", all_seg_rows), ("cv.csv", all_cv_rows)):
            if tab:
                p = os.path.join(a.out, name)
                with open(p, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=list(tab[0].keys()))
                    w.writeheader()
                    w.writerows(tab)
                print(f"保存: {p}")
        if a.plot:
            plot(a.out, curves, all_cv_rows)
    elif a.plot:
        print("--plot には --out が必要です")


def plot(out, curves, cv_rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib がないため、図は作りません（pip install matplotlib）")
        return
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for seg, cu in curves.items():
        axes[0].plot(cu["c"], cu["S"], marker="o", label=f"curve (seg {seg} m)")
        axes[0].errorbar(cu["c"], cu["S_raw"], yerr=cu["sd"], fmt="none", alpha=0.4)
        rs = [r for r in cv_rows if r["seg_m"] == seg]
        axes[1].scatter([r["c"] for r in rs], [r["c_hat"] for r in rs], s=10, alpha=0.5, label=f"seg {seg} m")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("compaction [-]")
    axes[0].set_ylabel("extra settlement by tracks [mm]")
    axes[0].legend()
    lim = [min(min(cu["c"]) for cu in curves.values()) - 0.02, max(max(cu["c"]) for cu in curves.values()) + 0.02]
    axes[1].plot(lim, lim, color="k", lw=0.8)
    axes[1].set_xlim(lim)
    axes[1].set_ylim(lim)
    axes[1].set_xlabel("true compaction [-]")
    axes[1].set_ylabel("estimated compaction (leave-one-file-out) [-]")
    axes[1].legend()
    for ax in axes:
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p = os.path.join(out, "calibration.png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    print(f"保存: {p}")


if __name__ == "__main__":
    main()