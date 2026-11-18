"""
フェーズ1：締固めの列の J（案A）の準備（T33）。

notes decisions/2026-11-18_締固めの列のJは締固めを動かす取り直しで作る.md、handoff の T33。

使い方（コンテナの中、ワークスペース直下）:
  python3 analysis/phase1/check_compaction_j.py --parts B S            # 既存の記録だけ（T31 の 105 本）
  python3 analysis/phase1/check_compaction_j.py --parts B S T --report data/phase1/compaction_j/report.md

部分:
  B. s と K3 の連動（T31 の記録）：作業ごとに、エピソードごとの K3 の中央値（履帯が踏む時点、履帯の位置のマス）を
     s の点（1.10・1.22・1.28・1.34・1.40）で並べ、(i) 直線の傾き × 0.06、(ii) ±0.06 の点の差の半分 を ΔK3 とし、
     範囲比（÷ 0.30）で出す。
  S. 追加の沈下（T31 の記録）：phase0 と同じ定義（履帯が踏んだ後の高さ − 踏む直前の高さ。下がると負。S は正にした値）。
     削った地面のマス（削った厚さ > --min-cut-mm）だけを使い、記録・履帯ごとに 1 m 区間で平均してから、
     エピソードの観測は区間の平均の平均とする。点ごとの平均・標準偏差と、基準との差（範囲の幅で正規化した J̃ の目安）。
  T. 試し（data/phase1/compaction_j/run_*）：締固めを 0.94・1.06 に設定した点と基準。
     設定した程度と K3（実測）の関係、追加の沈下、地形の経路の3成分の Δ観測と信号 ÷ 標準偏差、要る回数、水増し、
     白色化した J の列の cos（Σ と φ・c・ρ・s の J は T27 の flat_cut の地形の経路の記録から）。
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
import check_compaction_candidates as ccc   # noqa: E402
import check_ident_terrain as cit           # noqa: E402
from check_ident import DESIGN, set_s_step  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
D1 = os.path.join(ROOT, "data", "phase1")
CELLS_T31 = os.path.join(D1, "compaction_track", "track_cells_t31.csv")
TRIAL = os.path.join(D1, "compaction_j")
TERRAIN_FC = [os.path.join(D1, "vis_net", "run_*"), os.path.join(D1, "terrain_flat_cut", "run_*")]
TASKS = ["flat_cut", "flat_piecewise", "pile_push"]
S_POINTS = {"s110": 1.10, "s_m0p06": 1.22, "base": 1.28, "s_p0p06": 1.34, "s140": 1.40}
RANGE_K = 0.30          # 締固めの範囲 0.90〜1.20 の幅
STEP_K = 0.06
OBS = cit.OBS

OUT = []


def p(s=""):
    OUT.append(s)


# ---------------------------------------------------------------- 共通
def episode_table(cells, min_cut_mm, seg=1.0):
    """マスの表 → エピソードごとの K3 の中央値・平均と追加の沈下 S（削った地面、1 m 区間の平均の平均）"""
    rows = []
    for ep, h in cells.groupby("ep"):
        cut = h[h.cut_mm > min_cut_mm]
        segS = (-cut.extra_mm).groupby([cut.group, np.floor(cut.x / seg)]).mean()
        rows.append({"ep": ep, "task": h.task.iloc[0], "point": h.point.iloc[0], "s": h.s.iloc[0],
                     "n_cells": len(h), "n_cut": len(cut), "n_seg": len(segS),
                     "K3_med": float(h.K3.median()), "K3_cut_mean": float(cut.K3.mean()),
                     "S": float(segS.mean()), "S_seg_sd": float(segS.std(ddof=1)) if len(segS) > 1 else math.nan,
                     "x_min": float(cut.x.min()) if len(cut) else math.nan, "x_max": float(cut.x.max()) if len(cut) else math.nan})
    return pd.DataFrame(rows)


def mse(v):
    v = np.asarray(v, float)
    return v.mean(), (v.std(ddof=1) / math.sqrt(len(v)) if len(v) > 1 else math.nan)


# ---------------------------------------------------------------- B
def part_b(E):
    p("## B. s と K3 の連動（T31 の記録、エピソードごとの K3 の中央値）\n")
    p("ΔK3 は s の刻み 0.06 あたり。(i) は 5 点の直線の傾き × 0.06、(ii) は ±0.06 の点の差の半分 (K3(1.34) − K3(1.22))/2。"
      "範囲比は ΔK3 ÷ 0.30（締固めの範囲の幅）。± は標準誤差。\n")
    p("| 作業 | 傾き dK3/ds [/s] | (i) ΔK3（傾き × 0.06） | (i) 範囲比 | (ii) ΔK3（±0.06 の点） | (ii) 範囲比 | 基準の K3 の中央値 |")
    p("|---|---|---|---|---|---|---|")
    res = {}
    for t in TASKS:
        e = E[(E.task == t) & E.point.isin(S_POINTS)]
        x = e.point.map(S_POINTS).to_numpy()
        y = e.K3_med.to_numpy()
        lr = stats.linregress(x, y)
        a, sa = lr.slope * STEP_K, lr.stderr * STEP_K
        mp, sp = mse(e[e.point == "s_p0p06"].K3_med)
        mm, sm = mse(e[e.point == "s_m0p06"].K3_med)
        b, sb = (mp - mm) / 2, math.hypot(sp, sm) / 2
        base = e[e.point == "base"].K3_med.mean()
        res[t] = (a, b)
        p(f"| {t} | {lr.slope:+.3f} ± {lr.stderr:.3f} | {a:+.4f} ± {sa:.4f} | {a / RANGE_K:+.3f} | {b:+.4f} ± {sb:.4f} | "
          f"{b / RANGE_K:+.3f} | {base:.4f} |")
    p("")
    return res


# ---------------------------------------------------------------- S
def part_s(E, min_cut_mm):
    p("## S. 追加の沈下（T31 の記録）\n")
    p(f"削った地面のマス（削った厚さ > {min_cut_mm:g} mm）。S は沈下（下がると正）[mm]。エピソードの観測は、履帯ごとの 1 m 区間の平均の平均。\n")
    p("### S1. 使えたマスと区間（作業ごと、基準）\n")
    p("| 作業 | マス／エピソード（全体） | 削った地面のマス | 1 m 区間 | 記録の座標 x の範囲 [m] |")
    p("|---|---|---|---|---|")
    for t in TASKS:
        e = E[(E.task == t) & (E.point == "base")]
        p(f"| {t} | {e.n_cells.mean():.0f} | {e.n_cut.mean():.0f} | {e.n_seg.mean():.1f} | {e.x_min.min():.2f}〜{e.x_max.max():.2f} |")
    p("\n### S2. 点ごとの S（エピソードの平均 ± 標準偏差、本数）と、基準との差から求めた J̃ の目安\n")
    p("J̃ は範囲の幅あたり [mm]（φ 25°・c 30 kPa・ρ 700・s 0.30）。中心差分（±の点）。t は差 ÷ 標準誤差。\n")
    p("| 作業 | 基準 | φ −10° / +10° | J̃_φ（t） | c −1.5 / +1.5 | J̃_c（t） | ρ −70 / +70 | J̃_ρ（t） | s 1.22 / 1.34 | J̃_s（t） | s 1.10 / 1.40 |")
    p("|---|---|---|---|---|---|---|---|---|---|---|")
    pairs = {"φ": ("phi_m10", "phi_p10"), "c": ("c_m1p5", "c_p1p5"), "ρ": ("rho_m70", "rho_p70"), "s": ("s_m0p06", "s_p0p06")}
    out = {}
    for t in TASKS:
        g = {k: v.S.to_numpy() for k, v in E[E.task == t].groupby("point")}
        cells = [f"{g['base'].mean():.1f} ± {g['base'].std(ddof=1):.1f}（{len(g['base'])}）"]
        for n, (lo, hi) in pairs.items():
            w = DESIGN[n][1]
            whi = abs(list(w.values())[0])
            d = g[hi].mean() - g[lo].mean()
            se = math.sqrt(g[hi].var(ddof=1) / len(g[hi]) + g[lo].var(ddof=1) / len(g[lo]))
            J = d * whi
            out[(t, n)] = J
            cells.append(f"{g[lo].mean():.1f} / {g[hi].mean():.1f}")
            cells.append(f"{J:+.1f}（{d / se:+.1f}）")
        cells.append(f"{g['s110'].mean():.1f} / {g['s140'].mean():.1f}")
        p(f"| {t} | " + " | ".join(cells) + " |")
    p("\nS3. 参考：基準の K3（エピソードの中央値の平均）と、phase0 の較正曲線（1 m 区間）で同じ K3 に当たる S。\n")
    curve = pd.read_csv(os.path.join(ROOT, "data", "phase0", "analysis", "calibration", "curve.csv"))
    cv = curve[curve.seg_m == 1.0].sort_values("c")
    p("| 作業 | 基準の K3（削った地面のマスの平均） | 基準の S [mm] | 較正曲線の S（同じ K3）[mm] |")
    p("|---|---|---|---|")
    for t in TASKS:
        e = E[(E.task == t) & (E.point == "base")]
        k = e.K3_cut_mean.mean()
        p(f"| {t} | {k:.4f} | {e.S.mean():.1f} | {np.interp(k, cv.c, cv.S_mm):.1f} |")
    p("\n較正曲線（1 m 区間）の K3 と S [mm]：" + "、".join(f"{c:.3f}→{s:.1f}" for c, s in zip(cv.c, cv.S_mm)) + "\n")
    return out


# ---------------------------------------------------------------- T
def trial_episodes():
    eps, cells = [], []
    for rd in sorted(glob.glob(os.path.join(TRIAL, "run_*"))):
        ok = ccc.ok_files(rd)
        meta = {}
        with open(os.path.join(rd, "episodes.jsonl"), encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                meta[r.get("file")] = r
        for fn in sorted(ok):
            f = os.path.join(rd, fn)
            name = meta[fn]["episode_name"]
            pt = name[len("ex_ident_flat_cut_"):]
            df = pd.read_csv(f)
            last = df.iloc[-1]
            tc = ccc.track_cells(f[:-4] + "_compaction.csv")
            ep = os.path.relpath(f, D1)
            for c in tc:
                c.update(task="flat_cut", point=pt, ep=ep, s=1.28)
            cells += tc
            eps.append({"ep": ep, "point": pt, "set": meta[fn].get("param_compaction", 1.0),
                        "dev95": ccc.dev95(df), **{o: float(last[o]) for o in OBS},
                        "cut_volume": float(last["cut_volume"])})
    return pd.DataFrame(eps), pd.DataFrame(cells)


def part_t(min_cut_mm, boot):
    p("## T. 試し（flat_cut、初期の地面の締固めの程度を設定）\n")
    TE, TC = trial_episodes()
    if TE.empty:
        p("試しの記録がない。\n")
        return
    ET = episode_table(TC, min_cut_mm)
    T = TE.merge(ET[["ep", "K3_med", "K3_cut_mean", "S", "n_cut"]], on="ep")
    p("### T1. 設定した程度と、履帯が踏む時点の K3（実測）\n")
    p("| 点 | 設定 | 本数 | K3 の中央値（エピソードの平均 ± 標準偏差） | K3 の平均（削った地面） | ΔK3（基準との差）| S [mm] | 深さのずれ 95% [cm] |")
    p("|---|---|---|---|---|---|---|---|")
    order = ["k_m0p06", "base", "k_p0p06"]
    g = {k: T[T.point == k] for k in order if (T.point == k).any()}
    b = g["base"].K3_cut_mean.mean()
    for k, h in g.items():
        p(f"| {k} | {h.set.iloc[0]:.2f} | {len(h)} | {h.K3_med.mean():.4f} ± {h.K3_med.std(ddof=1):.4f} | "
          f"{h.K3_cut_mean.mean():.4f} ± {h.K3_cut_mean.std(ddof=1):.4f} | {h.K3_cut_mean.mean() - b:+.4f} | "
          f"{h.S.mean():.1f} ± {h.S.std(ddof=1):.1f} | {h.dev95.max() * 100:.2f} |")
    if not ("k_m0p06" in g and "k_p0p06" in g):
        p("\n±の両方の点がそろっていないので、ここで止める。\n")
        return
    dK = g["k_p0p06"].K3_cut_mean.mean() - g["k_m0p06"].K3_cut_mean.mean()
    p(f"\nΔK3（+0.06 の点 − −0.06 の点、削った地面のマスの平均）= {dK:+.4f}（設定の差 0.12）。"
      f"J は Δ観測 ÷ ΔK3 × 0.30（範囲の幅あたり）とする。\n")

    # ---- 地形の経路の3成分
    set_s_step(0.06)
    X, devs, aux = cit.load_episodes(TERRAIN_FC)
    for k in ("k_m0p06", "k_p0p06"):
        X[k] = g[k][OBS].to_numpy(float)
    X["base_trial"] = g["base"][OBS].to_numpy(float)
    w = RANGE_K / dK
    DESIGN["K"] = (RANGE_K, {"k_p0p06": w, "k_m0p06": -w}, None)
    names = ["φ", "c", "ρ", "s", "K"]
    nb = len(X["base"])
    d = len(OBS)
    cH = (nb - d - 2) / (nb - 1)
    TT = cit.terrain_task(X, names, cH)
    p("### T2. 地形の経路の3成分（エピソードの終わり）\n")
    p(f"Σ は T27 の flat_cut の基準（{nb} 本、締固めは設定していない）。κ は点ごとの分散の倍率（Σ で測る）。\n")
    p("| 点 | 本数 | " + " | ".join(OBS) + " | κ |")
    p("|---|---|" + "---|" * len(OBS) + "---|")
    for k in ("k_m0p06", "base_trial", "base", "k_p0p06"):
        p(f"| {k} | {TT['nrep'][k]} | " + " | ".join(f"{v:.3f}" for v in TT["mean"][k]) + f" | {TT['kappa'][k]:.2f} |")
    sdb = np.sqrt(np.diag(TT["S"]))
    p("\n基準の標準偏差：" + "、".join(f"{o} {s:.3f}" for o, s in zip(OBS, sdb)) + "\n")
    J = TT["J"]["K"]
    dm = TT["mean"]["k_p0p06"] - TT["mean"]["k_m0p06"]
    sem = np.sqrt(np.diag(TT["S"]) * (TT["kappa"]["k_p0p06"] / TT["nrep"]["k_p0p06"] + TT["kappa"]["k_m0p06"] / TT["nrep"]["k_m0p06"]))
    p("成分ごと：" + "、".join(f"{o} Δ {v:+.3f} m³（Δ ÷ 標準誤差 {v / s:+.1f}）" for o, v, s in zip(OBS, dm, sem)) + "\n")
    F = cit.fisher_terrain(TT, names)
    infl = np.array([TT["infl"][n] for n in names])
    Fs = F - np.diag(infl)
    rng = np.random.default_rng(0)
    samples = []
    for _ in range(boot):
        Fb, ib = cit.boot_terrain(TT, names, rng)
        samples.append(Fb - np.diag(ib))
    sm = cit.summarize(Fs, samples, names)
    p("### T3. 判定の材料（地形の経路の3成分だけ）\n")
    p("| パラメータ | J̃（" + "・".join(OBS) + "） | χ² の p | 水増し ÷ F | 信号 | 信号 ÷ 標準偏差 | 下限（1つだけ）点推定（16〜84%） |")
    p("|---|---|---|---|---|---|---|")
    for i, n in enumerate(names):
        chi2 = float(TT["J"][n] @ TT["Sinv_raw"] @ TT["J"][n]) / TT["var"][n]
        sig = Fs[i, i]
        single = 1 / math.sqrt(sig) if sig > 0 else math.nan
        q = sm["single_q"][i]
        p(f"| {n} | {', '.join(f'{v:+.3f}' for v in TT['J'][n])} | {stats.chi2.sf(chi2, d):.2g} | {infl[i] / F[i, i]:.2f} | "
          f"{sig:.1f} | {sig / sm['sd'][i]:.2f} | {single:.3f}（{q[0]:.3f}〜{q[1]:.3f}） |")
    nK = TT["nrep"]["k_p0p06"]
    r = Fs[4, 4] / sm["sd"][4]
    need = nK * (2 / r) ** 2 if r > 0 else math.inf
    p(f"\n要る回数の目安（K）：信号 ÷ 標準偏差 は回数 n にほぼ √n で比例するとして、≥ 2 には各点 {max(need, 1):.1f} 本（1 未満は 1 とした）"
      f"（今は各 {nK} 本、{r:.2f}）。水増し ÷ F は 1/n に比例するとして、各 {nK} 本で {infl[4] / F[4, 4]:.2f}。\n")
    Jm = np.column_stack([TT["J"][n] for n in names])
    W = np.linalg.cholesky(TT["Sinv"]).T @ Jm
    Wn = W / np.linalg.norm(W, axis=0)
    G = Wn.T @ Wn
    p("### T4. 白色化した J の列の cos（3成分、Σ で白色化）\n")
    p("| | " + " | ".join(names) + " |")
    p("|---|" + "---|" * len(names))
    for i, n in enumerate(names):
        p(f"| {n} | " + " | ".join(f"{G[i, j]:+.2f}" for j in range(len(names))) + " |")
    p("")
    joint_table(Fs, F, names, [[0, 4], [3, 4], [0, 3], [0, 3, 4]], "3成分")
    # 片側の J（基準 → ±）
    p("### T4b. 片側の差（基準の試しの 3 本から ±の点へ）。J̃ = Δ観測 ÷ ΔK3 × 0.30\n")
    p("| 側 | ΔK3 | " + " | ".join(f"J̃ {o}" for o in OBS) + " | J̃ S [mm] | 白色化した cos（φ と） |")
    p("|---|---|" + "---|" * len(OBS) + "---|---|")
    Lw = np.linalg.cholesky(TT["Sinv"]).T
    wphi = Lw @ TT["J"]["φ"]
    bK, bS = g["base"].K3_cut_mean.mean(), g["base"].S.mean()
    for k, lab in (("k_m0p06", "下げる側（0.94）"), ("k_p0p06", "上げる側（1.06）")):
        dk = g[k].K3_cut_mean.mean() - bK
        jy = (TT["mean"][k] - TT["mean"]["base_trial"]) / dk * RANGE_K
        jS = (g[k].S.mean() - bS) / dk * RANGE_K
        wj = Lw @ jy
        p(f"| {lab} | {dk:+.4f} | " + " | ".join(f"{v:+.3f}" for v in jy) + f" | {jS:+.1f} | "
          f"{wj @ wphi / np.linalg.norm(wj) / np.linalg.norm(wphi):+.2f} |")
    p("")
    p("### T5. 追加の沈下の成分（4つ目の候補）\n")
    s4 = {k: h.S.to_numpy() for k, h in g.items()}
    dS = s4["k_p0p06"].mean() - s4["k_m0p06"].mean()
    se = math.sqrt(s4["k_p0p06"].var(ddof=1) / len(s4["k_p0p06"]) + s4["k_m0p06"].var(ddof=1) / len(s4["k_m0p06"]))
    p(f"S：−0.06 {s4['k_m0p06'].mean():.1f}・基準 {s4['base'].mean():.1f}・+0.06 {s4['k_p0p06'].mean():.1f} mm。"
      f"差 {dS:+.1f} mm（÷ 標準誤差 {dS / se:+.1f}）。J̃_K = {dS * w:+.1f} mm（範囲の幅あたり）。\n")
    part_t4(g, w, names, boot)
    part_t7(TT, Fs, names, boot)


def joint_table(Fs, F, names, combos, lab):
    """同時の下限（範囲比）と K との相関。水増しを引いた F（判定に使う）と、引かない F（参考）の両方"""
    p(f"同時の下限（{lab}、点推定、範囲比）。「引かない」は水増しを引かない F（下限は楽観的）。\n")
    p("| 組 | 水増しを引いた F：最小の固有値 | 下限 | K との相関 | 引かない F：下限 | K との相関 |")
    p("|---|---|---|---|---|---|")
    for idx in combos:
        cells = []
        for M in (Fs, F):
            Fx = M[np.ix_(idx, idx)]
            ev = np.linalg.eigvalsh(Fx).min()
            if ev > 0:
                C = np.linalg.inv(Fx)
                sdv = np.sqrt(np.diag(C))
                Rr = C / np.outer(sdv, sdv)
                b = "・".join(f"{names[j]} {v:.3f}" for j, v in zip(idx, sdv))
                r = "・".join(f"{names[j]} {Rr[-1, m]:+.2f}" for m, j in enumerate(idx[:-1])) if names[idx[-1]] == "K" else "—"
            else:
                b, r = "正定値でない", "—"
            cells.append((ev, b, r))
        p(f"| {'・'.join(names[j] for j in idx)} | {cells[0][0]:.1f} | {cells[0][1]} | {cells[0][2]} | {cells[1][1]} | {cells[1][2]} |")
    p("")


def part_t7(TT, Fs_ter, names, boot):
    """力の経路（flat_cut、30 成分）にも K の列を足して、地形 ＋ 力の5つ同時を出す（K の点の力は試しの記録）"""
    import check_ident_combine as cic
    prefix, (b0, b1), maxdev, pattern, skip = cic.TASKS["flat_cut"]
    FT = cic.load_task([os.path.join(ROOT, pattern), os.path.join(TRIAL, "run_*")], prefix, range(b0, b1 + 1),
                       maxdev, skip, names)
    cic.NAMES = list(names)
    Ff = cic.fisher(FT)
    inf_f = np.array([FT["infl"][n] for n in names])
    Ffs = Ff - np.diag(inf_f)
    p("### T7. 力の経路（flat_cut、30 成分）の K の列と、地形 ＋ 力の5つ同時\n")
    p(f"力の経路の基準は {FT['nrep']['base']} 本（試しの基準 3 本を含む）、K の点は試しの各 3 本。地形と力の観測は独立とみなす。\n")
    p("| パラメータ | 力：水増し ÷ F | 力：信号 | 地形：信号 |")
    p("|---|---|---|---|")
    for i, n in enumerate(names):
        p(f"| {n} | {inf_f[i] / Ff[i, i]:.2f} | {Ffs[i, i]:.1f} | {Fs_ter[i, i]:.1f} |")
    Jm = np.column_stack([FT["J"][n] for n in names])
    W = np.linalg.cholesky(FT["Sinv"]).T @ Jm
    Wn = W / np.linalg.norm(W, axis=0)
    G = Wn.T @ Wn
    p("\n力の経路の白色化した J の列の cos：" + "、".join(f"K–{names[i]} {G[4, i]:+.2f}" for i in range(4)) + "\n")
    tot = Fs_ter + Ffs
    rng = np.random.default_rng(3)
    samp = []
    for _ in range(boot):
        Fb, ib = cit.boot_terrain(TT, names, rng)
        Fq, iq = cic.boot_sig(FT, rng)
        samp.append(Fb - np.diag(ib) + Fq - np.diag(iq))
    sm = cit.summarize(tot, samp, names)
    joint_table(tot, cit.fisher_terrain(TT, names) + Ff, names, [[0, 4], [0, 3, 4], [0, 1, 2, 3, 4]], "地形 3成分 ＋ 力 flat_cut")
    p(f"5つ同時（地形 ＋ 力 flat_cut）：正定値の標本 {sm['pdfrac']:.0%}。中央値（5〜95%）：" +
      "、".join(f"{n} {sm['q'][2, i]:.3f}（{sm['q'][0, i]:.3f}〜{sm['q'][4, i]:.3f}）" for i, n in enumerate(names)) + "\n")
    p("信号 ÷ 標準偏差（地形 ＋ 力 flat_cut）：" + "、".join(f"{n} {sm['sig'][i] / sm['sd'][i]:.2f}" for i, n in enumerate(names)) + "\n")


def part_t4(g, w, names, boot):
    """観測を4成分（3成分 ＋ 追加の沈下 S [m]）にした場合。φ・c・ρ・s の点と基準は T31 の flat_cut（締固めの記録つき）"""
    cells = pd.read_csv(CELLS_T31)
    E = episode_table(cells[cells.task == "flat_cut"], 30.0)
    rows = []
    for _, e in E.iterrows():
        last = pd.read_csv(os.path.join(D1, "compaction_track", e.ep)).iloc[-1]
        rows.append([float(last[o]) for o in OBS] + [e.S / 1000.0])
    E4 = pd.DataFrame(rows, columns=OBS + ["S"]).assign(point=E.point.values)
    X = {k: h[OBS + ["S"]].to_numpy(float) for k, h in E4.groupby("point")}
    trial = {k: np.column_stack([h[OBS].to_numpy(float), h.S.to_numpy() / 1000.0]) for k, h in g.items()}
    X["base"] = np.vstack([X["base"], trial["base"]])
    X["k_m0p06"], X["k_p0p06"] = trial["k_m0p06"], trial["k_p0p06"]
    nb, d = len(X["base"]), 4
    cH = (nb - d - 2) / (nb - 1)
    obs_save = cit.OBS
    cit.OBS = OBS + ["S"]
    try:
        TT = cit.terrain_task(X, names, cH)
    finally:
        cit.OBS = obs_save
    p("### T6. 4成分（3成分 ＋ 追加の沈下 S）の場合（参考）\n")
    p(f"基準は T31 の 5 本 ＋ 試しの 3 本 = {nb} 本（Σ は 4×4、補正 (n − d − 2)/(n − 1) = {cH:.3f}）。φ・c・ρ・s の点は T31 の各 3 本。"
      "本数が少ないので目安。S は m で入れた。\n")
    sd = np.sqrt(np.diag(TT["S"]))
    R = TT["S"] / np.outer(sd, sd)
    p("基準の標準偏差：" + "、".join(f"{o} {v:.4f}" for o, v in zip(cit.OBS if False else OBS + ['S'], sd)) +
      f"。S と他の成分の相関：" + "、".join(f"{o} {R[3, i]:+.2f}" for i, o in enumerate(OBS)) + "\n")
    F = TT["J"] and np.column_stack([TT["J"][n] for n in names])
    Fm = F.T @ TT["Sinv"] @ F
    infl = np.array([TT["infl"][n] for n in names])
    Fs = Fm - np.diag(infl)
    rng = np.random.default_rng(2)
    samples = []
    obs_save = cit.OBS
    cit.OBS = OBS + ["S"]
    try:
        for _ in range(boot):
            Fb, ib = cit.boot_terrain(TT, names, rng)
            samples.append(Fb - np.diag(ib))
    finally:
        cit.OBS = obs_save
    sm = cit.summarize(Fs, samples, names)
    p("| パラメータ | J̃（pos・neg・pile・S） | 水増し ÷ F | 信号 ÷ 標準偏差 |")
    p("|---|---|---|---|")
    for i, n in enumerate(names):
        p(f"| {n} | {', '.join(f'{v:+.4f}' for v in TT['J'][n])} | {infl[i] / Fm[i, i]:.2f} | {Fs[i, i] / sm['sd'][i]:.2f} |")
    W = np.linalg.cholesky(TT["Sinv"]).T @ F
    Wn = W / np.linalg.norm(W, axis=0)
    G = Wn.T @ Wn
    p("\n白色化した J の列の cos（4成分）：" + "、".join(f"K–{names[i]} {G[4, i]:+.2f}" for i in range(4)) + "\n")
    joint_table(Fs, Fm, names, [[0, 4], [3, 4], [0, 3], [0, 3, 4], [0, 1, 2, 3, 4]], "4成分")



def main():
    ap = argparse.ArgumentParser(description="締固めの列の J の準備（T33）")
    ap.add_argument("--parts", nargs="+", default=["B", "S", "T"])
    ap.add_argument("--min-cut-mm", type=float, default=30.0)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--report")
    a = ap.parse_args()
    p("# 締固めの列の J の準備（T33）\n")
    E = None
    if {"B", "S"} & set(a.parts):
        cells = pd.read_csv(CELLS_T31)
        E = episode_table(cells, a.min_cut_mm)
    if "B" in a.parts:
        part_b(E)
    if "S" in a.parts:
        part_s(E, a.min_cut_mm)
    if "T" in a.parts:
        part_t(a.min_cut_mm, a.boot)
    text = "\n".join(OUT)
    print(text)
    if a.report:
        os.makedirs(os.path.dirname(a.report), exist_ok=True)
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
