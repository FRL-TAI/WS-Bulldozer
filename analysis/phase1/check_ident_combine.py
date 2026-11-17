"""
フェーズ1：同定可能性（力の経路）を、作業を組み合わせて評価する。作業ごとに求めたフィッシャー情報行列を足し合わせ、
φ・c・ρ の3つ同時の推定標準偏差の下限（範囲比）と推定値の相関が、作業の組み合わせでどう変わるかを出す。

置き場所: analysis/phase1/check_ident_combine.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_ident_combine.py [--tasks flat_cut flat_piecewise pile_push] [--report 結果.md]

作業ごとの解析（J・Σ・κ・線形性）は check_ident.py（load_task）と同じ。作業ごとの観測は独立とみなし、F を足す。
  F_合計 = Σ_作業 J̃ᵀ Σ⁻¹ J̃（作業ごとの基準の Σ）
--params で使うパラメータを選ぶ（既定は DESIGN のすべて。T17 で膨張率 s を足した。s の点がない記録では --params φ c ρ）。
同時の下限は T8 と同じく、次の3つで示す（notes の docs/phase1.md §8.1）。
  - F そのまま（雑音の水増しを含むので楽観的）
  - 目安：対角から水増しを引いた F で1つだけのときの下限 × （そのままの F での 同時 ÷ 1つだけ）
  - ブートストラップ：作業ごと・点ごとに記録を選び直して F を作り直し、そのままの F の3つ同時の下限の 5〜95%
"""
import argparse
import itertools
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_ident import DESIGN, S_DESIGNS, load_task, set_s_step   # noqa: E402

WS = os.path.abspath(os.path.join(HERE, "..", ".."))
# 作業 → (エピソード名の頭, 区切りの範囲, 除く深さのずれ [m], 記録の glob, 除く区切り)
# flat_piecewise の区切り 15（9.375〜10 m）は、6→9 cm に変えた直後で、落ち着くまでの 1.5 秒にまるごと入るので除く
TASKS = {
    "flat_cut": ("ex_ident_flat_cut_", (1, 15), None, "data/phase1/flat_cut/run_*", ()),
    "flat_piecewise": ("ex_ident_flat_piecewise_", (1, 22), None, "data/phase1/flat_piecewise/run_*", (15,)),
    "pile_push": ("ex_ident_pile_push_", (1, 22), 0.10, "data/phase1/pile_push/run_*", ()),
}
NAMES = list(DESIGN)    # main で --params に置き換える


def pairs_of(names):
    return [(i, j) for i in range(len(names)) for j in range(i + 1, len(names))]


def fisher(T, J=None):
    Jm = np.column_stack([(J or T["J"])[n] for n in NAMES])
    return Jm.T @ T["Sinv"] @ Jm


def joint(F):
    """同時の下限と相関・条件数。正定値でなければ None"""
    ev = np.linalg.eigvalsh(F)
    if ev.min() <= 0:
        return None
    Mi = np.linalg.inv(F)
    sd = np.sqrt(np.diag(Mi))
    return sd, Mi / np.outer(sd, sd), ev.max() / ev.min()


def boot_F(T, rng):
    mb = {k: T["X"][k][rng.integers(0, len(T["X"][k]), len(T["X"][k]))].mean(axis=0) for k in T["X"]}
    J = {n: sum(wt * mb[k] for k, wt in DESIGN[n][1].items()) for n in NAMES}
    return fisher(T, J)


def boot_sig(T, rng):
    """点ごとにエピソードを選び直し、J と水増し（κ を求め直す）から、そのままの F と水増しの対角を返す（T21）"""
    need = {k for n in NAMES for k in DESIGN[n][1]}
    Sinv = T["Sinv"]
    mb, tr = {}, {}
    for k in need:
        Xk = T["X"][k][rng.integers(0, len(T["X"][k]), len(T["X"][k]))]
        mb[k] = Xk.mean(axis=0)
        r = Xk - mb[k]
        nk = len(Xk)
        tr[k] = float(np.einsum("ij,jk,ik->i", r, Sinv, r).mean()) * nk / (nk - 1)   # tr(Σ⁻¹S)
    Jm = np.column_stack([sum(wt * mb[k] for k, wt in DESIGN[n][1].items()) for n in NAMES])
    infl = np.array([sum(wt ** 2 * tr[k] / len(T["X"][k]) for k, wt in DESIGN[n][1].items()) for n in NAMES])
    return Jm.T @ Sinv @ Jm, infl


def boot_check(tasks, combos, B, rng, p):
    """信号 ÷ ブートストラップの標準偏差と、下限の 16〜84% の幅（decisions/2026-11-17_信号のばらつきを判定と下限に見込む.md）"""
    nP = len(NAMES)
    point = {}
    for c in combos:
        F = sum(fisher(tasks[t]) for t in c)
        infl = np.array([sum(tasks[t]["infl"][n] for t in c) for n in NAMES])
        point[c] = F - np.diag(infl)
    samples = {c: [] for c in combos}
    for _ in range(B):
        per = {t: boot_sig(tasks[t], rng) for t in tasks}
        for c in combos:
            samples[c].append(sum(per[t][0] for t in c) - np.diag(sum(per[t][1] for t in c)))
    p(f"## 3. 信号のばらつきを見込んだ判定（ブートストラップ {B} 回。点ごとにエピソードを選び直し、J と水増しを求め直す）\n")
    p("信号 = 水増しを引いた F の対角。基準：信号 ÷ 標準偏差 ≥ 2。下限は範囲比で、点推定（16〜84%）。"
      "1つだけの下限の幅は信号が正の標本から、同時の下限は水増しを引いた F が正定値の標本から求めた。\n")
    p("ブートストラップの標本の平均は、点推定より大きく偏る（選び直した平均には元の雑音がもう一度乗り、重複のある標本では水増しが小さく出るため）。"
      "幅と正定値の割合は、各標本から偏り（標本の平均 − 点推定、行列ごと）を引いた標本で求めた。標準偏差は偏りによらない。"
      "偏りの大きさ（標本の平均 ÷ 点推定）も並べる。\n")
    p("| 組み合わせ | パラメータ | 信号 | 標準偏差 | 信号 ÷ 標準偏差 | ≥ 2 | 偏り（平均 ÷ 点推定） | 下限（1つだけ）点推定（16〜84%） | 信号が正の割合 | "
      f"下限（{nP}つ同時）点推定（16〜84%） |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    summary = []
    for c in combos:
        S_raw = np.array(samples[c])
        F0 = point[c]
        S = S_raw - (S_raw.mean(axis=0) - F0)      # 偏りを引いた標本
        pd0 = np.linalg.eigvalsh(F0).min() > 0
        joint0 = np.sqrt(np.diag(np.linalg.inv(F0))) if pd0 else np.full(nP, math.nan)
        pdmask = np.array([np.linalg.eigvalsh(x).min() > 0 for x in S])
        jb = np.array([np.sqrt(np.diag(np.linalg.inv(x))) for x in S[pdmask]]) if pdmask.any() else np.empty((0, nP))
        for i, n in enumerate(NAMES):
            sig, sd = F0[i, i], float(np.std(S[:, i, i], ddof=1))
            pos = S[:, i, i] > 0
            sb = 1 / np.sqrt(S[pos, i, i])
            q1 = np.percentile(sb, [16, 84]) if pos.any() else (math.nan, math.nan)
            qj = np.percentile(jb[:, i], [16, 50, 84]) if len(jb) else (math.nan,) * 3
            single0 = 1 / math.sqrt(sig) if sig > 0 else math.nan
            jtxt = (f"{joint0[i]:.3f}" if pd0 else f"正定値でない（中央値 {qj[1]:.3f}）") + f"（{qj[0]:.3f}〜{qj[2]:.3f}）"
            ok = sig / sd >= 2
            summary.append((c, n, sig / sd, ok))
            bias = S_raw[:, i, i].mean() / sig if sig > 0 else math.nan
            p(f"| {' ＋ '.join(c) if i == 0 else ''} | {n} | {sig:.1f} | {sd:.1f} | {sig / sd:.2f} | {'はい' if ok else '**いいえ**'} | {bias:.2f} | "
              f"{single0:.3f}（{q1[0]:.3f}〜{q1[1]:.3f}） | {pos.mean():.0%} | {jtxt} |")
        p(f"| | 正定値になった標本の割合 | {pdmask.mean():.0%} | | | | | | | |")
    p("")
    return summary


def main():
    ap = argparse.ArgumentParser(description="作業を組み合わせた同定可能性")
    ap.add_argument("--tasks", nargs="+", default=list(TASKS), help="使う作業")
    ap.add_argument("--bins", nargs=3, action="append", metavar=("TASK", "FIRST", "LAST"), default=[],
                    help="作業の区切りの範囲を変える（例 --bins flat_piecewise 1 22）")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--params", nargs="+", choices=list(DESIGN), help="使うパラメータ（既定は DESIGN のすべて）")
    ap.add_argument("--s-step", type=float, default=0.06, choices=sorted(S_DESIGNS), help="膨張率の中心差分の刻み（既定 0.06）")
    ap.add_argument("--boot-check", action="store_true",
                    help="信号 ÷ ブートストラップの標準偏差と、下限の 16〜84% の幅を足す（T21。既定では出さない）")
    ap.add_argument("--report")
    a = ap.parse_args()
    set_s_step(a.s_step)
    global NAMES
    NAMES = list(a.params) if a.params else list(DESIGN)
    pairs = pairs_of(NAMES)
    pair_lab = [f"{NAMES[i]}–{NAMES[j]}" for i, j in pairs]
    cfg = {k: list(v) for k, v in TASKS.items()}
    for t, f0, f1 in a.bins:
        cfg[t][1] = (int(f0), int(f1))

    out = []
    p = out.append
    tasks = {}
    for t in a.tasks:
        prefix, (b0, b1), maxdev, pattern, skip = cfg[t]
        tasks[t] = load_task([os.path.join(WS, pattern)], prefix, range(b0, b1 + 1), maxdev, skip, NAMES)
    p(f"# 作業を組み合わせた同定可能性（力の経路、{'・'.join(NAMES)}）\n")

    # ---- 作業ごとのまとめ
    p("## 1. 作業ごと\n")
    p("| 作業 | 区切り | 成分 | 基準の回数 | −F_x の雑音 [kN] | −F_z の雑音 [kN] | AR(1) | F_x・F_z の相関 | κ の最大（J に使う点） |")
    p("|---|---|---|---|---|---|---|---|---|")
    jpts = sorted({k for n in NAMES for k in DESIGN[n][1]})
    for t, T in tasks.items():
        co = T["co"]
        km = max(jpts, key=lambda k: T["kappa"][k])
        sk = sorted(set(range(T['bins'][0], T['bins'][-1] + 1)) - set(T['bins']))
        p(f"| {t} | {T['bins'][0]}〜{T['bins'][-1]}{'（' + '・'.join(map(str, sk)) + ' を除く）' if sk else ''} | {T['d']} | {T['nrep']['base']} | {co['sd_Fx']:.2f} | {co['sd_Fz']:.2f} | "
          f"{co['ar']:.2f} | {co['r_xz']:.2f} | {km} {T['kappa'][km]:.2f} |")
    p("\n| 作業 | パラメータ | F（そのまま） | 水増し ÷ F | 下限 σ/範囲（1つだけ、水増しを引いた値） |")
    p("|---|---|---|---|---|")
    for t, T in tasks.items():
        F = fisher(T)
        for i, n in enumerate(NAMES):
            Fs = F[i, i] - T["infl"][n]
            p(f"| {t} | {n} | {F[i, i]:.1f} | {T['infl'][n] / F[i, i]:.2f} | {(1 / math.sqrt(Fs)) if Fs > 0 else math.nan:.3f} |")
    p("\n**白色化した J の列の cos**（1 に近いほど、その作業では2つのパラメータを分けにくい）\n")
    p("| 作業 | " + " | ".join(pair_lab) + " |")
    p("|---|" + "---|" * len(pairs))
    for t, T in tasks.items():
        F = fisher(T)
        dg = np.sqrt(np.diag(F))
        C = F / np.outer(dg, dg)
        p(f"| {t} | " + " | ".join(f"{C[i, j]:+.2f}" for i, j in pairs) + " |")
    p("")

    # ---- 組み合わせ
    p("## 2. 作業の組み合わせ（F を足し合わせる）\n")
    rng = np.random.default_rng(0)
    combos = [c for r in range(1, len(tasks) + 1) for c in itertools.combinations(tasks, r)]
    rows = []
    for c in combos:
        F = sum(fisher(tasks[t]) for t in c)
        Fs = F - np.diag([sum(tasks[t]["infl"][n] for t in c) for n in NAMES])
        jr = joint(F)
        single_raw = 1 / np.sqrt(np.diag(F))
        single_sig = np.array([1 / math.sqrt(x) if x > 0 else math.nan for x in np.diag(Fs)])
        js = joint(Fs)
        boots, nonpd = [], 0
        for _ in range(a.boot):
            Fb = sum(boot_F(tasks[t], rng) for t in c)
            r = joint(Fb)
            if r is not None:
                boots.append(np.r_[r[0], [r[1][i, j] for i, j in pairs]])
            Fbs = Fb - np.diag([sum(tasks[t]["infl"][n] for t in c) for n in NAMES])
            if np.linalg.eigvalsh(Fbs).min() <= 0:
                nonpd += 1
        boots = np.array(boots)
        rows.append(dict(c=c, jr=jr, js=js, ev_s=float(np.linalg.eigvalsh(Fs).min()), single_raw=single_raw, single_sig=single_sig, boots=boots, nonpd=nonpd / a.boot))

    p(f"**{len(NAMES)}つ同時の推定標準偏差の下限（範囲比）**\n")
    p(f"| 組み合わせ | {NAMES[0]}（そのまま／目安／ブートストラップ 5〜95%） | " + " | ".join(NAMES[1:]) + " | 水増しを引いた F で直接 |")
    p("|---|" + "---|" * (len(NAMES) + 1))
    for r in rows:
        cells = []
        for i in range(len(NAMES)):
            if r["jr"] is None:
                cells.append("—")
                continue
            ratio = r["jr"][0][i] / r["single_raw"][i]
            q = np.percentile(r["boots"][:, i], [5, 95]) if len(r["boots"]) else (math.nan, math.nan)
            cells.append(f"{r['jr'][0][i]:.3f}／{r['single_sig'][i] * ratio:.3f}／{q[0]:.3f}〜{q[1]:.3f}")
        direct = ("、".join(f"{n} {x:.3f}" for n, x in zip(NAMES, r["js"][0])) + f"（最小の固有値 {r['ev_s']:.1f}）" if r["js"] is not None
                  else f"正定値でない（ブートストラップで {r['nonpd']:.0%}）")
        p(f"| {' ＋ '.join(r['c'])} | " + " | ".join(cells) + f" | {direct} |")
    p("\n**推定値の相関（そのままの F）と条件数**\n")
    p("相関の括弧内はブートストラップの 5〜95%。\n")
    p("| 組み合わせ | " + " | ".join(pair_lab) + " | 条件数 |")
    p("|---|" + "---|" * (len(pairs) + 1))
    nP = len(NAMES)
    for r in rows:
        if r["jr"] is None:
            p(f"| {' ＋ '.join(r['c'])} | " + " | ".join("—" for _ in pairs) + " | — |")
            continue
        C = r["jr"][1]
        cells = []
        for m, (i, j) in enumerate(pairs):
            q = np.percentile(r["boots"][:, nP + m], [5, 95]) if len(r["boots"]) else (math.nan, math.nan)
            cells.append(f"{C[i, j]:+.2f}（{q[0]:+.2f}〜{q[1]:+.2f}）")
        p(f"| {' ＋ '.join(r['c'])} | " + " | ".join(cells) + f" | {r['jr'][2]:.0f} |")
    p("")

    if a.boot_check:
        boot_check(tasks, combos, a.boot, np.random.default_rng(1), p)

    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
