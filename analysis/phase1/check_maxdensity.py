"""
フェーズ1（T12）：maxDensity を ρ に比例させる案（案D）の確認と、膨張率の両端での動作確認。

置き場所: analysis/phase1/check_maxdensity.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_maxdensity.py \
      --base "data/phase1/flat_cut/run_*" --md "data/phase1/maxdensity/run_*_t12_flat_v2" \
      --swell "data/phase1/maxdensity/run_*_t12_once" [--report 結果.md]

(a) ρ 1,900 の flat_cut を maxDensity 2,000・2,578 で削った記録（ex_maxdens_flat_cut_md2000・md2578）の、
    30 成分（−F_x・−F_z、0.625 m × 15 区切り。check_pilot_phi.py と同じ観測ベクトル）の平均の差 Δ を χ² 検定する。
    Σ は flat_cut の基準 15 回（ex_ident_flat_cut_base、ρ 1,474）から作る（check_pilot_phi.sigma_model）。
      χ² = Δᵀ Σ⁻¹ Δ / (1/n₁ + 1/n₂)、自由度 30。
    ρ 1,900 では雑音が基準より大きいことがある（docs/phase1.md §4.2）。2群の点の平均からのずれから求めた
    分散の倍率 κ（Mahalanobis の2乗の比）で χ² を割った値も並べる。
    合計の力（区切りの平均 −F_x・−F_z の 15 区切りの平均）のエピソードごとの値と、2群の差（ウェルチの t）も並べる。
(c) 膨張率 1.10・1.40 の flat_cut・pile_push（ex_swell_*）：走り切ったか（走行距離）、合計の力、
    pile_push の山の締固めの程度（締固めの記録の center の列、最初の記録で高さ 0.25 m を超えるマスの地表のボクセル）が 1/s か。
    その下のボクセル（元の地表のボクセル）は、元の地山（締固め 1）と山の土が混ざった値になる。
    山の密度は ρ × 締固めの程度 = ρ/s。
"""
import argparse
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_pilot_phi import BINS, collect, episode_files, obs_matrix, sigma_coeffs, sigma_model   # noqa: E402


def jsonl(patterns):
    out = []
    for p in patterns:
        for d in sorted(glob.glob(p)):
            f = os.path.join(d, "episodes.jsonl")
            if os.path.exists(f):
                for line in open(f, encoding="utf-8"):
                    if line.strip():
                        r = json.loads(line)
                        r["_dir"] = d
                        out.append(r)
    return out


def total_forces(eps):
    """エピソードごとの、15 区切りの平均の −F_x・−F_z [kN]"""
    X = obs_matrix(eps, BINS)
    nb = len(BINS)
    return X[:, :nb].mean(axis=1), X[:, nb:].mean(axis=1)


def welch(a, b):
    t, p = stats.ttest_ind(b, a, equal_var=False)
    return float(t), float(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", nargs="+", required=True)
    ap.add_argument("--md", nargs="+", required=True)
    ap.add_argument("--swell", nargs="+", required=True)
    ap.add_argument("--report")
    a = ap.parse_args()
    L = ["# T12：maxDensity の確認と膨張率の両端の動作確認", ""]

    # ---------------- (a)
    base = collect(episode_files(a.base, "ex_ident_flat_cut_base"))["ex_ident_flat_cut_base"]
    nb, d = len(BINS), 2 * len(BINS)
    co = sigma_coeffs(obs_matrix(base, BINS), nb, BINS)
    S = sigma_model(co["sd"], nb, co["ar"], co["r_xz"], BINS)
    Sinv = np.linalg.inv(S)
    md = collect(episode_files(a.md, "ex_maxdens_flat_cut_"))
    X0, X1 = obs_matrix(md["ex_maxdens_flat_cut_md2000"], BINS), obs_matrix(md["ex_maxdens_flat_cut_md2578"], BINS)
    n0, n1 = len(X0), len(X1)
    delta = X1.mean(axis=0) - X0.mean(axis=0)
    chi2 = float(delta @ Sinv @ delta / (1 / n0 + 1 / n1))
    p = float(stats.chi2.sf(chi2, d))
    res = np.vstack([X0 - X0.mean(axis=0), X1 - X1.mean(axis=0)])
    kappa = float(np.mean([r @ Sinv @ r for r in res])) / (d * ((n0 - 1) + (n1 - 1)) / (n0 + n1))
    chi2k = chi2 / kappa
    pk = float(stats.chi2.sf(chi2k, d))
    fx0, fz0 = total_forces(md["ex_maxdens_flat_cut_md2000"])
    fx1, fz1 = total_forces(md["ex_maxdens_flat_cut_md2578"])
    fxb, fzb = total_forces(base)
    tx, px = welch(fx0, fx1)
    tz, pz = welch(fz0, fz1)
    L += ["## (a) ρ 1,900 の flat_cut：maxDensity 2,000 と 2,578", "",
          f"- 本数：2,000 が {n0} 本、2,578 が {n1} 本。Σ は基準（ρ 1,474）{len(base)} 本から（AR(1) {co['ar']:.2f}、F_x・F_z の相関 {co['r_xz']:.2f}、"
          f"区切りの雑音 −F_x {co['sd_Fx']:.2f} kN・−F_z {co['sd_Fz']:.2f} kN）。",
          f"- 30 成分の χ² = {chi2:.1f}（自由度 {d}）、p = {p:.3g}。",
          f"- 2群の雑音の基準に対する倍率 κ = {kappa:.2f}。κ で割ると χ² = {chi2k:.1f}、p = {pk:.3g}。",
          f"- 成分ごとの差の大きさ：|Δ| の最大 −F_x {np.abs(delta[:nb]).max():.2f} kN・−F_z {np.abs(delta[nb:]).max():.2f} kN"
          f"（基準の区切りの雑音の二乗平均 −F_x {co['sd_Fx']:.2f}・−F_z {co['sd_Fz']:.2f} kN）。", "",
          "| 条件 | 本数 | −F_x の平均 [kN] | −F_z の平均 [kN] |", "|---|---|---|---|",
          f"| 基準（ρ 1,474、参考） | {len(fxb)} | {fxb.mean():.2f} ± {fxb.std(ddof=1):.2f} | {fzb.mean():.2f} ± {fzb.std(ddof=1):.2f} |",
          f"| ρ 1,900・maxDensity 2,000 | {n0} | {fx0.mean():.2f} ± {fx0.std(ddof=1):.2f}（{', '.join(f'{v:.2f}' for v in fx0)}） | {fz0.mean():.2f} ± {fz0.std(ddof=1):.2f}（{', '.join(f'{v:.2f}' for v in fz0)}） |",
          f"| ρ 1,900・maxDensity 2,578 | {n1} | {fx1.mean():.2f} ± {fx1.std(ddof=1):.2f}（{', '.join(f'{v:.2f}' for v in fx1)}） | {fz1.mean():.2f} ± {fz1.std(ddof=1):.2f}（{', '.join(f'{v:.2f}' for v in fz1)}） |",
          f"| 差（2,578 − 2,000） | | {fx1.mean() - fx0.mean():+.2f}（t = {tx:.2f}、p = {px:.2g}） | {fz1.mean() - fz0.mean():+.2f}（t = {tz:.2f}、p = {pz:.2g}） |",
          "", "（± は標準偏差。合計の力は 15 区切りの平均の −F_x・−F_z をエピソードごとに平均したもの）", ""]

    # ---------------- (c)
    L += ["## (c) 膨張率 1.10・1.40（ほかは dirt_1）", "",
          "| エピソード | 状態 | 走行距離 [m] | 読み戻した膨張率 | −F_x の平均 [kN] | −F_z の平均 [kN] | 山の地表のボクセルの締固めの程度（平均、マス数） | 1/s | 山の密度 ρ·c [kg/m³] | ρ/s | その下のボクセル（元の地表、地山と混ざる） |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted((r for r in jsonl(a.swell) if r["episode_name"].startswith("ex_swell_")), key=lambda r: r["episode_name"]):
        name, s, rho = r["episode_name"], r["label_swell"], r["label_rho0"]
        fx = fz = cs = c1 = float("nan")
        ncell = 0
        path = os.path.join(r["_dir"], r["file"])
        if str(r["status"]) == "ok" and "flat_cut" in name:
            e = collect([(name, path)])[name]
            fxa, fza = total_forces(e)
            fx, fz = fxa[0], fza[0]
        comp = os.path.splitext(path)[0] + "_compaction.csv"
        if os.path.exists(comp):
            c = pd.read_csv(comp)
            first = c[(c["sim_time"] == c["sim_time"].min()) & (c["lane"] == "center")]
            # 山の中ほど（高さが 0.25 m を超えるマス）。山の端のマスは崩れて地表のボクセルが元の地山と混ざるので除く
            pile = first[first["height"] > 0.25]
            ncell = len(pile)
            cs = float(pile["c_surface"].mean()) if ncell else float("nan")
            c1 = float(pile["c_z1"].mean()) if ncell else float("nan")
        L.append(f"| {name} | {r['status']} | {r.get('run_distance', float('nan')):.2f} | {s:.3f} | {fx:.2f} | {fz:.2f} | "
                 f"{cs:.4f}（{ncell}） | {1 / s:.4f} | {rho * cs:.1f} | {rho / s:.1f} | {c1:.4f} |")
    L += ["", "（pile_push の合計の力は、区切りの範囲が flat_cut と違うので出していない。山の値は、締固めの記録の center の列の最初の記録"
          "（phase lowering）で、高さが 0.25 m を超えるマス）", ""]
    text = "\n".join(L) + "\n"
    print(text)
    if a.report:
        open(a.report, "w", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
