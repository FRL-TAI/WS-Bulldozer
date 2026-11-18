"""
フェーズ1：緩い側の凸を 3作業の ±0.03 で確かめる（T35）。

notes decisions/2026-11-18_緩い側の凸を3作業の±0.03で確かめる.md

使い方（コンテナの中、ワークスペース直下）:
  python3 analysis/phase1/check_compaction_j35.py --report data/phase1/compaction_j/report_t35.md [--boot 1000]

記録・K3・J の作り方は check_compaction_j34.py（T34）と同じ（関数をそのまま使う）。T35 で足した記録：
  flat_piecewise・pile_push の 0.97・1.03（k_m0p03・k_p0p03）各 8 本、pile_push の 0.94 を 8 本（計 16 本）、
  flat_cut の 0.97・1.03 を各 3 本（計 8 本）。

T34 からの違い:
  - 側を4通りにする：緩い側・締まった側のそれぞれについて、割線（±0.06 の点と基準）と局所の傾き（±0.03 の点と基準）。
  - 折れ目の幅（±0.03 と ±0.06 の比、線形・段差の検定）を3作業で出す。
  - 5つ同時の下限を、割線と局所の傾きで1つの表に並べる。
  - 締固めの記録が届いた本が 2 本未満の点は、ΔK3 に flat_cut の同じ点の ΔK3 を使う（作業の基準の K3 に足す）。

出力:
  1. 点ごとの K3 と ΔK3、本数
  2. 列ごと（作業 × 経路 × 側〔4通り〕）の信号 ÷ 標準偏差、1つだけの下限、水増し ÷ F
  3. 折れ目の幅（3作業）
  4. 組み合わせ（側ごと）と、割線・局所の傾きの比較の表
"""
import argparse
import math
import os
import sys

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_compaction_j34 as j34          # noqa: E402
import check_ident_combine as cic           # noqa: E402
import check_ident_terrain as cit           # noqa: E402
import check_ident_terrain_combine as ctc   # noqa: E402
from check_ident import DESIGN, set_s_step  # noqa: E402

TASKS = ["flat_cut", "flat_piecewise", "pile_push"]
ALL5 = j34.ALL5
SIDES = {
    "緩い側・割線（±0.06）": ("base", "k_m0p06"),
    "緩い側・局所（±0.03）": ("base", "k_m0p03"),
    "締まった側・割線（±0.06）": ("k_p0p06", "base"),
    "締まった側・局所（±0.03）": ("k_p0p03", "base"),
}
POINTS = ["k_m0p06", "k_m0p03", "base", "k_p0p03", "k_p0p06"]
OUT = []


def p(s=""):
    OUT.append(s)


def main():
    ap = argparse.ArgumentParser(description="緩い側の凸を 3作業の ±0.03 で確かめる（T35）")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--x-min", type=float, default=3.1, help="K3 を平均するマスの記録の座標 x の下限 [m]")
    ap.add_argument("--min-k3", type=int, default=2, help="K3 の本数がこれ未満の点は flat_cut の ΔK3 を使う")
    ap.add_argument("--report")
    a = ap.parse_args()
    set_s_step(0.06)
    p("# 緩い側の凸を 3作業の ±0.03 で確かめる（T35）\n")

    # ---- 読み込み（T34 と同じ）
    K3, TT, FT, tnames = {}, {}, {}, {}
    for t in TASKS:
        K3[t] = j34.k3_points(t, a.x_min)
        X, names, exc = j34.load_terrain(t, ctc.TTASKS[t][3])
        tnames[t] = list(names) + ["K"]
        DESIGN["K"] = (j34.RANGE_K, {"k_p0p06": 1.0, "k_m0p06": -1.0}, None)
        nb, d = len(X["base"]), len(cit.OBS)
        TT[t] = cit.terrain_task(X, tnames[t], (nb - d - 2) / (nb - 1))
        TT[t]["d"] = d
        fp, (b0, b1), fmax, fpat, skip = cic.TASKS[t]
        FT[t] = cic.load_task([os.path.join(j34.WS, fpat), os.path.join(j34.WS, j34.KDIR[t])], fp, range(b0, b1 + 1),
                              fmax, skip, ALL5)
        if exc:
            p(f"{t}：深さのずれで除いた地形の記録 {len(exc)} 本（" + "、".join(f"{e[1]} {e[2] * 100:.1f} cm" for e in exc) + "）\n")

    # ---- 1. K3
    p("## 1. 点ごとの K3 と本数\n")
    p(f"マスは記録の座標 x ≥ {a.x_min:g} m。本数は K3・地形・力の順。"
      f"K3 の本数が {a.min_k3} 本未満の点は、ΔK3 に flat_cut の同じ点の ΔK3 を使った（「代用」）。\n")
    p("| 作業 | 点 | K3（平均 ± 標準偏差） | ΔK3（基準との差） | 本数（K3・地形・力） |")
    p("|---|---|---|---|---|")
    K3m = {}
    for t in ["flat_cut"] + [x for x in TASKS if x != "flat_cut"]:
        K3m[t] = {}
        for k in POINTS:
            v = K3[t].get(k, np.array([]))
            if len(v) >= a.min_k3 or k == "base":
                K3m[t][k] = float(v.mean())
        for k in POINTS:
            v = K3[t].get(k, np.array([]))
            note = ""
            if k not in K3m[t] and k in K3m["flat_cut"]:
                K3m[t][k] = K3m[t]["base"] + (K3m["flat_cut"][k] - K3m["flat_cut"]["base"])
                note = "（代用）"
            if k not in K3m[t]:
                continue
            sd = f"{v.std(ddof=1):.4f}" if len(v) > 1 else "—"
            mean = f"{v.mean():.4f}" if len(v) else "—"
            p(f"| {t} | {k} | {mean} ± {sd} | {K3m[t][k] - K3m[t]['base']:+.4f}{note} | "
              f"{len(v)}・{TT[t]['nrep'].get(k, 0)}・{FT[t]['nrep'].get(k, 0)} |")
    p("")

    # ---- 2. 列ごと
    p("## 2. 締固めの列（作業 × 経路 × 側）\n")
    p("信号は水増しを引いた F の対角、標準偏差はブートストラップ（偏りを引いた標本）。下限は1つだけ、範囲比。\n")
    p("| 作業 | 経路 | 側 | 水増し ÷ F | 信号 ÷ 標準偏差 | ≥ 2 か | 下限（1つだけ）点推定（16〜84%） |")
    p("|---|---|---|---|---|---|---|")
    rng = np.random.default_rng(0)
    for t in TASKS:
        for path in ("地形", "力"):
            for side, (hi, lo) in SIDES.items():
                Tchk = TT[t] if path == "地形" else FT[t]
                if not all(k in K3m[t] and k in Tchk["mean"] for k in (hi, lo)):
                    p(f"| {t} | {path} | {side} | — | — | — | 記録なし |")
                    continue
                j34.set_side(hi, lo, K3m[t])
                if path == "地形":
                    T, names = TT[t], tnames[t]
                    j34.refresh_terrain(T, names)
                    Fraw = cit.fisher_terrain(T, names)
                    F0 = j34.terr_F(T, names)
                    samp = [j34.terr_boot(T, names, rng) for _ in range(a.boot)]
                else:
                    T, names = FT[t], ALL5
                    j34.refresh_force(T, names)
                    cic.NAMES = list(names)
                    Fraw = cic.fisher(T)
                    F0 = j34.force_F(T, names)
                    samp = [j34.force_boot(T, names, rng) for _ in range(a.boot)]
                i = names.index("K")
                sig, sd, q = j34.column_stats(F0, samp, i)
                single = f"{1 / math.sqrt(sig):.3f}" if sig > 0 else "—"
                p(f"| {t} | {path} | {side} | {T['infl']['K'] / Fraw[i, i]:.2f} | {sig / sd:.2f} | "
                  f"{'はい' if sig / sd >= 2 else '**いいえ**'} | {single}（{q[0]:.3f}〜{q[1]:.3f}） |")
    p("")

    # ---- 3. 折れ目の幅（3作業）
    p("## 3. 折れ目の幅（3作業、±0.03 と ±0.06）\n")
    p("T34 §3 と同じ形。r は Δ06 の向きへの Δ03 の射影の比（Σ で測る）、ΔK3 あたりの効きの比は r ÷ (ΔK3_03/ΔK3_06)。"
      "線形の検定は Δ03 − (ΔK3_03/ΔK3_06)·Δ06 = 0、段差の検定は Δ03 − Δ06 = 0（κ を見込んだ χ²）。\n")
    p("| 作業 | 経路 | 側 | ΔK3_03 / ΔK3_06 | r | ΔK3 あたりの効きの比（0.03 ÷ 0.06） | 線形の p | 段差の p | 代表の成分 Δ03 / Δ06 |")
    p("|---|---|---|---|---|---|---|---|---|")
    for t in TASKS:
        for path in ("地形", "力"):
            T = TT[t] if path == "地形" else FT[t]
            Sinv = T["Sinv_raw"] if path == "地形" else T["Sinv"]
            d = T["d"]
            for side, (p3, p6) in (("緩い側", ("k_m0p03", "k_m0p06")), ("締まった側", ("k_p0p03", "k_p0p06"))):
                m = T["mean"]
                if p3 not in m or p6 not in m:
                    p(f"| {t} | {path} | {side} | — | — | — | — | — | 記録なし |")
                    continue
                D3, D6 = m[p3] - m["base"], m[p6] - m["base"]
                k3 = K3m[t][p3] - K3m[t]["base"]
                k6 = K3m[t][p6] - K3m[t]["base"]
                r = float(D3 @ Sinv @ D6) / float(D6 @ Sinv @ D6)
                v = lambda k: T["kappa"][k] / T["nrep"][k]  # noqa: E731
                lam = k3 / k6
                dl = D3 - lam * D6
                vl = v(p3) + lam ** 2 * v(p6) + (1 - lam) ** 2 * v("base")
                ds = D3 - D6
                vs = v(p3) + v(p6)
                pl = stats.chi2.sf(float(dl @ Sinv @ dl) / vl, d)
                ps = stats.chi2.sf(float(ds @ Sinv @ ds) / vs, d)
                if path == "地形":
                    rep = f"vis_net_pos {D3[0]:+.3f} / {D6[0]:+.3f}・vis_net_neg {D3[1]:+.3f} / {D6[1]:+.3f} m³"
                else:
                    nb = T["nb"]
                    rep = f"Σ(−F_x) {D3[:nb].sum():+.1f} / {D6[:nb].sum():+.1f}"
                p(f"| {t} | {path} | {side} | {k3:+.4f} / {k6:+.4f}（{lam:.2f}） | {r:.2f} | {r / lam:.2f} | "
                  f"{pl:.2g} | {ps:.2g} | {rep} |")
    p("")

    # ---- 4. 組み合わせ
    p("## 4. 組み合わせ（側ごと）\n")
    p("T34 §4 と同じ作り（信号のある列だけ：地形は φ・s・K、力は (i) φ・c・ρ・K、(ii) φ・c・ρ）。値は「点推定（正定値のとき）／"
      "偏りを引いた標本のうち正定値のものの中央値（5〜95%）」。\n")
    combos = [
        ("地形だけ：3作業（φ・s・K）", [], TASKS, ["φ", "s", "K"], None),
        ("地形 ＋ 力 (i)：3作業、φ・s・K（c・ρ は固定）", TASKS, TASKS, ["φ", "s", "K"], True),
        ("地形 ＋ 力 (ii)：3作業、φ・s・K（c・ρ は固定）", TASKS, TASKS, ["φ", "s", "K"], False),
        ("地形 ＋ 力 (i)：3作業、5つ同時", TASKS, TASKS, ALL5, True),
        ("地形 ＋ 力 (ii)：3作業、5つ同時", TASKS, TASKS, ALL5, False),
    ]
    TN, FI, FII = ["φ", "s", "K"], ["φ", "c", "ρ", "K"], ["φ", "c", "ρ"]
    summary = {}
    for side, (hi, lo) in SIDES.items():
        if not all(k in K3m[t] and k in TT[t]["mean"] and k in FT[t]["mean"] for t in TASKS for k in (hi, lo)):
            p(f"### {side}\n\n記録のない作業があるので省いた。\n")
            continue
        p(f"### {side}\n")
        p("| 組み合わせ | 正定値の標本 | 最小の固有値 | " + " | ".join(f"{n}" for n in ALL5) + " | φ–K の相関 | s–K の相関 |")
        p("|---|---|---|" + "---|" * len(ALL5) + "---|---|")
        tF, fFi, fFii = {}, {}, {}
        for t in TASKS:
            j34.set_side(hi, lo, K3m[t])
            j34.refresh_terrain(TT[t], tnames[t])
            j34.refresh_force(FT[t], ALL5)
            tF[t] = j34.embed(j34.terr_F(TT[t], TN), TN)
            fFi[t] = j34.embed(j34.force_F(FT[t], FI), FI)
            fFii[t] = j34.embed(j34.force_F(FT[t], FII), FII)
        samp = {c[0]: [] for c in combos}
        rng2 = np.random.default_rng(1)
        for _ in range(a.boot):
            tb, fbi, fbii = {}, {}, {}
            for t in TASKS:
                j34.set_side(hi, lo, K3m[t])
                tb[t] = j34.embed(j34.terr_boot(TT[t], TN, rng2), TN)
                fbi[t] = j34.embed(j34.force_boot(FT[t], FI, rng2), FI)
                fbii[t] = j34.embed(j34.force_boot(FT[t], FII, rng2), FII)
            for lab, ft, tt, nm, meas in combos:
                samp[lab].append(sum([tb[t] for t in tt] + [(fbi if meas else fbii)[t] for t in ft]))
        for lab, ft, tt, nm, meas in combos:
            idx = [ALL5.index(n) for n in nm]
            F0 = sum([tF[t] for t in tt] + [(fFi if meas else fFii)[t] for t in ft])[np.ix_(idx, idx)]
            sm = [x[np.ix_(idx, idx)] for x in samp[lab]]
            names_of = {n: nm.index(n) for n in nm}
            pairs = [(names_of[x], names_of[y]) for x, y in (("φ", "K"), ("s", "K")) if x in names_of and y in names_of]
            r = ctc.summarize(F0, sm, pairs)
            cells = []
            for n in ALL5:
                if n not in names_of:
                    cells.append("—")
                    continue
                i = names_of[n]
                j0 = f"{r['joint0'][i]:.3f}" if r["pd0"] else "—"
                q = r["q"][:, i]
                cells.append(f"{j0}／{q[2]:.3f}（{q[0]:.3f}〜{q[4]:.3f}）")
            cor = []
            for pr in pairs:
                c0 = f"{r['c0'][pr]:+.2f}" if r["pd0"] else "—"
                cor.append(f"{c0}／{r['cq'][pr][1]:+.2f}")
            p(f"| {lab} | {r['pdfrac']:.0%} | {r['evmin']:.1f} | " + " | ".join(cells) + " | " + " | ".join(cor) + " |")
            if "5つ同時" in lab:
                summary[(side, "(i)" if meas else "(ii)")] = (r["pdfrac"], [r["q"][2, names_of[n]] for n in ALL5],
                                                             r["cq"][pairs[0]][1])
        p("")

    p("### 5つ同時の下限：割線と局所の傾きの比較（3作業、地形 ＋ 力、正定値の標本の中央値、範囲比）\n")
    p("| 側 | J の作り方 | 力の K の列 | 正定値の標本 | φ | c | ρ | s | K | φ–K の相関 |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    for side in SIDES:
        if (side, "(i)") not in summary:
            continue
        s0, how = side.split("・")
        for m in ("(i)", "(ii)"):
            fr, v, cphik = summary[(side, m)]
            p(f"| {s0} | {how} | {m} | {fr:.0%} | " + " | ".join(f"{x:.3f}" for x in v) + f" | {cphik:+.2f} |")
    p("")

    text = "\n".join(OUT)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
