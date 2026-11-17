"""
フェーズ1（T14）：排土板の前の土の質量・体積（front_*）と掘削体積（excavated_volume_step）の確かめ。

置き場所: analysis/phase1/check_front_soil.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_front_soil.py "data/phase1/front_soil/run_*" [--report 結果.md] [--fig 図.png]

Unity の BladeStatePublisher が AGX 2.37 の Terrain の API で出す列（docs/bull_ope/output_data.md）：
  front_soil_mass          getSoilAggregateMass(shovel, PRIMARY)   土塊の質量 [kg]（PRIMARY では inner shape の分を含む）
  front_soil_mass_deform   getSoilAggregateMass(shovel, DEFORM_*)  の3つの和 [kg]
  front_dynamic_mass       getDynamicMass(shovel)                  inner shape の中の動く土の質量 [kg]
  front_inner_volume       getInnerVolume(shovel)                  inner shape の体積 [m3]
  front_dead_load_fraction getLastDeadLoadFraction(shovel)         inner shape のうち動く土の割合 [-]
  excavated_volume_step    getLastExcavatedVolume()                直前のステップに地形全体で掘削された体積 [m3]

比べるもの：
  flat_cut  ：front_soil_mass を cut_volume × ρ（地山を削った質量の積算）と、
              excavated_volume_step の積算を cut_volume と比べる（走行距離ごと）。
  pile_push ：山（長さ × 3.0 m × 高さ、緩い状態の体積。密度 ρ/s）の質量と比べる。
              押している土の質量 ≈ 山の質量のうち刃先が通り過ぎた分 + cut_volume × ρ になるはず。
"""
import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

COLS = ["front_soil_mass", "front_soil_mass_deform", "front_dynamic_mass", "front_inner_volume",
        "front_dead_load_fraction", "excavated_volume_step"]
PILE_WIDTH = 3.0   # m（ex_ident_pile_push・dataset_pile_push の山の幅）


def load(patterns):
    eps = []
    for p in patterns:
        for d in sorted(glob.glob(p)):
            f = os.path.join(d, "episodes.jsonl")
            if not os.path.exists(f):
                continue
            for line in open(f, encoding="utf-8"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("status") != "ok":
                    continue
                df = pd.read_csv(os.path.join(d, r["file"]))
                eps.append((r, df))
    return eps


def at_distance(run, dists):
    """走行距離が初めて d 以上になった行"""
    out = []
    for d in dists:
        i = np.searchsorted(run["distance"].to_numpy(), d)
        out.append(run.iloc[min(i, len(run) - 1)])
    return out


def summarize(r, df):
    rho, s = r["label_rho0"], r["label_swell"]
    missing = [c for c in COLS if c not in df.columns]
    if missing:
        return None, f"列がない: {missing}"
    nan = {c: int(df[c].isna().sum()) for c in COLS}
    # 掘削体積の積算（lowering から。lowering でも刃先は地面に入る）
    df = df.copy()
    df["excavated_cum"] = df["excavated_volume_step"].fillna(0).cumsum()
    # 記録は 50 Hz で AGX のステップと同じ周期（関門2）。ステップを飛ばすと積算が少なくなる
    run = df[df["phase"] == "running"].reset_index(drop=True)
    is_pile = "pile_push" in r["episode_name"]
    if is_pile:
        p_len, p_h, p_start = r["param_pile_length"], r["param_pile_height"], r["param_pile_start"]
        pile_mass = p_len * PILE_WIDTH * p_h * rho / s
        dists = [1.0, p_start, p_start + 0.5 * p_len, p_start + p_len, p_start + p_len + 2, run["distance"].max() - 0.1]
    else:
        pile_mass = 0.0
        p_start = p_len = None
        dists = [1.0, 2.5, 5.0, 7.5, run["distance"].max() - 0.1]
    rows = []
    for d, row in zip(dists, at_distance(run, dists)):
        passed = 0.0
        if is_pile:
            # 刃先が通り過ぎた山の長さ（開始時の刃先からの距離 ≈ 走行距離）
            passed = np.clip(row["distance"] - p_start, 0, p_len) / p_len * pile_mass
        rows.append({
            "distance": row["distance"], "t": row["t"],
            **{c: row[c] for c in COLS},
            "excavated_cum": row["excavated_cum"], "cut_volume": row["cut_volume"],
            "cut_mass": row["cut_volume"] * rho, "pile_passed_mass": passed,
            "expected_mass": row["cut_volume"] * rho + passed,
        })
    summ = {
        "name": r["episode_name"], "file": r["file"], "rho": rho, "swell": s, "pile_mass": pile_mass,
        "nan": nan, "rows": rows,
        "max_front_soil_mass": float(run["front_soil_mass"].max()),
        "max_front_dynamic_mass": float(run["front_dynamic_mass"].max()),
        "inner_volume_range": (float(run["front_inner_volume"].min()), float(run["front_inner_volume"].max())),
        "excavated_cum_end": float(df["excavated_cum"].iloc[-1]),
        "cut_volume_end": float(run["cut_volume"].iloc[-1]),
        "excavated_nonzero_frac": float((df["excavated_volume_step"].fillna(0) != 0).mean()),
    }
    return summ, None


def fmt(v, nd=1):
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{nd}f}"


def report(summs):
    L = []
    for sm in summs:
        L.append(f"### {sm['name']}（{sm['file']}）")
        L.append(f"- ρ {sm['rho']:.0f}、s {sm['swell']:.2f}、山の質量 {sm['pile_mass']:.0f} kg")
        L.append(f"- NaN の行数: {sm['nan']}")
        L.append(f"- running 中の最大：front_soil_mass {sm['max_front_soil_mass']:.0f} kg、"
                 f"front_dynamic_mass {sm['max_front_dynamic_mass']:.0f} kg、"
                 f"front_inner_volume {sm['inner_volume_range'][0]:.3f}〜{sm['inner_volume_range'][1]:.3f} m³")
        L.append(f"- 最後の行：excavated_volume_step の積算 {sm['excavated_cum_end']:.3f} m³、"
                 f"cut_volume {sm['cut_volume_end']:.3f} m³（比 {sm['excavated_cum_end'] / sm['cut_volume_end']:.3f}）、"
                 f"excavated_volume_step が 0 でない行の割合 {sm['excavated_nonzero_frac']:.2f}")
        L.append("")
        L.append("| 走行距離 [m] | front_soil_mass [kg] | deform [kg] | dynamic [kg] | inner_volume [m³] | dead_load | "
                 "掘削体積の積算 [m³] | cut_volume [m³] | cut_volume×ρ [kg] | 通り過ぎた山 [kg] | 見込み [kg] | front_soil_mass ÷ 見込み |")
        L.append("|" + "---|" * 12)
        for rw in sm["rows"]:
            ratio = rw["front_soil_mass"] / rw["expected_mass"] if rw["expected_mass"] > 0 else float("nan")
            L.append(f"| {rw['distance']:.2f} | {fmt(rw['front_soil_mass'])} | {fmt(rw['front_soil_mass_deform'])} | "
                     f"{fmt(rw['front_dynamic_mass'])} | {fmt(rw['front_inner_volume'], 3)} | {fmt(rw['front_dead_load_fraction'], 3)} | "
                     f"{fmt(rw['excavated_cum'], 3)} | {fmt(rw['cut_volume'], 3)} | {fmt(rw['cut_mass'])} | "
                     f"{fmt(rw['pile_passed_mass'])} | {fmt(rw['expected_mass'])} | {fmt(ratio, 2)} |")
        L.append("")
    return "\n".join(L)


def figure(eps, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    for r, df in eps:
        run = df[df["phase"] == "running"]
        rho = r["label_rho0"]
        lbl = r["episode_name"].replace("ex_ident_", "")
        l, = axes[0].plot(run["distance"], run["front_soil_mass"], label=f"{lbl} front_soil_mass")
        axes[0].plot(run["distance"], run["front_dynamic_mass"], ls=":", color=l.get_color(), label=f"{lbl} front_dynamic_mass")
        axes[0].plot(run["distance"], run["cut_volume"] * rho, ls="--", color=l.get_color(), label=f"{lbl} cut_volume×ρ")
        exc = df["excavated_volume_step"].fillna(0).cumsum()[run.index]
        axes[1].plot(run["distance"], exc, color=l.get_color(), label=f"{lbl} excavated_volume_step の積算")
        axes[1].plot(run["distance"], run["cut_volume"], ls="--", color=l.get_color(), label=f"{lbl} cut_volume")
    axes[0].set_ylabel("質量 [kg]")
    axes[1].set_ylabel("体積 [m³]")
    axes[1].set_xlabel("走行距離 [m]")
    for a in axes:
        a.legend(fontsize=7)
        a.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--report")
    ap.add_argument("--fig")
    a = ap.parse_args()
    eps = load(a.runs)
    summs = []
    for r, df in eps:
        sm, err = summarize(r, df)
        if err:
            print(f"{r['episode_name']}: {err}")
            continue
        summs.append(sm)
    text = report(summs)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("# check_front_soil の結果\n\n" + text + "\n")
    if a.fig:
        figure(eps, a.fig)


if __name__ == "__main__":
    main()
