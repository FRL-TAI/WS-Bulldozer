"""
フェーズ1：同定可能性（力の経路）の解析。ex_ident_flat_cut_* の記録から、φ・c・ρ の J の列、
フィッシャー情報行列、推定標準偏差の下限（範囲比）、線形性を求める。

置き場所: analysis/phase1/check_ident.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_ident.py 'data/phase1/flat_cut/run_*' \
      [--pilot 'data/phase1/pilot_phi/run_*'] [--gate6 'data/validation/gate6/run_*'] [--report 結果.md]

観測ベクトル：距離 0.625 m ごとの −F_x・−F_z の平均（区切り 1〜15、30 成分。check_pilot_phi.py と同じ）。
Σ：基準の繰り返しから、区切りごとの分散・AR(1)・F_x・F_z の相関で作る（check_pilot_phi.sigma_model）。

差分（notes の docs/phase1.md §5）。パラメータは範囲の幅で正規化する（θ̃ = θ / 幅）。
  J̃ = Σ_k w_k · F̄_k（F̄_k は点 k の平均の観測ベクトル）
  φ：中心差分 (F(+10°) − F(−10°)) / (20°/25°)
  c：中心差分 (F(+1.5 kPa) − F(−1.5 kPa)) / (3/30)（参考に T7 の2次の片側差分と片側の傾きも並べる）
  ρ：中心差分 (F(+70) − F(−70)) / (140/700)
点 k の雑音は基準の Σ の κ_k 倍とみなす（κ_k は点ごとの分散の倍率。点の平均からのずれの Mahalanobis の2乗から求める）。
J̃ の雑音の共分散は (Σ_k w_k² κ_k / n_k) Σ なので、J̃ᵀΣ⁻¹J̃ は期待値で d · Σ_k w_k² κ_k/n_k だけ水増しされる（d は成分の数）。
χ² = J̃ᵀΣ⁻¹J̃ / (Σ_k w_k² κ_k/n_k) は、効果がなければ自由度 d の χ² に従う。
フィッシャー情報行列 F = J̃ᵀΣ⁻¹J̃（3×3）は、対角から水増し分を引いた値も出す（φ・c・ρ の中心差分は点を共有しないので、非対角は水増しされない）。推定標準偏差の下限（範囲比）は √(F⁻¹)ᵢᵢ。
"""
import argparse
import math
import os
import sys

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_pilot_phi import (BINS, GATE6, collect, episode_files, obs_matrix,   # noqa: E402
                             sigma_coeffs, sigma_model)

PREFIX = "ex_ident_flat_cut_"
# パラメータ → (範囲の幅, {点: 重み（範囲で正規化した差分の係数）}, 線形性の点 (中, 端1, 端2))
#   線形性は d = F(中) − (F(端1) + F(端2))/2（中が2つの端のちょうど中間）
DESIGN = {
    "φ": (25.0, {"phi_p10": 1 / 0.8, "phi_m10": -1 / 0.8}, ("phi_p5", "base", "phi_p10")),
    "c": (30.0, {"c_p1p5": 1 / 0.1, "c_m1p5": -1 / 0.1}, ("base", "c_m1p5", "c_p1p5")),
    "ρ": (700.0, {"rho_p70": 1 / 0.2, "rho_m70": -1 / 0.2}, ("rho_p35", "base", "rho_p70")),
}
# 参考に並べる c の差分（decisions/2026-11-17_cは中心差分±1.5kPaにする.md）
C_REFERENCE = {
    "T7 の2次の片側差分（2.1・3.6・5.1）": {"base": -3 / 0.1, "c_p1p5": 4 / 0.1, "c_p3": -1 / 0.1},
    "片側の傾き (F(5.1) − F(2.1))/3 kPa": {"c_p3": 1 / 0.1, "base": -1 / 0.1},
}
STEP_DEG = {"φ": 20.0, "ρ": 140.0}   # 中心差分の両端の差（元の単位）。傾きの比較用


def main():
    ap = argparse.ArgumentParser(description="同定可能性（力の経路）の解析")
    ap.add_argument("paths", nargs="+", help="collect_data の出力フォルダ（glob 可）")
    ap.add_argument("--pilot", nargs="*", default=[], help="φ の試験の出力フォルダ（±5° との比較）")
    ap.add_argument("--gate6", nargs="*", default=[], help="関門6 の出力フォルダ（phi25/phi50 との比較）")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル")
    a = ap.parse_args()

    out = []
    p = out.append
    eps = collect(episode_files(a.paths, PREFIX))
    pts = {k[len(PREFIX):]: v for k, v in eps.items()}
    nrep = {k: len(v) for k, v in sorted(pts.items())}
    p(f"# 同定可能性（力の経路、flat_cut）の解析\n\n記録：{', '.join(a.paths)}\n\n点ごとの回数：{nrep}\n")
    need = {k for _, w, lin in DESIGN.values() for k in list(w) + list(lin or [])}
    missing = sorted(need - set(pts))
    if missing:
        raise SystemExit(f"記録のない点：{missing}")

    nb = len(BINS)
    d = 2 * nb
    X = {k: obs_matrix(v, BINS) for k, v in pts.items()}
    mean = {k: x.mean(axis=0) for k, x in X.items()}
    co = sigma_coeffs(X["base"], nb)
    S = sigma_model(co["sd"], nb, co["ar"], co["r_xz"])
    Sinv = np.linalg.inv(S)
    # 点ごとの分散の倍率 κ：点の平均からのずれの Mahalanobis の2乗（基準の Σ）の平均 ÷ その期待値 d(n−1)/n
    kappa = {}
    for k, x in X.items():
        r = x - x.mean(axis=0)
        kappa[k] = float(np.mean([v @ Sinv @ v for v in r])) / (d * (len(x) - 1) / len(x)) if len(x) > 1 else math.nan

    # ---- 1. Σ の係数
    p(f"## 1. 基準の雑音（基準 {nrep['base']} 回）\n")
    p("| 項目 | この記録 | φ の試験（基準 10 回） | 関門6 | 比（÷ 関門6） |")
    p("|---|---|---|---|---|")
    pilot_co = None
    if a.pilot:
        pe = collect(episode_files(a.pilot, PREFIX))
        if PREFIX + "base" in pe:
            pilot_co = sigma_coeffs(obs_matrix(pe[PREFIX + "base"], BINS), nb)
    for key, name in (("sd_Fx", "−F_x の区切りの標準偏差 [kN]（二乗平均）"), ("sd_Fz", "−F_z の区切りの標準偏差 [kN]"),
                      ("ar", "AR(1) の係数"), ("r_xz", "F_x・F_z の相関")):
        pv = f"{pilot_co[key]:.3f}" if pilot_co else "—"
        p(f"| {name} | {co[key]:.3f} | {pv} | {GATE6[key]:.2f} | {co[key] / GATE6[key]:.2f} |")
    p(f"\n距離の差ごとの相関（1〜5）：{', '.join(f'{x:.2f}' for x in co['lags'])}\n")
    p("**点ごとの分散の倍率 κ**（基準の Σ に対する比。線形性の χ² と J の水増しの見積もりに見込む。F は基準の Σ で作る）\n")
    p("| 点 | n | κ |")
    p("|---|---|---|")
    for k in sorted(kappa):
        p(f"| {k} | {nrep[k]} | {kappa[k]:.2f} |")
    p("")
    noise_ok = co["sd_Fx"] <= 1.5 * GATE6["sd_Fx"] and co["sd_Fz"] <= 1.5 * GATE6["sd_Fz"]

    # ---- 2. パラメータごとの J
    p("## 2. パラメータごとの J の列（30 成分）\n")
    p("水増し分と χ² は、点ごとの分散の倍率 κ を見込んだ値（J̃ の雑音の倍率 Σ w²κ/n）。\n")
    p("| パラメータ | χ² | p | F（そのまま） | 水増し分 | F（水増しを引いた値） | 水増し ÷ F | 下限 σ/範囲（そのまま） | 下限 σ/範囲（水増しを引いた値） |")
    p("|---|---|---|---|---|---|---|---|---|")
    J, infl, flags = {}, {}, []
    rows_ref = [(f"c 参考：{lab}", w) for lab, w in C_REFERENCE.items() if all(k in mean for k in w)]
    for name, w in [(n, dw[1]) for n, dw in DESIGN.items()] + rows_ref:
        Jv = sum(wt * mean[k] for k, wt in w.items())
        v = sum(wt ** 2 * kappa[k] / nrep[k] for k, wt in w.items())   # J̃ の雑音の倍率（κ を見込む）
        F_raw = float(Jv @ Sinv @ Jv)
        bias = d * v
        F_sig = F_raw - bias
        chi2 = F_raw / v
        pv = float(stats.chi2.sf(chi2, d))
        frac = bias / F_raw
        if name not in DESIGN:      # 参考の行：表に出すだけ（cos は中心差分の J と比べる）
            cos = float(Jv @ Sinv @ J["c"]) / math.sqrt(F_raw * float(J["c"] @ Sinv @ J["c"]))
            p(f"| {name}（中心差分との cos {cos:.2f}、長さの比 {math.sqrt(F_raw / float(J['c'] @ Sinv @ J['c'])):.2f}） | {chi2:.1f} | {pv:.2g} | {F_raw:.1f} | {bias:.1f} | {F_sig:.1f} | {frac:.2f} | "
              f"{1 / math.sqrt(F_raw):.3f} | {(1 / math.sqrt(F_sig)) if F_sig > 0 else math.nan:.3f} |")
            continue
        J[name], infl[name] = Jv, bias
        p(f"| {name} | {chi2:.1f} | {pv:.2g} | {F_raw:.1f} | {bias:.1f} | {F_sig:.1f} | {frac:.2f} | "
          f"{1 / math.sqrt(F_raw):.3f} | {(1 / math.sqrt(F_sig)) if F_sig > 0 else math.nan:.3f} |")
        if name == "c" and (pv >= 0.05 or frac > 0.5):
            # 回数を k 倍にすると水増しは 1/k、信号（水増しを引いた F）は変わらない。
            # 水増し ÷ F ≤ 0.5 ⇔ 水増し/k ≤ 信号 ⇔ k ≥ 水増し ÷ 信号
            k_frac = bias / F_sig if F_sig > 0 else math.inf
            flags.append(f"{name}：p = {pv:.2g}、水増し ÷ F = {frac:.2f}。水増しを 50% 以下にするには、すべての点の回数を約 {k_frac:.1f} 倍"
                         f"（{', '.join(f'{k} {math.ceil(nrep[k] * k_frac)}' for k in w)} 回）")
    p("")

    # ---- 3. 3×3 のフィッシャー情報行列
    names = list(DESIGN)
    Jm = np.column_stack([J[n] for n in names])
    F = Jm.T @ Sinv @ Jm
    F_sig = F - np.diag([infl[n] for n in names])
    p("## 3. φ・c・ρ のフィッシャー情報行列（範囲で正規化、1 エピソードの観測）\n")
    for label, M in (("そのまま", F), ("対角から水増しを引いた値", F_sig)):
        p(f"**{label}**\n")
        p("| | " + " | ".join(names) + " |")
        p("|---|" + "---|" * len(names))
        for i, n in enumerate(names):
            p(f"| {n} | " + " | ".join(f"{M[i, j]:.1f}" for j in range(len(names))) + " |")
        try:
            Minv = np.linalg.inv(M)
            sd = np.sqrt(np.diag(Minv))
            corr = Minv / np.outer(sd, sd)
            ev = np.linalg.eigvalsh(M)
            p("\n| パラメータ | 推定標準偏差の下限 σ/範囲（3つ同時） | 1つだけのとき | 比（同時 ÷ 1つ） |")
            p("|---|---|---|---|")
            for i, n in enumerate(names):
                single = 1 / math.sqrt(M[i, i]) if M[i, i] > 0 else math.nan
                p(f"| {n} | {sd[i]:.3f} | {single:.3f} | {sd[i] / single:.2f} |")
            p(f"\n推定値の相関：φ–c {corr[0, 1]:+.2f}、φ–ρ {corr[0, 2]:+.2f}、c–ρ {corr[1, 2]:+.2f}。"
              f"固有値 {', '.join(f'{x:.2f}' for x in ev)}、条件数 {ev.max() / ev.min():.1f}\n")
        except np.linalg.LinAlgError:
            p("\n逆行列が求まらない（特異）\n")
    # ブートストラップ：点ごとに記録を選び直して J を求め直し、3つ同時の下限のばらつきを見る（Σ は固定）
    rng = np.random.default_rng(0)
    B = 1000
    boot, boot_corr, nonpd = [], [], 0
    for _ in range(B):
        mb = {k: X[k][rng.integers(0, len(X[k]), len(X[k]))].mean(axis=0) for k in X}
        Jb = np.column_stack([sum(wt * mb[k] for k, wt in DESIGN[n][1].items()) for n in names])
        Fb = Jb.T @ Sinv @ Jb
        Fbs = Fb - np.diag([infl[n] for n in names])
        if np.linalg.eigvalsh(Fbs).min() <= 0:
            nonpd += 1
        Mi = np.linalg.inv(Fb)
        sdb = np.sqrt(np.diag(Mi))
        boot.append(sdb)
        boot_corr.append([Mi[0, 1] / sdb[0] / sdb[1], Mi[0, 2] / sdb[0] / sdb[2], Mi[1, 2] / sdb[1] / sdb[2]])
    boot, boot_corr = np.array(boot), np.array(boot_corr)
    p(f"**ブートストラップ**（点ごとに記録を選び直す、{B} 回、Σ は固定。「そのまま」の F で求めた3つ同時の下限）\n")
    p("| パラメータ | 中央値 | 5〜95% |")
    p("|---|---|---|")
    for i, n in enumerate(names):
        q = np.percentile(boot[:, i], [5, 50, 95])
        p(f"| {n} | {q[1]:.3f} | {q[0]:.3f}〜{q[2]:.3f} |")
    qc = np.percentile(boot_corr, [5, 50, 95], axis=0)
    p(f"\n推定値の相関（中央値、5〜95%）：φ–c {qc[1, 0]:+.2f}（{qc[0, 0]:+.2f}〜{qc[2, 0]:+.2f}）、"
      f"φ–ρ {qc[1, 1]:+.2f}（{qc[0, 1]:+.2f}〜{qc[2, 1]:+.2f}）、c–ρ {qc[1, 2]:+.2f}（{qc[0, 2]:+.2f}〜{qc[2, 2]:+.2f}）。"
      f"対角から水増しを引くと正定値でなくなる割合：{nonpd / B:.0%}\n")
    # グラム行列（白色化した J の列を長さ1にしたもの）の条件数
    Lc = np.linalg.cholesky(Sinv)
    W = Lc.T @ Jm
    Wn = W / np.linalg.norm(W, axis=0)
    G = Wn.T @ Wn
    evg = np.linalg.eigvalsh(G)
    p(f"補助：白色化して長さをそろえた J の列のグラム行列の条件数 {evg.max() / evg.min():.1f}"
      f"（列どうしの cos：φ–c {G[0, 1]:+.2f}、φ–ρ {G[0, 2]:+.2f}、c–ρ {G[1, 2]:+.2f}）\n")

    # ---- 4. 線形性
    p("## 4. 線形性（d = F(中) − (F(端1) + F(端2))/2。φ は +5° と 0°・+10°、c は 2.1 と 0.6・3.6、ρ は +35 と 0・+70）\n")
    p("| パラメータ | χ²（30 成分） | p | |d| ÷ |半刻みの変化|（Σ で測る） | Fx_sat の d [kN] | 標準誤差 | Fx_sat の (端2 − 端1)/2 [kN] |")
    p("|---|---|---|---|---|---|---|")
    lin_bad = []
    p("χ² は点ごとの分散の倍率 κ を見込んだ値（d の雑音の倍率 Σ coef²κ/n）。括弧内は κ を見込まない値。\n")
    for name, (_, _, lin) in DESIGN.items():
        if not lin:
            continue
        h, z, f1 = lin
        dl = mean[h] - (mean[z] + mean[f1]) / 2
        vd0 = 1 / nrep[h] + 0.25 / nrep[z] + 0.25 / nrep[f1]
        vd = kappa[h] / nrep[h] + 0.25 * kappa[z] / nrep[z] + 0.25 * kappa[f1] / nrep[f1]
        chi2_0 = float(dl @ Sinv @ dl) / vd0
        chi2 = float(dl @ Sinv @ dl) / vd
        pv = float(stats.chi2.sf(chi2, d))
        half = (mean[f1] - mean[z]) / 2
        ratio = math.sqrt(max(float(dl @ Sinv @ dl), 0)) / math.sqrt(float(half @ Sinv @ half))
        fs = {k: np.array([e["Fx_sat"] for e in pts[k]]) for k in (h, z, f1)}
        dsat = fs[h].mean() - (fs[z].mean() + fs[f1].mean()) / 2
        se = math.sqrt(fs[h].var(ddof=1) / len(fs[h]) + 0.25 * fs[z].var(ddof=1) / len(fs[z]) + 0.25 * fs[f1].var(ddof=1) / len(fs[f1]))
        p(f"| {name}（{h}） | {chi2:.1f}（{chi2_0:.1f}） | {pv:.2g}（{stats.chi2.sf(chi2_0, d):.2g}） | {ratio:.2f} | {dsat:+.2f} | {se:.2f} | {(fs[f1].mean() - fs[z].mean()) / 2:+.2f} |")
        if name in ("φ", "c") and pv < 0.05:
            lin_bad.append(f"{name} の線形性（曲がり）：χ² の p = {pv:.2g} < 0.05")
    p("")

    # ---- 5. Fx_sat（参考）
    p("## 5. 点ごとの Fx_sat（参考。判定には使わない）\n")
    p("| 点 | n | 平均 [kN] | 標準偏差 [kN] |")
    p("|---|---|---|---|")
    for k in sorted(pts):
        v = np.array([e["Fx_sat"] for e in pts[k]])
        p(f"| {k} | {len(v)} | {v.mean():.2f} | {v.std(ddof=1):.2f} |")
    p("")

    # ---- 6. φ の比較
    p("## 6. 参考：φ の J の比較（30 成分の傾き、kN/° 単位のベクトル）\n")
    s10 = (mean["phi_p10"] - mean["phi_m10"]) / STEP_DEG["φ"]

    def cmp(sv, label):
        cos = float(sv @ s10 / np.linalg.norm(sv) / np.linalg.norm(s10))
        p(f"- {label}：長さの比（±10° ÷ {label}）{np.linalg.norm(s10) / np.linalg.norm(sv):.2f}、向きの一致（cos）{cos:.2f}")
    if a.pilot:
        pe = collect(episode_files(a.pilot, PREFIX))
        if PREFIX + "phi_p5" in pe and PREFIX + "phi_m5" in pe:
            cmp((obs_matrix(pe[PREFIX + "phi_p5"], BINS).mean(0) - obs_matrix(pe[PREFIX + "phi_m5"], BINS).mean(0)) / 10.0,
                "φ の試験の ±5°")
    if a.gate6:
        g = collect(episode_files(a.gate6, "val_sens_"))
        if "val_sens_phi25" in g and "val_sens_phi50" in g:
            cmp((obs_matrix(g["val_sens_phi50"], BINS).mean(0) - obs_matrix(g["val_sens_phi25"], BINS).mean(0)) / 25.0,
                "関門6 の phi25・phi50")
            f25 = np.array([e["Fx_sat"] for e in g["val_sens_phi25"]])
            f50 = np.array([e["Fx_sat"] for e in g["val_sens_phi50"]])
            fs10 = (np.mean([e["Fx_sat"] for e in pts["phi_p10"]]) - np.mean([e["Fx_sat"] for e in pts["phi_m10"]])) / 20
            p(f"- Fx_sat の傾き：±10° {fs10:.3f} kN/°、関門6（25° の差）{(f50.mean() - f25.mean()) / 25:.3f} kN/°")
    p("")

    # ---- 7. 判定
    p("## 7. 止める条件の判定\n")
    p(f"- 基準の区切りの雑音が関門6 の 1.5 倍以内：{'はい' if noise_ok else 'いいえ（止める）'}"
      f"（−F_x {co['sd_Fx'] / GATE6['sd_Fx']:.2f} 倍、−F_z {co['sd_Fz'] / GATE6['sd_Fz']:.2f} 倍）")
    p(f"- c で χ² の p ≥ 0.05 または水増し > 50%：{'いいえ' if not flags else 'はい（止める）'}")
    for f in flags:
        p(f"  - {f}")
    p(f"- φ・c の曲がりの χ² が p < 0.05（κ を見込む）：{'いいえ' if not lin_bad else 'はい（止める）'}")
    for f in lin_bad:
        p(f"  - {f}")
    if "c_m1p5" in kappa:
        p(f"- c_m1p5 の分散の倍率 κ が 2 倍を超える：{'はい（止める）' if kappa['c_m1p5'] > 2 else 'いいえ'}（κ = {kappa['c_m1p5']:.2f}）")

    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
