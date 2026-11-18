"""
道すじ全体の体積の出入り ΔV_net（vis_net。粒子を含む高さ場）が膨張率 s とともに変わるかを確かめる（T25）。

置き場所: analysis/phase1/check_vis_net.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_vis_net.py data/phase1/vis_net/run_<日時>_t25 [--report 結果.md]

記録の列（BladeStatePublisher.cs の PileVolume。notes decisions/2026-11-18_sの判定は道すじ全体の体積の出入りで行う.md）:
  vis_net_pos / vis_net_neg / vis_net : 収支の窓（刃先の後ろ 16 m〜前 3 m・±3 m）での、粒子を含む高さ − 開始時の粒子を含む高さ の
                                         正の部分・負の部分（正の値）・差 [m3]。1 秒ごと（raising の間と進行状況が変わった回は毎回）
  pile_volume_vis : V_pile と同じ範囲の、粒子を含む高さ場から求める山の体積 [m3]（T24。こちらは h0 が地形の高さ）
  cut_volume      : それまでに地山を削った体積 [m3]（bull_ope が刃先の深さから積算）

エピソード名 ex_ident_flat_cut_<点>（base・s_m0p06・s_p0p06）。s は label_swell。

出すもの（エピソードの終わり＝最後の行の値）:
  1. エピソードごと：深さのずれの 95% 点、vis_net_pos・vis_net_neg・vis_net、cut_volume、1 + vis_net / cut_volume、
     こぼれた割合 1 − pile_volume_vis / vis_net_pos、vis_net の最後の更新からの時間
  2. s ごとの平均 ± 標準誤差（エピソードを選び直すブートストラップ）
  3. s に対する傾き ± 標準誤差（最小二乗の式と、s の点ごとに選び直すブートストラップの大きいほう）、傾き ÷ 標準誤差、
     傾き ÷ 平均の cut_volume（ΔV_net ≈ (s − 1)·V_cut なら 1）
  4. 走行中の vis_net の推移（2 m ごと、s ごとの平均）
"""
import argparse
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "validation"))
from check_physics import list_targets, settled_cut_rows  # noqa: E402

NBOOT = 2000
NAME_RE = re.compile(r"ex_ident_flat_cut_(base|s_m0p06|s_p0p06)")
COLS = ["vis_net_pos", "vis_net_neg", "vis_net", "cut_volume", "1+vis_net/cut", "こぼれた割合"]


def episode(path):
    df = pd.read_csv(path)
    if not NAME_RE.search(str(df["episode_name"].iloc[0])):
        return None
    rows = settled_cut_rows(df)
    dev95 = float(np.percentile(np.abs(rows["depth"] - rows["target_depth"]), 95)) if rows is not None else np.nan
    last = df.iloc[-1]
    # vis_net が最後に変わった行からの時間（終わりの値が新しいかの確認）
    ch = np.flatnonzero(np.diff(df["vis_net"].to_numpy()) != 0)
    stale = float(df["t"].iloc[-1] - df["t"].iloc[ch[-1] + 1]) if len(ch) else np.nan
    m = {"vis_net_pos": last["vis_net_pos"], "vis_net_neg": last["vis_net_neg"], "vis_net": last["vis_net"],
         "cut_volume": last["cut_volume"]}
    m["1+vis_net/cut"] = 1 + m["vis_net"] / m["cut_volume"]
    m["こぼれた割合"] = 1 - last["pile_volume_vis"] / m["vis_net_pos"]
    run = df[df["phase"] == "running"]
    return dict(s=float(df["label_swell"].iloc[0]), file=os.path.basename(path), dev95=dev95, m=m, stale=stale,
                nan=int(df[["vis_net_pos", "vis_net_neg", "vis_net"]].isna().any(axis=1).sum()), rows=len(df),
                last_phase=str(last["phase"]), run=run[["distance", "vis_net", "cut_volume"]])


def slope(x, y):
    X = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ beta
    s2 = float(r @ r) / (len(x) - 2)
    return float(beta[1]), float(np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1]))


def main():
    ap = argparse.ArgumentParser(description="道すじ全体の体積の出入りと膨張率（T25）")
    ap.add_argument("paths", nargs="+", help="collect_data の出力フォルダ、または CSV")
    ap.add_argument("--report")
    a = ap.parse_args()
    eps = sorted((e for e in (episode(p) for p in list_targets(a.paths)) if e is not None), key=lambda e: (e["s"], e["file"]))
    rng = np.random.default_rng(0)
    out = []
    p = out.append
    p("# 道すじ全体の体積の出入りと膨張率（T25）\n")
    p("値はエピソードの最後の行（raising の終わり）。こぼれた割合 = 1 − pile_volume_vis ÷ vis_net_pos（V_pile の範囲の外にある、開始時より高い部分の割合）。"
      f"標準誤差はエピソードを選び直すブートストラップ（{NBOOT} 回）。\n")
    p("## 1. エピソードごと\n")
    p("| 記録 | s | 深さのずれ 95% [cm] | 最後の進行状況 | 最後の更新からの時間 [s] | NaN の行 | " + " | ".join(COLS) + " |")
    p("|---|---|---|---|---|---|" + "---|" * len(COLS))
    for e in eps:
        p(f"| {e['file']} | {e['s']:.2f} | {e['dev95'] * 100:.2f} | {e['last_phase']} | {e['stale']:.2f} | {e['nan']}/{e['rows']} | "
          + " | ".join(f"{e['m'][k]:.3f}" for k in COLS) + " |")
    levels = sorted({e["s"] for e in eps})
    p("\n## 2. s ごとの平均 ± 標準誤差\n")
    p("| s | 本数 | 深さのずれ 95% [cm]（最大） | " + " | ".join(COLS) + " |")
    p("|---|---|---|" + "---|" * len(COLS))
    for s in levels:
        g = [e for e in eps if e["s"] == s]
        cells = []
        for k in COLS:
            v = np.array([e["m"][k] for e in g], float)
            bs = [rng.choice(v, len(v)).mean() for _ in range(NBOOT)]
            cells.append(f"{v.mean():.3f} ± {np.std(bs, ddof=1):.3f}")
        p(f"| {s:.2f} | {len(g)} | {max(e['dev95'] for e in g) * 100:.2f} | " + " | ".join(cells) + " |")
    p("\n## 3. s に対する傾き\n")
    p("標準誤差は最小二乗の式（残差から）と、s の点ごとにエピソードを選び直すブートストラップの大きいほう。"
      "傾き ÷ 平均の cut_volume は、ΔV_net ≈ (s − 1)·V_cut なら 1。\n")
    p("| 量 | 傾き [/s] | 標準誤差（式） | 標準誤差（ブートストラップ） | 傾き ÷ 標準誤差 | ≥ 2 か | 傾き ÷ 平均の cut_volume |")
    p("|---|---|---|---|---|---|---|")
    x = np.array([e["s"] for e in eps])
    cut_mean = float(np.mean([e["m"]["cut_volume"] for e in eps]))
    for k in COLS:
        y = np.array([e["m"][k] for e in eps], float)
        sl, se = slope(x, y)
        bsl = []
        for _ in range(NBOOT):
            idx = np.concatenate([rng.choice(np.flatnonzero(x == s), (x == s).sum()) for s in levels])
            bsl.append(slope(x[idx], y[idx])[0])
        seb = float(np.std(bsl, ddof=1))
        sem = max(se, seb)
        p(f"| {k} | {sl:+.4f} | {se:.4f} | {seb:.4f} | {sl / sem:+.2f} | {'はい' if abs(sl) >= 2 * sem else 'いいえ'} | {sl / cut_mean:+.3f} |")
    p(f"\n平均の cut_volume：{cut_mean:.3f} m³\n")
    p("## 4. 走行中の vis_net の推移（距離 2 m ごとの最後の値、s ごとの平均）\n")
    marks = [2, 4, 6, 8, 10]
    p("| s | " + " | ".join(f"{d} m の vis_net（cut_volume）" for d in marks) + " |")
    p("|---|" + "---|" * len(marks))
    for s in levels:
        g = [e for e in eps if e["s"] == s]
        cells = []
        for d in marks:
            vv, cc = [], []
            for e in g:
                r = e["run"][e["run"]["distance"] <= d]
                if len(r):
                    vv.append(r["vis_net"].iloc[-1]); cc.append(r["cut_volume"].iloc[-1])
            cells.append(f"{np.mean(vv):.3f}（{np.mean(cc):.3f}）" if vv else "—")
        p(f"| {s:.2f} | " + " | ".join(cells) + " |")
    p("")
    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
