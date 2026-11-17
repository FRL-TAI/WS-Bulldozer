"""
フェーズ1：貫入抵抗の段差が「ワールドの位置」で決まるか「削り始めからの距離」で決まるかの確認。
削り始める位置を ±2 m ずらした記録（ex_step_shift_p2・m2）と、flat_cut の基準（ex_ident_flat_cut_base）を比べる。

置き場所: analysis/phase1/check_step_shift.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_step_shift.py \
      --base "data/phase1/flat_cut/run_*" --shift "data/phase1/step_shift/run_*" \
      [--report 結果.md] [--csv 記録ごとの値.csv]

段差の見つけ方（場所を仮定しない）
  - 削り始め：目標深さが正の行で、前進の速さが初めて 0.02 m/s を超えた行。その直前の刃先の位置を x_cut とし、
    削り始めからの距離 s = edge_x − x_cut とする。走り出しの 1.5 秒（SETTLE）は除く。
  - −F_pen_x の移動中央値（9 行）について、s_c の前（s_c − 0.9〜−0.2 m）と後（+0.2〜+0.9 m）の中央値の差が
    最大になる s_c を、s = 1.5 m〜（最後 − 1 m）で 0.025 m ごとに探す。
  - 段差の位置は、s_c ± 0.5 m の中で、移動中央値が前後の中央値の中点を初めて超える点とする（T2 と同じ定義）。
  - 前後の差は、段差の位置から前 −0.34〜−0.06 m、後 +0.06〜+0.34 m の平均の差（T2 の窓
    edge_x −0.6〜−0.32 m・−0.2〜+0.08 m を、段差の位置 −0.26 m からの相対にしたもの）。−F_x・−F_z も同じ窓で求める。
  - 道のり：走行中（phase running）の機体の位置 x・y の移動量の積算。m2 では後退した 2 m を含む。
"""
import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "validation"))
from check_physics import SETTLE   # noqa: E402

V_GO = 0.02                       # 走り出したとみなす速さ [m/s]
MED_ROWS = 9                      # 移動中央値の行数（T2 と同じ）
SCAN_PRE, SCAN_POST = (-0.9, -0.2), (0.2, 0.9)       # 段差を探す前後の窓 [m]（s_c からの相対）
DIFF_PRE, DIFF_POST = (-0.34, -0.06), (0.06, 0.34)   # 前後の差の窓 [m]（段差の位置からの相対）


def episode_files(patterns, prefixes):
    out = []
    for p in patterns:
        for d in sorted(glob.glob(p)):
            jl = os.path.join(d, "episodes.jsonl")
            if not os.path.exists(jl):
                continue   # 収集が始まる前に止まった run（config.json だけ）は読み飛ばす
            with open(jl, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line) if line.strip() else None
                    if r and str(r.get("status")) == "ok" and r["episode_name"] in prefixes:
                        out.append((r["episode_name"], os.path.join(d, r["file"])))
    return out


def analyse(path):
    d = pd.read_csv(path)
    run = d[d["phase"] == "running"].reset_index(drop=True)
    path_len = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(run["x"]), np.diff(run["y"])))])
    cut = run["target_depth"].to_numpy() > 0
    go = np.flatnonzero(cut & (run["v_forward"].to_numpy() > V_GO))
    i_go = int(go[0])
    x_cut = float(run["edge_x"].iloc[i_go - 1] if i_go > 0 and cut[i_go - 1] else run["edge_x"].iloc[i_go])
    t_go = float(run["t"].iloc[i_go])
    keep = (np.arange(len(run)) >= i_go) & cut & (run["t"].to_numpy() >= t_go + SETTLE)
    r = run[keep].reset_index(drop=True)
    s = (r["edge_x"] - x_cut).to_numpy()
    pen = (-r["F_pen_x"] / 1000).to_numpy()
    fx = (-r["F_total_x"] / 1000).to_numpy()
    fz = (-r["F_total_z"] / 1000).to_numpy()
    med = pd.Series(pen).rolling(MED_ROWS, center=True, min_periods=1).median().to_numpy()

    best = None
    for sc in np.arange(1.5, s.max() - 1.0, 0.025):
        a = med[(s >= sc + SCAN_PRE[0]) & (s <= sc + SCAN_PRE[1])]
        b = med[(s >= sc + SCAN_POST[0]) & (s <= sc + SCAN_POST[1])]
        if len(a) < 5 or len(b) < 5:
            continue
        diff = np.median(b) - np.median(a)
        if best is None or diff > best[0]:
            best = (diff, sc, np.median(a), np.median(b))
    _, sc, lo, hi = best
    win = np.flatnonzero((s >= sc - 0.5) & (s <= sc + 0.5) & (med > (lo + hi) / 2))
    j = int(win[0])
    s_step = float(s[j])

    def step_of(v):
        a = v[(s >= s_step + DIFF_PRE[0]) & (s <= s_step + DIFF_PRE[1])]
        b = v[(s >= s_step + DIFF_POST[0]) & (s <= s_step + DIFF_POST[1])]
        return float(a.mean()), float(b.mean())

    p0, p1 = step_of(pen)
    x0, x1 = step_of(fx)
    z0, z1 = step_of(fz)
    i_run = int(np.flatnonzero(keep)[j])
    return {
        "x_start": float(run["edge_x"].iloc[0]), "x_cut": x_cut, "cut_length": float(s.max()),
        "edge_min": float(run["edge_x"].min()), "edge_max": float(run["edge_x"].max()),
        "s_step": s_step, "edge_step": float(r["edge_x"].iloc[j]), "path_step": float(path_len[i_run]),
        "pen_pre": p0, "pen_post": p1, "pen_ratio": p1 / p0 if p0 > 0 else float("nan"),
        "dFx": x1 - x0, "dFz": z1 - z0,
    }


def main():
    ap = argparse.ArgumentParser(description="貫入抵抗の段差が位置で決まるか距離で決まるかの確認")
    ap.add_argument("--base", nargs="+", required=True, help="flat_cut の基準の run（ex_ident_flat_cut_base を読む）")
    ap.add_argument("--shift", nargs="+", required=True, help="ex_step_shift_* の run")
    ap.add_argument("--report")
    ap.add_argument("--csv")
    a = ap.parse_args()

    groups = {"ex_ident_flat_cut_base": "基準（ずらさない）", "ex_step_shift_p2": "+2 m", "ex_step_shift_m2": "−2 m"}
    files = episode_files(a.base, ["ex_ident_flat_cut_base"]) + episode_files(a.shift, ["ex_step_shift_p2", "ex_step_shift_m2"])
    rows = []
    for name, f in files:
        rec = analyse(f)
        rec.update({"episode": name, "file": os.path.relpath(f)})
        rows.append(rec)
    df = pd.DataFrame(rows)
    if a.csv:
        df.to_csv(a.csv, index=False)

    base = df[df["episode"] == "ex_ident_flat_cut_base"]
    e_base, s_base = base["edge_step"].median(), base["s_step"].median()
    L = ["# 貫入抵抗の段差の位置（開始位置をずらした記録）", "",
         f"基準 {len(base)} 本の段差：削り始めからの距離 {s_base:.2f} m（中央値）、edge_x {e_base:.2f} m（中央値）。", "",
         "## 条件ごと（中央値、括弧内は最小〜最大）", "",
         "| 条件 | 本数 | 削り始めの edge_x [m] | 削った距離 [m] | 段差の距離 s [m] | 段差の edge_x [m] | 道のり [m] | 位置で決まる場合の s [m] | 距離で決まる場合の s [m] | −F_pen_x 前 → 後 [kN] | 比 | Δ(−F_x) [kN] | Δ(−F_z) [kN] |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]

    def rng(v, f="{:.2f}"):
        return f"{f.format(v.median())}（{f.format(v.min())}〜{f.format(v.max())}）"

    for key, label in groups.items():
        g = df[df["episode"] == key]
        if g.empty:
            continue
        L.append(f"| {label} | {len(g)} | {rng(g['x_cut'])} | {rng(g['cut_length'])} | {rng(g['s_step'])} | {rng(g['edge_step'])} | "
                 f"{rng(g['path_step'])} | {e_base - g['x_cut'].median():.2f} | {s_base:.2f} | "
                 f"{g['pen_pre'].median():.2f} → {g['pen_post'].median():.2f} | {g['pen_ratio'].median():.2f} | "
                 f"{rng(g['dFx'])} | {rng(g['dFz'])} |")
    L += ["", "## 記録ごと", "",
          "| 条件 | 記録 | 削り始めの edge_x | 削った距離 | edge_x の範囲 | 段差の s | 段差の edge_x | 道のり | −F_pen_x 前 → 後 | Δ(−F_x) | Δ(−F_z) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        L.append(f"| {groups[r['episode']]} | {os.path.basename(r['file'])} | {r['x_cut']:.2f} | {r['cut_length']:.2f} | "
                 f"{r['edge_min']:.2f}〜{r['edge_max']:.2f} | {r['s_step']:.2f} | {r['edge_step']:.2f} | {r['path_step']:.2f} | "
                 f"{r['pen_pre']:.2f} → {r['pen_post']:.2f} | {r['dFx']:+.2f} | {r['dFz']:+.2f} |")
    text = "\n".join(L) + "\n"
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    main()
