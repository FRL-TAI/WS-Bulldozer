"""
フェーズ1：締固めの列の J を、折れ目の両側で3作業について求める（T34）。

notes decisions/2026-11-18_締固めの列は折れ目の両側で別々に判定する.md、
      decisions/2026-11-18_力の経路の締固めの効きは交絡として表に入れる.md

使い方（コンテナの中、ワークスペース直下）:
  python3 analysis/phase1/check_compaction_j34.py --report data/phase1/compaction_j/report_t34.md [--boot 1000]

記録:
  締固めの点（ex_ident_<作業>_k_*）：flat_cut は data/phase1/compaction_j/（T33 の試しと T34）、
  flat_piecewise・pile_push は data/phase1/compaction_j_<作業>/。
  地形の経路の基準と φ・c・ρ・s の点は T27 と同じ（check_ident_terrain_combine.TTASKS）、力の経路は T21 と同じ（check_ident_combine.TASKS）。
  締固めの点の記録のフォルダにある基準（T33 の試しの 3 本）も、基準に含める。
  pile_push は深さのずれの 95% 点が 10 cm を超える記録を除く（§5 と同じ）。

K3（ΔK3 に使う）:
  エピソードごとに、履帯が踏む時点の K3 を、刃先が通った地面のマス（記録の座標 x ≥ --x-min）で平均する。
  締固めの点は記録の _compaction.csv から（check_compaction_candidates.track_cells）、
  基準は T31 の track_cells_t31.csv（基準 5 本）と、T33 の試しの基準（flat_cut の 3 本）。

側（J̃ = Δ観測 ÷ ΔK3 × 0.30、範囲の幅あたり）:
  緩い側（下げる側）：基準 − 0.94 の点、締まった側（上げる側）：1.06 の点 − 基準、中心差分：1.06 − 0.94（参考）。
  DESIGN["K"] を側ごとに置き換え、J・κ・水増し・ブートストラップはほかの列と同じ関数で求める。

出力:
  1. 点ごとの K3 と ΔK3、本数
  2. 列ごと（作業 × 経路 × 側）の信号 ÷ 標準偏差、1つだけの下限、水増し ÷ F、白色化した cos
  3. 折れ目の幅（flat_cut）：±0.03 と ±0.06 の Δ観測の比（Σ で測る）と、線形・段差のそれぞれの仮説の χ²
  4. 組み合わせ：地形だけの φ・s・K（作業ごと、3作業）、地形 ＋ 力の5つ同時（flat_cut、3作業）を (i) 力の K の列を測った値、
     (ii) 0 の2通りで
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
import check_compaction_candidates as ccc    # noqa: E402
import check_ident_combine as cic            # noqa: E402
import check_ident_terrain as cit            # noqa: E402
import check_ident_terrain_combine as ctc    # noqa: E402
from check_ident import DESIGN, set_s_step   # noqa: E402

WS = os.path.abspath(os.path.join(HERE, "..", ".."))
D1 = os.path.join(WS, "data", "phase1")
TASKS = ["flat_cut", "flat_piecewise", "pile_push"]
KDIR = {"flat_cut": "data/phase1/compaction_j/run_2*", "flat_piecewise": "data/phase1/compaction_j_flat_piecewise/run_2*",
        "pile_push": "data/phase1/compaction_j_pile_push/run_2*"}
CELLS_T31 = os.path.join(D1, "compaction_track", "track_cells_t31.csv")
RANGE_K = 0.30
ALL5 = ["φ", "c", "ρ", "s", "K"]
SIDES = {"緩い側": ("base", "k_m0p06"), "締まった側": ("k_p0p06", "base"), "中心差分（参考）": ("k_p0p06", "k_m0p06")}
OUT = []


def p(s=""):
    OUT.append(s)


# ---------------------------------------------------------------- K3
def k3_of_cells(cells, x_min):
    c = [r["K3"] for r in cells if r["x"] >= x_min and math.isfinite(r["K3"])]
    return float(np.mean(c)) if c else math.nan


def k3_points(task, x_min):
    """点 → エピソードごとの K3 の配列"""
    out = {}
    t31 = pd.read_csv(CELLS_T31)
    t31 = t31[(t31.task == task) & (t31.point == "base") & (t31.x >= x_min)]
    out["base"] = list(t31.groupby("ep").K3.mean().to_numpy())
    prefix = f"ex_ident_{task}_"
    for rd in sorted(glob.glob(os.path.join(WS, KDIR[task]))):
        if not os.path.exists(os.path.join(rd, "episodes.jsonl")):
            continue
        ok = ccc.ok_files(rd)
        with open(os.path.join(rd, "episodes.jsonl"), encoding="utf-8") as f:
            meta = {r.get("file"): r for r in map(json.loads, f)}
        for fn in sorted(ok):
            name = meta[fn]["episode_name"]
            if not name.startswith(prefix):
                continue
            pt = name[len(prefix):]
            cells = ccc.track_cells(os.path.join(rd, fn[:-4] + "_compaction.csv"))
            out.setdefault(pt, []).append(k3_of_cells(cells, x_min))
    return {k: np.array(v) for k, v in out.items()}


def load_terrain(task, maxdev):
    """地形の経路の観測：基準と φ・c・ρ・s の点は ctc.load（T27 と同じ）、締固めの点のフォルダは episodes.jsonl で
    status ok の主の CSV だけ（_compaction.csv や収集中の CSV を読まない）"""
    from check_physics import settled_cut_rows
    prefix, pats, names, _ = ctc.TTASKS[task]
    X, devs, exc, aux = ctc.load(prefix, pats, maxdev)
    X = {k: list(v) for k, v in X.items()}
    for rd in sorted(glob.glob(os.path.join(WS, KDIR[task]))):
        jl = os.path.join(rd, "episodes.jsonl")
        if not os.path.exists(jl):
            continue
        with open(jl, encoding="utf-8") as f:
            rows = [json.loads(x) for x in f if x.strip()]
        for r in rows:
            if r.get("status") != "ok" or not r["episode_name"].startswith(prefix):
                continue
            path = os.path.join(rd, r["file"])
            df = pd.read_csv(path)
            pt = r["episode_name"][len(prefix):]
            sr = settled_cut_rows(df)
            dev95 = float(np.percentile(np.abs(sr["depth"] - sr["target_depth"]), 95)) if sr is not None else math.nan
            if maxdev is not None and not dev95 <= maxdev:
                exc.append((os.path.relpath(path, WS), pt, dev95))
                continue
            y = np.array([df.iloc[-1][c] for c in cit.OBS], float)
            if not np.isnan(y).any():
                X.setdefault(pt, []).append(y)
    return {k: np.array(v) for k, v in X.items()}, names, exc


# ---------------------------------------------------------------- 側ごとの K の列
def set_side(hi, lo, K3m):
    w = RANGE_K / (K3m[hi] - K3m[lo])
    DESIGN["K"] = (RANGE_K, {hi: w, lo: -w}, None)


def refresh_terrain(T, names):
    """DESIGN を変えたあと、地形の T の J・var・infl を作り直す（terrain_task と同じ式）"""
    for n in names:
        T["J"][n] = sum(wt * T["mean"][k] for k, wt in DESIGN[n][1].items())
        T["var"][n] = sum(wt ** 2 * T["kappa"][k] / T["nrep"][k] for k, wt in DESIGN[n][1].items())
        T["infl"][n] = T["d"] * T["cH"] * T["var"][n]


def refresh_force(T, names):
    for n in names:
        w = DESIGN[n][1]
        T["J"][n] = sum(wt * T["mean"][k] for k, wt in w.items())
        T["infl"][n] = T["d"] * sum(wt ** 2 * T["kappa"][k] / T["nrep"][k] for k, wt in w.items())


def terr_F(T, names):
    return cit.fisher_terrain(T, names) - np.diag([T["infl"][n] for n in names])


def force_F(T, names):
    cic.NAMES = list(names)
    return cic.fisher(T) - np.diag([T["infl"][n] for n in names])


def terr_boot(T, names, rng):
    Fb, ib = cit.boot_terrain(T, names, rng)
    return Fb - np.diag(ib)


def force_boot(T, names, rng):
    cic.NAMES = list(names)
    Fb, ib = cic.boot_sig(T, rng)
    return Fb - np.diag(ib)


def embed(F, names):
    M = np.zeros((5, 5))
    idx = [ALL5.index(n) for n in names]
    M[np.ix_(idx, idx)] = F
    return M


def whiten_cos(Sinv, J, names):
    Jm = np.column_stack([J[n] for n in names])
    W = np.linalg.cholesky(Sinv).T @ Jm
    Wn = W / np.linalg.norm(W, axis=0)
    return Wn.T @ Wn


def column_stats(F0, samples, i):
    S_raw = np.array([x[i, i] for x in samples])
    S = S_raw - (S_raw.mean() - F0[i, i])
    sd = float(np.std(S, ddof=1))
    pos = S > 0
    q = np.percentile(1 / np.sqrt(S[pos]), [16, 84]) if pos.any() else (math.nan, math.nan)
    return F0[i, i], sd, q


# ---------------------------------------------------------------- 本体
def main():
    ap = argparse.ArgumentParser(description="締固めの列の J（折れ目の両側、3作業）（T34）")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--x-min", type=float, default=3.1, help="K3 を平均するマスの記録の座標 x の下限 [m]（刃先が通った地面）")
    ap.add_argument("--tasks", nargs="+", default=TASKS, help="使う作業（途中の確認用）")
    ap.add_argument("--report")
    a = ap.parse_args()
    TASKS[:] = [t for t in TASKS if t in a.tasks]
    set_s_step(0.06)
    p("# 締固めの列の J（折れ目の両側、3作業）（T34）\n")

    # ---- 読み込み
    K3, TT, FT, tnames = {}, {}, {}, {}
    for t in TASKS:
        K3[t] = k3_points(t, a.x_min)
        X, names, exc = load_terrain(t, ctc.TTASKS[t][3])
        tnames[t] = list(names) + ["K"]
        DESIGN["K"] = (RANGE_K, {"k_p0p06": 1.0, "k_m0p06": -1.0}, None)   # 仮（側ごとに置き換える）
        nb, d = len(X["base"]), len(cit.OBS)
        TT[t] = cit.terrain_task(X, tnames[t], (nb - d - 2) / (nb - 1))
        TT[t]["d"] = d
        fp, (b0, b1), fmax, fpat, skip = cic.TASKS[t]
        FT[t] = cic.load_task([os.path.join(WS, fpat), os.path.join(WS, KDIR[t])], fp, range(b0, b1 + 1), fmax, skip, ALL5)
        if exc:
            p(f"{t}：深さのずれで除いた地形の記録 {len(exc)} 本（" + "、".join(f"{e[1]} {e[2] * 100:.1f} cm" for e in exc) + "）\n")

    # ---- 1. K3
    p("## 1. 点ごとの K3（履帯が踏む時点、刃先が通った地面のマスの平均）と本数\n")
    p(f"マスは記録の座標 x ≥ {a.x_min:g} m。基準の K3 は T31 の 5 本（flat_cut は T33 の試しの 3 本を足して 8 本）。"
      "本数は K3・地形・力の順。\n")
    p("| 作業 | 点 | K3（平均 ± 標準偏差） | ΔK3（基準との差） | 本数（K3・地形・力） |")
    p("|---|---|---|---|---|")
    K3m = {}
    for t in TASKS:
        K3m[t] = {k: float(v.mean()) for k, v in K3[t].items()}
        for k in ["k_m0p06", "k_m0p03", "base", "k_p0p03", "k_p0p06"]:
            if k not in K3[t]:
                continue
            v = K3[t][k]
            p(f"| {t} | {k} | {v.mean():.4f} ± {v.std(ddof=1):.4f} | {v.mean() - K3m[t]['base']:+.4f} | "
              f"{len(v)}・{TT[t]['nrep'].get(k, 0)}・{FT[t]['nrep'].get(k, 0)} |")
    p("")

    # ---- 2. 列ごと
    p("## 2. 締固めの列（作業 × 経路 × 側）\n")
    p("J̃ は範囲の幅（0.30）あたり。信号は水増しを引いた F の対角、標準偏差はブートストラップ（偏りを引いた標本）。"
      "cos は経路ごとに Σ で白色化した J の列どうし（地形の flat_piecewise・pile_push は φ・s の列だけ）。\n")
    p("| 作業 | 経路 | 側 | 水増し ÷ F | 信号 ÷ 標準偏差 | ≥ 2 か | 下限（1つだけ）点推定（16〜84%） | cos（K と φ・c・ρ・s） |")
    p("|---|---|---|---|---|---|---|---|")
    rng = np.random.default_rng(0)
    for t in TASKS:
        for side, (hi, lo) in SIDES.items():
            set_side(hi, lo, K3m[t])
            for path in ("地形", "力"):
                if path == "地形":
                    T, names = TT[t], tnames[t]
                    refresh_terrain(T, names)
                    Fraw = cit.fisher_terrain(T, names)
                    F0 = terr_F(T, names)
                    samp = [terr_boot(T, names, rng) for _ in range(a.boot)]
                    G = whiten_cos(T["Sinv"], T["J"], names)
                    infl = T["infl"]["K"]
                else:
                    T, names = FT[t], ALL5
                    refresh_force(T, names)
                    cic.NAMES = list(names)
                    Fraw = cic.fisher(T)
                    F0 = force_F(T, names)
                    samp = [force_boot(T, names, rng) for _ in range(a.boot)]
                    G = whiten_cos(T["Sinv"], T["J"], names)
                    infl = T["infl"]["K"]
                i = names.index("K")
                sig, sd, q = column_stats(F0, samp, i)
                single = f"{1 / math.sqrt(sig):.3f}" if sig > 0 else "—"
                cs = "・".join(f"{n} {G[i, j]:+.2f}" for j, n in enumerate(names) if n != "K")
                p(f"| {t} | {path} | {side} | {infl / Fraw[i, i]:.2f} | {sig / sd:.2f} | {'はい' if sig / sd >= 2 else '**いいえ**'} | "
                  f"{single}（{q[0]:.3f}〜{q[1]:.3f}） | {cs} |")
    p("")

    # ---- 3. 折れ目の幅（flat_cut）
    t = "flat_cut"
    if all(k in TT[t]["mean"] for k in ("k_m0p03", "k_p0p03")):
        p("## 3. 折れ目の幅（flat_cut、±0.03 と ±0.06）\n")
        p("Δ03・Δ06 は基準から ±0.03・±0.06 の点への観測の差。r = (Δ03ᵀΣ⁻¹Δ06)/(Δ06ᵀΣ⁻¹Δ06) は Δ06 の向きへの射影の比で、"
          "効きが ΔK3 に比例する（傾き）なら ΔK3 の比（約 0.5）、段差なら約 1 になる。"
          "χ²（線形）は Δ03 − (ΔK3_03/ΔK3_06)·Δ06、χ²（段差）は Δ03 − Δ06 が 0 かの検定（κ を見込む）。"
          "ΔK3 あたりの効きの比は r × ΔK3_06/ΔK3_03。\n")
        p("| 経路 | 側 | ΔK3_03 / ΔK3_06 | r | ΔK3 あたりの効きの比（0.03 ÷ 0.06） | χ²（線形）の p | χ²（段差）の p | 代表の成分 Δ03 / Δ06 |")
        p("|---|---|---|---|---|---|---|---|")
        for path in ("地形", "力"):
            T = TT[t] if path == "地形" else FT[t]
            Sinv = T["Sinv_raw"] if path == "地形" else T["Sinv"]
            d = T["d"]
            for side, (p3, p6) in (("緩い側", ("k_m0p03", "k_m0p06")), ("締まった側", ("k_p0p03", "k_p0p06"))):
                m = T["mean"]
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
                    rep = f"vis_net_neg {D3[1]:+.3f} / {D6[1]:+.3f} m³"
                else:
                    nb = T["nb"]
                    rep = f"Σ(−F_x) {D3[:nb].sum():+.1f} / {D6[:nb].sum():+.1f}"
                p(f"| {path} | {side} | {k3:+.4f} / {k6:+.4f}（{lam:.2f}） | {r:.2f} | {r / lam:.2f} | {pl:.2g} | {ps:.2g} | {rep} |")
        p("")

    # ---- 4. 組み合わせ
    p("## 4. 組み合わせ（側ごと）\n")
    p("水増しを引いた F。点推定が正定値でなければ「—」。続けて、偏りを引いた標本のうち正定値のものの中央値（5〜95%）。"
      "§8.7 の主な表と同じく、信号のある列だけで作る：地形の経路は φ・s・K、力の経路は (i) φ・c・ρ・K（K の列を測った値）、"
      "(ii) φ・c・ρ（K の列を 0）。力の経路の s の効きは 0 とみなす。作業どうし・経路どうしの観測は独立とみなす。\n")
    combos = [
        ("地形だけ：flat_cut", [], ["flat_cut"], ["φ", "s", "K"], None),
        ("地形だけ：flat_piecewise", [], ["flat_piecewise"], ["φ", "s", "K"], None),
        ("地形だけ：pile_push", [], ["pile_push"], ["φ", "s", "K"], None),
        ("地形だけ：3作業", [], TASKS, ["φ", "s", "K"], None),
        ("地形 ＋ 力 (i)：flat_cut、φ・s・K（c・ρ は固定）", ["flat_cut"], ["flat_cut"], ["φ", "s", "K"], True),
        ("地形 ＋ 力 (ii)：flat_cut、φ・s・K（c・ρ は固定）", ["flat_cut"], ["flat_cut"], ["φ", "s", "K"], False),
        ("地形 ＋ 力 (i)：3作業、φ・s・K（c・ρ は固定）", TASKS, TASKS, ["φ", "s", "K"], True),
        ("地形 ＋ 力 (ii)：3作業、φ・s・K（c・ρ は固定）", TASKS, TASKS, ["φ", "s", "K"], False),
        ("地形 ＋ 力 (i)：flat_cut", ["flat_cut"], ["flat_cut"], ALL5, True),
        ("地形 ＋ 力 (ii)：flat_cut", ["flat_cut"], ["flat_cut"], ALL5, False),
        ("地形 ＋ 力 (i)：3作業", TASKS, TASKS, ALL5, True),
        ("地形 ＋ 力 (ii)：3作業", TASKS, TASKS, ALL5, False),
    ]
    combos = [c for c in combos if set(c[1]) <= set(TASKS) and set(c[2]) <= set(TASKS)
              and not ("3作業" in c[0] and len(TASKS) < 3)]
    TN = ["φ", "s", "K"]          # 地形の経路で組み合わせに入れる列（§8.7 と同じく信号のある列。c・ρ は外す）
    FI = ["φ", "c", "ρ", "K"]     # 力の経路 (i)（s は外す。§8.7 と同じく力の経路の s の効きは 0 とみなす）
    FII = ["φ", "c", "ρ"]         # 力の経路 (ii)（K の列も 0）
    for side, (hi, lo) in SIDES.items():
        p(f"### {side}\n")
        p("| 組み合わせ | 正定値の標本 | 最小の固有値 | " + " | ".join(f"{n} 点推定／中央値（5〜95%）" for n in ALL5) +
          " | φ–K の相関 | s–K の相関 | c–ρ の相関 |")
        p("|---|---|---|" + "---|" * len(ALL5) + "---|---|---|")
        tF, fFi, fFii = {}, {}, {}
        for t in TASKS:
            set_side(hi, lo, K3m[t])
            refresh_terrain(TT[t], tnames[t])
            refresh_force(FT[t], ALL5)
            tF[t] = embed(terr_F(TT[t], TN), TN)
            fFi[t] = embed(force_F(FT[t], FI), FI)
            fFii[t] = embed(force_F(FT[t], FII), FII)
        samp = {c[0]: [] for c in combos}
        rng2 = np.random.default_rng(1)
        for _ in range(a.boot):
            tb, fbi, fbii = {}, {}, {}
            for t in TASKS:
                set_side(hi, lo, K3m[t])
                tb[t] = embed(terr_boot(TT[t], TN, rng2), TN)
                fbi[t] = embed(force_boot(FT[t], FI, rng2), FI)
                fbii[t] = embed(force_boot(FT[t], FII, rng2), FII)
            for lab, ft, tt, nm, meas in combos:
                samp[lab].append(sum([tb[t] for t in tt] + [(fbi if meas else fbii)[t] for t in ft]))
        for lab, ft, tt, nm, meas in combos:
            idx = [ALL5.index(n) for n in nm]
            F0 = sum([tF[t] for t in tt] + [(fFi if meas else fFii)[t] for t in ft])[np.ix_(idx, idx)]
            sm = [x[np.ix_(idx, idx)] for x in samp[lab]]
            pairs = []
            names_of = {n: nm.index(n) for n in nm}
            for a_, b_ in (("φ", "K"), ("s", "K"), ("c", "ρ")):
                if a_ in names_of and b_ in names_of:
                    pairs.append((names_of[a_], names_of[b_]))
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
            for a_, b_ in (("φ", "K"), ("s", "K"), ("c", "ρ")):
                if a_ in names_of and b_ in names_of:
                    pr = (names_of[a_], names_of[b_])
                    c0 = f"{r['c0'][pr]:+.2f}" if r["pd0"] else "—"
                    cor.append(f"{c0}／{r['cq'][pr][1]:+.2f}")
                else:
                    cor.append("—")
            p(f"| {lab} | {r['pdfrac']:.0%} | {r['evmin']:.1f} | " + " | ".join(cells) + " | " + " | ".join(cor) + " |")
        p("")

    text = "\n".join(OUT)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
