"""
フェーズ0 の報告（notes の docs/phase0.md）の図1〜11 と、本文の値の表（figure_values.csv）を作る。

入力は data/phase0/ の記録だけ。どの記録を使うかは data/phase0/MANIFEST.md の表で決める（「使う」が ○ の行）。
1回の実行で、次の順に処理する：
  1. 解析：既存の4本（check_cut_bands.py・check_track_settlement.py・calibrate_settlement.py。
     check_compaction.py は関数を import）を、MANIFEST の記録に対して実行する。出力は data/phase0/analysis/
       cut_levels       B1_bands + B3_levels の時系列       → 図6(b)、§3.3 の表の切削抵抗の比
       cut_patterns     B3_patterns の時系列               → 図5
       cut_then_cut     B2_then_cut の時系列               → 図5（B2）
       settlement       B1_bands + B3_levels の締固めの記録 → calibration（--seg 0.5 1、--target）→ 図6(a)・図7
       settlement_then_cut  B2_then_cut の締固めの記録     → 図8（区間ごとの値は図8 が segments_fig8.csv に書く）
       hardening_<条件>/{cut_bands,settlement}            → 図9〜11
  2. 図：実験A（図2〜4）は締固めの記録を check_compaction.py の関数で集計し、ほかは 1 の出力を読む。
     図1 はエピソードの定数から描く模式図。図8 は B2 の締固めの記録と較正曲線（calibrate_settlement.py の関数）から描く。
  3. 本文の値の表 figure_values.csv（図・項目・値）と、追加の確認（図5 の基準の帯、図11 の刃先の層の w）。

図の中の文字は英語。各図で使った値を標準出力にも表示する。
較正の正解（--target）は既定で K3（c_cut_col3：履帯が踏む時点の z0〜z2 の平均。decisions/2026-11-18_較正の正解をK3に変える.md）。
--target c_start で、削る前の値を正解にした以前の図を作れる。区間（そろわない区間を除く基準）は c_start で決め、正解の列によらない。

使い方（numpy・matplotlib と bull_ope が必要なので、コンテナの中で install/setup.bash を source して実行する）：
  python3 analysis/phase0/plot_figures.py                 # 解析 → 全図 → figure_values.csv
  python3 analysis/phase0/plot_figures.py --skip-analysis --only 6 7   # 解析の出力を使い回して図を選ぶ
  出力：data/phase0/figures/（--out で変更）、data/phase0/figure_values.csv
"""
import argparse
import csv
import math
import os
import statistics
import subprocess
import sys
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_compaction as cc  # noqa: E402
import check_track_settlement as cts  # noqa: E402
import calibrate_settlement as cs  # noqa: E402

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

HERE = os.path.dirname(os.path.abspath(__file__))
HARDENING = [("baseline", "Default (KE 1, NE 0.0833)", C1),
             ("NE1", "NE 1.0", C2),
             ("KE0", "KE 0 (no hardening)", C3)]


# ---------------------------------------------------------------- MANIFEST と解析
def read_manifest(d):
    """MANIFEST.md の記録の表を読む。列：記録 | 実験 | エピソード | seed | KE | NE | 使う | 図・表"""
    rows, head = [], None
    with open(os.path.join(d, "MANIFEST.md"), encoding="utf-8") as f:
        for line in f:
            if not line.startswith("|"):
                head = None if not line.strip() else head
                continue
            cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
            if cells[0] == "記録":
                head = cells
            elif head and not set(cells[0]) <= set("-: "):
                rows.append(dict(zip(head, cells)))
    if not rows:
        raise SystemExit("MANIFEST.md に記録の表がありません")
    return rows


def records(exp, compaction=False):
    """MANIFEST で「使う」が ○ の、実験 exp の記録のパス（compaction=True なら締固めの記録）"""
    out = []
    for r in MANIFEST:
        if r["実験"] == exp and r["使う"].startswith("○"):
            p = os.path.join(OPTS.data, r["記録"])
            out.append(p[:-4] + "_compaction.csv" if compaction else p)
    if not out:
        raise SystemExit(f"MANIFEST に実験 {exp} の使う記録がありません")
    return out


HARDENING_SETS = {"baseline": "hardening_baseline", "NE1": "hardening_NE1", "KE0": "hardening_KE0"}


def A(*parts):
    """解析の出力のパス（data/phase0/analysis/...）"""
    return os.path.join(OPTS.data, "analysis", *parts)


def run_analysis():
    def sh(script, args, log):
        cmd = [sys.executable, os.path.join(HERE, script)] + args
        os.makedirs(os.path.dirname(log), exist_ok=True)
        print("  $ " + " ".join(os.path.relpath(c, WS) if c.startswith(WS) else c for c in cmd))
        with open(log, "w", encoding="utf-8") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=WS)
        if r.returncode:
            raise SystemExit(f"{script} が失敗しました（{log}）")
    levels = records("B1_bands") + records("B3_levels")
    levels_c = records("B1_bands", True) + records("B3_levels", True)
    sh("check_cut_bands.py", levels + ["--out", A("cut_levels")], A("cut_levels.log"))
    sh("check_cut_bands.py", records("B3_patterns") + ["--out", A("cut_patterns")], A("cut_patterns.log"))
    sh("check_cut_bands.py", records("B2_then_cut") + ["--out", A("cut_then_cut")], A("cut_then_cut.log"))
    sh("check_track_settlement.py", levels_c + ["--out", A("settlement")], A("settlement.log"))
    sh("calibrate_settlement.py", [A("settlement", "cells.csv"), "--seg", "0.5", "1", "--target", OPTS.target,
                                   "--out", A("calibration")],
       A("calibration.log"))
    sh("check_track_settlement.py", records("B2_then_cut", True) + ["--out", A("settlement_then_cut")],
       A("settlement_then_cut.log"))
    for cond, exp in HARDENING_SETS.items():
        sh("check_cut_bands.py", records(exp) + ["--out", A(f"hardening_{cond}", "cut_bands")],
           A(f"hardening_{cond}", "cut_bands.log"))
        sh("check_track_settlement.py", records(exp, True) + ["--out", A(f"hardening_{cond}", "settlement")],
           A(f"hardening_{cond}", "settlement.log"))


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
COL_DEPTH = 0.8   # 深さ方向の平均を取る範囲 [m]（§3.1 の「0.8 m までの平均」）
DH_SCALE = 1.03   # 沈下量から深さ方向の平均を求めるときの沈下の倍率（check_compaction.py の --dh-scale）。
                  # 実験A の2記録の 5b の k（1.0325・1.0325・1.0331・1.0362）の平均を小数2桁に丸めた値
Z_OFFSET = 0.0125  # 地表のボクセルの中心のワールドの高さ [m]（check_compaction.py の --z-offset と同じ）


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
    colavg = []   # 通過の終わりごとの、履帯のマスの深さ COL_DEPTH までの平均の締固めの程度（質量で重み付け）
    for t in ends:
        v = [cc.column_average(r, first[r["_cell"]], cols, 0.3125, Z_OFFSET, COL_DEPTH)[1] for r in tb[t]
             if r["_group"] in ("track_L", "track_R") and r["_cell"] in first]
        colavg.append(float(np.nanmean(v)))
    est_err = []  # 最後の記録で、沈下量だけから求めた深さ方向の平均 − 真値（check_compaction.py の 5a と同じ式、--dh-scale DH_SCALE）
    for r in tb[times[-1]]:
        r0 = first.get(r["_cell"])
        if r["_group"] not in ("track_L", "track_R") or r0 is None:
            continue
        _, c_true, M, T_old = cc.column_average(r, r0, cols, 0.3125, Z_OFFSET, COL_DEPTH)
        if math.isfinite(c_true):
            est_err.append(M / (T_old + DH_SCALE * (r["_h"] - r0["_h"])) - c_true)
    last = {r["_cell"]: r for r in tb[times[-1]]}
    pred, meas = [], []
    for key, r in last.items():
        if r["_group"] not in ("track_L", "track_R") or key not in first:
            continue
        p, _ = cc.predict_settlement(r, first[key], cols, 0.3125, Z_OFFSET)
        if math.isfinite(p):
            pred.append(p * 1000.0)
            meas.append((r["_h"] - first[key]["_h"]) * 1000.0)
    return {"surf": surf, "depth": depth, "pred": np.array(pred), "meas": np.array(meas), "n_passes": len(passes),
            "colavg": colavg, "col_rmse": float(np.sqrt(np.mean(np.square(est_err)))) if est_err else math.nan}


_EXP_A = {}


def exp_a_runs():
    if not _EXP_A:
        for p in records("A_passes", True):
            _EXP_A[os.path.basename(p)] = exp_a(p)
    return list(_EXP_A.items())


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
    runs = [r for _, r in exp_a_runs()]
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
    ca = np.array([r["colavg"] for r in runs])
    axs[0].fill_between(passes, ca.min(0), ca.max(0), color=C1, alpha=0.12, lw=0)
    axs[0].plot(passes, ca.mean(0), marker="^", ls=":", color=C1, mfc="white",
                label=f"Under tracks, mean to {COL_DEPTH:.1f} m depth")
    tc, tdh, call, _ = vals["track"]
    frac1 = (tc[1] - tc[0]) / (tc[-1] - tc[0])
    cm = ca.mean(0)
    frac1_col = (cm[1] - cm[0]) / (cm[-1] - cm[0])
    axs[0].set(xlabel="Pass number [-]", ylabel="Degree of compaction [-]",
               title="(a) Degree of compaction (surface and depth mean)")
    axs[1].set(xlabel="Pass number [-]", ylabel="Settlement [mm]", title="(b) Settlement (downward positive)")
    for ax in axs:
        ax.set_xticks(passes)
    axs[0].text(0.97, 0.55, f"Pass 1 reaches {frac1 * 100:.0f}% of final (surface),\n"
                f"{frac1_col * 100:.0f}% (depth mean); final {tc[-1]:.3f}",
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
    return {"pass1 fraction (surface)": f"{frac1 * 100:.1f}%",
            "pass1 fraction (depth mean)": f"{frac1_col * 100:.1f}%",
            "final depth-mean c": f"{cm[-1]:.4f}",
            "depth-mean c from settlement RMSE": f"{max(r['col_rmse'] for r in runs):.4f}",
            "depth-mean change at end": f"{cm[-1] - cm[0]:.4f}",
            "final surface c": f"{tc[-1]:.4f}",
            "final settlement mm": f"{tdh[-1]:.1f}", "run diff c": f"{run_diff_c:.4f}",
            "run diff settlement mm": f"{run_diff_dh:.2f}",
            "center/control max |dc|": f"{max(abs(vals[k][2] - 1).max() for k in ('center', 'control')):.4f}"}


# ---------------------------------------------------------------- 図3
def fig03(d, out):
    runs = [r for _, r in exp_a_runs()]
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
    fig, ax = plt.subplots(figsize=(4.4, 4.2))
    res = {}
    for (f, r), col, mk in zip(exp_a_runs(), (C1, C2, C3, C4), ("o", "s", "^", "D")):
        m, p = -r["meas"], -r["pred"]
        ratio = p.mean() / m.mean()
        corr = float(np.corrcoef(p, m)[0, 1])
        name = f.split("_")[1]
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
    eff = read_csv(A("cut_patterns", "effects.csv"))
    cats = [("全幅 1.16 深0.8m", "Full width\n(0.8 m)"), ("履帯2本 1.16 深0.8m", "Two tracks\n(0.8 m)"),
            ("中央 1.16 深0.8m", "Center\n(0.8 m)"), ("全幅 1.16 深0.3m", "Full width,\nshallow (0.3 m)")]
    cmp_rows = [r for r in read_csv(A("cut_then_cut", "compare.csv")) if r["region"] == "踏固め"]
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
    eff = read_csv(A("cut_levels", "effects.csv"))
    by = defaultdict(list)
    for r in eff:
        by[round(fl(r["level"]), 2)].append(fl(r["R_sep_N_ratio"]))
    by[1.0] = [1.0]
    return dict(sorted(by.items()))


def fig06(d, out):
    curve = [r for r in read_csv(A("calibration", "curve.csv")) if r["seg_m"] == "1.0"]
    cv = [r for r in read_csv(A("calibration", "cv.csv")) if r["seg_m"] == "1.0"]
    c = np.array([fl(r["c"]) for r in curve]); S = np.array([fl(r["S_mm"]) for r in curve])
    sd = np.array([fl(r["S_sd_mm"]) for r in curve])
    fig, axs = plt.subplots(2, 1, figsize=(5.6, 6.2), sharex=True)
    ax = axs[0]
    ax.scatter([fl(r["c"]) for r in cv], [fl(r["S"]) for r in cv], s=8, color="#c9c8c2", edgecolors="none",
               label="1 m segments")
    ax.errorbar(c, S, yerr=sd, color=C1, marker="o", capsize=2, label="Calibration curve (mean ± SD)")
    ax.set(ylabel="Additional settlement [mm]", title="(a) Additional settlement under tracks after cutting"
           + ("\n(x: K3, mean of top 3 voxels at track passage)" if OPTS.target == "c_cut_col3" else ""))
    ax.legend(fontsize=8)
    ax = axs[1]
    lv = levels_ratio(d)
    for k, v in lv.items():
        ax.scatter([k] * len(v), v, s=14, color=C2, alpha=0.55, edgecolors="none")
    ax.plot(list(lv), [np.mean(v) for v in lv.values()], color=C2, marker="o", label="Mean")
    ax.axhline(1, color=INK2, lw=0.8, ls="--")
    ax.set(xlabel="Degree of compaction [-]" + (" ((b): level as set)" if OPTS.target != "c_start" else ""),
           ylabel="Cutting resistance ratio [-]",
           title="(b) Separation resistance, ratio to adjacent undisturbed ground (full width)")
    ax.legend(fontsize=8, loc="center left")
    fig.tight_layout()
    save(fig, out, "fig06_calibration_and_cut.png")
    res = {f"S {cc_:.2f}": f"{s:.1f}" for cc_, s in zip(c, S)}
    res.update({f"ratio {k:.2f}": f"{np.mean(v):.2f}" for k, v in lv.items()})
    pos = defaultdict(list)
    for r in read_csv(A("cut_levels", "effects.csv")):
        pos[(r["band"], round(fl(r["level"]), 2))].append(fl(r["R_sep_N_ratio"]))
    for band in ("1", "3"):
        res[f"ratio band{band}"] = ", ".join(f"{l:.2f}:{np.mean(pos[(b, l)]):.2f}" for b, l in sorted(pos) if b == band)
    return res


# ---------------------------------------------------------------- 図7
def fig07(d, out):
    cv = [r for r in read_csv(A("calibration", "cv.csv")) if r["seg_m"] == "1.0"]
    c = np.array([fl(r["c"]) for r in cv]); ch = np.array([fl(r["c_hat"]) for r in cv])
    err = ch - c
    rmse = lambda m: float(np.sqrt(np.mean(err[m] ** 2)))
    allm = np.ones_like(c, bool); low = c < 1.15; sat = (c > 1.11) & (c < 1.17)
    fig, ax = plt.subplots(figsize=(4.4, 4.2))
    jit = (np.random.default_rng(0).random(len(c)) - 0.5) * 0.008
    ax.scatter(c + jit, ch, s=12, color=C1, alpha=0.6, edgecolors="none", label="1 m segments, leave-one-run-out\n(x jittered by ±0.004)")
    ax.plot([0.75, 1.25], [0.75, 1.25], color=INK2, lw=1, ls="--", label="1:1")
    ax.set(xlim=(0.75, 1.25), ylim=(0.75, 1.25),
           xlabel="True degree of compaction" + (" (K3) " if OPTS.target == "c_cut_col3" else " ") + "[-]",
           ylabel="Estimated degree of compaction [-]", title="Cross-validation of the calibration curve")
    ax.set_aspect("equal")
    note(ax, f"RMSE all: {rmse(allm):.3f} (n={allm.sum()})\nRMSE < 1.15: {rmse(low):.3f}\n"
             f"RMSE 1.12–1.16: {rmse(sat):.3f}", "lower right")
    ax.legend(fontsize=7, loc="upper left")
    fig.tight_layout()
    save(fig, out, "fig07_cross_validation.png")
    out_n = sum(r["out_of_range"] == "True" for r in cv)
    return {"target": OPTS.target, "n": f"{allm.sum()}", "RMSE all": f"{rmse(allm):.4f}", "RMSE <1.15": f"{rmse(low):.4f}",
            "RMSE 1.12–1.16": f"{rmse(sat):.4f}", "bias all": f"{err.mean():+.4f}", "out of range": f"{out_n}",
            "true range": f"{c.min():.3f}–{c.max():.3f}"}


# ---------------------------------------------------------------- 図8
def calibration_curve(seg=1.0):
    """図6(a)・図7 と同じ較正曲線（calibrate_settlement.py の既定の設定と --target で、settlement/cells.csv から作る）"""
    cells = cs.load_cells(A("settlement", "cells.csv"), OPTS.target)
    segments, _ = cs.make_segments(cells, seg, 0.01, 2)
    return cs.build_curve(segments, 0.02)


MIN_CELLS = 2        # 区間に必要なマスの数（calibrate_settlement.py の --min-cells の既定）
C_FLAT = 0.005       # 削る前の程度が 1.00 とみなす幅（|c − 1| ≤ これ）
C_COMPACTED = 1.01   # 削る前の程度がこれを超えるマスを「踏み固めた」とする


def then_cut_segments(path, cells_rows, curve, seg=1.0):
    """B2 の1記録の 1 m 区間（区間の形は較正と同じ：履帯ごと、履帯の位置のマス、マス MIN_CELLS 以上）。
    較正と違い、削る前の程度のばらつき（--homog）では除かない。区間は calibrate_settlement.make_segments で作る。
    境目・踏み固めたかの判定は削る前の程度（c_start）で行い、正解の列（--target）によらない。
    戻り値：区間ごとの dict（x0, 履帯, マスの数, S, 逆算値, 範囲外か, 削る前の地表の程度の統計, 正解の列の平均,
    深さ方向の平均, 境目か）"""
    name = os.path.basename(path)
    rows = cc.load(path)
    cols, _ = cc.depth_columns(rows)
    t0 = cts.cut_start_time(cts.load(path))
    tb = cc.by_time(rows)
    t_cut = cc.nearest_time(sorted(tb), t0)
    snap = {(r["lane"], r["unity_ix"], r["unity_iy"]): r for r in tb[t_cut]}
    cells, depth = [], {}
    for c in cells_rows:
        x, cst, S, tgt = fl(c["x"]), fl(c["c_start"]), -fl(c["extra_mm"]), fl(c[OPTS.target])
        if not all(math.isfinite(v) for v in (x, cst, S, tgt)):
            continue
        r = next((v for k, v in snap.items() if k[0] == c["lane"] and abs(v["_x"] - x) < 1e-3), None)
        depth[(c["group"], x)] = cc.column_average(r, r, cols, 0.3125, Z_OFFSET, COL_DEPTH)[0] if r is not None else math.nan
        cells.append({"file": name, "group": c["group"], "x": x, "c": cst, "S": S, "tgt": tgt})
    segs, _ = cs.make_segments(cells, seg, math.inf, MIN_CELLS)
    members = defaultdict(list)
    for c in cells:
        members[(c["group"], round(math.floor(c["x"] / seg) * seg, 6))].append(c)
    out = []
    for s in sorted(segs, key=lambda s: (s["group"], s["x0"])):
        m = members[(s["group"], round(s["x0"], 6))]
        assert len(m) == s["n"], (name, s["group"], s["x0"])
        cv = np.array([c["c"] for c in m])
        est, outr = cs.invert(curve, s["S"])
        out.append({"x0": s["x0"], "track": s["group"], "n": s["n"], "S": s["S"], "est": est, "out": outr,
                    "c_mean": float(cv.mean()), "c_sd": float(cv.std()), "c_min": float(cv.min()), "c_max": float(cv.max()),
                    "tgt": float(np.mean([c["tgt"] for c in m])),
                    "depth": float(np.nanmean([depth[(c["group"], c["x"])] for c in m])),
                    "boundary": bool((np.abs(cv - 1) <= C_FLAT).any() and (cv > C_COMPACTED).any())})
    return out


def fig08(d, out):
    from matplotlib.lines import Line2D
    curve = calibration_curve()
    cells = read_csv(A("settlement_then_cut", "cells.csv"))
    seeds = {os.path.basename(r["記録"])[:-4] + "_compaction.csv": int(r["seed"]) for r in MANIFEST
             if r["実験"] == "B2_then_cut" and r["使う"].startswith("○")}
    fig, axs = plt.subplots(1, 2, figsize=(8.6, 3.9), sharey=True)
    table = []
    LS = {"track_L": "-", "track_R": "--"}
    for p in records("B2_then_cut", True):
        name = os.path.basename(p)
        compacted = seeds[name] % 2 == 0
        ax = axs[0 if compacted else 1]
        segs = then_cut_segments(p, [c for c in cells if c["file"] == name], curve)
        for tr in ("track_L", "track_R"):
            ss = [s for s in segs if s["track"] == tr]
            x = [s["x0"] + 0.5 for s in ss]
            ax.plot(x, [s["c_mean"] for s in ss], color=C2, ls=LS[tr], lw=1, marker="s", ms=2.5, alpha=0.8)
            if OPTS.target != "c_start":
                ax.plot(x, [s["tgt"] for s in ss], color=C4, ls=LS[tr], lw=1, marker="D", ms=2.5, alpha=0.9)
            ax.plot(x, [s["depth"] for s in ss], color=C3, ls=LS[tr], lw=1, marker="^", ms=2.5, alpha=0.8)
            ax.plot(x, [s["est"] for s in ss], color=C1, ls=LS[tr], lw=1.2)
            for xi, s in zip(x, ss):
                ax.plot(xi, s["est"], ls="none", marker="X" if s["boundary"] else "o", ms=6 if s["boundary"] else 4.5,
                        color=C1, mfc="white" if s["out"] else C1, mew=1.2, zorder=3)
        for s in segs:
            table.append({"file": name, "seed": seeds[name], "run": "compacted" if compacted else "control",
                          "track": s["track"], "x0_m": f"{s['x0']:.1f}", "x1_m": f"{s['x0'] + 1:.1f}", "n_cells": s["n"],
                          "S_mm": f"{s['S']:.2f}", "c_hat": f"{s['est']:.4f}", "out_of_range": int(s["out"]),
                          "c_surface_mean": f"{s['c_mean']:.4f}", "c_surface_sd": f"{s['c_sd']:.4f}",
                          "c_surface_min": f"{s['c_min']:.4f}", "c_surface_max": f"{s['c_max']:.4f}",
                          f"{OPTS.target}_mean": f"{s['tgt']:.4f}",
                          f"c_depth_mean_{COL_DEPTH:.1f}m": f"{s['depth']:.4f}", "boundary": int(s["boundary"])})
    for ax, title in zip(axs, ("(a) Compacted by tracks (2 round trips), then cut", "(b) Control: cut without compaction")):
        ax.axhline(1, color=INK2, lw=0.8, ls=":")
        ax.set(xlabel="x along path (from machine reference at start) [m]", title=title)
    axs[0].set_ylabel("Degree of compaction [-]")
    h = [Line2D([], [], color=C1, marker="o", ms=4.5, label="Estimated (calibration curve)"),
         Line2D([], [], color=C1, marker="o", ms=4.5, mfc="white", ls="none", label="Out of range (clipped)"),
         Line2D([], [], color=C1, marker="X", ms=6, ls="none", label="Boundary segment"),
         Line2D([], [], color=C2, marker="s", ms=2.5, label="Surface (before cutting)"),
         *([Line2D([], [], color=C4, marker="D", ms=2.5, label="K3: top 3 voxels at track passage (true)")]
           if OPTS.target != "c_start" else []),
         Line2D([], [], color=C3, marker="^", ms=2.5, label=f"Mean to {COL_DEPTH:.1f} m depth (before cutting)"),
         Line2D([], [], color=INK2, ls="-", label="Left track"),
         Line2D([], [], color=INK2, ls="--", label="Right track")]
    fig.legend(handles=h, fontsize=7.5, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.1))
    note(axs[1], "1 m segments per track, cells under tracks;\none line per run and track", "upper right")
    fig.tight_layout()
    save(fig, out, "fig08_natural_compaction.png")
    p = A("settlement_then_cut", "segments_fig8.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"  -> {p}")
    res = {}

    def summary(rs, mean=False):
        inr = [fl(r["c_hat"]) for r in rs if not int(r["out_of_range"])]
        n_out = sum(int(r["out_of_range"]) for r in rs)
        txt = f"in range {len(inr)}" + (f" ({min(inr):.3f}–{max(inr):.3f}" + (f", mean {np.mean(inr):.3f}" if mean else "") + ")"
                                        if inr else "")
        return txt + f", out of range {n_out} (of {len(rs)} segments)"
    comp = [r for r in table if r["run"] == "compacted"]
    ctrl = [r for r in table if r["run"] == "control"]
    is_c = lambda r: fl(r["c_surface_mean"]) > C_COMPACTED
    res["B2 compacted run, compacted (excl. boundary)"] = summary([r for r in comp if is_c(r) and not int(r["boundary"])])
    res["B2 compacted run, boundary"] = summary([r for r in comp if int(r["boundary"])])
    res["B2 compacted run, not compacted"] = summary([r for r in comp if not is_c(r) and not int(r["boundary"])], True)
    res["B2 control run"] = summary(ctrl, True)

    def err(rs):  # 正解の列に対する逆算値の誤差（範囲内の区間だけ）
        rs = [r for r in rs if not int(r["out_of_range"])]
        e = np.array([fl(r["c_hat"]) - fl(r[f"{OPTS.target}_mean"]) for r in rs])
        tg = [fl(r[f"{OPTS.target}_mean"]) for r in rs]
        return (f"n {len(e)}, bias {e.mean():+.3f}, RMSE {math.sqrt(np.mean(e ** 2)):.3f}, "
                f"{OPTS.target} {min(tg):.3f}–{max(tg):.3f}") if len(e) else "n 0"
    res[f"B2 err vs {OPTS.target}, compacted (excl. boundary)"] = err([r for r in comp if is_c(r) and not int(r["boundary"])])
    res[f"B2 err vs {OPTS.target}, compacted x=4–6 m"] = err([r for r in comp if is_c(r) and not int(r["boundary"])
                                                            and 4 <= fl(r["x0_m"]) <= 6])
    res[f"B2 err vs {OPTS.target}, boundary"] = err([r for r in comp if int(r["boundary"])])
    res[f"B2 err vs {OPTS.target}, not compacted"] = err([r for r in comp if not is_c(r) and not int(r["boundary"])])
    res[f"B2 err vs {OPTS.target}, control"] = err(ctrl)
    return res


# ---------------------------------------------------------------- 図9
BAND_POS = {"1": "Band 1 (3–5 m)", "3": "Band 3 (7–9 m)"}   # 締め固めた帯の位置（刃先の開始位置から）


def hardening_ratios(d, cond):
    """各帯の比抵抗 ÷ 同じ記録の帯2・4（地山）の比抵抗の平均（docs/phase0.md §3.4 の表の定義）。
    戻り値：(程度ごとの比, 地山の比抵抗の平均, 帯2・4 の w, {(帯の番号, 程度): [(比, w), ...]})"""
    rows = read_csv(A(f"hardening_{cond}", "cut_bands", "bands.csv"))
    byf = defaultdict(list)
    for r in rows:
        byf[r["file"]].append(r)
    ratios, bank, bank_w, by_pos = defaultdict(list), [], [], defaultdict(list)
    for rs in byf.values():
        ref = statistics.mean(fl(r["specific_kPa"]) for r in rs if r["band"] in ("2", "4"))
        bank.append(ref)
        bank_w += [fl(r["state_c"]) for r in rs if r["band"] in ("2", "4")]
        for r in rs:
            if r["band"] in ("1", "3"):
                lv = round(fl(r["level"]), 2)
                ratios[lv].append(fl(r["specific_kPa"]) / ref)
                by_pos[(r["band"], lv)].append((fl(r["specific_kPa"]) / ref, fl(r["state_c"])))
    return dict(sorted(ratios.items())), statistics.mean(bank), bank_w, dict(by_pos)


def fig09(d, out):
    fig, axs = plt.subplots(1, 2, figsize=(9.0, 3.9), sharey=True)
    res = {}
    for k, (cond, label, col) in enumerate(HARDENING):
        rat, bank, _, by_pos = hardening_ratios(d, cond)
        res[cond] = ", ".join(f"{lv:.2f}:{np.mean(v):.2f}" for lv, v in rat.items()) + f"; bank {bank:.1f} kPa"
        off = (k - 1) * 0.008
        for ax, band in zip(axs, ("1", "3")):
            lv = sorted(l for b, l in by_pos if b == band)
            v = [[x[0] for x in by_pos[(band, l)]] for l in lv]
            for l, vv in zip(lv, v):
                ax.scatter([l + off] * len(vv), vv, s=12, color=col, alpha=0.45, edgecolors="none")
            ax.plot([l + off for l in lv], [np.mean(vv) for vv in v], color=col, marker="o",
                    label=f"{label}; undisturbed {bank:.0f} kPa")
            res[f"{cond} band{band}"] = ", ".join(
                f"{l:.2f}:{np.mean([x[0] for x in by_pos[(band, l)]]):.2f}"
                f"(w {'/'.join(f'{x[1]:.3f}' for x in by_pos[(band, l)])})" for l in lv)
    for ax, band in zip(axs, ("1", "3")):
        ax.axhline(1, color=INK2, lw=0.8, ls="--")
        ax.set(xlabel="Degree of compaction of the band [-]", title=f"({'ab'[band == '3']}) Compacted band at {BAND_POS[band]}")
    axs[0].set_ylabel("Specific cutting resistance ratio [-]")
    axs[0].legend(fontsize=7.5, loc="upper left")
    note(axs[1], "Ratio to undisturbed bands 2 and 4 of the same run;\none dot per run (1.16: 2 runs, others: 1 run)",
         "upper left")
    fig.tight_layout()
    save(fig, out, "fig09_hardening_cut.png")
    return res


# ---------------------------------------------------------------- 図10
def fig10(d, out):
    fig, ax = plt.subplots(figsize=(5.6, 3.9))
    res = {}
    for k, (cond, label, col) in enumerate(HARDENING):
        rows = read_csv(A(f"hardening_{cond}", "settlement", "by_level.csv"))
        fit = {r["x"]: r for r in read_csv(A(f"hardening_{cond}", "settlement", "fit.csv"))}["c_start"]
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


# ---------------------------------------------------------------- 追加の確認（本文の結論は変えない）
def check_pen_reference(d):
    """図5：貫入抵抗の比を、前の地山の帯・後ろの地山の帯・両隣の平均のそれぞれで割って比べる"""
    rows = read_csv(A("cut_patterns", "bands.csv"))
    byf = defaultdict(dict)
    for r in rows:
        byf[r["file"]][int(r["band"])] = r
    out = defaultdict(lambda: defaultdict(list))
    for bands in byf.values():
        for i in (1, 3):
            if i not in bands or (i - 1) not in bands or (i + 1) not in bands:
                continue
            for key in ("R_pen_N", "R_sep_N"):
                v, prev, nxt = (fl(bands[j][key]) for j in (i, i - 1, i + 1))
                lab = bands[i]["label"]
                out[(lab, key)]["prev"].append(v / prev)
                out[(lab, key)]["next"].append(v / nxt)
                out[(lab, key)]["both"].append(v / ((prev + nxt) / 2))
    bank = defaultdict(list)   # 地山の帯どうしの比（後ろ ÷ 前）：帯の位置だけで増える分
    for bands in byf.values():
        for i in (0, 2):
            if i in bands and (i + 2) in bands:
                for key in ("R_pen_N", "R_sep_N"):
                    bank[(i, i + 2, key)].append(fl(bands[i + 2][key]) / fl(bands[i][key]))
    res = {}
    for (lab, key), v in sorted(out.items()):
        res[f"{lab} {key} ratio prev/next/both"] = " / ".join(f"{np.mean(v[k]):.2f}" for k in ("prev", "next", "both"))
    for (i, j, key), v in sorted(bank.items()):
        res[f"bank band{j}/band{i} {key}"] = f"{np.mean(v):.2f} (n={len(v)})"
    return res


def check_edge_layer_w(d, blade_offset=2.8, trim=0.5):
    """図11：帯2・4 で刃が来る直前の、刃先の高さに当たるボクセルの締固めの程度（CompactionProbe）と、
    同じ帯の state_compaction_mean（check_cut_bands.py の bands.csv の state_c）を並べる"""
    res = {}
    depth = 0.08    # ex_compaction_bands・levels の切削深さ
    for cond, exp in HARDENING_SETS.items():
        st = defaultdict(list)
        for r in read_csv(A(f"hardening_{cond}", "cut_bands", "bands.csv")):
            if r["band"] in ("2", "4"):
                st[r["band"]].append(fl(r["state_c"]))
        w = defaultdict(list)
        for p in records(exp, True):
            rows = cc.load(p)
            cols, _ = cc.depth_columns(rows)
            tb = cc.by_time(rows)
            times = sorted(tb)
            first = {r["_cell"]: r for r in tb[times[0]]}
            mx = {t: tb[t][0]["_mx"] if "_mx" in tb[t][0] else fl(tb[t][0]["machine_x"]) for t in times}
            lv_of = {}   # この記録の帯1・3 の締固めの程度（check_cut_bands.py の bands.csv から）
            for r in read_csv(A(f"hardening_{cond}", "cut_bands", "bands.csv")):
                if r["file"] == os.path.basename(p).replace("_compaction.csv", ".csv") and r["band"] in ("1", "3"):
                    lv_of[r["band"]] = round(fl(r["level"]), 2)
            for band, (a, b) in (("1", (3.0, 5.0)), ("2", (5.0, 7.0)), ("3", (7.0, 9.0)), ("4", (9.0, 11.0))):
                lo, hi = a + trim + blade_offset, b - trim + blade_offset     # 締固めの記録の x（機体の基準点が原点）
                for cell, r0 in first.items():
                    if r0["_group"] not in ("track_L", "track_R", "center") or not lo <= r0["_x"] <= hi:
                        continue
                    before = [t for t in times if mx[t] + blade_offset < r0["_x"]]
                    if not before:
                        continue
                    r = next((v for v in tb[before[-1]] if v["_cell"] == cell), None)
                    if r is None:
                        continue
                    h_edge = r0["_h"] - depth
                    k = math.floor((r["_h"] - Z_OFFSET) / 0.3125 + 0.5) - math.floor((h_edge - Z_OFFSET) / 0.3125 + 0.5)
                    if 0 <= k < len(cols):
                        key = band if band in ("2", "4") else f"{band}@{lv_of.get(band, math.nan):.2f}"
                        w[key].append(cc.to_float(r[cols[k]]))
        for key in sorted(k for k in w if "@" in k):
            v = np.array(w[key])
            res[f"{cond} compacted band{key} edge-layer w (probe)"] = (
                f"mean {v.mean():.4f}, min {v.min():.4f}, max {v.max():.4f}, share<1 {np.mean(v < 0.9995) * 100:.0f}% (n={len(v)} cells)")
        for band in ("2", "4"):
            v, s_ = np.array(w[band]), np.array(st[band])
            res[f"{cond} band{band} edge-layer w (probe)"] = (
                f"mean {v.mean():.4f}, min {v.min():.4f}, max {v.max():.4f}, share<1 {np.mean(v < 0.9995) * 100:.0f}% (n={len(v)} cells)"
                if len(v) else "no probe cells (outside probe range x <= 12 m)")
            res[f"{cond} band{band} state_compaction_mean"] = (
                f"mean {s_.mean():.4f}, min {s_.min():.4f}, max {s_.max():.4f} (n={len(s_)} runs)")
    return res


CHECKS = {"check5_pen_reference": check_pen_reference, "check11_edge_layer_w": check_edge_layer_w}


FIGS = {1: fig01, 2: fig02, 3: fig03, 4: fig04, 5: fig05, 6: fig06, 7: fig07, 8: fig08, 9: fig09, 10: fig10, 11: fig11}


def main():
    global OPTS, MANIFEST
    ap = argparse.ArgumentParser(description="フェーズ0 の図1〜11 と本文の値の表を作る")
    ap.add_argument("--data", default=os.path.join(WS, "data", "phase0"), help="記録のフォルダ（既定 <ws>/data/phase0）")
    ap.add_argument("--out", help="図の出力先（既定 <data>/figures）")
    ap.add_argument("--only", type=int, nargs="+", help="描く図の番号（例 --only 6 7）。figure_values.csv は書かない")
    ap.add_argument("--skip-analysis", action="store_true", help="解析を実行せず、前回の data/phase0/analysis/ を使う")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--target", default="c_cut_col3", choices=["c_cut_col3", "c_start"],
                    help="較正の正解の列（既定 c_cut_col3 = K3。c_start は削る前の値）")
    OPTS = ap.parse_args()
    OPTS.out = OPTS.out or os.path.join(OPTS.data, "figures")
    MANIFEST = read_manifest(OPTS.data)
    os.makedirs(OPTS.out, exist_ok=True)
    if not OPTS.skip_analysis:
        print("解析")
        run_analysis()
    values = []
    for n in OPTS.only or sorted(FIGS):
        print(f"図{n}")
        res = FIGS[n](OPTS.data, OPTS.out)
        for k, v in (res or {}).items():
            print(f"  {k}: {v}")
            values.append({"figure": n, "item": k, "value": v})
    if OPTS.only:
        return
    for name, fn in CHECKS.items():
        print(name)
        for k, v in fn(OPTS.data).items():
            print(f"  {k}: {v}")
            values.append({"figure": name, "item": k, "value": v})
    p = os.path.join(OPTS.data, "figure_values.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["figure", "item", "value"])
        w.writeheader()
        w.writerows(values)
    print(f"保存: {p}")


if __name__ == "__main__":
    main()
