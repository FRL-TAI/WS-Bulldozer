"""
土の山の体積 V_pile（地形の高さ ＋ 動く土 ÷ (ρ/s)）を、cut_volume・front_soil_mass と比べ、
関門5 の実効の摩擦係数（−F_x = a + b·M·g の傾き b）を3つの質量で出し直す（T15）。

置き場所: analysis/phase1/check_pile_volume.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_pile_volume.py data/phase1/pile_volume/run_<日時>_t15 \
      --report data/phase1/pile_volume/check_pile_volume.md --fig data/phase1/pile_volume/pile_volume.png

記録の列（BladeStatePublisher.cs の PileVolume）:
  pile_volume（V_pile）、pile_vol_terrain・pile_vol_dynamic（その内訳）、pile_vol_terrain_setup（h0 を山を含む地形にした場合）、
  pile_volume_front150・front250・wide・ridge（感度用）、pile_bulk_density（ρ/s）、dyn_*（動く土の合計）、bal_*（収支の確認用、0.5 s ごと）

出すもの:
  1. 比較        走行距離ごとに、M_pile = V_pile·ρ/s、cut_volume·ρ、front_soil_mass（pile_push は触れていない山の分も）
  2. 範囲        刃先の前 2.0 m の地面の高さ − 開始時の高さ（中心線）、前 1.5・2.5 m・横に広げたときの V_pile の変化 [%]
  3. 密度        排土板を上げている間の「動く土の減り ÷ (ρ/s)」と「地形の体積の増え」
  4. 質量の収支  cut_volume·ρ と M_pile ＋ 横の畝の質量、広い窓での削った分・積もった分
  5. 関門5       val_constant_depth* を check_physics.py と同じ処理（0.625 m ごとの平均、走り出しから 1.5 s を除く）で、
                 −F_x = a + b·M·g の b を M = cut_volume·ρ、M_pile、M_pile ＋ 横の畝、front_soil_mass で求める
                 （直線の領域 V < 1.0 m³ と全体。残差の RMS も。横の範囲の見直しの基準は decisions/2026-11-17_V_pileの横の範囲は排土板の幅のままにする.md）
  6. 膨張率ごと  --swell に T17 の記録（ex_ident_*_s_* と ex_swell_flat_cut_s110）を渡すと、作業・膨張率の点ごとに M_pile での b を求める
                 （ρ/s の換算が合っていれば、b は s によらない。T18）。--paths の ex_ident_*_base も基準として並べる
"""
import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "validation"))
from check_physics import BIN, list_targets, settled_cut_rows   # noqa: E402

G = 9.81
GATE5_REF = 0.878            # 関門5 の実効の摩擦係数（cut_volume、直線の領域）
GATE5_BAND = (0.79, 0.97)    # ±10%
LINEAR_V = 1.0               # 直線の領域：cut_volume < 1.0 m³（関門5 と同じ）
DIST_SHOW = [1, 2, 3, 4, 6, 8, 10, 12, 14]
COLORS = {"pile": "#2a78d6", "cut": "#eb6834", "front": "#1baf7a", "untouched": "#eda100"}


def load(paths):
    eps = []
    for p in list_targets(paths):
        df = pd.read_csv(p)
        if "pile_volume" not in df:
            continue
        df["rho_s"] = df["pile_bulk_density"]
        df["M_pile"] = df["pile_volume"] * df["rho_s"]
        df["M_cut"] = df["cut_volume"] * df["label_rho0"]
        df["M_untouched"] = (df["pile_vol_terrain"] - df["pile_vol_terrain_setup"]) * df["rho_s"]
        df["M_ridge"] = df["pile_volume_ridge"] * df["rho_s"]
        eps.append((os.path.basename(p), str(df["episode_name"].iloc[0]), df))
    return eps


def at_distance(df, dists):
    run = df[df["phase"] == "running"]
    rows = []
    for d in dists:
        if run["distance"].max() < d - 0.05:
            continue
        rows.append(run.iloc[int(np.argmin(np.abs(run["distance"].to_numpy() - d)))])
    return pd.DataFrame(rows)


def gate5_bins(df):
    rows = settled_cut_rows(df)
    if rows is None:
        return None
    key = np.floor(rows["distance"] / BIN).astype(int).astype(str) + "_" + rows["target_depth"].round(4).astype(str)
    b = pd.DataFrame({"key": key, "Fx": rows["F_total_x"], "V": rows["cut_volume"], "M_cut": rows["M_cut"],
                      "M_pile": rows["M_pile"], "M_pile_ridge": rows["M_pile"] + rows["M_ridge"],
                      "M_front": rows["front_soil_mass"]})
    return b.groupby("key", sort=False).mean(numeric_only=True)


def slope(m, fx, rms=False):
    m, fx = np.asarray(m, float), np.asarray(fx, float)
    ok = np.isfinite(m) & np.isfinite(fx)
    if ok.sum() < 3:
        return (float("nan"),) * (4 if rms else 3)
    b, a = np.polyfit(m[ok] * G, -fx[ok], 1)
    r = np.corrcoef(m[ok], -fx[ok])[0, 1]
    if rms:
        res = -fx[ok] - (a + b * m[ok] * G)
        return a, b, r, float(np.sqrt(np.mean(res ** 2)))
    return a, b, r


def main():
    ap = argparse.ArgumentParser(description="土の山の体積の比較と関門5 の出し直し（T15）")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--swell", nargs="*", default=[], help="T17 の記録（6. 膨張率ごとの係数）")
    ap.add_argument("--report")
    ap.add_argument("--fig")
    a = ap.parse_args()
    lines = ["# 土の山の体積の確認（T15）", ""]

    def out(s=""):
        print(s)
        lines.append(s)

    eps = load(a.paths)
    if not eps:
        out("pile_volume の列がある記録がありません")
        return
    rho_s = float(eps[0][2]["rho_s"].iloc[-1])
    out(f"ρ/s = {rho_s:.1f} kg/m³（dirt_1）。M_pile = V_pile·ρ/s、M_cut = cut_volume·ρ。")
    out("")

    # ---- 1. 比較 ----
    out("## 1. 走行距離ごとの比較 [kg]")
    out("")
    for fname, name, df in eps:
        if not name.startswith("ex_ident"):
            continue
        t = at_distance(df, DIST_SHOW)
        out(f"### {fname}")
        out("")
        head = "| 距離 [m] | M_cut | M_pile | 地形の分 | 動く土の分 | M_pile ÷ M_cut | front_soil_mass | 横の畝 |"
        if "pile_push" in name:
            head += " 触れていない山 |"
        out(head)
        out("|" + " --- |" * (head.count("|") - 1))
        for _, r in t.iterrows():
            s = (f"| {r['distance']:.1f} | {r['M_cut']:.0f} | {r['M_pile']:.0f} | {r['pile_vol_terrain'] * rho_s:.0f} | "
                 f"{r['pile_vol_dynamic'] * rho_s:.0f} | {r['M_pile'] / r['M_cut'] if r['M_cut'] > 0 else float('nan'):.2f} | "
                 f"{r['front_soil_mass']:.0f} | {r['M_ridge']:.0f} |")
            if "pile_push" in name:
                s += f" {r['M_untouched']:.0f} |"
            out(s)
        out("")

    # ---- 2. 範囲 ----
    out("## 2. 範囲の確かめ")
    out("")
    out("前 2.0 m の端に土があるかは、帯の体積で見た：1.5〜2.0 m の帯 = V_pile − 前 1.5 m、2.0〜2.5 m の帯 = 前 2.5 m − V_pile。"
        "（`ground_profile_125cm` より遠い列は走行中に一定で使えない。）pile_push は、触れていない山が範囲に入る間（触れていない山 ≥ 50 kg）を除く。"
        "変化 [%] は running の行で V_pile > 0.2 m³ の行の中央値（絶対値の最大）。")
    out("")
    out("| 記録 | 1.5〜2.0 m の帯 [m³] 中央値（最大） | 2.0〜2.5 m の帯 [m³] 中央値（最大） | 前 1.5 m [%] | 前 2.5 m [%] | 横に1マス広げる [%] | 横の畝 ÷ V_pile [%] | 上端までの距離 [m] |")
    out("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for fname, name, df in eps:
        run = df[(df["phase"] == "running") & (df["pile_volume"] > 0.2)]
        if len(run) == 0:
            continue
        if "pile_push" in name:     # 触れる前の山が範囲にある間は除く（山を押している区間を見る）
            run = run[run["M_untouched"] < 50]
            if len(run) == 0:
                continue
        band1 = run["pile_volume"] - run["pile_volume_front150"]
        band2 = run["pile_volume_front250"] - run["pile_volume"]
        def pc(col):
            v = (run[col] / run["pile_volume"] - 1) * 100
            return f"{v.median():+.1f}（{v.abs().max():.1f}）"
        ridge = run["pile_volume_ridge"] / run["pile_volume"] * 100
        out(f"| {fname} | {band1.median():.3f}（{band1.max():.3f}） | {band2.median():.3f}（{band2.max():.3f}） | {pc('pile_volume_front150')} | {pc('pile_volume_front250')} | "
            f"{pc('pile_volume_wide')} | {ridge.median():.1f}（{ridge.max():.1f}） | {run['pile_back_offset'].median():.3f} |")
    out("")

    # ---- 3. 密度 ----
    out("## 3. 密度の確かめ（排土板を上げている間）")
    out("")
    out("raising の最初と最後の行の差。範囲：V_pile の範囲の粒子と地形の分。窓：広い窓（後ろ 16 m〜前 3 m・±3 m）の地形の体積と、"
        "地形全体の粒子（bal_* は 0.5 s ごとなので、raising の中で値が変わった最初と最後）。比 = 地形の増え ÷ (粒子の減り ÷ (ρ/s))。")
    out("")
    out("| 記録 | 粒子の減り（範囲）[kg] | 地形の増え（範囲）[m³] | 比（範囲） | 粒子の減り（全体）[kg] | 地形の増え（窓）[m³] | 比（窓） | 比が 1 になる密度（窓）[kg/m³] |")
    out("| --- | --- | --- | --- | --- | --- | --- | --- |")
    dens = []
    for fname, name, df in eps:
        r = df[df["phase"] == "raising"]
        if len(r) < 10:
            continue
        f, l = r.iloc[0], r.iloc[-1]
        dm_r = f["pile_mass_particle"] - l["pile_mass_particle"]
        dv_r = l["pile_vol_terrain"] - f["pile_vol_terrain"]
        bal = r["bal_vol_pos"] + r["bal_vol_neg"]
        ch = r.index[bal.diff().fillna(0) != 0]
        i0 = ch[0] - 1 if len(ch) else r.index[0]
        i1 = ch[-1] if len(ch) else r.index[-1]
        dm_w = df.loc[i0, "dyn_mass_particle_total"] - df.loc[i1, "dyn_mass_particle_total"]
        dv_w = (df.loc[i1, "bal_vol_pos"] + df.loc[i1, "bal_vol_neg"]) - (df.loc[i0, "bal_vol_pos"] + df.loc[i0, "bal_vol_neg"])
        ratio_r = dv_r / (dm_r / rho_s) if dm_r > 1 else float("nan")
        ratio_w = dv_w / (dm_w / rho_s) if dm_w > 1 else float("nan")
        rho_eff = dm_w / dv_w if dv_w > 1e-3 else float("nan")
        dens.append((ratio_w, rho_eff))
        out(f"| {fname} | {dm_r:.0f} | {dv_r:.3f} | {ratio_r:.2f} | {dm_w:.0f} | {dv_w:.3f} | {ratio_w:.2f} | {rho_eff:.0f} |")
    if dens:
        rw = np.array([d[0] for d in dens if np.isfinite(d[0])])
        out("")
        out(f"比（窓）の中央値 {np.median(rw):.2f}（{rw.min():.2f}〜{rw.max():.2f}）。")
    out("")

    # ---- 4. 質量の収支 ----
    out("## 4. 質量の収支（running の最後の行）")
    out("")
    out("削った分：広い窓の Σ min(h − h0, 0)·A × ρ（履帯の沈下も含む）。積もった分：Σ max(h − h0, 0)·A × ρ/s ＋ 地形全体の粒子。"
        "地形全体の質量の変化：calculateTotalMass の最初と最後の差（この列がある記録だけ。重いので外した）。")
    out("")
    out("| 記録 | M_cut | M_pile ＋ 横の畝 | 差 | 窓の削った分 | 窓の積もった分 ＋ 粒子 | うち V_pile の範囲の外 | 地形全体の質量の変化 [kg] |")
    out("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for fname, name, df in eps:
        run = df[df["phase"] == "running"]
        if len(run) == 0:
            continue
        l = run.iloc[-1]
        rho = l["label_rho0"]
        cut_w = -l["bal_vol_neg"] * rho
        dep_w = l["bal_vol_pos"] * rho_s + l["dyn_mass_particle_total"]
        outside = dep_w - (l["M_pile"] + l["M_ridge"])
        dmass = (df["bal_mass_terrain_total"].iloc[-1] - df["bal_mass_terrain_total"].iloc[0]
                 if "bal_mass_terrain_total" in df else float("nan"))   # 試しの版だけにある列
        out(f"| {fname} | {l['M_cut']:.0f} | {l['M_pile'] + l['M_ridge']:.0f} | {l['M_cut'] - l['M_pile'] - l['M_ridge']:+.0f} | "
            f"{cut_w:.0f} | {dep_w:.0f} | {outside:.0f} | {dmass:+.1f} |")
    out("")

    # ---- 5. 関門5 ----
    out("## 5. 関門5 の出し直し：−F_x = a + b·M·g")
    out("")
    B = []
    for fname, name, df in eps:
        if not name.startswith("val_constant_depth"):
            continue
        b = gate5_bins(df)
        if b is not None:
            b["ep"] = fname
            B.append(b)
    if not B:
        out("val_constant_depth* の記録がありません")
    else:
        B = pd.concat(B)
        lo = B[B["V"] < LINEAR_V]
        out(f"{len(B['ep'].unique())} エピソード、{len(B)} 区切り（直線の領域 V < {LINEAR_V} m³ は {len(lo)} 区切り）。"
            f"tanφ = {math.tan(math.radians(39.98)):.3f}、tanδ = 0.4167。")
        out("")
        out("| M | 直線の領域：b / a [kN] / 相関 / 残差の RMS [kN] | 全体：b / a [kN] / 相関 / 残差の RMS [kN] | b ÷ tanφ（直線） | 0.79〜0.97 の内か（直線） |")
        out("| --- | --- | --- | --- | --- |")
        res = {}
        for col, label in [("M_cut", "cut_volume·ρ"), ("M_pile", "M_pile（V_pile·ρ/s）"),
                           ("M_pile_ridge", "M_pile ＋ 横の畝"), ("M_front", "front_soil_mass")]:
            al, bl, rl, el = slope(lo[col], lo["Fx"], rms=True)
            aa, ba, ra, ea = slope(B[col], B["Fx"], rms=True)
            res[col] = dict(r=(rl, ra), rms=(el, ea))
            inside = "内" if GATE5_BAND[0] <= bl <= GATE5_BAND[1] else "外"
            out(f"| {label} | {bl:.3f} / {al / 1000:+.2f} / {rl:.3f} / {el / 1000:.2f} | {ba:.3f} / {aa / 1000:+.2f} / {ra:.3f} / {ea / 1000:.2f} | "
                f"{bl / math.tan(math.radians(39.98)):.2f} | {inside} |")
        out("")
        out(f"関門5 の記録での値は {GATE5_REF}（cut_volume、直線の領域）。")
        out("")
        # 横の範囲の見直しの基準：相関の差 ≥ 0.02、または残差の RMS が 5% 以上下がる
        out("**横の畝を足したときの変化**（見直しの基準：相関の差 ≥ 0.02、または残差の RMS が 5% 以上下がる）")
        out("")
        out("| 領域 | 相関（M_pile → ＋畝） | 差 | 残差の RMS [kN]（M_pile → ＋畝） | 変化 | 基準を超えたか |")
        out("| --- | --- | --- | --- | --- | --- |")
        for k, lab in ((0, "直線の領域"), (1, "全体")):
            r0, r1 = res["M_pile"]["r"][k], res["M_pile_ridge"]["r"][k]
            e0, e1 = res["M_pile"]["rms"][k], res["M_pile_ridge"]["rms"][k]
            over = (r1 - r0 >= 0.02) or (e1 <= 0.95 * e0)
            out(f"| {lab} | {r0:.3f} → {r1:.3f} | {r1 - r0:+.3f} | {e0 / 1000:.2f} → {e1 / 1000:.2f} | {(e1 / e0 - 1) * 100:+.1f}% | {'はい' if over else 'いいえ'} |")
        out("")

    # ---- 6. 膨張率ごとの係数 ----
    if a.swell:
        swell_section(eps, load(a.swell), out)

    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"レポート: {a.report}")

    if a.fig:
        plot(eps, B if isinstance(B, pd.DataFrame) else None, a.fig)


def swell_section(base_eps, sw_eps, out):
    """作業・膨張率の点ごとに、−F_x = a + b·M_pile·g の b（0.625 m ごとの平均、走り出しと深さを変えた直後の 1.5 s を除く。
    作業の区切りの扱いは check_physics.settled_cut_rows と同じ）"""
    out("## 6. 膨張率ごとの M_pile での係数（T17 の記録）")
    out("")
    out("作業・点ごとに、記録をまとめて −F_x = a + b·M_pile·g を当てはめた（0.625 m ごとの平均）。"
        "ρ/s の換算が合っていれば、b は s によらない。base は T15 の記録（flat_cut・pile_push の各2本。flat_piecewise はなし）。"
        "全体と、M_pile < 1,150 kg（V_pile < 1.0 m³）の区切りで求めた。")
    out("")
    out("| 作業 | 点（s） | 本数 | 区切り | 全体：b / a [kN] / 相関 | M_pile < 1,150 kg：b / 相関（区切り） |")
    out("| --- | --- | --- | --- | --- | --- |")
    groups = {}
    for fname, name, df in list(base_eps) + list(sw_eps):
        if not (name.startswith("ex_ident_") or name.startswith("ex_swell_flat_cut")):
            continue
        task = ("flat_cut" if "flat_cut" in name else "flat_piecewise" if "flat_piecewise" in name else "pile_push")
        b = gate5_bins(df)
        if b is None:
            continue
        s = float(df["label_swell"].iloc[0])
        groups.setdefault((task, s, name.split("_")[-1] if "swell" not in name else "s110"), []).append(b)
    summary = {}
    for (task, s, point), bl in sorted(groups.items()):
        B = pd.concat(bl)
        aa, ba, ra = slope(B["M_pile"], B["Fx"])
        lo = B[B["M_pile"] < 1150]
        _, bl_, rl_ = slope(lo["M_pile"], lo["Fx"])
        summary.setdefault(task, []).append((s, ba))
        out(f"| {task} | {point}（{s:g}） | {len(bl)} | {len(B)} | {ba:.3f} / {aa / 1000:+.2f} / {ra:.2f} | {bl_:.3f} / {rl_:.2f}（{len(lo)}） |")
    out("")
    out("| 作業 | b（全体）の s への傾き db/ds（1.25〜1.31 の点） | b の範囲（全体） |")
    out("| --- | --- | --- |")
    for task, v in summary.items():
        pts = [(s, b) for s, b in v if 1.2 <= s <= 1.35]
        if len(pts) >= 2:
            ss, bb = np.array(pts).T
            k = np.polyfit(ss, bb, 1)[0]
            out(f"| {task} | {k:+.2f}（{len(pts)} 点） | {min(b for _, b in v):.3f}〜{max(b for _, b in v):.3f} |")
    out("")


def plot(eps, B, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": ["Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"], "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.color": "#e0e0e0", "grid.linewidth": 0.6})
    ident = [e for e in eps if e[1].startswith("ex_ident")]
    n = len(ident)
    fig, axes = plt.subplots(1, n + 1, figsize=(4.6 * (n + 1), 4.0))
    for ax, (fname, name, df) in zip(axes, ident):
        run = df[df["phase"] == "running"]
        ax.plot(run["distance"], run["M_cut"], color=COLORS["cut"], lw=2, label="cut_volume·ρ")
        ax.plot(run["distance"], run["M_pile"], color=COLORS["pile"], lw=2, label="M_pile")
        ax.plot(run["distance"], run["front_soil_mass"], color=COLORS["front"], lw=1.2, label="front_soil_mass")
        if "pile_push" in name:
            ax.plot(run["distance"], run["M_untouched"], color=COLORS["untouched"], lw=1.2, ls="--", label="触れていない山")
        ax.set_title(fname.replace(".csv", ""), fontsize=9)
        ax.set_xlabel("走行距離 [m]")
        ax.set_ylabel("質量 [kg]")
        ax.legend(fontsize=7, frameon=False)
    ax = axes[-1]
    if B is not None:
        for col, c, label in [("M_cut", COLORS["cut"], "cut_volume·ρ"), ("M_pile", COLORS["pile"], "M_pile"),
                              ("M_front", COLORS["front"], "front_soil_mass")]:
            ax.scatter(B[col] * G / 1000, -B["Fx"] / 1000, s=14, color=c, alpha=0.75, label=label, edgecolors="none")
        lim = max(ax.get_xlim()[1], ax.get_ylim()[1])
        ax.plot([0, lim], [0, GATE5_REF * lim], color="#888888", lw=1, ls=":", label=f"傾き {GATE5_REF}")
        ax.set_xlabel("M·g [kN]")
        ax.set_ylabel("−F_x [kN]")
        ax.set_title("関門5：0.625 m ごとの平均", fontsize=9)
        ax.legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    print(f"図: {path}")


if __name__ == "__main__":
    main()
