"""
フェーズ1：同定可能性（地形の経路、flat_cut）の解析（T26）。観測はエピソードの終わり（最後の行）の
(vis_net_pos, vis_net_neg, pile_volume_vis) の3成分。力の経路（check_ident.py・check_ident_combine.py）と組み合わせた下限も出す。

置き場所: analysis/phase1/check_ident_terrain.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_ident_terrain.py 'data/phase1/vis_net/run_*' 'data/phase1/terrain_flat_cut/run_*' \
      [--report 結果.md] [--boot 1000]

notes decisions/2026-11-18_sは地形の経路で判定し地形の経路の行をflat_cutから作る.md

手順（力の経路の §5・§8 と同じ考え方）:
  - 点ごとの観測 y（3成分）の平均から、中心差分で J̃ を作る（重みは check_ident.DESIGN。パラメータは範囲の幅で正規化）。
  - Σ（3×3）は基準の記録の標本共分散。標本共分散の逆行列は精度を大きく見積もるので、Σ⁻¹ に (n − d − 2)/(n − 1) を掛ける
    （n は基準の本数、d = 3。逆ウィシャートの期待値の補正。下限は大きくなる側）。
  - 点ごとの分散の倍率 κ、雑音の水増し d·c_H·Σ w²κ/n、χ² = J̃ᵀΣ⁻¹J̃ / (c_H·Σ w²κ/n)（c_H は上の補正。χ² は補正によらない）。
  - 信号 = 水増しを引いた F の対角。ブートストラップ（点ごとにエピソードを選び直し、J と水増しを求め直す）で、
    信号 ÷ 標準偏差、1つだけの下限の 16〜84%、同時の下限（水増しを引いた F が正定値の標本の 5・16・50・84・95%）、正定値の割合。
    幅と割合は、各標本から偏り（標本の平均 − 点推定）を引いた標本で求める（T21・T23 と同じ）。
  - 力の経路の F（check_ident_combine.load_task、作業ごとの基準の Σ）を足し、地形 ＋ 力の組み合わせの4つ同時の下限と c–ρ の相関を出す。
    力の経路と地形の経路の観測は独立とみなす（エピソードも別）。
  - 線形性：d = y(中) − (y(端1) + y(端2))/2（φ は +5° と 0°・+10°、c は 2.1 と 0.6・3.6、ρ は +35 と 0・+70。s は線形性の点がないので出さない）。
  - 補助：点ごとの vis_net_neg − cut_volume の平均（沈下などの分）、深さのずれの 95% 点が 5 cm を超えた記録の一覧。
"""
import argparse
import glob
import math
import os
import re
import sys

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "validation"))
import check_ident_combine as cic   # noqa: E402
from check_ident import DESIGN, set_s_step   # noqa: E402
from check_physics import settled_cut_rows   # noqa: E402

WS = os.path.abspath(os.path.join(HERE, "..", ".."))
PREFIX = "ex_ident_flat_cut_"
OBS = ["vis_net_pos", "vis_net_neg", "pile_volume_vis"]
NAMES = ["φ", "c", "ρ", "s"]
LIN = {"φ": ("phi_p5", "base", "phi_p10"), "c": ("base", "c_m1p5", "c_p1p5"), "ρ": ("rho_p35", "base", "rho_p70")}
DEV_LIMIT = 0.05


def load_episodes(patterns):
    files = sorted(f for p in patterns for f in glob.glob(os.path.join(p, "ep[0-9]*.csv")))
    pts, devs, aux = {}, [], {}
    for f in files:
        df = pd.read_csv(f)
        name = str(df["episode_name"].iloc[0])
        if not name.startswith(PREFIX):
            continue
        pt = name[len(PREFIX):]
        last = df.iloc[-1]
        y = np.array([last[c] for c in OBS], float)
        if np.isnan(y).any():
            continue
        rows = settled_cut_rows(df)
        dev95 = float(np.percentile(np.abs(rows["depth"] - rows["target_depth"]), 95)) if rows is not None else math.nan
        pts.setdefault(pt, []).append(y)
        aux.setdefault(pt, []).append(float(last["vis_net_neg"] - last["cut_volume"]))
        devs.append((os.path.relpath(f, WS), pt, dev95))
    return {k: np.array(v) for k, v in pts.items()}, devs, aux


def terrain_task(X, names, cH):
    d = len(OBS)
    S = np.cov(X["base"], rowvar=False)
    Sinv = np.linalg.inv(S) * cH
    Sinv_raw = np.linalg.inv(S)
    nrep = {k: len(v) for k, v in X.items()}
    mean = {k: v.mean(axis=0) for k, v in X.items()}
    kappa = {}
    for k, x in X.items():
        r = x - x.mean(axis=0)
        kappa[k] = float(np.mean([v @ Sinv_raw @ v for v in r])) / (d * (len(x) - 1) / len(x)) if len(x) > 1 else math.nan
    J = {n: sum(wt * mean[k] for k, wt in DESIGN[n][1].items()) for n in names}
    var = {n: sum(wt ** 2 * kappa[k] / nrep[k] for k, wt in DESIGN[n][1].items()) for n in names}
    infl = {n: d * cH * var[n] for n in names}
    return dict(X=X, S=S, Sinv=Sinv, Sinv_raw=Sinv_raw, cH=cH, d=d, nrep=nrep, mean=mean, kappa=kappa, J=J, var=var, infl=infl)


def fisher_terrain(T, names, J=None):
    Jm = np.column_stack([(J or T["J"])[n] for n in names])
    return Jm.T @ T["Sinv"] @ Jm


def boot_terrain(T, names, rng):
    """点ごとに選び直し、そのままの F と水増しの対角を返す（check_ident_combine.boot_sig と同じ形）"""
    need = sorted({k for n in names for k in DESIGN[n][1]})   # 並べた順で回す（set の順は実行ごとに変わり、乱数の当たり方が変わる。T34）
    mb, tr = {}, {}
    for k in need:
        Xk = T["X"][k][rng.integers(0, len(T["X"][k]), len(T["X"][k]))]
        mb[k] = Xk.mean(axis=0)
        r = Xk - mb[k]
        nk = len(Xk)
        tr[k] = float(np.einsum("ij,jk,ik->i", r, T["Sinv"], r).mean()) * nk / (nk - 1)   # c_H·tr(Σ⁻¹S)
    Jm = np.column_stack([sum(wt * mb[k] for k, wt in DESIGN[n][1].items()) for n in names])
    infl = np.array([sum(wt ** 2 * tr[k] / len(T["X"][k]) for k, wt in DESIGN[n][1].items()) for n in names])
    return Jm.T @ T["Sinv"] @ Jm, infl


def summarize(F0, samples, names):
    """点推定 F0（水増しを引いた値）と標本から、偏りを引いた幅・正定値の割合・同時の下限・相関"""
    nP = len(names)
    S_raw = np.array(samples)
    S = S_raw - (S_raw.mean(axis=0) - F0)
    pd0 = np.linalg.eigvalsh(F0).min() > 0
    pdmask = np.array([np.linalg.eigvalsh(x).min() > 0 for x in S])
    jb = np.array([np.sqrt(np.diag(np.linalg.inv(x))) for x in S[pdmask]]) if pdmask.any() else np.empty((0, nP))
    cb = np.array([(lambda M: M[1, 2] / math.sqrt(M[1, 1] * M[2, 2]))(np.linalg.inv(x)) for x in S[pdmask]]) if pdmask.any() and nP > 2 else np.empty(0)
    out = dict(pd0=pd0, pdfrac=float(pdmask.mean()), joint0=np.sqrt(np.diag(np.linalg.inv(F0))) if pd0 else np.full(nP, math.nan),
               q=np.percentile(jb, [5, 16, 50, 84, 95], axis=0) if len(jb) else np.full((5, nP), math.nan),
               sd=np.array([np.std(S[:, i, i], ddof=1) for i in range(nP)]), sig=np.diag(F0),
               bias=np.diag(S_raw.mean(axis=0)) / np.diag(F0),
               corr0=(lambda M: M[1, 2] / math.sqrt(M[1, 1] * M[2, 2]))(np.linalg.inv(F0)) if pd0 and nP > 2 else math.nan,
               corrq=np.percentile(cb, [16, 50, 84]) if len(cb) else np.full(3, math.nan),
               single_q=[np.percentile(1 / np.sqrt(S[S[:, i, i] > 0, i, i]), [16, 84]) if (S[:, i, i] > 0).any() else (math.nan, math.nan) for i in range(nP)],
               evmin=float(np.linalg.eigvalsh(F0).min()))
    return out


def main():
    ap = argparse.ArgumentParser(description="地形の経路の同定可能性（flat_cut、T26）")
    ap.add_argument("paths", nargs="+", help="collect_data の出力フォルダ（glob 可）")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--report")
    a = ap.parse_args()
    set_s_step(0.06)
    names = NAMES
    X, devs, aux = load_episodes(a.paths)
    need = {k for n in names for k in DESIGN[n][1]} | {k for v in LIN.values() for k in v}
    missing = sorted(need - set(X))
    if missing:
        raise SystemExit(f"記録のない点：{missing}")
    nb = len(X["base"])
    d = len(OBS)
    cH = (nb - d - 2) / (nb - 1)
    T = terrain_task(X, names, cH)
    rng = np.random.default_rng(0)
    out = []
    p = out.append
    p("# 地形の経路の同定可能性（flat_cut、エピソードの終わりの3成分）\n")
    p(f"観測：{', '.join(OBS)}（最後の行）。基準 {nb} 本。Σ⁻¹ に (n − d − 2)/(n − 1) = {cH:.3f} を掛けた。ブートストラップ {a.boot} 回。\n")
    p("## 1. 点ごとの本数・平均・κ\n")
    p("| 点 | 本数 | " + " | ".join(f"{c} 平均" for c in OBS) + " | κ | vis_net_neg − cut_volume 平均 [m³] |")
    p("|---|---|" + "---|" * len(OBS) + "---|---|")
    for k in sorted(X):
        p(f"| {k} | {T['nrep'][k]} | " + " | ".join(f"{v:.3f}" for v in T["mean"][k]) + f" | {T['kappa'][k]:.2f} | {np.mean(aux[k]):.3f} |")
    sd0 = np.sqrt(np.diag(T["S"]))
    R = T["S"] / np.outer(sd0, sd0)
    p(f"\n基準の標準偏差：{', '.join(f'{c} {s:.3f}' for c, s in zip(OBS, sd0))} [m³]。相関：pos–neg {R[0, 1]:+.2f}、pos–pile {R[0, 2]:+.2f}、neg–pile {R[1, 2]:+.2f}\n")

    p("## 2. パラメータごとの J と判定（地形の経路だけ）\n")
    p("J̃ は範囲の幅で正規化（パラメータが範囲の幅だけ変わったときの変化 [m³]）。\n")
    p("| パラメータ | J̃（" + "・".join(OBS) + "） | χ² の p | 水増し ÷ F | 信号 | 信号 ÷ 標準偏差 | ≥ 2 か | 下限（1つだけ）点推定（16〜84%） |")
    p("|---|---|---|---|---|---|---|---|")
    F = fisher_terrain(T, names)
    infl = np.array([T["infl"][n] for n in names])
    Fs = F - np.diag(infl)
    samples = []
    for _ in range(a.boot):
        Fb, ib = boot_terrain(T, names, rng)
        samples.append(Fb - np.diag(ib))
    sm = summarize(Fs, samples, names)
    for i, n in enumerate(names):
        chi2 = float(T["J"][n] @ T["Sinv_raw"] @ T["J"][n]) / T["var"][n]
        pv = float(stats.chi2.sf(chi2, d))
        sig = Fs[i, i]
        single = 1 / math.sqrt(sig) if sig > 0 else math.nan
        q = sm["single_q"][i]
        p(f"| {n} | {', '.join(f'{v:+.3f}' for v in T['J'][n])} | {pv:.2g} | {infl[i] / F[i, i]:.2f} | {sig:.1f} | {sig / sm['sd'][i]:.2f} | "
          f"{'はい' if sig / sm['sd'][i] >= 2 else '**いいえ**'} | {single:.3f}（{q[0]:.3f}〜{q[1]:.3f}） |")
    Jm = np.column_stack([T["J"][n] for n in names])
    W = np.linalg.cholesky(T["Sinv"]).T @ Jm
    Wn = W / np.linalg.norm(W, axis=0)
    G = Wn.T @ Wn
    p("\n白色化した J の列の cos：" + "、".join(f"{names[i]}–{names[j]} {G[i, j]:+.2f}" for i in range(4) for j in range(i + 1, 4)) + "\n")

    p("## 3. 線形性（d = y(中) − (y(端1) + y(端2))/2、κ を見込む）\n")
    p("| パラメータ | χ²（3 成分） | p | |d| ÷ |半刻みの変化|（Σ で測る） |")
    p("|---|---|---|---|")
    for n, (m, e1, e2) in LIN.items():
        dv = T["mean"][m] - (T["mean"][e1] + T["mean"][e2]) / 2
        var = T["kappa"][m] / T["nrep"][m] + (T["kappa"][e1] / T["nrep"][e1] + T["kappa"][e2] / T["nrep"][e2]) / 4
        chi2 = float(dv @ T["Sinv_raw"] @ dv) / var
        h = (T["mean"][e2] - T["mean"][e1]) / 2
        ratio = math.sqrt(dv @ T["Sinv_raw"] @ dv) / math.sqrt(h @ T["Sinv_raw"] @ h)
        p(f"| {n}（{m} と {e1}・{e2}） | {chi2:.2f} | {stats.chi2.sf(chi2, d):.2g} | {ratio:.2f} |")
    p("")

    # ---- 力の経路
    cic.NAMES = list(names)
    ftasks = {}
    for t, (prefix, (b0, b1), maxdev, pattern, skip) in cic.TASKS.items():
        ftasks[t] = cic.load_task([os.path.join(WS, pattern)], prefix, range(b0, b1 + 1), maxdev, skip, names)

    def force_point(ts):
        return sum(cic.fisher(ftasks[t]) - np.diag([ftasks[t]["infl"][n] for n in names]) for t in ts)

    combos = [("地形だけ", (), True), ("力：flat_cut だけ", ("flat_cut",), False), ("力：3作業", tuple(ftasks), False),
              ("地形 ＋ 力：flat_cut", ("flat_cut",), True), ("地形 ＋ 力：3作業", tuple(ftasks), True)]
    pts0 = {lab: (Fs if ter else 0) + (force_point(ts) if ts else 0) for lab, ts, ter in combos}
    samp = {lab: [] for lab, _, _ in combos}
    rng2 = np.random.default_rng(1)
    for _ in range(a.boot):
        Fb, ib = boot_terrain(T, names, rng2)
        ter_b = Fb - np.diag(ib)
        per = {t: cic.boot_sig(ftasks[t], rng2) for t in ftasks}
        for lab, ts, ter in combos:
            samp[lab].append((ter_b if ter else 0) + sum(per[t][0] - np.diag(per[t][1]) for t in ts))
    p("## 4. 4つ同時（φ・c・ρ・s）の下限（範囲比）と c–ρ の相関\n")
    p("水増しを引いた F。点推定が正定値でなければ「—」。幅は偏りを引いた標本のうち正定値のものから（5〜95%、括弧内は 16〜84%）。"
      "相関は推定値の相関（F⁻¹ から）。力の経路の F は check_ident_combine と同じ（s は ±0.06、pile_push の s は各 10 回）。\n")
    p("| 組み合わせ | 正定値の標本 | 最小の固有値（点推定） | " + " | ".join(f"{n} 点推定／中央値（5〜95%、16〜84%）" for n in names) + " | c–ρ の相関 点推定／中央値（16〜84%） |")
    p("|---|---|---|" + "---|" * len(names) + "---|")
    res = {}
    for lab, _, _ in combos:
        r = summarize(pts0[lab], samp[lab], names)
        res[lab] = r
        cells = []
        for i in range(len(names)):
            j0 = f"{r['joint0'][i]:.3f}" if r["pd0"] else "—"
            q = r["q"][:, i]
            cells.append(f"{j0}／{q[2]:.3f}（{q[0]:.3f}〜{q[4]:.3f}、{q[1]:.3f}〜{q[3]:.3f}）")
        c0 = f"{r['corr0']:+.2f}" if r["pd0"] else "—"
        p(f"| {lab} | {r['pdfrac']:.0%} | {r['evmin']:.1f} | " + " | ".join(cells) + f" | {c0}／{r['corrq'][1]:+.2f}（{r['corrq'][0]:+.2f}〜{r['corrq'][2]:+.2f}） |")
    p("\n**信号（水増しを引いた F の対角）÷ ブートストラップの標準偏差**\n")
    p("| 組み合わせ | " + " | ".join(names) + " |")
    p("|---|" + "---|" * len(names))
    for lab, _, _ in combos:
        r = res[lab]
        p(f"| {lab} | " + " | ".join(f"{r['sig'][i]:.1f} ÷ {r['sd'][i]:.1f} = {r['sig'][i] / r['sd'][i]:.2f}" for i in range(len(names))) + " |")
    p("")

    p(f"## 5. 深さのずれの 95% 点が {DEV_LIMIT * 100:.0f} cm を超えた記録\n")
    over = [x for x in devs if x[2] > DEV_LIMIT]
    p("| 記録 | 点 | 深さのずれ 95% [cm] |")
    p("|---|---|---|")
    for f, pt, dv in over:
        p(f"| {f} | {pt} | {dv * 100:.2f} |")
    if not over:
        p("| なし | | |")
    allv = np.array([x[2] for x in devs])
    p(f"\n全 {len(devs)} 本の深さのずれの 95% 点：{allv.min() * 100:.2f}〜{allv.max() * 100:.2f} cm（中央値 {np.median(allv) * 100:.2f} cm）\n")
    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
