"""
粒子を含む前方の高さの列（ground_terrain_* / ground_vis_* / ground_ptop_*）を確かめる（T23）。

置き場所: analysis/phase1/check_forward_height.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_forward_height.py 'data/phase1/forward_height/run_*/ep[0-9]*.csv' [--report 結果.md]

記録の列（BladeStatePublisher.cs。中身は docs/bull_ope/output_data.md の「前方の地面の高さの列」）:
  ground_profile_XXXcm（TerrainData）、ground_terrain_XXXcm（AGX の地形の高さ）、ground_vis_XXXcm（粒子を含む高さ）、
  ground_ptop_XXXcm（確かめ用の粒子の上端）。XXX = 025〜200（25 cm ごと）

出すもの（エピソードごと。走行中で距離 5 m 以降の行）:
  1. 深さのずれ |depth − target_depth| の 95% 点（check_physics.settled_cut_rows の行。関門3 の U3）
  2. 点ごとの h − ground_h0 の中央値／最大、粒子を含む高さが地形より 1 mm 以上高い行の割合、
     |terrain − profile| の中央値／最大、vis − ptop の中央値
  3. 中心線の断面から幅一様として求めた体積の目安（2.96 m × 0.25 m × Σ max(h − h0, 0)）と V_pile の比較
  4. 8点の最大の高さ、NaN の行、粒子の数、粒子のうち「排土板の上端〜刃先の前 0.5 m」にある割合
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "validation"))
from check_physics import settled_cut_rows  # noqa: E402

D = [25, 50, 75, 100, 125, 150, 175, 200]
W = 2.96            # 排土板の幅 [m]（体積の目安に使う）
MIN_DIST = 5.0      # 走行距離がこれ [m] 以降の行を使う（T22 と同じ）


def main():
    ap = argparse.ArgumentParser(description="粒子を含む前方の高さの列の確認（T23）")
    ap.add_argument("paths", nargs="+", help="エピソードの CSV（glob 可）")
    ap.add_argument("--report")
    a = ap.parse_args()
    files = sorted(f for p in a.paths for f in glob.glob(p))
    out = []
    p = out.append
    p("# 粒子を含む前方の高さの列の確認（T23）\n")
    for path in files:
        df = pd.read_csv(path)
        h0 = df["ground_h0"].iloc[0]
        rows = settled_cut_rows(df)
        dev95 = float(np.percentile(np.abs(rows["depth"] - rows["target_depth"]), 95)) if rows is not None else np.nan
        run = df[(df["phase"] == "running") & (df["distance"] > MIN_DIST)]
        p(f"## {os.path.basename(path)}\n")
        p(f"走行中（{MIN_DIST:.0f} m 以降）{len(run)} 行、深さのずれの 95% 点 {dev95 * 100:.2f} cm\n")
        p("| 点 | profile 中央値/最大 [cm] | terrain | vis | ptop | vis > terrain + 1 mm の行 | |terrain − profile| 中央値/最大 [mm] | vis − ptop 中央値 [cm] |")
        p("|---|---|---|---|---|---|---|---|")
        for d in D:
            c = f"{d:03d}cm"
            pr, te, vi, pt = (run[f"ground_{k}_{c}"] - h0 for k in ("profile", "terrain", "vis", "ptop"))
            f = lambda s: f"{s.median() * 100:.1f} / {s.max() * 100:.1f}"  # noqa: E731
            dtp = (run[f"ground_terrain_{c}"] - run[f"ground_profile_{c}"]).abs()
            p(f"| {d} cm | {f(pr)} | {f(te)} | {f(vi)} | {f(pt)} | {(vi > te + 1e-3).mean():.0%} | "
              f"{dtp.median() * 1000:.2f} / {dtp.max() * 1000:.1f} | {(vi - pt).median() * 100:.1f} |")

        def vol(k):
            return W * 0.25 * sum(np.clip(run[f"ground_{k}_{d:03d}cm"] - h0, 0, None) for d in D)
        Vv, Vt = vol("vis"), vol("terrain")
        pv = run["pile_volume"]
        p(f"\n- V_pile 中央値 {pv.median():.3f} m³（地形 {run['pile_vol_terrain'].median():.3f}、粒子 {run['pile_vol_dynamic'].median():.3f}、"
          f"粒子の割合 {(run['pile_vol_dynamic'] / pv).median():.2f}）")
        p(f"- 中心線からの体積の目安：vis {Vv.median():.3f}・terrain {Vt.median():.3f} m³。vis ÷ V_pile 中央値 {(Vv / pv).median():.2f}、"
          f"terrain ÷ pile_vol_terrain {(Vt / run['pile_vol_terrain']).median():.2f}、相関（vis の目安と V_pile）{np.corrcoef(Vv, pv)[0, 1]:.2f}")
        mv = run[[f"ground_vis_{d:03d}cm" for d in D]].max(axis=1) - h0
        mt = run[[f"ground_terrain_{d:03d}cm" for d in D]].max(axis=1) - h0
        p(f"- 8点の最大 − h0（中央値/最大）：vis {mv.median() * 100:.1f} / {mv.max() * 100:.1f} cm、terrain {mt.median() * 100:.1f} / {mt.max() * 100:.1f} cm")
        nan_v = df[[f"ground_vis_{d:03d}cm" for d in D]].isna().any(axis=1).sum()
        nan_p = df[[f"ground_ptop_{d:03d}cm" for d in D]].isna().any(axis=1).sum()
        near = (run["dyn_mass_particle_near"] / run["pile_mass_particle"]).median()
        p(f"- NaN の行：vis {nan_v}、ptop {nan_p}。粒子の数（中央値/最大）{run['dyn_num_particles'].median():.0f} / {run['dyn_num_particles'].max():.0f}、"
          f"粒子のうち上端〜刃先の前 0.5 m にある割合 {near:.2f}、ground_h0 − terrain_200cm {(h0 - run['ground_terrain_200cm'].iloc[0]) * 1000:.2f} mm\n")
    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
