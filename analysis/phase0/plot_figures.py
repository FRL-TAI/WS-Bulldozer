"""
フェーズ0 の報告（notes の docs/phase0.md）の図1〜11 を描く。

既存の解析スクリプトの関数と、それらが --out で保存した表を使う（記録や数値は変えない）。
  実験A（図2〜4）   ：締固めの記録 compaction_*_ex_compaction_passes.csv を check_compaction.py の関数で集計
  実験B（図5・6下）  ：check_cut_bands.py の出力（effects.csv、compare.csv）
  較正（図6上・7）   ：calibrate_settlement.py の出力（curve.csv、cv.csv）
  硬化（図9〜11）    ：check_cut_bands.py の出力（bands.csv）と check_track_settlement.py の出力（by_level.csv、fit.csv）
  図1               ：エピソードの定数（ex_compaction_bands / patterns / levels）から描く模式図

図の中の文字は英語。各図で使った値（本文と照合するための値）を標準出力に表示する。

使い方（numpy と matplotlib が必要なので、コンテナの中で実行する）：
  python3 analysis/phase0/plot_figures.py                 # 全図
  python3 analysis/phase0/plot_figures.py --only 6 7      # 図を選ぶ
  python3 analysis/phase0/plot_figures.py --out DIR       # 出力先（既定 data/figures/phase0）

図8（自然に踏み固めた地面の逆算値）は、使う記録（ex_compaction_then_cut の締固めの記録）が
残っていないため描かない（実行すると理由を表示する）。
"""
import argparse
import csv
import math
import os
import statistics
import sys
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_compaction as cc  # noqa: E402

WS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# ---------------------------------------------------------------- 見た目
# 色は分類用の固定の順番（青・橙・水色・黄）。量の大小は青の濃淡（1色）で表す
C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3de"
BLUE_RAMP = ["#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
             "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "lines.linewidth": 1.5, "lines.markersize": 5, "figure.facecolor": "white",
    "axes.facecolor": "white", "savefig.facecolor": "white",
})

# 実験A の記録（関門の判断に使った2回。1本目 045543 は通過を判定できず、051320 は履帯ごとに1列だけの記録）
EXP_A_FILES = ["compaction_20261111_060234_ex_compaction_passes.csv",
               "compaction_20261111_060815_ex_compaction_passes.csv"]
HARDENING = [("baseline", "Default (KE 1, NE 0.0833)", C1),
             ("NE1", "NE 1.0", C2),
             ("KE0", "KE 0 (no hardening)", C3)]


def read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fl(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return math.nan


def save(fig, out, name):
    path = os.path.join(out, name)
    fig.savefig(path, dpi=OPTS.dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {path}")


def note(ax, text, loc="upper right"):
    xy = {"upper right": (0.98, 0.97, "right", "top"), "upper left": (0.02, 0.97, "left", "top"),
          "lower left": (0.02, 0.03, "left", "bottom"), "lower right": (0.98, 0.03, "right", "bottom")}[loc]
    ax.text(xy[0], xy[1], text, transform=ax.transAxes, ha=xy[2], va=xy[3], fontsize=8, color=INK2)


# ---------------------------------------------------------------- 実験A の集計（check_compaction.py の関数）
def exp_a(path, x0=0.5, x1=7.5):
    """通過ごとの地表の締固めの程度・沈下（列ごと）、深さ方向の分布（履帯）、マスごとの予測沈下と実測沈下"""
    rows_all = cc.load(path)
    cols, _ = cc.depth_columns(rows_all)
    snaps = cc.snapshots(rows_all)
    t_first = snaps[0][0]
    h0 = {r["_cell"]: r["_h"] for r in rows_all if r["_t"] == t_first}
    rows = cc.in_range(rows_all, x0, x1)
    passes = cc.detect_passes(snaps)
    tb = cc.by_time(rows)
    times = sorted(tb)
    ends = [t_first] + [cc.nearest_time(times, te) for _, _, _, te in passes]

    lanes = {"track": ("track_L", "track_R"), "center": ("center",), "control": ("control",)}
    surf = {k: [] for k in lanes}
    for t in ends:
        for k, groups in lanes.items():
            vals = [cc.summarize(tb[t], g, h0) for g in groups]
            surf[k].append((float(np.mean([v[0] for v in vals])), float(np.mean([v[1] for v in vals]))))

    depth = []   # 通過の終わりごとの、履帯のマスの c_z0..c_z5 の平均
    for t in ends:
        g = [r for r in tb[t] if r["_group"] in ("track_L", "track_R")]
        depth.append([float(np.nanmean([cc.to_float(r[c]) for r in g])) for c in cols])

    first = {r["_cell"]: r for r in tb[t_first]}
    last = {r["_cell"]: r for r in tb[times[-1]]}
    pred, meas = [], []
    for key, r in last.items():
        if r["_group"] not in ("track_L", "track_R") or key not in first:
            continue
        p, _ = cc.predict_settlement(r, first[key], cols, 0.3125, 0.0)
        if math.isfinite(p):
            pred.append(p * 1000.0)
            meas.append((r["_h"] - first[key]["_h"]) * 1000.0)
    return {"surf": surf, "depth": depth, "pred": np.array(pred), "meas": np.array(meas), "n_passes": len(passes)}


# ---------------------------------------------------------------- 図1
def fig01(d, out):
    blade_half = 2.96 / 2           # 排土板の幅 2.96 m
    edge_to_ref, track_half_len = 2.8, 1.1
    track_c, track_w = 0.86, 0.6
    bands = [(1.0 + 2 * i, 3.0 + 2 * i) for i in range(5)]
    fig, axs = plt.subplots(3, 1, figsize=(7.5, 8.6), gridspec_kw={"height_ratios": [1.25, 1.0, 1.0]})

    # (a) 平面図
    ax = axs[0]
    for i, (a, b) in enumerate(bands):
        comp = i in (1, 3)
        ax.add_patch(Rectangle((a, -2.0), b - a, 4.0, facecolor=BLUE_RAMP[3] if comp else "#f1f0ec",
                               edgecolor="white", lw=1.5))
        ax.text((a + b) / 2, 2.2, f"Band {i}", ha="center", va="bottom", fontsize=8, color=INK)
    ref = -edge_to_ref
    for s in (1, -1):
        ax.add_patch(Rectangle((ref - track_half_len, s * track_c - track_w / 2), 2 * track_half_len, track_w,
                               facecolor=INK2, edgecolor="none"))
    ax.plot([0, 0], [-blade_half, blade_half], color=C2, lw=3, solid_capstyle="butt")
    ax.plot(ref, 0, marker="+", color=INK, ms=9, mew=1.5)
    ax.annotate("Blade edge (x = 0 at start)", (0, blade_half), (0.2, 3.3), fontsize=8, color=INK,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.annotate("Machine reference\n(2.8 m behind edge)", (ref, 0), (-6.3, -3.6), fontsize=8, color=INK,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.annotate("Tracks (±1.1 m, width 0.6 m)", (ref - 0.6, track_c + 0.3), (-6.6, 2.6), fontsize=8, color=INK,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.annotate("", (13.5, -2.6), (0, -2.6), arrowprops=dict(arrowstyle="->", color=INK, lw=1))
    ax.text(6.75, -2.85, "Travel: 13.5 m at 0.5 m/s, cutting depth 0.08 m", ha="center", va="top", fontsize=8)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, facecolor=BLUE_RAMP[3]), Rectangle((0, 0), 1, 1, facecolor="#f1f0ec")],
              labels=["Compacted (set degree)", "Undisturbed (1.00)"], fontsize=8, loc="upper right", ncol=2,
              bbox_to_anchor=(1.0, 1.02))
    ax.set(xlim=(-7, 14.5), ylim=(-4.0, 4.2), xlabel="x (forward from blade edge at start) [m]",
           ylabel="y (left) [m]", title="(a) Plan view at start (2 m bands, full-width layout)")
    ax.set_aspect("equal")
    ax.grid(False)

    # (b) 縦断面
    ax = axs[1]
    for i, (a, b) in enumerate(bands):
        if i in (1, 3):
            ax.add_patch(Rectangle((a, -0.8), b - a, 0.8, facecolor=BLUE_RAMP[3], edgecolor="white", lw=1.5))
    ax.plot([7.0, 9.4], [-0.3, -0.3], color=INK, lw=1, ls="--")
    ax.text(9.5, -0.3, "0.3 m (shallow variant)", ha="left", va="center", fontsize=8, color=INK)
    ax.text(9.5, -0.8, "0.8 m (set depth)", ha="left", va="center", fontsize=8, color=INK)
    ax.plot([-1, 14], [0, 0], color=INK2, lw=1)
    ax.plot([0, 13.5], [-0.08, -0.08], color=C2, lw=1.5)
    ax.text(12.0, -0.12, "cut at 0.08 m", ha="center", va="top", fontsize=8, color=INK)
    ax.set(xlim=(-1, 14), ylim=(-1.0, 0.2), xlabel="x [m]", ylabel="z (from initial surface) [m]",
           title="(b) Longitudinal section (vertical scale exaggerated)")

    # (c) 幅方向の範囲
    ax = axs[2]
    layouts = [("Full width", [(-2.0, 2.0)]),
               ("Two tracks", [(track_c - track_w / 2, track_c + track_w / 2),
                               (-track_c - track_w / 2, -track_c + track_w / 2)]),
               ("Center", [(-0.6, 0.6)]),
               ("Shallow (full width, 0.3 m)", [(-2.0, 2.0)])]
    for j, (name, ranges) in enumerate(layouts):
        yy = len(layouts) - 1 - j
        for lo, hi in ranges:
            ax.add_patch(Rectangle((lo, yy - 0.3), hi - lo, 0.6, facecolor=BLUE_RAMP[3], edgecolor="none"))
        ax.text(-2.6, yy, name, ha="right", va="center", fontsize=8)
    ax.axvspan(-blade_half, blade_half, color=C2, alpha=0.10, lw=0)
    for s in (1, -1):
        ax.axvline(s * blade_half, color=C2, lw=1)
    ax.text(0, 3.55, "blade width 2.96 m", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set(xlim=(-5.6, 2.6), ylim=(-0.6, 4.0), xlabel="y (left) [m]", yticks=[],
           title="(c) Lateral extent of the compacted band (Exp. B3 patterns)")
    ax.grid(False)
    ax.spines["left"].set_visible(False)
    fig.tight_layout()
    save(fig, out, "fig01_layout.png")
    return {"bands": "1–11 m, 2 m each", "blade edge": "2.8 m ahead", "tracks": "±1.1 m"}


# ---------------------------------------------------------------- 図2
def fig02(d, out):
    runs = [exp_a(os.path.join(d, "compaction", f)) for f in EXP_A_FILES]
    n = runs[0]["n_passes"]
    passes = np.arange(n + 1)
    fig, axs = plt.subplots(1, 2, figsize=(8.2, 3.4))
    lanes = [("track", "Under tracks", C1, "-", "o"), ("control", "Outside track path", C3, "-", "o"),
             ("center", "Machine centerline", C2, "--", "s")]
    vals = {}
    for k, label, col, ls, mk in lanes:
        c = np.array([[v[0] for v in r["surf"][k]] for r in runs])
        dh = np.array([[-v[1] for v in r["surf"][k]] for r in runs])
        for ax, y in ((axs[0], c), (axs[1], dh)):
            ax.fill_between(passes, y.min(0), y.max(0), color=col, alpha=0.18, lw=0)
            ax.plot(passes, y.mean(0), marker=mk, ls=ls, color=col, label=label,
                    mfc="white" if mk == "s" else col, ms=6 if mk == "s" else 5)
        vals[k] = (c.mean(0), dh.mean(0), c, dh)
    tc, tdh, call, _ = vals["track"]
    frac1 = (tc[1] - tc[0]) / (tc[-1] - tc[0])
    axs[0].set(xlabel="Pass number [-]", ylabel="Surface degree of compaction [-]",
               title="(a) Surface degree of compaction")
    axs[1].set(xlabel="Pass number [-]", ylabel="Settlement [mm]", title="(b) Settlement (downward positive)")
    for ax in axs:
        ax.set_xticks(passes)
    axs[0].text(0.97, 0.55, f"Pass 1 reaches {frac1 * 100:.0f}% of final\nfinal {tc[-1]:.3f}",
                transform=axs[0].transAxes, ha="right", va="center", fontsize=8, color=INK2)
    axs[1].text(0.97, 0.55, f"final {tdh[-1]:.1f} mm", transform=axs[1].transAxes,
                ha="right", va="center", fontsize=8, color=INK2)
    axs[0].legend(loc="lower right", fontsize=8, bbox_to_anchor=(1.0, 0.07))
    axs[1].text(0.97, 0.12, "Lines: mean of 2 runs; band: range\nCenterline and outside path stay at 0",
                transform=axs[1].transAxes, ha="right", va="bottom", fontsize=8, color=INK2)
    fig.tight_layout()
    save(fig, out, "fig02_passes.png")
    run_diff_c = abs(call[0, -1] - call[1, -1])
    run_diff_dh = abs(vals["track"][3][0, -1] - vals["track"][3][1, -1])
    return {"pass1 fraction (surface)": f"{frac1 * 100:.1f}%", "final surface c": f"{tc[-1]:.4f}",
            "final settlement mm": f"{tdh[-1]:.1f}", "run diff c": f"{run_diff_c:.4f}",
            "run diff settlement mm": f"{run_diff_dh:.2f}",
            "center/control max |dc|": f"{max(abs(vals[k][2] - 1).max() for k in ('center', 'control')):.4f}"}


# ---------------------------------------------------------------- 図3
def fig03(d, out):
    runs = [exp_a(os.path.join(d, "compaction", f)) for f in EXP_A_FILES]
    prof = np.mean([np.array(r["depth"]) for r in runs], axis=0)   # (通過, 層)
    n_layer = prof.shape[1]
    layers = np.arange(n_layer)
    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    idx = np.linspace(2, len(BLUE_RAMP) - 1, len(prof)).astype(int)
    for p, row in enumerate(prof):
        ax.plot(row, layers, marker="o", ms=4, color=BLUE_RAMP[idx[p]] if p else INK2,
                label="Before" if p == 0 else f"Pass {p}", lw=1.2)
    ax.invert_yaxis()
    ax.set_yticks(layers)
    ax.set_yticklabels([f"{k}  ({k * 0.3125:.2f})" for k in layers])
    ax.set(xlabel="Degree of compaction under tracks [-]",
           ylabel="Voxel layer below surface (top depth [m])", title="Depth profile after each pass")
    ax.legend(fontsize=7, loc="lower right", ncol=2)
    fig.tight_layout()
    save(fig, out, "fig03_depth_profile.png")
    reach = [k for k in layers if prof[-1, k] - prof[0, k] > 0.001]
    return {"final z0..z2": ", ".join(f"{v:.4f}" for v in prof[-1, :3]),
            "layers with change > 0.001": f"{len(reach)} (z0–z{reach[-1]})"}


# ---------------------------------------------------------------- 図4
def fig04(d, out):
    runs = [exp_a(os.path.join(d, "compaction", f)) for f in EXP_A_FILES]
    fig, ax = plt.subplots(figsize=(4.4, 4.2))
    res = {}
    for r, f, col, mk in zip(runs, EXP_A_FILES, (C1, C2), ("o", "s")):
        m, p = -r["meas"], -r["pred"]
        ratio = p.mean() / m.mean()
        corr = float(np.corrcoef(p, m)[0, 1])
        name = f.split("_")[2]
        ax.scatter(m, p, s=16, color=col, marker=mk, alpha=0.8, edgecolors="white", linewidths=0.4,
                   label=f"Run {name} (ratio {ratio:.3f}, r = {corr:.3f})")
        res[name] = (ratio, corr, len(m))
    lo, hi = 25, 65
    ax.plot([lo, hi], [lo, hi], color=INK2, lw=1, ls="--", label="1:1")
    ax.set(xlim=(lo, hi), ylim=(lo, hi), xlabel="Measured settlement [mm]",
           ylabel="Settlement from mass conservation [mm]", title="Settlement vs. mass conservation\n(per cell, under tracks)")
    ax.set_aspect("equal")
    ax.legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    save(fig, out, "fig04_mass_conservation.png")
    return {k: f"ratio {v[0]:.3f}, r {v[1]:.3f} (n={v[2]})" for k, v in res.items()}


# ---------------------------------------------------------------- 図5
def fig05(d, out):
    eff = read_csv(os.path.join(d, "compaction", "expB3_patterns", "effects.csv"))
    cats = [("全幅 1.16 深0.8m", "Full width\n(0.8 m)"), ("履帯2本 1.16 深0.8m", "Two tracks\n(0.8 m)"),
            ("中央 1.16 深0.8m", "Center\n(0.8 m)"), ("全幅 1.16 深0.3m", "Full width,\nshallow (0.3 m)")]
    cmp_rows = [r for r in read_csv(os.path.join(d, "compaction", "expB2", "compare.csv")) if r["region"] == "踏固め"]
    b2 = [fl(r["R_sep_comp"]) / fl(r["R_sep_ctrl"]) for r in cmp_rows]
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    res = {}
    for i, (key, _) in enumerate(cats):
        g = [r for r in eff if r["label"] == key]
        for off, col, name, lab in ((-0.17, C1, "R_sep_N_ratio", "Separation resistance"),
                                    (0.17, C2, "R_pen_N_ratio", "Penetration resistance")):
            v = [fl(r[name]) for r in g]
            ax.scatter([i + off] * len(v), v, s=14, color=col, alpha=0.55, edgecolors="none")
            ax.plot([i + off - 0.12, i + off + 0.12], [np.mean(v)] * 2, color=col, lw=2.5,
                    label=lab if i == 0 else None)
            res[f"{key} {name.split('_')[1]}"] = f"{np.mean(v):.2f} (n={len(v)})"
    i = len(cats)
    ax.scatter([i - 0.17] * len(b2), b2, s=14, color=C1, alpha=0.55, edgecolors="none")
    ax.plot([i - 0.29, i - 0.05], [np.mean(b2)] * 2, color=C1, lw=2.5)
    ax.text(i + 0.17, 0.15, "n/a", ha="center", fontsize=8, color=INK2)
    res["B2 sep"] = f"{np.mean(b2):.2f} (n={len(b2)} bins)"
    ax.axhline(1, color=INK2, lw=0.8, ls="--")
    ax.set_xticks(range(len(cats) + 1))
    ax.set_xticklabels([c[1] for c in cats] + ["B2: compacted\nby tracks"], fontsize=8)
    ax.set(ylabel="Ratio to adjacent undisturbed ground [-]", ylim=(0, 5.5),
           title="Cutting resistance by compacted extent (degree 1.16)")
    ax.legend(fontsize=8, loc="upper right")
    note(ax, "Bars: mean; dots: individual bands (B2: 0.5 m bins vs. control run)", "upper left")
    fig.tight_layout()
    save(fig, out, "fig05_patterns.png")
    return res


# ---------------------------------------------------------------- 図6
def levels_ratio(d):
    eff = read_csv(os.path.join(d, "compaction", "expB3_levels", "effects.csv"))
    by = defaultdict(list)
    for r in eff:
        by[round(fl(r["level"]), 2)].append(fl(r["R_sep_N_ratio"]))
    by[1.0] = [1.0]
    return dict(sorted(by.items()))


def fig06(d, out):
    curve = [r for r in read_csv(os.path.join(d, "compaction", "calibration", "curve.csv")) if r["seg_m"] == "1.0"]
    cv = [r for r in read_csv(os.path.join(d, "compaction", "calibration", "cv.csv")) if r["seg_m"] == "1.0"]
    c = np.array([fl(r["c"]) for r in curve]); S = np.array([fl(r["S_mm"]) for r in curve])
    sd = np.array([fl(r["S_sd_mm"]) for r in curve])
    fig, axs = plt.subplots(2, 1, figsize=(5.6, 6.2), sharex=True)
    ax = axs[0]
    ax.scatter([fl(r["c"]) for r in cv], [fl(r["S"]) for r in cv], s=8, color="#c9c8c2", edgecolors="none",
               label="1 m segments")
    ax.errorbar(c, S, yerr=sd, color=C1, marker="o", capsize=2, label="Calibration curve (mean ± SD)")
    ax.set(ylabel="Additional settlement [mm]", title="(a) Additional settlement under tracks after cutting")
    ax.legend(fontsize=8)
    ax = axs[1]
    lv = levels_ratio(d)
    for k, v in lv.items():
        ax.scatter([k] * len(v), v, s=14, color=C2, alpha=0.55, edgecolors="none")
    ax.plot(list(lv), [np.mean(v) for v in lv.values()], color=C2, marker="o", label="Mean")
    ax.axhline(1, color=INK2, lw=0.8, ls="--")
    ax.set(xlabel="Degree of compaction [-]", ylabel="Cutting resistance ratio [-]",
           title="(b) Separation resistance, ratio to adjacent undisturbed ground (full width)")
    ax.legend(fontsize=8, loc="center left")
    fig.tight_layout()
    save(fig, out, "fig06_calibration_and_cut.png")
    res = {f"S {cc_:.2f}": f"{s:.1f}" for cc_, s in zip(c, S)}
    res.update({f"ratio {k:.2f}": f"{np.mean(v):.2f}" for k, v in lv.items()})
    return res


# ---------------------------------------------------------------- 図7
def fig07(d, out):
    cv = [r for r in read_csv(os.path.join(d, "compaction", "calibration", "cv.csv")) if r["seg_m"] == "1.0"]
    c = np.array([fl(r["c"]) for r in cv]); ch = np.array([fl(r["c_hat"]) for r in cv])
    err = ch - c
    rmse = lambda m: float(np.sqrt(np.mean(err[m] ** 2)))
    allm = np.ones_like(c, bool); low = c < 1.15; sat = (c > 1.11) & (c < 1.17)
    fig, ax = plt.subplots(figsize=(4.4, 4.2))
    jit = (np.random.default_rng(0).random(len(c)) - 0.5) * 0.008
    ax.scatter(c + jit, ch, s=12, color=C1, alpha=0.6, edgecolors="none", label="1 m segments, leave-one-run-out\n(x jittered by ±0.004)")
    ax.plot([0.75, 1.25], [0.75, 1.25], color=INK2, lw=1, ls="--", label="1:1")
    ax.set(xlim=(0.75, 1.25), ylim=(0.75, 1.25), xlabel="True degree of compaction [-]",
           ylabel="Estimated degree of compaction [-]", title="Cross-validation of the calibration curve")
    ax.set_aspect("equal")
    note(ax, f"RMSE all: {rmse(allm):.3f} (n={allm.sum()})\nRMSE < 1.15: {rmse(low):.3f}\n"
             f"RMSE 1.12–1.16: {rmse(sat):.3f}", "lower right")
    ax.legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    save(fig, out, "fig07_cross_validation.png")
    return {"RMSE all": f"{rmse(allm):.4f}", "RMSE <1.15": f"{rmse(low):.4f}", "RMSE 1.12–1.16": f"{rmse(sat):.4f}"}


# ---------------------------------------------------------------- 図8
def fig08(d, out):
    print("  図8は描きません：自然に踏み固めた地面（ex_compaction_then_cut）の締固めの記録"
          "（compaction_*_ex_compaction_then_cut.csv）が data/ に残っていません")
    return None


# ---------------------------------------------------------------- 図9
def hardening_ratios(d, cond):
    """各帯の比抵抗 ÷ 同じ記録の帯2・4（地山）の比抵抗の平均（docs/phase0.md §3.4 の表の定義）"""
    rows = read_csv(os.path.join(d, "hardening", cond, "cut_bands", "bands.csv"))
    byf = defaultdict(list)
    for r in rows:
        byf[r["file"]].append(r)
    ratios, bank, bank_w = defaultdict(list), [], []
    for rs in byf.values():
        ref = statistics.mean(fl(r["specific_kPa"]) for r in rs if r["band"] in ("2", "4"))
        bank.append(ref)
        bank_w += [fl(r["state_c"]) for r in rs if r["band"] in ("2", "4")]
        for r in rs:
            if r["band"] in ("1", "3"):
                ratios[round(fl(r["level"]), 2)].append(fl(r["specific_kPa"]) / ref)
    return dict(sorted(ratios.items())), statistics.mean(bank), bank_w


def fig09(d, out):
    fig, ax = plt.subplots(figsize=(6.0, 3.9))
    res = {}
    for k, (cond, label, col) in enumerate(HARDENING):
        rat, bank, _ = hardening_ratios(d, cond)
        off = (k - 1) * 0.008
        for lv, v in rat.items():
            ax.scatter([lv + off] * len(v), v, s=12, color=col, alpha=0.45, edgecolors="none")
        ax.plot([lv + off for lv in rat], [np.mean(v) for v in rat.values()], color=col, marker="o",
                label=f"{label}; undisturbed {bank:.0f} kPa")
        res[cond] = ", ".join(f"{lv:.2f}:{np.mean(v):.2f}" for lv, v in rat.items()) + f"; bank {bank:.1f} kPa"
    ax.axhline(1, color=INK2, lw=0.8, ls="--")
    ax.set(xlabel="Degree of compaction of the band [-]", ylabel="Specific cutting resistance ratio [-]",
           title="Cutting resistance by hardening setting\n(ratio to undisturbed bands 2 and 4 of the same run)")
    ax.legend(fontsize=7.5, loc="upper left")
    fig.tight_layout()
    save(fig, out, "fig09_hardening_cut.png")
    return res


# ---------------------------------------------------------------- 図10
def fig10(d, out):
    fig, ax = plt.subplots(figsize=(5.6, 3.9))
    res = {}
    for k, (cond, label, col) in enumerate(HARDENING):
        rows = read_csv(os.path.join(d, "hardening", cond, "settlement", "by_level.csv"))
        fit = {r["x"]: r for r in read_csv(os.path.join(d, "hardening", cond, "settlement", "fit.csv"))}["c_start"]
        c = np.array([fl(r["c_start"]) for r in rows]) + (k - 1) * 0.004
        S = -np.array([fl(r["extra_mm"]) for r in rows]); sd = np.array([fl(r["extra_sd"]) for r in rows])
        ax.errorbar(c, S, yerr=sd, color=col, marker="o", ms=4, capsize=2, lw=1.3,
                    label=f"{label}: H {fl(fit['H_mm']):.0f} mm, c_sat {fl(fit['c_sat']):.3f}")
        res[cond] = (f"1.00: {S[np.argmin(abs(c - 1.0))]:.1f} mm, 0.78: {S[0]:.0f} mm, "
                     f"H {fl(fit['H_mm']):.0f}, c_sat {fl(fit['c_sat']):.3f}")
    ax.set(xlabel="Degree of compaction before cutting [-]", ylabel="Additional settlement [mm]",
           title="Additional settlement by hardening setting (mean ± SD per cell)")
    ax.legend(fontsize=7.5)
    fig.tight_layout()
    save(fig, out, "fig10_hardening_calibration.png")
    return res


# ---------------------------------------------------------------- 図11
def fig11(d, out):
    w = np.linspace(0.75, 1.25, 1001)
    fig, ax = plt.subplots(figsize=(5.6, 3.9))
    for (cond, label, col), (KE, NE) in zip(HARDENING, [(1.0, 0.0833), (1.0, 1.0), (0.0, 1.0)]):
        E = 1 + np.sign(w - 1) * KE * np.abs(w - 1) ** NE
        ax.plot(w, E, color=col, label=label, lw=1.8)
    bank_w = []
    for cond, _, _ in HARDENING:
        bank_w += hardening_ratios(d, cond)[2]
    lo, hi = min(bank_w), max(bank_w)
    ax.axvspan(lo, hi, color=INK2, alpha=0.12, lw=0)
    ax.text(lo - 0.005, 1.35, f"Undisturbed ground\nwhile cutting\n{lo:.2f}–{hi:.2f}",
            ha="right", va="center", fontsize=7.5, color=INK)
    ax.axvline(1, color=INK2, lw=0.8, ls="--")
    ax.set(xlim=(0.75, 1.25), ylim=(0, 2.05), xlabel="Degree of compaction while cutting, w [-]",
           ylabel="Stiffness ratio E/E0 [-]", title="E/E0 = 1 ± KE·|w − 1|^NE (+ for w > 1, − for w < 1)")
    ax.legend(fontsize=8, loc="upper left")
    note(ax, "w range: state_compaction_mean in bands 2 and 4\n(blade-front surface, all 3 settings)", "lower right")
    fig.tight_layout()
    save(fig, out, "fig11_hardening_law.png")
    E_lo = 1 - 1.0 * abs(hi - 1) ** 0.0833
    return {"w range": f"{lo:.3f}–{hi:.3f}", "E/E0 default at w=hi": f"{E_lo:.2f}",
            "E/E0 default at w=lo": f"{1 - abs(lo - 1) ** 0.0833:.2f}"}


FIGS = {1: fig01, 2: fig02, 3: fig03, 4: fig04, 5: fig05, 6: fig06, 7: fig07, 8: fig08, 9: fig09, 10: fig10, 11: fig11}


def main():
    global OPTS
    ap = argparse.ArgumentParser(description="フェーズ0 の図1〜11 を描く")
    ap.add_argument("--data", default=os.path.join(WS, "data"), help="データのフォルダ（既定 <ws>/data）")
    ap.add_argument("--out", default=os.path.join(WS, "data", "figures", "phase0"), help="出力先")
    ap.add_argument("--only", type=int, nargs="+", help="描く図の番号（例 --only 6 7）")
    ap.add_argument("--dpi", type=int, default=150)
    OPTS = ap.parse_args()
    os.makedirs(OPTS.out, exist_ok=True)
    for n in OPTS.only or sorted(FIGS):
        print(f"図{n}")
        res = FIGS[n](OPTS.data, OPTS.out)
        for k, v in (res or {}).items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
