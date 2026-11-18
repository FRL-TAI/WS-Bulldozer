"""
締固めの列の定義と範囲の下限を決めるための材料を集める（T29。決定はしない）。

置き場所: analysis/phase1/check_compaction_candidates.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_compaction_candidates.py [--report data/phase1/compaction_candidates/report.md]

notes の decisions/2026-11-17_締固めの列の定義.md（「履帯が踏む時点の表層の締固めの程度」）の候補：
  K1  地表のボクセル1つ（c_z0。phase0 の c_cut と同じ）
  K2  表層 2 層の平均（c_z0・c_z1 の単純平均）
  K3  表層 3 層の平均（c_z0〜c_z2 の単純平均。phase0 の c_cut_col3 と同じ）
  K4  深さ方向の重み付け：ボクセル k の土の厚さ t_k（地表のボクセルは 0.3125 m × 土の割合、その下は 0.3125 m）に
      exp(−z_k / L) を掛けた重みの平均（z_k は地表から測ったボクセル k の土の中点の深さ、L = 0.3125 m、c_z0〜c_z5）
「履帯が踏む時点」は phase0 の check_track_settlement.py と同じ：排土板は通り過ぎたが履帯はまだ来ていない最後の記録。

出すもの:
  A. フェーズ1 の同定用の記録（力の経路・地形の経路、3作業、すべての点）の時系列の締固めの列
     state_cut_compaction_mean（刃先の高さのボクセル、刃先の前 0〜0.5 m）と state_compaction_mean（地表、刃先の前 0〜1 m）の
     分布（running の行、作業 × 点）、エピソードごとの平均の、基準との差 ± 標準誤差。
     ※ どちらも「履帯が踏む時点」の値ではない（記録に深さ方向・履帯の位置の値がない）。
  B. 締固めの記録（*_compaction.csv）から、履帯が踏む時点の候補 K1〜K4（履帯の位置のマス）
     - phase0 の B1（帯）・B3（程度）：削る前が地山（|c_start − 1| ≤ 0.005）のマスの分布（flat_cut に近い）
     - phase0 の B2：踏み固めた記録・対照の記録
     - T12 の pile_push（s = 1.10・1.40、data/phase1/maxdensity/run_*_t12_once）
     候補どうしの相関。
  C. phase0 の較正（図7）：較正の正解を c_start・K1〜K4 に変えたときの交差検証（1 m 区間。区間は c_start でそろうものに固定）
     phase0 の B2（図8）：区間ごとの逆算値（c_start の較正曲線）と、区間の平均の K1〜K4・c_start との差
  D. 往復するエピソードの折り返し（obs.distance ≤ 0.2 m）の余裕：後退の区間ごとの、開始位置からの最小の直線距離と、
     開始時の向きに直交する横のずれ
"""
import argparse
import glob
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "phase0"))
import calibrate_settlement as cs   # noqa: E402
import check_track_settlement as cts   # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
D1 = os.path.join(ROOT, "data", "phase1")
D0 = os.path.join(ROOT, "data", "phase0")
CELL = 0.3125
Z_OFFSET = 0.0125
L_DECAY = 0.3125
CANDS = ["K1", "K2", "K3", "K4"]
QS = [0, 5, 50, 95, 100]
TASKS = ["flat_cut", "flat_piecewise", "pile_push"]

OUT = []


def p(s=""):
    OUT.append(s)
    print(s)


def fmt(v, d=3):
    return "—" if v is None or not np.isfinite(v) else f"{v:.{d}f}"


def qrow(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    if not len(v):
        return ["—"] * 5
    return [fmt(x) for x in np.percentile(v, QS)]


# ============================================================ A. フェーズ1 の時系列
NAME = re.compile(r"ex_(?:ident|swell)_(flat_cut|flat_piecewise|pile_push)_(.+)\.csv$")


def phase1_episodes():
    """同定用の記録（力の経路・地形の経路。地形の経路の flat_cut は T25 の vis_net を含む）と、
    膨張率の端のエピソード（ex_swell_*：flat_cut の s = 1.10 は力の経路の swell の回、s = 1.40 と pile_push は T12）"""
    out = []
    dirs = [("flat_cut", "force"), ("flat_piecewise", "force"), ("pile_push", "force"), ("vis_net", "terrain"),
            ("terrain_flat_cut", "terrain"), ("terrain_flat_piecewise", "terrain"), ("terrain_pile_push", "terrain"),
            ("maxdensity", "force")]
    for d, route in dirs:
        for f in sorted(glob.glob(os.path.join(D1, d, "run_*", "ep*.csv"))):
            m = NAME.search(os.path.basename(f))
            if not m or f.endswith("_compaction.csv"):
                continue
            if d == "maxdensity" and "_swell_" not in os.path.basename(f):
                continue
            out.append({"path": f, "route": route, "task": m.group(1), "point": m.group(2)})
    return out


def part_a():
    eps = phase1_episodes()
    rows = []
    pooled = defaultdict(lambda: defaultdict(list))
    for e in eps:
        d = pd.read_csv(e["path"], usecols=lambda c: c in (
            "phase", "state_compaction_mean", "state_cut_compaction_mean", "state_cut_compaction_min",
            "state_cut_compaction_n", "label_swell"))
        r = d[d.phase == "running"]
        cut = r[r.state_cut_compaction_n > 0]
        key = (e["task"], e["point"])
        pooled[key]["cut"] += list(cut.state_cut_compaction_mean)
        pooled[key]["cutmin"] += list(cut.state_cut_compaction_min)
        pooled[key]["surf"] += list(r.state_compaction_mean)
        rows.append({**e, "cut_mean": cut.state_cut_compaction_mean.mean(), "surf_mean": r.state_compaction_mean.mean(),
                     "cut_frac": len(cut) / max(len(r), 1),
                     "swell": float(d.label_swell.dropna().iloc[0]) if "label_swell" in d and d.label_swell.notna().any() else np.nan})
    ep = pd.DataFrame(rows)
    p("## A. フェーズ1 の同定用の記録の時系列の締固めの列（running の行）")
    p("")
    p(f"エピソード {len(ep)} 本（力の経路 {int((ep.route == 'force').sum())}、地形の経路 {int((ep.route == 'terrain').sum())}）。"
      "力の経路と地形の経路は点ごとにまとめた。")
    p("")
    for col, label in (("cut", "state_cut_compaction_mean（刃先の高さのボクセル、刃先の前 0〜0.5 m の平均）"),
                       ("cutmin", "state_cut_compaction_min（同じ範囲の最小）"),
                       ("surf", "state_compaction_mean（地表、刃先の前 0〜1 m の平均）")):
        p(f"### {label}")
        p("")
        p("| 作業 | 点 | 本数 | 行数 | 最小 | 5% | 中央値 | 95% | 最大 |")
        p("|---|---|---|---|---|---|---|---|---|")
        for task in TASKS:
            pts = sorted({pt for (t, pt) in pooled if t == task}, key=lambda s: (s != "base", s))
            for pt in pts:
                v = pooled[(task, pt)][col]
                n = int(((ep.task == task) & (ep.point == pt)).sum())
                p(f"| {task} | {pt} | {n} | {len(v)} | " + " | ".join(qrow(v)) + " |")
        p("")
    p("### エピソードごとの平均の、基準との差（平均の差 ± 標準誤差。state_cut_compaction_mean・state_compaction_mean）")
    p("")
    p("| 作業 | 点 | 本数 | cut の平均 | 基準との差 | surf の平均 | 基準との差 |")
    p("|---|---|---|---|---|---|---|")
    for task in TASKS:
        e_t = ep[ep.task == task]
        b = e_t[e_t.point == "base"]
        for pt in sorted(e_t.point.unique(), key=lambda s: (s != "base", s)):
            x = e_t[e_t.point == pt]
            cells = []
            for col in ("cut_mean", "surf_mean"):
                m = x[col].mean()
                if pt == "base":
                    cells += [fmt(m, 4), "—"]
                else:
                    diff = m - b[col].mean()
                    se = math.sqrt(x[col].var(ddof=1) / len(x) + b[col].var(ddof=1) / len(b))
                    cells += [fmt(m, 4), f"{diff:+.4f} ± {se:.4f}"]
            p(f"| {task} | {pt} | {len(x)} | " + " | ".join(cells) + " |")
    p("")
    return ep


# ============================================================ B. 締固めの記録から、履帯が踏む時点の候補
def surface_fill(h):
    u = (h - Z_OFFSET) / CELL + 0.5
    f = u - math.floor(u)
    return 1.0 if f < 1e-6 else f


def candidates(r):
    cz = r["_cz"]
    k = {"K1": cz[0] if cz else math.nan,
         "K2": float(np.mean(cz[:2])) if len(cz) >= 2 and all(np.isfinite(cz[:2])) else math.nan,
         "K3": float(np.mean(cz[:3])) if len(cz) >= 3 and all(np.isfinite(cz[:3])) else math.nan}
    f = surface_fill(r["_h"])
    t = [CELL * f] + [CELL] * (len(cz) - 1)
    z, top, w, s = [], 0.0, [], 0.0
    for tk in t:
        z.append(top + tk / 2)
        top += tk
    w = np.array([tk * math.exp(-zk / L_DECAY) for tk, zk in zip(t, z)])
    c = np.array(cz)
    ok = np.isfinite(c)
    k["K4"] = float((w[ok] * c[ok]).sum() / w[ok].sum()) if ok.all() else math.nan
    k["fill"] = f
    return k


class A:   # check_track_settlement の既定と同じ
    blade_offset = 2.8
    track_front = 1.1
    margin = 0.3


def track_cells(path):
    """check_track_settlement.analyze_file と同じ判定で、履帯が踏む直前の記録から候補を求める"""
    rows = cts.load(path)
    t0 = cts.cut_start_time(rows)
    run = [r for r in rows if r["_t"] >= t0]
    mx_final = max(r["_mx"] for r in run)
    cells = defaultdict(list)
    for r in run:
        if r["_group"] in ("track_L", "track_R"):
            cells[(r["lane"], r["unity_ix"], r["unity_iy"])].append(r)
    out = []
    for key, rs in cells.items():
        rs.sort(key=lambda r: r["_t"])
        x = rs[0]["_x"]
        if mx_final < x + A.track_front + A.margin:
            continue
        lo, hi = x - A.blade_offset + A.margin, x - A.track_front - A.margin
        mid = [r for r in rs if lo <= r["_mx"] <= hi]
        if not mid:
            continue
        r0, rc, re_ = rs[0], mid[-1], rs[-1]
        out.append({"file": os.path.basename(path), "lane": key[0], "group": r0["_group"], "x": x,
                    "c_start": r0["_c"], "cut_mm": (r0["_h"] - rc["_h"]) * 1000.0,
                    "extra_mm": (re_["_h"] - rc["_h"]) * 1000.0, **candidates(rc)})
    return out


def manifest():
    m = []
    with open(os.path.join(D0, "MANIFEST.md"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("| `") and "○" in line:
                cols = [c.strip() for c in line.strip().strip("|").split("|")]
                m.append({"rec": cols[0].strip("`"), "exp": cols[1], "seed": int(cols[3])})
    return m


def part_b():
    man = manifest()
    allc = []
    for r in man:
        if r["exp"] not in ("B1_bands", "B3_levels", "B2_then_cut"):
            continue
        cp = os.path.join(D0, r["rec"][:-4] + "_compaction.csv")
        for c in track_cells(cp):
            c["exp"] = r["exp"]
            c["run"] = ("compacted" if r["seed"] % 2 == 0 else "control") if r["exp"] == "B2_then_cut" else ""
            allc.append(c)
    for cp in sorted(glob.glob(os.path.join(D1, "maxdensity", "run_*_t12_once", "*pile_push*_compaction.csv"))):
        s = "1.10" if "s110" in cp else "1.40"
        for c in track_cells(cp):
            c["exp"] = f"T12_pile_push_s{s}"
            c["run"] = ""
            allc.append(c)
    df = pd.DataFrame(allc)

    p("## B. 締固めの記録（*_compaction.csv）から求めた、履帯が踏む時点の候補（履帯の位置のマス）")
    p("")
    p(f"候補：K1 地表のボクセル、K2 表層 2 層の平均、K3 表層 3 層の平均、K4 土の厚さ × exp(−z/{L_DECAY} m) の重み付け平均（c_z0〜c_z5）。")
    p("")
    groups = [
        ("B1・B3：削る前が地山（|c_start−1| ≤ 0.005）", (df.exp.isin(["B1_bands", "B3_levels"])) & ((df.c_start - 1).abs() <= 0.005)),
        ("B1・B3：削る前に締め固めた（c_start > 1.005）", (df.exp.isin(["B1_bands", "B3_levels"])) & (df.c_start > 1.005)),
        ("B1・B3：削る前に緩めた（c_start < 0.995）", (df.exp.isin(["B1_bands", "B3_levels"])) & (df.c_start < 0.995)),
        ("B2 踏み固めた記録：踏み固めた（c_start > 1.01）", (df.exp == "B2_then_cut") & (df.run == "compacted") & (df.c_start > 1.01)),
        ("B2 踏み固めた記録：地山（|c_start−1| ≤ 0.005）", (df.exp == "B2_then_cut") & (df.run == "compacted") & ((df.c_start - 1).abs() <= 0.005)),
        ("B2 対照の記録", (df.exp == "B2_then_cut") & (df.run == "control")),
        ("T12 pile_push s = 1.10", df.exp == "T12_pile_push_s1.10"),
        ("T12 pile_push s = 1.40", df.exp == "T12_pile_push_s1.40"),
    ]
    p("| 群 | マス | 削った厚さ 中央値 mm | 候補 | 最小 | 5% | 中央値 | 95% | 最大 | < 1/1.40 (0.714) | < 1/1.10 (0.909) | > 1.20 |")
    p("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, m in groups:
        g = df[m]
        for i, k in enumerate(["c_start"] + CANDS):
            v = g[k].to_numpy(float)
            v = v[np.isfinite(v)]
            frac = lambda cond: f"{100 * cond.mean():.0f}%" if len(v) else "—"
            head = f"| {name} | {len(g)} | {fmt(g.cut_mm.median(), 1)} " if i == 0 else "| | | "
            p(head + f"| {k} | " + " | ".join(qrow(v)) + f" | {frac(v < 1 / 1.40)} | {frac(v < 1 / 1.10)} | {frac(v > 1.20)} |")
    p("")
    p("土の割合（地表のボクセル、履帯が踏む直前）：" + "、".join(
        f"{n} 中央値 {df[m].fill.median():.2f}" for n, m in groups if m.any()))
    p("")

    p("### 候補どうしの相関（すべてのマス、群をまとめて）")
    p("")
    cols = ["c_start"] + CANDS
    cm = df[cols].corr()
    p("| | " + " | ".join(cols) + " |")
    p("|---|" + "---|" * len(cols))
    for a in cols:
        p(f"| {a} | " + " | ".join(f"{cm.loc[a, b]:.3f}" for b in cols) + " |")
    p("")
    p("### 候補どうしの相関（地山以外のマスだけ：|c_start − 1| > 0.005、または pile_push）")
    p("")
    sub = df[((df.c_start - 1).abs() > 0.005) | df.exp.str.startswith("T12")]
    cm = sub[cols].corr()
    p(f"マス {len(sub)}")
    p("")
    p("| | " + " | ".join(cols) + " |")
    p("|---|" + "---|" * len(cols))
    for a in cols:
        p(f"| {a} | " + " | ".join(f"{cm.loc[a, b]:.3f}" for b in cols) + " |")
    p("")
    p("### 追加の沈下との順位相関（Spearman、マスごと）")
    p("")
    p("| 群 | マス | " + " | ".join(cols) + " |")
    p("|---|---|" + "---|" * len(cols))
    for name, m in [("B1・B3（較正）", df.exp.isin(["B1_bands", "B3_levels"])), ("B2", df.exp == "B2_then_cut"),
                    ("T12 pile_push", df.exp.str.startswith("T12"))]:
        g = df[m]
        S = -g.extra_mm
        p(f"| {name} | {len(g)} | " + " | ".join(fmt(g[k].corr(S, method="spearman")) for k in cols) + " |")
    p("")

    p("### T12 pile_push：前後の位置ごとの候補（1 m 区間、左右の履帯をまとめた平均）")
    p("")
    p("x は開始時の機体の基準点からの前後の位置。山は刃先の 3〜5 m 先（基準点からは約 5.8〜7.8 m）に置いた。")
    p("")
    p("| s | x [m] | マス | 削った厚さ mm | c_start | K1 | K2 | K3 | K4 | 追加の沈下 mm |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    for s in ("1.10", "1.40"):
        g = df[df.exp == f"T12_pile_push_s{s}"].copy()
        g["x0"] = np.floor(g.x)
        for x0, h in g.groupby("x0"):
            p(f"| {s} | {x0:.0f}〜{x0 + 1:.0f} | {len(h)} | {h.cut_mm.mean():.1f} | {h.c_start.mean():.3f} | "
              + " | ".join(f"{h[k].mean():.3f}" for k in CANDS) + f" | {-h.extra_mm.mean():.1f} |")
    p("")
    return df


# ============================================================ C. 較正（図7）と B2（図8）
def segments_fixed(df, target, seg=1.0):
    """区間は c_start がそろう（SD ≤ 0.01）・マス 2 以上のものに固定し、正解だけを target の区間平均に変える"""
    out = []
    for (f, g, k), h in df.groupby(["file", "group", np.floor(df.x / seg)]):
        if len(h) < 2 or h.c_start.std(ddof=0) > 0.01:
            continue
        out.append({"file": f, "group": g, "x0": k * seg, "n": len(h), "c": float(h[target].mean()),
                    "S": float(-h.extra_mm.mean())})
    return out


def part_c(df):
    cal = df[df.exp.isin(["B1_bands", "B3_levels"])]
    p("## C. phase0 の較正（図7）と B2（図8）での対応")
    p("")
    p("### 較正の正解を変えたときの交差検証（記録を1つずつ除く、1 m 区間、程度の刻み 0.02）")
    p("")
    p("区間は c_start がそろう区間に固定した（図7 と同じ区間の集合）。正解だけを各候補の区間平均にした。")
    p("")
    p("| 正解 | 区間 | 正解の範囲 | RMSE（全体） | 平均誤差 | RMSE（< 1.15） | 範囲外 |")
    p("|---|---|---|---|---|---|---|")
    for k in ["c_start"] + CANDS:
        segs = segments_fixed(cal, k)
        res = cs.cross_validate(segs, 0.02)
        summ = cs.summarize(res, 1.15)
        cv = [s["c"] for s in segs]
        allr = summ.get("全体") or next(iter(summ.values()))
        low = next((v for kk, v in summ.items() if "<" in kk or "未満" in kk), None)
        p(f"| {k} | {len(segs)} | {min(cv):.3f}〜{max(cv):.3f} | {allr['rmse']:.4f} | {allr['bias']:+.4f} | "
          f"{fmt(low['rmse'], 4) if low else '—'} | {allr['out']} |")
    p("")
    p("（summarize の区分：" + "、".join(cs.summarize(cs.cross_validate(segments_fixed(cal, 'c_start'), 0.02), 1.15).keys()) + "）")
    p("")

    # B2：図8 と同じ区間（1 m、履帯ごと、マス 2 以上、c_start のばらつきでは除かない）
    curve = cs.build_curve(segments_fixed(cal, "c_start"), 0.02)
    b2 = df[df.exp == "B2_then_cut"]
    seg_rows = []
    for (f, g, k), h in b2.groupby(["file", "group", np.floor(b2.x)]):
        if len(h) < 2:
            continue
        S = float(-h.extra_mm.mean())
        est, outr = cs.invert(curve, S)
        cv = h.c_start.to_numpy()
        boundary = bool((np.abs(cv - 1) <= 0.005).any() and (cv > 1.01).any())
        seg_rows.append({"run": h.run.iloc[0], "x0": k, "est": est, "out": outr, "boundary": boundary,
                         "cut_mm": h.cut_mm.mean(), "c_start": h.c_start.mean(),
                         **{c: h[c].mean() for c in CANDS}})
    sg = pd.DataFrame(seg_rows)
    sg["cat"] = np.where(sg.run == "control", "対照の記録",
                         np.where(sg.boundary, "踏み固めた記録：境目",
                                  np.where(sg.c_start > 1.01, "踏み固めた記録：踏み固めた", "踏み固めた記録：踏み固めていない")))
    p("### B2：区間ごとの逆算値（c_start の較正曲線）と候補の区間平均")
    p("")
    p("| 区分 | 区間 | うち範囲外 | 削った厚さ mm | 逆算値 | c_start | K1 | K2 | K3 | K4 |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    for cat, h in sg.groupby("cat"):
        p(f"| {cat} | {len(h)} | {int(h.out.sum())} | {h.cut_mm.mean():.1f} | {h.est.mean():.3f} | {h.c_start.mean():.3f} | "
          + " | ".join(f"{h[c].mean():.3f}" for c in CANDS) + " |")
    p("")
    p("逆算値との差（範囲内の区間だけ。平均の差・RMSE・相関）：")
    p("")
    p("| 対象 | 区間 | " + " | ".join(["c_start"] + CANDS) + " |")
    p("|---|---|" + "---|" * (1 + len(CANDS)))
    for name, h in [("範囲内のすべて", sg[~sg.out]),
                    ("踏み固めた記録の範囲内（境目を含む）", sg[(~sg.out) & (sg.run == "compacted")]),
                    ("削った区間（削った厚さ > 30 mm）の範囲内", sg[(~sg.out) & (sg.cut_mm > 30)]),
                    ("踏み固めた記録の x = 4〜6 m（踏み固めた土を削った区間）", sg[(~sg.out) & (sg.run == "compacted") & sg.x0.between(4, 6)]),
                    ("踏み固めた記録の x = 7〜8 m（地山を削った区間）", sg[(~sg.out) & (sg.run == "compacted") & sg.x0.between(7, 8)]),
                    ("対照の記録の範囲内", sg[(~sg.out) & (sg.run == "control")])]:
        cells = []
        for c in ["c_start"] + CANDS:
            d = h[c] - h.est
            r = h[c].corr(h.est) if len(h) > 2 else math.nan
            cells.append(f"{d.mean():+.3f}・{math.sqrt((d ** 2).mean()):.3f}・{fmt(r, 2)}")
        p(f"| {name} | {len(h)} | " + " | ".join(cells) + " |")
    p("")
    p("削った区間（> 30 mm）の区間ごとの値：")
    p("")
    p("| 記録 | x [m] | 削った厚さ mm | 逆算値 | 範囲外 | c_start | K1 | K2 | K3 | K4 |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in sg[sg.cut_mm > 30].sort_values(["run", "x0"]).iterrows():
        p(f"| {r.run} | {r.x0:.0f} | {r.cut_mm:.1f} | {r.est:.3f} | {'○' if r.out else ''} | {r.c_start:.3f} | "
          + " | ".join(f"{r[c]:.3f}" for c in CANDS) + " |")
    p("")
    return sg


# ============================================================ D. 折り返し
def part_d():
    recs = (sorted(glob.glob(os.path.join(D0, "A_passes", "*_ex_compaction_passes.csv")))
            + sorted(glob.glob(os.path.join(D0, "B2_then_cut", "*_ex_compaction_then_cut.csv")))
            + sorted(glob.glob(os.path.join(D1, "readout", "*_ex_compaction_passes.csv")))
            + sorted(glob.glob(os.path.join(D1, "maxdensity", "run_*", "*compaction_passes*.csv"))))
    recs = [r for r in recs if not r.endswith("_compaction.csv")]
    p("## D. 往復するエピソードの折り返しの余裕")
    p("")
    p("後退の区間（cmd_vx < 0 が続く区間）ごとに、開始位置からの最小の直線距離（記録の distance の列）と、"
      "そのときの、開始時の向きに直交する横のずれ（記録の最初の行の x・y・yaw から）と向きの変化を求めた。`ex_compaction_passes`・`ex_compaction_then_cut` は"
      "最小の直線距離が 0.2 m 以下になったときに折り返す。T12 の `_md2000`・`_md2578` は edge_x の進みで判定する。")
    p("")
    p("| 記録 | 判定 | ρ | 後退の回数 | 折り返した回数 | 最小距離の最大 [m] | 横のずれ [m]（後退ごと） | 向きの変化 [deg]（後退ごと） |")
    p("|---|---|---|---|---|---|---|---|")
    for f in recs:
        d = pd.read_csv(f, usecols=lambda c: c in ("t", "x", "y", "yaw", "cmd_vx", "distance", "label_rho0", "phase"))
        x0, y0, yaw0 = d.x.iloc[0], d.y.iloc[0], d.yaw.iloc[0]
        ux, uy = math.cos(yaw0), math.sin(yaw0)
        back = (d.cmd_vx < 0).to_numpy()
        legs, i = [], 0
        while i < len(d):
            if back[i]:
                j = i
                while j < len(d) and back[j]:
                    j += 1
                legs.append((i, j))
                i = j
            else:
                i += 1
        mins, lat, dyaw, turned = [], [], [], 0
        for a, b in legs:
            seg = d.iloc[a:b]
            dist = seg.distance.to_numpy()          # bull_ope が判定に使う開始位置からの直線距離（記録の列）
            k = int(np.nanargmin(dist))
            r = seg.iloc[k]
            mins.append(float(dist[k]))
            lat.append(float(-(r.x - x0) * uy + (r.y - y0) * ux))
            dyaw.append(math.degrees((r.yaw - yaw0 + math.pi) % (2 * math.pi) - math.pi))
            if b < len(d):                           # 記録の終わりより前に後退が終わった（折り返した）
                turned += 1
        rule = "edge_x" if re.search(r"_md\d+", f) else "distance ≤ 0.2"
        rho = d.label_rho0.dropna().iloc[0] if "label_rho0" in d and d.label_rho0.notna().any() else math.nan
        p(f"| {os.path.relpath(f, ROOT)} | {rule} | {rho:.0f} | {len(legs)} | {turned} | {max(mins) if mins else math.nan:.3f} | "
          + "・".join(f"{v:+.3f}" for v in lat) + " | " + "・".join(f"{v:+.2f}" for v in dyaw) + " |")
    p("")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--report")
    a = ap.parse_args()
    p("# 締固めの列の候補と範囲の下限の材料（T29）")
    p("")
    part_a()
    df = part_b()
    part_c(df)
    part_d()
    if a.report:
        os.makedirs(os.path.dirname(a.report), exist_ok=True)
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
        df.to_csv(os.path.join(os.path.dirname(a.report), "track_cells.csv"), index=False)
        print(f"保存: {a.report}")


if __name__ == "__main__":
    main()
