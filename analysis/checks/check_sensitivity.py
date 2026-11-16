"""
関門6（再現性と識別可能性）の点検。val_sens_* の結果から、エピソードごとの特徴量を求め、
同じ条件の繰り返しのばらつき（再現性）と、土質・速度を変えたときの変化（識別可能性）を比べる。

置き場所: src/bull_ope/analysis/checks/check_sensitivity.py（check_physics.py と同じ場所）
使い方:
  cd /workspaces/ws-bulldozer/src/bull_ope
  python3 analysis/checks/check_sensitivity.py <collect_data の出力フォルダ> [...] [--report 結果.md] [--plot 図.png]

特徴量（走行中の行を距離 0.625 m ごとに平均してから求める。関門5と同じ）
  kx      前後の力の傾き [kN/m³]（削った体積 V < 1.0 m³ で −F_x = ax + kx V と近似）
  ax      前後の力の切片 [kN]（削り始めの抵抗）
  kz      上下の力の傾き [kN/m³]（同じく −F_z）
  kz/kx   土の山の分の、上下と前後の力の比
  Fx_sat  頭打ちの前後の力 [kN]（V > 2.0 m³ の平均）
  Fz_sat  頭打ちの上下の力 [kN]
  Fpen    貫入抵抗の平均 [kN]（−F_pen_x）
  kx_pred 関門5の式 ρ g tanφ による傾きの予測 [kN/m³]（比べるための参考）

判定（条件ごと、特徴量ごと）
  z = （その条件の平均 − 基準の平均）÷ 基準の繰り返しの標準偏差
  |z| ≥ 3 なら「区別できる」、|z| < 3 なら「区別できない」とみなす（繰り返しの数が少ないので目安）
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_physics import G, binned, list_targets, settled_cut_rows   # noqa: E402

V_LIN = 1.0       # 直線の領域の上限 [m³]
V_SAT = 2.0       # 頭打ちの領域の下限 [m³]
Z_DIST = 3.0      # 区別できるとみなす |z|
FEATURES = ["kx", "ax", "kz", "kz/kx", "Fx_sat", "Fz_sat", "Fpen"]


def features(df):
    rows = settled_cut_rows(df)
    if rows is None:
        return None
    b = binned(rows)
    f = {}
    lo = b[b["V"] < V_LIN]
    if len(lo) >= 3:
        kx, ax = np.polyfit(lo["V"], -lo["Fx"], 1)
        kz, _ = np.polyfit(lo["V"], -lo["Fz"], 1)
        f.update(kx=kx / 1000, ax=ax / 1000, kz=kz / 1000, **{"kz/kx": kz / kx})
    hi = b[b["V"] > V_SAT]
    if len(hi) >= 2:
        f.update(Fx_sat=-hi["Fx"].mean() / 1000, Fz_sat=-hi["Fz"].mean() / 1000)
    f["Fpen"] = -rows["F_pen_x"].mean() / 1000
    first = df.iloc[0]
    rho, phi = float(first["label_rho0"]), float(first["label_phi"])
    f["kx_pred"] = rho * G * np.tan(np.radians(phi)) / 1000
    f["c"], f["phi"], f["rho"] = float(first["label_c"]), phi, rho
    f["speed"] = float(rows["cmd_vx"].median())
    return f


def main():
    ap = argparse.ArgumentParser(description="関門6（再現性と識別可能性）の点検")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--base", default="val_sens_base", help="基準の条件のエピソード名")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル名")
    ap.add_argument("--plot", help="図を保存するファイル名（matplotlib が必要）")
    a = ap.parse_args()

    recs = []
    for path in list_targets(a.paths):
        df = pd.read_csv(path)
        if "sim_time" not in df:
            continue
        f = features(df)
        if f is not None:
            f["name"] = str(df["episode_name"].iloc[0])
            f["file"] = os.path.basename(path)
            recs.append(f)
    if not recs:
        print("削るエピソードがありません")
        return
    t = pd.DataFrame(recs)

    lines = ["# 関門6の点検（再現性と識別可能性）", ""]

    def out(s=""):
        print(s)
        lines.append(s)

    # 1. 再現性（基準の繰り返し）
    base = t[t["name"] == a.base]
    out(f"## 1. 再現性（{a.base} × {len(base)} 回）")
    out("")
    out("| 特徴量 | 平均 | 標準偏差 | 変動係数 |")
    out("| --- | --- | --- | --- |")
    sigma = {}
    for k in FEATURES + ["kx_pred"]:
        v = base[k].dropna() if k in base else pd.Series(dtype=float)
        if len(v) >= 2:
            sigma[k] = v.std(ddof=1)
            cv = sigma[k] / abs(v.mean()) if v.mean() != 0 else float("nan")
            out(f"| {k} | {v.mean():.3f} | {sigma[k]:.3f} | {cv * 100:.1f}% |")
        else:
            out(f"| {k} | — | — | — |")
    out("")

    # 2. 条件ごとの平均
    out("## 2. 条件ごとの平均（回数）")
    out("")
    cols = ["c", "phi", "rho", "speed"] + FEATURES + ["kx_pred"]
    g = t.groupby("name")
    means = g[cols].mean()
    out("| 条件 | 回数 | c [Pa] | φ [°] | ρ [kg/m³] | 速度 [m/s] | " + " | ".join(FEATURES) + " | kx_pred | kx ÷ kx_pred |")
    out("| --- | --- | --- | --- | --- | --- | " + " | ".join("---" for _ in FEATURES) + " | --- | --- |")
    for name, m in means.iterrows():
        n = int(g.size()[name])
        vals = " | ".join("—" if pd.isna(m[k]) else f"{m[k]:.2f}" for k in FEATURES)
        ratio = m["kx"] / m["kx_pred"] if not pd.isna(m["kx"]) else float("nan")
        out(f"| {name} | {n} | {m['c']:.0f} | {m['phi']:.2f} | {m['rho']:.0f} | {m['speed']:.2f} | {vals} | {m['kx_pred']:.1f} | {ratio:.2f} |")
    out("")

    # 3. 基準との差（z）
    if a.base in means.index and sigma:
        out(f"## 3. 基準との差 z =（平均 − 基準の平均）÷ 基準の標準偏差（|z| ≥ {Z_DIST:.0f} を太字）")
        out("")
        out("| 条件 | " + " | ".join(FEATURES) + " |")
        out("| --- | " + " | ".join("---" for _ in FEATURES) + " |")
        b0 = means.loc[a.base]
        for name, m in means.iterrows():
            if name == a.base:
                continue
            cells = []
            for k in FEATURES:
                if k not in sigma or sigma[k] == 0 or pd.isna(m[k]) or pd.isna(b0[k]):
                    cells.append("—")
                    continue
                z = (m[k] - b0[k]) / sigma[k]
                pct = (m[k] - b0[k]) / abs(b0[k]) * 100 if b0[k] != 0 else float("nan")
                s = f"{z:+.1f}（{pct:+.0f}%）"
                cells.append(f"**{s}**" if abs(z) >= Z_DIST else s)
            out(f"| {name} | " + " | ".join(cells) + " |")
        out("")

    out("## エピソードごとの特徴量")
    out("")
    out("| ファイル | 条件 | " + " | ".join(FEATURES) + " |")
    out("| --- | --- | " + " | ".join("---" for _ in FEATURES) + " |")
    for _, r in t.sort_values(["name", "file"]).iterrows():
        out(f"| {r['file']} | {r['name']} | " + " | ".join("—" if pd.isna(r.get(k)) else f"{r[k]:.2f}" for k in FEATURES) + " |")

    if a.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib がないため図は作らない")
        else:
            fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
            for name, d in t.groupby("name"):
                ax[0].plot(d["kx_pred"], d["kx"], "o", label=name)
                ax[1].plot(d["kx"], d["Fx_sat"], "o", label=name)
                ax[2].plot(d["kx"], d["kz/kx"], "o", label=name)
            lim = [0, max(t["kx_pred"].max(), t["kx"].max()) * 1.1]
            ax[0].plot(lim, lim, "k--", lw=1)
            ax[0].set_xlabel("rho g tan(phi) [kN/m3]")
            ax[0].set_ylabel("kx [kN/m3]")
            ax[1].set_xlabel("kx [kN/m3]")
            ax[1].set_ylabel("Fx_sat [kN]")
            ax[2].set_xlabel("kx [kN/m3]")
            ax[2].set_ylabel("kz/kx")
            for x in ax:
                x.grid(alpha=0.3)
            ax[2].legend(fontsize=7, loc="best")
            fig.tight_layout()
            fig.savefig(a.plot, dpi=100)
            print(f"\n図を保存しました: {a.plot}")

    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"レポートを保存しました: {a.report}")


if __name__ == "__main__":
    main()