"""
フェーズ1：φ だけの小さな試験（ex_ident_flat_cut_*）の解析。刻み ±5° と回数が足りるか、
合計の力（−F_x・−F_z）に貫入抵抗の段差の影響が残るかを確かめる。

置き場所: analysis/phase1/check_pilot_phi.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_pilot_phi.py data/phase1/pilot_phi/run_*_pilot_phi \
      [--gate6 data/validation/gate6/run_*] [--report 結果.md] [--csv 区切りの値.csv]

観測ベクトル（notes の decisions/2026-11-17_貫入抵抗は観測から外す.md）
  30 成分（主）：距離 0.625 m ごとの −F_x・−F_z の平均（区切り 1〜15、距離 0.625〜10 m）
  20 成分（参考）：段差より前の区切りだけ（基準の記録で、刃先 edge_x の最大が −0.3 m 未満の区切り）
  −F_pen_x は観測に入れない（段差の確認にだけ使う）

雑音の共分散 Σ（decisions/2026-11-17_観測の雑音の共分散と貫入抵抗の段差.md）
  Σ = D^½ (R_FxFz ⊗ R_AR) D^½。D は基準の繰り返しから求めた区切りごとの分散、
  R_AR は AR(1)（係数 a）、R_FxFz は同じ区切りの F_x・F_z の相関 r。

φ の判定（decisions/2026-11-17_同定可能性の判定基準.md）
  パラメータは範囲の幅（φ は 25°）で正規化する。J̃ = (F(φ+5) − F(φ−5)) / (10°/25°)。
  推定標準偏差の下限（範囲比）= 1 / √(J̃ᵀ Σ⁻¹ J̃)（1エピソードの観測）。
  J は n 回ずつの平均の差で求めるので、雑音で J̃ᵀΣ⁻¹J̃ が水増しされる（期待値で 2d/n/h̃²、d は成分の数）。
  χ² = n/2 · Δᵀ Σ⁻¹ Δ は、φ の効果がなければ自由度 d の χ² に従う。水増しを引いた信号から、
  χ² 検定の検出力と、J の向きへ射影したときの t（t ≥ 3 に必要な n）を、n = 10・15・20 で並べる。
"""
import argparse
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "validation"))
from check_physics import BIN, settled_cut_rows   # noqa: E402

PHI_RANGE = 25.0                 # φ の想定範囲の幅 [deg]
BINS = list(range(1, 16))        # 区切り 1〜15（距離 0.625〜10 m）
STEP_EDGE = -0.3                 # これより前（刃先 edge_x が小さい）の区切りを「段差の前」とする
PRE_WIN, POST_WIN = (-0.6, -0.32), (-0.2, 0.08)   # 段差の前後の窓（刃先 edge_x、T2 と同じ）
V_SAT = 2.0                      # Fx_sat の下限の体積 [m³]（関門6 と同じ）
GATE6 = {"sd_Fx": 2.47, "sd_Fz": 0.67, "ar": 0.25, "r_xz": 0.40}   # 関門6 の値（notes の reports/2026-11-17_同定可能性の解析の準備.md）


# ---------------------------------------------------------------- 読み込み
def episode_files(paths, prefix):
    out = []
    for p in paths:
        for d in sorted(glob.glob(p)):
            with open(os.path.join(d, "episodes.jsonl"), encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line) if line.strip() else None
                    if r and str(r.get("status")) == "ok" and r["episode_name"].startswith(prefix):
                        out.append((r["episode_name"], os.path.join(d, r["file"])))
    return out


def episode_summary(path):
    """区切りごとの −F_x・−F_z・−F_pen_x [kN] と刃先の位置、段差の前後の差、Fx_sat"""
    rows = settled_cut_rows(pd.read_csv(path))
    if rows is None:
        return None
    k = np.floor(rows["distance"] / BIN).astype(int)
    b = rows.assign(k=k).groupby("k").agg(
        Fx=("F_total_x", lambda s: -s.mean() / 1e3), Fz=("F_total_z", lambda s: -s.mean() / 1e3),
        Fpen=("F_pen_x", lambda s: -s.mean() / 1e3), V=("cut_volume", "mean"),
        ex_max=("edge_x", "max"))
    b = b.reindex(BINS)
    ex = rows["edge_x"]
    pre, post = rows[(ex > PRE_WIN[0]) & (ex < PRE_WIN[1])], rows[(ex > POST_WIN[0]) & (ex < POST_WIN[1])]
    step = {c: (-post[col].mean() + pre[col].mean()) / 1e3
            for c, col in (("Fx", "F_total_x"), ("Fz", "F_total_z"), ("Fpen", "F_pen_x"))}
    sat = b[b["V"] > V_SAT]
    return {"bins": b, "step": step, "Fx_sat": float(sat["Fx"].mean()) if len(sat) else math.nan,
            "phi": float(rows["label_phi"].iloc[0])}


def collect(files):
    eps = {}
    for name, path in files:
        s = episode_summary(path)
        if s is not None:
            eps.setdefault(name, []).append(s)
    return eps


def obs_matrix(eps, bins):
    """エピソード × 成分（−F_x の区切り, −F_z の区切り）"""
    return np.array([np.r_[e["bins"].loc[bins, "Fx"].to_numpy(), e["bins"].loc[bins, "Fz"].to_numpy()] for e in eps])


# ---------------------------------------------------------------- Σ
def lag_corr(res, nb, lag):
    """同じ成分の、区切りの差 lag の相関（成分と区切りの組で平均）"""
    out = []
    for c in range(2):
        for i in range(nb - lag):
            a, b = res[:, c * nb + i], res[:, c * nb + i + lag]
            if np.std(a) > 0 and np.std(b) > 0:
                out.append(np.corrcoef(a, b)[0, 1])
    return float(np.mean(out)) if out else math.nan


def sigma_coeffs(X, nb):
    res = X - X.mean(axis=0)
    sd = res.std(axis=0, ddof=1)
    lags = [lag_corr(res, nb, L) for L in range(1, 6)]
    rxz = float(np.mean([np.corrcoef(res[:, i], res[:, nb + i])[0, 1] for i in range(nb)]))
    return {"sd": sd, "sd_Fx": float(np.sqrt(np.mean(sd[:nb] ** 2))), "sd_Fz": float(np.sqrt(np.mean(sd[nb:] ** 2))),
            "lags": lags, "ar": max(lags[0], 0.0), "r_xz": rxz}


def sigma_model(sd, nb, ar, rxz):
    idx = np.arange(nb)
    R_ar = ar ** np.abs(idx[:, None] - idx[None, :])
    R = np.kron(np.array([[1.0, rxz], [rxz, 1.0]]), R_ar)
    return np.outer(sd, sd) * R


# ---------------------------------------------------------------- 本体
def fisher_table(mean, nrep, Sinv, d, h_norm, label):
    """φ の中心差分。mean は点ごとの平均の観測ベクトル、nrep は点ごとの回数。
    Δ = F(+5°) − F(−5°)。雑音だけでも n/2·ΔᵀΣ⁻¹Δ は自由度 d の χ² に従う（期待値 d）ので、
    ΔᵀΣ⁻¹Δ から雑音の分 2d/n を引いた値を「信号」とみなす。"""
    from scipy import stats
    n_used = min(nrep["phi_p5"], nrep["phi_m5"])
    delta = mean["phi_p5"] - mean["phi_m5"]
    m2 = float(delta @ Sinv @ delta)            # Δᵀ Σ⁻¹ Δ（雑音で水増しされた値）
    m2_sig = m2 - 2.0 * d / n_used              # 雑音の分を引いた値
    chi2 = n_used / 2.0 * m2
    pval = float(stats.chi2.sf(chi2, d))
    crit = float(stats.chi2.ppf(0.95, d))
    rows = []
    for n in (10, 15, 20):
        lam = n / 2.0 * max(m2_sig, 0.0)        # 非心度（信号の分）
        power = float(stats.ncx2.sf(crit, d, lam)) if lam > 0 else 0.05
        rows.append({"観測": label, "n": n, "期待される χ²": d + lam, "χ² 検定の検出力": power,
                     "射影の t": math.sqrt(lam)})
    F_raw, F_sig = m2 / h_norm ** 2, m2_sig / h_norm ** 2
    summary = {"観測": label, "成分の数": d, "χ²": chi2, "p": pval,
               "F（そのまま）": F_raw, "F（雑音の分を引いた値）": F_sig,
               "下限 σ/範囲（そのまま）": 1 / math.sqrt(F_raw) if F_raw > 0 else math.nan,
               "下限 σ/範囲（雑音の分を引いた値）": 1 / math.sqrt(F_sig) if F_sig > 0 else math.nan,
               "射影の t ≥ 3 に必要な n": math.ceil(18.0 / m2_sig) if m2_sig > 0 else math.inf}
    return summary, rows


def main():
    ap = argparse.ArgumentParser(description="φ だけの小さな試験の解析")
    ap.add_argument("paths", nargs="+", help="collect_data の出力フォルダ（glob 可）")
    ap.add_argument("--gate6", nargs="*", default=[], help="関門6 の出力フォルダ（phi25/phi50 との比較）")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル")
    ap.add_argument("--csv", help="点ごとの区切りの平均を保存する CSV")
    a = ap.parse_args()

    out = []
    p = out.append
    eps = collect(episode_files(a.paths, "ex_ident_flat_cut_"))
    pts = {k.replace("ex_ident_flat_cut_", ""): v for k, v in eps.items()}
    nrep = {k: len(v) for k, v in pts.items()}
    p(f"# φ の試験の解析\n\n記録：{', '.join(a.paths)}\n\n点ごとの回数：{nrep}\n")
    for need in ("base", "phi_m5", "phi_p5", "phi_p2p5"):
        if need not in pts:
            raise SystemExit(f"点 {need} の記録がありません")

    # 段差の前の区切り（基準の記録で、刃先の最大が STEP_EDGE 未満）
    ex_max = np.nanmax(np.array([e["bins"]["ex_max"].to_numpy() for e in pts["base"]]), axis=0)
    pre_bins = [b for b, x in zip(BINS, ex_max) if x < STEP_EDGE]
    p(f"段差の前の区切り（20 成分の場合）：{pre_bins}（区切りの刃先の最大 edge_x：" +
      ", ".join(f"{b}:{x:.2f}" for b, x in zip(BINS, ex_max)) + "）\n")

    results = {}
    for label, bins in (("30 成分", BINS), (f"{2 * len(pre_bins)} 成分（段差の前）", pre_bins)):
        nb = len(bins)
        X = {k: obs_matrix(v, bins) for k, v in pts.items()}
        if any(np.isnan(x).any() for x in X.values()):
            raise SystemExit(f"{label}：区切りに欠けがあります")
        co = sigma_coeffs(X["base"], nb)
        S = sigma_model(co["sd"], nb, co["ar"], co["r_xz"])
        Sinv = np.linalg.inv(S)
        mean = {k: x.mean(axis=0) for k, x in X.items()}
        summ, rows = fisher_table(mean, nrep, Sinv, 2 * nb, 10.0 / PHI_RANGE, label)
        # 線形性 d = F(+2.5) − (F(0) + F(+5))/2
        dlin = mean["phi_p2p5"] - (mean["base"] + mean["phi_p5"]) / 2
        Sd = S * (1 / nrep["phi_p2p5"] + 0.25 / nrep["base"] + 0.25 / nrep["phi_p5"])
        chi2 = float(dlin @ np.linalg.inv(Sd) @ dlin)
        half = (mean["phi_p5"] - mean["base"]) / 2
        Shalf = S * (0.25 / nrep["base"] + 0.25 / nrep["phi_p5"])
        results[label] = dict(co=co, summ=summ, rows=rows, chi2=chi2, d=2 * nb,
                              lin_ratio=float(math.sqrt(max(dlin @ np.linalg.inv(Shalf) @ dlin, 0)) /
                                              math.sqrt(max(half @ np.linalg.inv(Shalf) @ half, 1e-12))))

    # ---- Σ の係数
    p("## 1. 基準の雑音（Σ の係数）\n")
    p("| 項目 | この試験（基準 %d 回） | 関門6 | 比 |" % nrep["base"])
    p("|---|---|---|---|")
    co = results["30 成分"]["co"]
    for key, name in (("sd_Fx", "−F_x の区切りの標準偏差 [kN]（二乗平均）"), ("sd_Fz", "−F_z の区切りの標準偏差 [kN]"),
                      ("ar", "AR(1) の係数（隣の区切りの相関）"), ("r_xz", "同じ区切りの F_x・F_z の相関")):
        p(f"| {name} | {co[key]:.3f} | {GATE6[key]:.2f} | {co[key] / GATE6[key]:.2f} |")
    p(f"\n距離の差ごとの相関（1〜5）：{', '.join(f'{x:.2f}' for x in co['lags'])}\n")

    # ---- Fx_sat
    p("## 2. Fx_sat（V > 2.0 m³ の −F_x の平均）\n")
    p("| 点 | φ [°] | n | 平均 [kN] | 標準偏差 [kN] |")
    p("|---|---|---|---|---|")
    fs = {}
    for k in ("phi_m5", "base", "phi_p2p5", "phi_p5"):
        v = np.array([e["Fx_sat"] for e in pts[k]])
        fs[k] = v
        p(f"| {k} | {pts[k][0]['phi']:.2f} | {len(v)} | {v.mean():.2f} | {v.std(ddof=1):.2f} |")
    d_sat = fs["phi_p5"].mean() - fs["phi_m5"].mean()
    se = math.sqrt(fs["phi_p5"].var(ddof=1) / len(fs["phi_p5"]) + fs["phi_m5"].var(ddof=1) / len(fs["phi_m5"]))
    sig = fs["base"].std(ddof=1)
    p(f"\nΔ = Fx_sat(+5°) − Fx_sat(−5°) = {d_sat:.2f} kN（標準誤差 {se:.2f}、Δ/SE = {d_sat / se:.1f}）。"
      f"傾き {d_sat / 10:.3f} kN/°。")
    p(f"Δ/SE ≥ 3 に必要な回数（基準の σ = {sig:.2f} kN、n ≥ 2(3σ/Δ)²）：両側それぞれ {math.ceil(2 * (3 * sig / d_sat) ** 2)} 回\n")
    lin_sat = fs["phi_p2p5"].mean() - (fs["base"].mean() + fs["phi_p5"].mean()) / 2
    se_lin = math.sqrt(fs["phi_p2p5"].var(ddof=1) / len(fs["phi_p2p5"]) + 0.25 * fs["base"].var(ddof=1) / len(fs["base"]) +
                       0.25 * fs["phi_p5"].var(ddof=1) / len(fs["phi_p5"]))
    p(f"線形性（Fx_sat）：d = F(+2.5°) − (F(0) + F(+5°))/2 = {lin_sat:+.2f} kN（標準誤差 {se_lin:.2f}）。"
      f"半刻みの変化 (F(+5°) − F(0))/2 = {(fs['phi_p5'].mean() - fs['base'].mean()) / 2:+.2f} kN\n")

    # ---- フィッシャー情報
    p("## 3. φ だけのフィッシャー情報（観測ベクトル）\n")
    p("Δ = F(+5°) − F(−5°)。χ² = n/2·ΔᵀΣ⁻¹Δ は、φ の効果がなければ自由度 = 成分の数の χ² に従う（期待値 = 成分の数）。"
      "「雑音の分を引いた値」は ΔᵀΣ⁻¹Δ から 2d/n を引いたもの。射影の t は、J の向きが分かっているときの t（スカラーの Δ/SE に当たる）。\n")
    p("| 観測 | 成分の数 | χ²（n=10） | p | F（そのまま） | F（雑音の分を引いた値） | 下限 σ/範囲（そのまま） | 下限 σ/範囲（雑音の分を引いた値） | 射影の t ≥ 3 に必要な n |")
    p("|---|---|---|---|---|---|---|---|---|")
    for r in results.values():
        s = r["summ"]
        p(f"| {s['観測']} | {s['成分の数']} | {s['χ²']:.1f} | {s['p']:.3f} | {s['F（そのまま）']:.1f} | {s['F（雑音の分を引いた値）']:.1f} | "
          f"{s['下限 σ/範囲（そのまま）']:.3f} | {s['下限 σ/範囲（雑音の分を引いた値）']:.3f} | {s['射影の t ≥ 3 に必要な n']} |")
    p("\n| 観測 | n（両側それぞれ） | 期待される χ² | χ² 検定（5%）の検出力 | 射影の t |")
    p("|---|---|---|---|---|")
    for r in results.values():
        for row in r["rows"]:
            p(f"| {row['観測']} | {row['n']} | {row['期待される χ²']:.1f} | {row['χ² 検定の検出力']:.2f} | {row['射影の t']:.1f} |")
    p("\n線形性（観測ベクトル）：d = F(+2.5°) − (F(0) + F(+5°))/2 の χ²（自由度 = 成分の数）と、"
      "半刻みの変化に対する大きさの比（Σ で測った長さの比）")
    for label, r in results.items():
        p(f"- {label}：χ² = {r['chi2']:.1f}（自由度 {r['d']}）、|d| ÷ |半刻みの変化| = {r['lin_ratio']:.2f}")
    p("")

    # ---- 関門6 との比較
    if a.gate6:
        g = collect(episode_files(a.gate6, "val_sens_"))
        p("## 4. 関門6 の phi25・phi50 との比較\n")
        if "val_sens_phi25" in g and "val_sens_phi50" in g:
            f25 = np.array([e["Fx_sat"] for e in g["val_sens_phi25"]])
            f50 = np.array([e["Fx_sat"] for e in g["val_sens_phi50"]])
            Xg = {k: obs_matrix(g[k], BINS).mean(axis=0) for k in ("val_sens_phi25", "val_sens_phi50")}
            Xp = {k: obs_matrix(pts[k], BINS).mean(axis=0) for k in ("phi_m5", "phi_p5")}
            sg, sp = (Xg["val_sens_phi50"] - Xg["val_sens_phi25"]) / 25, (Xp["phi_p5"] - Xp["phi_m5"]) / 10
            cos = float(sg @ sp / np.linalg.norm(sg) / np.linalg.norm(sp))
            p(f"- Fx_sat の傾き：関門6（phi25 {len(f25)} 回・phi50 {len(f50)} 回、25° の差）{(f50.mean() - f25.mean()) / 25:.3f} kN/°、"
              f"この試験（±5°）{d_sat / 10:.3f} kN/°")
            p(f"- 30 成分の傾きのベクトル：長さの比（この試験 ÷ 関門6）{np.linalg.norm(sp) / np.linalg.norm(sg):.2f}、"
              f"向きの一致（cos）{cos:.2f}\n")

    # ---- 段差
    p("## 5. 段差の確認（刃先 −0.6〜−0.32 m と −0.2〜+0.08 m の差、後 − 前）\n")
    sdb = results["30 成分"]["co"]
    p(f"区切りの雑音（基準、二乗平均）：−F_x {sdb['sd_Fx']:.2f} kN、−F_z {sdb['sd_Fz']:.2f} kN\n")
    p("| 点 | n | −F_pen_x [kN] | −F_x [kN] | −F_x ÷ 雑音 | −F_z [kN] | −F_z ÷ 雑音 |")
    p("|---|---|---|---|---|---|---|")
    allst = {}
    for k in ("phi_m5", "base", "phi_p2p5", "phi_p5"):
        st = pd.DataFrame([e["step"] for e in pts[k]])
        allst[k] = st
        m, s = st.mean(), st.std(ddof=1) / math.sqrt(len(st))
        p(f"| {k} | {len(st)} | {m.Fpen:+.2f}（±{s.Fpen:.2f}） | {m.Fx:+.2f}（±{s.Fx:.2f}） | {m.Fx / sdb['sd_Fx']:+.2f} | "
          f"{m.Fz:+.2f}（±{s.Fz:.2f}） | {m.Fz / sdb['sd_Fz']:+.2f} |")
    st_all = pd.concat(allst.values())
    m, s = st_all.mean(), st_all.std(ddof=1) / math.sqrt(len(st_all))
    p(f"| すべて | {len(st_all)} | {m.Fpen:+.2f}（±{s.Fpen:.2f}） | {m.Fx:+.2f}（±{s.Fx:.2f}） | {m.Fx / sdb['sd_Fx']:+.2f} | "
      f"{m.Fz:+.2f}（±{s.Fz:.2f}） | {m.Fz / sdb['sd_Fz']:+.2f} |")
    # φ で大きさが変わるか（1元配置の F 検定）
    for comp in ("Fpen", "Fx", "Fz"):
        groups = [allst[k][comp].to_numpy() for k in allst]
        grand = np.concatenate(groups)
        ssb = sum(len(x) * (x.mean() - grand.mean()) ** 2 for x in groups)
        ssw = sum(((x - x.mean()) ** 2).sum() for x in groups)
        dfb, dfw = len(groups) - 1, len(grand) - len(groups)
        Fst = (ssb / dfb) / (ssw / dfw) if ssw > 0 else math.nan
        p(f"- {comp}：φ の4点で段差の大きさが違うか（1元配置の F = {Fst:.2f}、自由度 {dfb}・{dfw}。F > 2.9 で 5% 有意の目安）")
    p("")

    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    if a.csv:
        recs = []
        for k, v in pts.items():
            for i, e in enumerate(v):
                for b in BINS:
                    r = e["bins"].loc[b]
                    recs.append({"point": k, "rep": i, "phi": e["phi"], "bin": b, "Fx_kN": r.Fx, "Fz_kN": r.Fz,
                                 "Fpen_kN": r.Fpen, "V": r.V, "edge_x_max": r.ex_max})
        pd.DataFrame(recs).to_csv(a.csv, index=False)


if __name__ == "__main__":
    main()
