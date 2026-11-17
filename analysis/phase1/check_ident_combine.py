"""
フェーズ1：同定可能性（力の経路）を、作業を組み合わせて評価する。作業ごとに求めたフィッシャー情報行列を足し合わせ、
φ・c・ρ の3つ同時の推定標準偏差の下限（範囲比）と推定値の相関が、作業の組み合わせでどう変わるかを出す。

置き場所: analysis/phase1/check_ident_combine.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_ident_combine.py [--tasks flat_cut flat_piecewise pile_push] [--report 結果.md]

作業ごとの解析（J・Σ・κ・線形性）は check_ident.py（load_task）と同じ。作業ごとの観測は独立とみなし、F を足す。
  F_合計 = Σ_作業 J̃ᵀ Σ⁻¹ J̃（作業ごとの基準の Σ）
3つ同時の下限は T8 と同じく、次の3つで示す（notes の docs/phase1.md §8.1）。
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
from check_ident import DESIGN, load_task   # noqa: E402

WS = os.path.abspath(os.path.join(HERE, "..", ".."))
# 作業 → (エピソード名の頭, 区切りの範囲, 除く深さのずれ [m], 記録の glob, 除く区切り)
# flat_piecewise の区切り 15（9.375〜10 m）は、6→9 cm に変えた直後で、落ち着くまでの 1.5 秒にまるごと入るので除く
TASKS = {
    "flat_cut": ("ex_ident_flat_cut_", (1, 15), None, "data/phase1/flat_cut/run_*", ()),
    "flat_piecewise": ("ex_ident_flat_piecewise_", (1, 22), None, "data/phase1/flat_piecewise/run_*", (15,)),
    "pile_push": ("ex_ident_pile_push_", (1, 22), 0.10, "data/phase1/pile_push/run_*", ()),
}
NAMES = list(DESIGN)


def fisher(T, J=None):
    Jm = np.column_stack([(J or T["J"])[n] for n in NAMES])
    return Jm.T @ T["Sinv"] @ Jm


def joint(F):
    """3つ同時の下限と相関・条件数。正定値でなければ None"""
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


def main():
    ap = argparse.ArgumentParser(description="作業を組み合わせた同定可能性")
    ap.add_argument("--tasks", nargs="+", default=list(TASKS), help="使う作業")
    ap.add_argument("--bins", nargs=3, action="append", metavar=("TASK", "FIRST", "LAST"), default=[],
                    help="作業の区切りの範囲を変える（例 --bins flat_piecewise 1 22）")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--report")
    a = ap.parse_args()
    cfg = {k: list(v) for k, v in TASKS.items()}
    for t, f0, f1 in a.bins:
        cfg[t][1] = (int(f0), int(f1))

    out = []
    p = out.append
    tasks = {}
    for t in a.tasks:
        prefix, (b0, b1), maxdev, pattern, skip = cfg[t]
        tasks[t] = load_task([os.path.join(WS, pattern)], prefix, range(b0, b1 + 1), maxdev, skip)
    p("# 作業を組み合わせた同定可能性（力の経路、φ・c・ρ）\n")

    # ---- 作業ごとのまとめ
    p("## 1. 作業ごと\n")
    p("| 作業 | 区切り | 成分 | 基準の回数 | −F_x の雑音 [kN] | −F_z の雑音 [kN] | AR(1) | F_x・F_z の相関 | κ の最大（J に使う点） |")
    p("|---|---|---|---|---|---|---|---|---|")
    jpts = sorted({k for _, w, _ in DESIGN.values() for k in w})
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
    p("| 作業 | φ–c | φ–ρ | c–ρ |")
    p("|---|---|---|---|")
    for t, T in tasks.items():
        F = fisher(T)
        dg = np.sqrt(np.diag(F))
        C = F / np.outer(dg, dg)
        p(f"| {t} | {C[0, 1]:+.2f} | {C[0, 2]:+.2f} | {C[1, 2]:+.2f} |")
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
                boots.append(np.r_[r[0], r[1][0, 1], r[1][0, 2], r[1][1, 2]])
            Fbs = Fb - np.diag([sum(tasks[t]["infl"][n] for t in c) for n in NAMES])
            if np.linalg.eigvalsh(Fbs).min() <= 0:
                nonpd += 1
        boots = np.array(boots)
        rows.append(dict(c=c, jr=jr, js=js, ev_s=float(np.linalg.eigvalsh(Fs).min()), single_raw=single_raw, single_sig=single_sig, boots=boots, nonpd=nonpd / a.boot))

    p("**3つ同時の推定標準偏差の下限（範囲比）**\n")
    p("| 組み合わせ | φ（そのまま／目安／ブートストラップ 5〜95%） | c | ρ | 水増しを引いた F で直接 |")
    p("|---|---|---|---|---|")
    for r in rows:
        cells = []
        for i in range(3):
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
    p("| 組み合わせ | φ–c | φ–ρ | c–ρ（ブートストラップ 5〜95%） | 条件数 |")
    p("|---|---|---|---|---|")
    for r in rows:
        if r["jr"] is None:
            p(f"| {' ＋ '.join(r['c'])} | — | — | — | — |")
            continue
        C = r["jr"][1]
        q = np.percentile(r["boots"][:, 5], [5, 95]) if len(r["boots"]) else (math.nan, math.nan)
        p(f"| {' ＋ '.join(r['c'])} | {C[0, 1]:+.2f} | {C[0, 2]:+.2f} | {C[1, 2]:+.2f}（{q[0]:+.2f}〜{q[1]:+.2f}） | {r['jr'][2]:.0f} |")
    p("")

    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
