"""
フェーズ1：地形の経路の行（3作業）と、経路ごとに信号のある列で作る力 ＋ 地形の組み合わせ（T27）。

置き場所: analysis/phase1/check_ident_terrain_combine.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_ident_terrain_combine.py [--report 結果.md] [--boot 1000] [--drop パスの一部 …]

notes decisions/2026-11-18_地形の経路はφとsの列で組み合わせを作る.md

地形の経路（check_ident_terrain.py と同じ手順）:
  観測はエピソードの終わりの (vis_net_pos, vis_net_neg, pile_volume_vis)。Σ は基準の標本共分散で、Σ⁻¹ に (n − d − 2)/(n − 1) を掛ける。
  flat_cut は φ・c・ρ・s の点、flat_piecewise・pile_push は φ・s の点だけ（c・ρ は測っていない）。
  pile_push は、深さのずれの 95% 点が 10 cm を超える記録（潜り）を除く（§5 と同じ）。
組み合わせ（主な結果）:
  力の経路は作業ごとの (φ, c, ρ) の F（check_ident_combine.load_task、s の列は外す。力の経路の s の効きは 0 とみなす）、
  地形の経路は作業ごとの (φ, s) の F（c・ρ の列は外す）。どちらも水増しを引き、4×4（φ, c, ρ, s）に埋めて足す。
  ブートストラップは、地形・力の作業ごとに同じ回で選び直し、偏りを引いた標本で正定値の割合・5〜95% の幅・相関を求める。
"""
import argparse
import glob
import math
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "validation"))
import check_ident_combine as cic   # noqa: E402
from check_ident import DESIGN, set_s_step   # noqa: E402
from check_ident_terrain import OBS, boot_terrain, fisher_terrain, terrain_task   # noqa: E402
from check_physics import settled_cut_rows   # noqa: E402

WS = os.path.abspath(os.path.join(HERE, "..", ".."))
ALL = ["φ", "c", "ρ", "s"]
# 地形の経路の作業 → (エピソード名の頭, 記録の glob, 使うパラメータ, 除く深さのずれ [m])
TTASKS = {
    "flat_cut": ("ex_ident_flat_cut_", ["data/phase1/vis_net/run_*", "data/phase1/terrain_flat_cut/run_*"], ["φ", "c", "ρ", "s"], None),
    "flat_piecewise": ("ex_ident_flat_piecewise_", ["data/phase1/terrain_flat_piecewise/run_*"], ["φ", "s"], None),
    "pile_push": ("ex_ident_pile_push_", ["data/phase1/terrain_pile_push/run_*"], ["φ", "s"], 0.10),
}
LIN = {"φ": ("phi_p5", "base", "phi_p10"), "c": ("base", "c_m1p5", "c_p1p5"), "ρ": ("rho_p35", "base", "rho_p70")}
DEV_LIMIT = 0.05


def load(prefix, patterns, max_dev, drop=()):
    files = sorted(f for p in patterns for f in glob.glob(os.path.join(WS, p, "ep[0-9]*.csv")))
    files = [f for f in files if not any(d in os.path.relpath(f, WS) for d in drop)]
    pts, devs, excluded, aux = {}, [], [], {}
    for f in files:
        df = pd.read_csv(f)
        name = str(df["episode_name"].iloc[0])
        if not name.startswith(prefix):
            continue
        pt = name[len(prefix):]
        rows = settled_cut_rows(df)
        dev95 = float(np.percentile(np.abs(rows["depth"] - rows["target_depth"]), 95)) if rows is not None else math.nan
        devs.append((os.path.relpath(f, WS), pt, dev95))
        if max_dev is not None and not dev95 <= max_dev:
            excluded.append((os.path.relpath(f, WS), pt, dev95))
            continue
        last = df.iloc[-1]
        y = np.array([last[c] for c in OBS], float)
        if np.isnan(y).any():
            continue
        pts.setdefault(pt, []).append(y)
        aux.setdefault(pt, []).append(float(last["vis_net_neg"] - last["cut_volume"]))
    return {k: np.array(v) for k, v in pts.items()}, devs, excluded, aux


def embed(F, names):
    M = np.zeros((4, 4))
    idx = [ALL.index(n) for n in names]
    M[np.ix_(idx, idx)] = F
    return M


def summarize(F0, samples, pairs):
    nP = F0.shape[0]
    S_raw = np.array(samples)
    S = S_raw - (S_raw.mean(axis=0) - F0)
    pd0 = np.linalg.eigvalsh(F0).min() > 0
    pdmask = np.array([np.linalg.eigvalsh(x).min() > 0 for x in S])
    inv = [np.linalg.inv(x) for x in S[pdmask]]
    jb = np.array([np.sqrt(np.diag(M)) for M in inv]) if inv else np.empty((0, nP))

    def corr(M, i, j):
        return M[i, j] / math.sqrt(M[i, i] * M[j, j])
    cq = {pr: (np.percentile([corr(M, *pr) for M in inv], [16, 50, 84]) if inv else np.full(3, math.nan)) for pr in pairs}
    M0 = np.linalg.inv(F0) if pd0 else None
    return dict(pd0=pd0, pdfrac=float(pdmask.mean()), evmin=float(np.linalg.eigvalsh(F0).min()),
                joint0=np.sqrt(np.diag(M0)) if pd0 else np.full(nP, math.nan),
                q=np.percentile(jb, [5, 16, 50, 84, 95], axis=0) if len(jb) else np.full((5, nP), math.nan),
                c0={pr: (corr(M0, *pr) if pd0 else math.nan) for pr in pairs}, cq=cq,
                sd=np.array([np.std(S[:, i, i], ddof=1) for i in range(nP)]), sig=np.diag(F0))


def main():
    ap = argparse.ArgumentParser(description="地形の経路の行（3作業）と経路ごとの列の組み合わせ（T27）")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--report")
    ap.add_argument("--drop", nargs="*", default=[],
                    help="除く記録（パスの一部）。深さのずれが大きい記録を除いた場合に判定が変わるかの確認用")
    a = ap.parse_args()
    set_s_step(0.06)
    out = []
    p = out.append
    p("# 地形の経路の行（3作業）と、経路ごとに信号のある列で作る組み合わせ（T27）\n")
    rng = np.random.default_rng(0)
    TT, alldev, allexc = {}, [], []
    p("## 1. 作業ごとの地形の経路の判定\n")
    for t, (prefix, pats, names, maxdev) in TTASKS.items():
        X, devs, exc, aux = load(prefix, pats, maxdev, a.drop)
        alldev += [(t,) + d for d in devs]
        allexc += [(t,) + e for e in exc]
        need = {k for n in names for k in DESIGN[n][1]} | {k for n in names if n in LIN for k in LIN[n]}
        missing = sorted(need - set(X))
        if missing:
            raise SystemExit(f"{t}：記録のない点：{missing}")
        nb = len(X["base"])
        d = len(OBS)
        cH = (nb - d - 2) / (nb - 1)
        T = terrain_task(X, names, cH)
        TT[t] = (T, names)
        F = fisher_terrain(T, names)
        infl = np.array([T["infl"][n] for n in names])
        Fs = F - np.diag(infl)
        samples = [(lambda r: r[0] - np.diag(r[1]))(boot_terrain(T, names, rng)) for _ in range(a.boot)]
        S_raw = np.array(samples)
        S = S_raw - (S_raw.mean(axis=0) - Fs)
        p(f"### {t}（基準 {nb} 本、Σ⁻¹ × {cH:.3f}）\n")
        p("| 点 | " + " | ".join(sorted(X)) + " |")
        p("|---|" + "---|" * len(X))
        p("| 本数 | " + " | ".join(str(len(X[k])) for k in sorted(X)) + " |")
        p("| κ | " + " | ".join(f"{T['kappa'][k]:.2f}" for k in sorted(X)) + " |")
        p("| neg − cut_volume [m³] | " + " | ".join(f"{np.mean(aux[k]):.3f}" for k in sorted(X)) + " |")
        sd0 = np.sqrt(np.diag(T["S"]))
        p(f"\n基準の平均 {', '.join(f'{c} {m:.3f}' for c, m in zip(OBS, T['mean']['base']))}、標準偏差 {', '.join(f'{s:.3f}' for s in sd0)} [m³]\n")
        p("| パラメータ | J̃（pos・neg・pile） | χ² の p | 水増し ÷ F | 信号 | 信号 ÷ 標準偏差 | ≥ 2 か | 下限（1つだけ）点推定（16〜84%） |")
        p("|---|---|---|---|---|---|---|---|")
        for i, n in enumerate(names):
            chi2 = float(T["J"][n] @ T["Sinv_raw"] @ T["J"][n]) / T["var"][n]
            pv = float(stats.chi2.sf(chi2, d))
            sig, sd = Fs[i, i], float(np.std(S[:, i, i], ddof=1))
            pos = S[:, i, i] > 0
            q = np.percentile(1 / np.sqrt(S[pos, i, i]), [16, 84]) if pos.any() else (math.nan, math.nan)
            single = f"{1 / math.sqrt(sig):.3f}" if sig > 0 else "求まらない（信号が負）"
            p(f"| {n} | {', '.join(f'{v:+.3f}' for v in T['J'][n])} | {pv:.2g} | {infl[i] / F[i, i]:.2f} | {sig:.1f} | {sig / sd:.2f} | "
              f"{'はい' if sig / sd >= 2 else '**いいえ**'} | {single}（{q[0]:.3f}〜{q[1]:.3f}） |")
        lin = []
        for n in names:
            if n not in LIN:
                continue
            m, e1, e2 = LIN[n]
            dv = T["mean"][m] - (T["mean"][e1] + T["mean"][e2]) / 2
            var = T["kappa"][m] / T["nrep"][m] + (T["kappa"][e1] / T["nrep"][e1] + T["kappa"][e2] / T["nrep"][e2]) / 4
            chi2 = float(dv @ T["Sinv_raw"] @ dv) / var
            lin.append(f"{n} p = {stats.chi2.sf(chi2, d):.2g}")
        p("\n線形性（κ を見込む）：" + "、".join(lin) + "\n")
        if "φ" in names and "s" in names:
            ii = [names.index("φ"), names.index("s")]
            F2 = Fs[np.ix_(ii, ii)]
            pd0 = np.linalg.eigvalsh(F2).min() > 0
            if pd0:
                M = np.linalg.inv(F2)
                p(f"φ・s の2つ同時（点推定）：φ {math.sqrt(M[0, 0]):.3f}、s {math.sqrt(M[1, 1]):.3f}、相関 {M[0, 1] / math.sqrt(M[0, 0] * M[1, 1]):+.2f}\n")
            else:
                p("φ・s の2つ同時：点推定は正定値でない\n")

    # ---- 力の経路（φ, c, ρ）
    fnames = ["φ", "c", "ρ"]
    cic.NAMES = list(fnames)
    FT = {}
    for t, (prefix, (b0, b1), maxdev, pattern, skip) in cic.TASKS.items():
        FT[t] = cic.load_task([os.path.join(WS, pattern)], prefix, range(b0, b1 + 1), maxdev, skip, fnames)

    def force_pt(t):
        return embed(cic.fisher(FT[t]) - np.diag([FT[t]["infl"][n] for n in fnames]), fnames)

    def terr_pt(t):
        T, names = TT[t]
        Fs = fisher_terrain(T, ["φ", "s"]) - np.diag([T["infl"][n] for n in ["φ", "s"]])
        return embed(Fs, ["φ", "s"])

    combos = [
        ("力だけ：3作業（φ・c・ρ、参考）", list(FT), [], [0, 1, 2]),
        ("地形 ＋ 力：flat_cut", ["flat_cut"], ["flat_cut"], [0, 1, 2, 3]),
        ("地形（flat_cut）＋ 力：3作業", list(FT), ["flat_cut"], [0, 1, 2, 3]),
        ("地形 ＋ 力：3作業", list(FT), list(TT), [0, 1, 2, 3]),
        ("地形だけ：3作業（φ・s）", [], list(TT), [0, 3]),
    ]
    pt0 = {lab: sum([force_pt(t) for t in ft] + [terr_pt(t) for t in tt]) for lab, ft, tt, _ in combos}
    samp = {lab: [] for lab, *_ in combos}
    rng2 = np.random.default_rng(1)
    for _ in range(a.boot):
        fb = {t: (lambda r: embed(r[0] - np.diag(r[1]), fnames))(cic.boot_sig(FT[t], rng2)) for t in FT}
        tb = {t: (lambda r: embed(r[0] - np.diag(r[1]), ["φ", "s"]))(boot_terrain(TT[t][0], ["φ", "s"], rng2)) for t in TT}
        for lab, ft, tt, _ in combos:
            samp[lab].append(sum([fb[t] for t in ft] + [tb[t] for t in tt]))
    p("## 2. 組み合わせ（力 (φ, c, ρ) ＋ 地形 (φ, s)、4×4 に埋めて足す）\n")
    p("力の経路の s の効きは 0 とみなす（雑音に埋もれていたため）。水増しを引いた F。値は、点推定が正定値ならその値、"
      "続けて偏りを引いた標本のうち正定値のものの中央値（5〜95%）。\n")
    p("| 組み合わせ | 正定値（点推定） | 正定値の標本 | 最小の固有値 | φ | c | ρ | s | c–ρ の相関 | φ–s の相関 |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    res = {}
    for lab, ft, tt, idx in combos:
        F0 = pt0[lab][np.ix_(idx, idx)]
        sm_ = [x[np.ix_(idx, idx)] for x in samp[lab]]
        pairs = []
        if 1 in idx and 2 in idx:
            pairs.append((idx.index(1), idx.index(2)))
        if 0 in idx and 3 in idx:
            pairs.append((idx.index(0), idx.index(3)))
        r = summarize(F0, sm_, pairs)
        res[lab] = (r, idx)
        cells = []
        for k in range(4):
            if k not in idx:
                cells.append("—")
                continue
            i = idx.index(k)
            j0 = f"{r['joint0'][i]:.3f}" if r["pd0"] else "正定値でない"
            q = r["q"][:, i]
            cells.append(f"{j0}／{q[2]:.3f}（{q[0]:.3f}〜{q[4]:.3f}）")

        def ccell(pr):
            if pr not in r["cq"]:
                return "—"
            c0 = f"{r['c0'][pr]:+.2f}" if r["pd0"] else "—"
            return f"{c0}／{r['cq'][pr][1]:+.2f}（{r['cq'][pr][0]:+.2f}〜{r['cq'][pr][2]:+.2f}）"
        cr = (idx.index(1), idx.index(2)) if (1 in idx and 2 in idx) else None
        fs = (idx.index(0), idx.index(3)) if (0 in idx and 3 in idx) else None
        p(f"| {lab} | {'はい' if r['pd0'] else 'いいえ'} | {r['pdfrac']:.0%} | {r['evmin']:.1f} | " + " | ".join(cells)
          + f" | {ccell(cr) if cr else '—'} | {ccell(fs) if fs else '—'} |")
    p("\n**信号（水増しを引いた F の対角）÷ ブートストラップの標準偏差**\n")
    p("| 組み合わせ | φ | c | ρ | s |")
    p("|---|---|---|---|---|")
    for lab, *_ in combos:
        r, idx = res[lab]
        cells = []
        for k in range(4):
            if k not in idx:
                cells.append("—")
                continue
            i = idx.index(k)
            cells.append(f"{r['sig'][i]:.1f} ÷ {r['sd'][i]:.1f} = {r['sig'][i] / r['sd'][i]:.2f}")
        p(f"| {lab} | " + " | ".join(cells) + " |")
    p("")

    p(f"## 3. 深さのずれの 95% 点が {DEV_LIMIT * 100:.0f} cm を超えた記録（地形の経路の記録）\n")
    p("| 作業 | 記録 | 点 | 深さのずれ 95% [cm] | J に入るか | 除いたか |")
    p("|---|---|---|---|---|---|")
    jpts = {k for n in ALL for k in DESIGN[n][1]}
    exset = {e[1] for e in allexc}
    over = [x for x in alldev if x[3] > DEV_LIMIT]
    for t, f, pt, dv in over:
        p(f"| {t} | {f} | {pt} | {dv * 100:.2f} | {'はい' if pt in jpts or pt == 'base' else 'いいえ（線形性だけ）'} | {'はい（10 cm 超）' if f in exset else 'いいえ'} |")
    if not over:
        p("| なし | | | | | |")
    for t in TTASKS:
        v = np.array([x[3] for x in alldev if x[0] == t])
        p(f"\n{t}：{len(v)} 本、深さのずれの 95% 点 {v.min() * 100:.2f}〜{v.max() * 100:.2f} cm（中央値 {np.median(v) * 100:.2f} cm）")
    p("")
    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
