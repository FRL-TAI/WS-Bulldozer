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
  E.（T31）締固めの記録つきで取り直した同定用のエピソード（data/phase1/compaction_track/）の、履帯が踏む時点の K3
     （主）と K1・K4（参考）：作業 × 点ごとの分布、0.90 を下回るマスの割合、基準との差、s による動き、
     刃先の前の代わりの量（state_cut_compaction_mean）との対応、深さのずれの 95% 点（締固めの記録を取らない回との比較）。
     v2 の折り返しの確かめ（data/phase1/compaction_track/turnaround_v2/）：後退ごとの横のずれと向きの変化。

使い方（T31 の E だけ）：
  python3 analysis/phase1/check_compaction_candidates.py --parts E --report data/phase1/compaction_track/report.md
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
sys.path.insert(0, os.path.join(HERE, "..", "validation"))
from check_physics import settled_cut_rows   # noqa: E402

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


# ============================================================ E. T31：締固めの記録つきの取り直し
DT = os.path.join(D1, "compaction_track")
K_LOW = 0.90            # 締固めの範囲の下限（暫定。decisions/2026-11-18_締固めの範囲の下限は暫定0.90とし取り直しで確かめる.md）
MAX_DEV = 0.10          # pile_push の潜り（深さのずれの 95% 点）[m]
BLADE_OFFSET = 2.8      # 機体の基準点から刃先までの前後の距離 [m]（check_track_settlement の既定）
CUT_AHEAD = 0.25        # state_cut_compaction_* の範囲（刃先の前 0〜0.5 m）の中ほど [m]
POINT_S = {"base": 1.28, "s_m0p06": 1.22, "s_p0p06": 1.34, "s110": 1.10, "s140": 1.40}
POINT_ORDER = ["base", "s_m0p06", "s_p0p06", "s110", "s140", "phi_m10", "phi_p10", "c_m1p5", "c_p1p5",
               "rho_m70", "rho_p70"]


def dev95(df):
    rows = settled_cut_rows(df)
    return float(np.percentile(np.abs(rows["depth"] - rows["target_depth"]), 95)) if rows is not None else math.nan


def proxy_bins(df):
    """刃先の前の代わりの量 state_cut_compaction_mean を、範囲の中ほどの位置（記録の座標 x、1 m ごと）でまとめる"""
    r = df[(df.phase == "running") & (df.state_cut_compaction_n > 0)]
    x = r.distance + BLADE_OFFSET + CUT_AHEAD
    return r.assign(k=np.floor(x)).groupby("k").state_cut_compaction_mean.mean()


def ok_files(run_dir):
    """episodes.jsonl で status が ok で、締固めの記録が届いた（compaction_rows > 0）エピソードの CSV の名前
    （途中で止めた・失敗した回と、Unity から締固めの記録が届かなかった回を除く）"""
    import json
    out = set()
    with open(os.path.join(run_dir, "episodes.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("status") == "ok" and r.get("file") and r.get("compaction_rows", 0) > 0:
                out.add(r["file"])
    return out


def track_episodes():
    eps, cells = [], []
    ok = {}
    for f in sorted(glob.glob(os.path.join(DT, "*", "run_*", "ep*.csv"))):
        if f.endswith("_compaction.csv"):
            continue
        rd = os.path.dirname(f)
        if rd not in ok:
            ok[rd] = ok_files(rd)
        if os.path.basename(f) not in ok[rd]:
            continue
        m = NAME.search(os.path.basename(f))
        cp = f[:-4] + "_compaction.csv"
        if not m or not os.path.exists(cp):
            continue
        df = pd.read_csv(f)
        e = {"file": os.path.relpath(f, DT), "task": m.group(1), "point": m.group(2), "dev95": dev95(df),
             "s": float(df.label_swell.iloc[0]), "proxy": proxy_bins(df),
             "proxy_mean": df.loc[(df.phase == "running") & (df.state_cut_compaction_n > 0), "state_cut_compaction_mean"].mean()}
        tc = track_cells(cp)
        for c in tc:
            c.update(task=e["task"], point=e["point"], ep=e["file"], s=e["s"])
        e["n_cells"] = len(tc)
        e["x_max"] = max((c["x"] for c in tc), default=math.nan)
        e["K3_med"] = float(np.median([c["K3"] for c in tc])) if tc else math.nan
        e["K3_mean"] = float(np.mean([c["K3"] for c in tc])) if tc else math.nan
        eps.append(e)
        cells += tc
    return pd.DataFrame(eps), pd.DataFrame(cells)


def old_dev95():
    """締固めの記録を取らない回（力の経路の記録）の深さのずれの 95% 点（作業 × 点）"""
    out = defaultdict(list)
    for task in TASKS:
        for f in sorted(glob.glob(os.path.join(D1, task, "run_*", "ep*.csv"))):
            m = NAME.search(os.path.basename(f))
            if m and not f.endswith("_compaction.csv") and m.group(2) in POINT_ORDER:
                out[(task, m.group(2))].append(dev95(pd.read_csv(f)))
    return out


def part_e(skip_old=False):
    ep, ce = track_episodes()
    p("## E. 締固めの記録つきで取り直した同定用のエピソード（T31）")
    p("")
    if ep.empty:
        p("記録がない")
        return ce
    drop = ep[(ep.task == "pile_push") & (ep.dev95 > MAX_DEV)]
    p(f"記録 {len(ep)} 本（作業ごと：" + "、".join(f"{t} {int((ep.task == t).sum())}" for t in TASKS) + "）。"
      f"pile_push の潜り（深さのずれの 95% 点 > {MAX_DEV:.2f} m）で除いた記録 {len(drop)} 本"
      + ("：" + "、".join(f"{r.file}（{r.dev95 * 100:.1f} cm）" for r in drop.itertuples()) if len(drop) else "") + "。")
    p("")
    ep = ep.drop(drop.index)
    ce = ce[~ce.ep.isin(drop.file)]
    order = lambda pts: sorted(pts, key=lambda s: POINT_ORDER.index(s) if s in POINT_ORDER else 99)

    p("### E1. 記録の範囲と本数")
    p("")
    p("| 作業 | 点 | 本数 | マスの数（1本あたり） | 履帯が通り切ったマスの x の最大 [m] | 深さのずれの 95% 点 [cm]（中央値・最大） |")
    p("|---|---|---|---|---|---|")
    for t in TASKS:
        for pt in order(ep[ep.task == t].point.unique()):
            x = ep[(ep.task == t) & (ep.point == pt)]
            p(f"| {t} | {pt} | {len(x)} | {x.n_cells.mean():.0f} | {x.x_max.max():.2f} | "
              f"{x.dev95.median() * 100:.2f}・{x.dev95.max() * 100:.2f} |")
    p("")
    if not skip_old:
        old = old_dev95()
        p("深さのずれの 95% 点の比較（締固めの記録を取らない力の経路の記録。同じ作業・点。中央値・最大 [cm]、本数）：")
        p("")
        p("| 作業 | 点 | 記録あり（T31） | 記録なし（力の経路） |")
        p("|---|---|---|---|")
        for t in TASKS:
            for pt in order(ep[ep.task == t].point.unique()):
                x = ep[(ep.task == t) & (ep.point == pt)].dev95
                o = np.array(old.get((t, pt), []))
                p(f"| {t} | {pt} | {x.median() * 100:.2f}・{x.max() * 100:.2f}（{len(x)}） | "
                  + (f"{np.median(o) * 100:.2f}・{o.max() * 100:.2f}（{len(o)}）" if len(o) else "—") + " |")
        p("")

    for k, label in (("K3", "K3（表層 3 層の平均。主）"), ("K1", "K1（地表のボクセル。参考）"), ("K4", "K4（重み付け。参考）")):
        p(f"### E2. 履帯が踏む時点の {label}：作業 × 点の分布")
        p("")
        p(f"| 作業 | 点 | s | マス | 最小 | 5% | 中央値 | 95% | 最大 | {K_LOW:.2f} 未満の割合 |")
        p("|---|---|---|---|---|---|---|---|---|---|")
        for t in TASKS:
            for pt in order(ce[ce.task == t].point.unique()):
                v = ce[(ce.task == t) & (ce.point == pt)][k].to_numpy()
                p(f"| {t} | {pt} | {ce[(ce.task == t) & (ce.point == pt)].s.iloc[0]:.2f} | {len(v)} | " + " | ".join(qrow(v))
                  + f" | {np.mean(v < K_LOW) * 100:.2f}% |")
            v = ce[ce.task == t][k].to_numpy()
            p(f"| **{t} 全点** | | | {len(v)} | " + " | ".join(qrow(v)) + f" | {np.mean(v < K_LOW) * 100:.2f}% |")
        v = ce[k].to_numpy()
        p(f"| **3作業・全点** | | | {len(v)} | " + " | ".join(qrow(v)) + f" | {np.mean(v < K_LOW) * 100:.2f}% |")
        p("")
    kmin = ce.K3.min()
    r = ce.loc[ce.K3.idxmin()]
    p(f"**全点の K3 の最小値は {kmin:.4f}（{r.task}・{r.point}・{r.ep}、{r.group}、x = {r.x:.2f} m）で、"
      f"{K_LOW:.2f} {'以上' if kmin >= K_LOW else '未満'}である。**")
    p("")

    p("### E3. 基準との差（エピソードごとの K3 の中央値の平均の差 ± 標準誤差。判定はしない）")
    p("")
    p("| 作業 | 点 | 本数 | K3 の中央値（エピソードの平均） | 基準との差 |")
    p("|---|---|---|---|---|")
    for t in TASKS:
        e_t = ep[ep.task == t]
        b = e_t[e_t.point == "base"].K3_med
        for pt in order(e_t.point.unique()):
            x = e_t[e_t.point == pt].K3_med
            if pt == "base":
                p(f"| {t} | {pt} | {len(x)} | {x.mean():.4f} | — |")
            else:
                se = math.sqrt(x.var(ddof=1) / len(x) + b.var(ddof=1) / len(b))
                p(f"| {t} | {pt} | {len(x)} | {x.mean():.4f} | {x.mean() - b.mean():+.4f} ± {se:.4f} |")
    p("")

    p("### E4. s による動き（基準と s の4点。エピソードごとの K3 の中央値と最小値）")
    p("")
    p("| 作業 | s 1.10 | 1.22 | 1.28（基準） | 1.34 | 1.40 | 傾き d(中央値)/ds ± 標準誤差 | 最小値（s ごと） |")
    p("|---|---|---|---|---|---|---|---|")
    for t in TASKS:
        e_t = ep[(ep.task == t) & ep.point.isin(POINT_S)]
        c_t = ce[(ce.task == t) & ce.point.isin(POINT_S)]
        cols, mins = [], []
        for sv in (1.10, 1.22, 1.28, 1.34, 1.40):
            x = e_t[np.isclose(e_t.s, sv)].K3_med
            cols.append(f"{x.mean():.4f}" if len(x) else "—")
            mv = c_t[np.isclose(c_t.s, sv)].K3
            mins.append(f"{mv.min():.3f}" if len(mv) else "—")
        if len(e_t) > 2:
            A_ = np.vstack([e_t.s, np.ones(len(e_t))]).T
            coef, res, *_ = np.linalg.lstsq(A_, e_t.K3_med, rcond=None)
            dof = len(e_t) - 2
            s2 = float(((e_t.K3_med - A_ @ coef) ** 2).sum()) / dof
            se = math.sqrt(s2 * np.linalg.inv(A_.T @ A_)[0, 0])
            slope = f"{coef[0]:+.4f} ± {se:.4f}"
        else:
            slope = "—"
        p(f"| {t} | " + " | ".join(cols) + f" | {slope} | " + "・".join(mins) + " |")
    p("")

    p("### E5. 刃先の前の代わりの量（state_cut_compaction_mean）との対応")
    p("")
    p("1 m ごと（記録の座標 x。代わりの量は、刃先の前 0〜0.5 m の範囲の中ほど distance + 2.8 + 0.25 m で置いた）に、"
      "K3 の平均（履帯 2 本のマス）と代わりの量の平均を比べた。エピソード単位は、マスの K3 の平均と、running で削っている行の代わりの量の平均。")
    p("")
    p("| 作業 | 1 m の区切りの数 | K3 − 代わりの量（平均・標準偏差） | 相関（1 m） | 相関（エピソード） |")
    p("|---|---|---|---|---|")
    for t in TASKS:
        e_t = ep[ep.task == t]
        pairs = []
        for e in e_t.itertuples():
            cc = ce[ce.ep == e.file]
            kb = cc.assign(k=np.floor(cc.x)).groupby("k").K3.mean()
            j = kb.index.intersection(e.proxy.index)
            pairs += list(zip(kb[j], e.proxy[j]))
        a_ = np.array(pairs)
        if len(a_) > 2:
            d = a_[:, 0] - a_[:, 1]
            r1 = np.corrcoef(a_[:, 0], a_[:, 1])[0, 1]
            r2 = np.corrcoef(e_t.K3_mean, e_t.proxy_mean)[0, 1] if len(e_t) > 2 else math.nan
            p(f"| {t} | {len(a_)} | {d.mean():+.4f}・{d.std():.4f} | {r1:+.2f} | {fmt(r2, 2)} |")
    p("")
    return ce


def part_turnaround_v2():
    recs = sorted(f for f in glob.glob(os.path.join(DT, "turnaround_v2", "*_v2*.csv")) if not f.endswith("_compaction.csv"))
    p("### E6. 折り返しの別名版（v2）の確かめ")
    p("")
    p("後退の区間ごとに、判定に使う進み p の最小値と、そのときの開始時の向きに直交する横のずれ・向きの変化（D と同じ求め方）。")
    p("")
    p("| 記録 | ρ | 後退の回数 | ROUND_TRIPS | p の最小値 [m]（後退ごと） | 横のずれ [m]（後退ごと） | 向きの変化 [deg]（後退ごと） | raising |")
    p("|---|---|---|---|---|---|---|---|")
    sys.path.insert(0, os.path.join(HERE, "..", "validation"))
    import check_recording as cr
    for f in recs:
        d = pd.read_csv(f)
        run = d[d.phase == "running"].reset_index(drop=True)
        pr = cr.progress_series(run)
        x0, y0, yaw0 = run.x.iloc[0], run.y.iloc[0], run.yaw.iloc[0]
        ux, uy = math.cos(yaw0), math.sin(yaw0)
        back = (run.cmd_vx < 0).to_numpy()
        legs, i = [], 0
        while i < len(run):
            if back[i]:
                j = i
                while j < len(run) and back[j]:
                    j += 1
                legs.append((i, j))
                i = j
            else:
                i += 1
        pm, lat, dyaw = [], [], []
        for a_, b_ in legs:
            k = a_ + int(np.argmin(pr[a_:b_]))
            r = run.iloc[k]
            pm.append(pr[k])
            lat.append(-(r.x - x0) * uy + (r.y - y0) * ux)
            dyaw.append(math.degrees((r.yaw - yaw0 + math.pi) % (2 * math.pi) - math.pi))
        name = str(d.episode_name.iloc[0])
        want = cr.expected_round_trips(name, d.seed.iloc[0])
        p(f"| {os.path.basename(f)} | {d.label_rho0.iloc[0]:.0f} | {len(legs)} | {want} | " + "・".join(f"{v:.3f}" for v in pm)
          + " | " + "・".join(f"{v:+.3f}" for v in lat) + " | " + "・".join(f"{v:+.2f}" for v in dyaw)
          + f" | {'あり' if 'raising' in set(d.phase) else 'なし'} |")
    p("")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--report")
    ap.add_argument("--parts", default="ABCD", help="出す部分（例 ABCD、E）")
    ap.add_argument("--skip-old", action="store_true", help="E で、締固めの記録を取らない回の深さのずれを読まない")
    a = ap.parse_args()
    if "E" in a.parts and set(a.parts) == {"E"}:
        p("# 締固めの記録つきの取り直し（T31）")
    else:
        p("# 締固めの列の候補と範囲の下限の材料（T29）")
    p("")
    df = None
    if "A" in a.parts:
        part_a()
    if set("BCD") & set(a.parts):
        df = part_b()
        if "C" in a.parts:
            part_c(df)
        if "D" in a.parts:
            part_d()
    if "E" in a.parts:
        ce = part_e(a.skip_old)
        part_turnaround_v2()
        if a.report and ce is not None and len(ce):
            os.makedirs(os.path.dirname(a.report), exist_ok=True)
            ce.to_csv(os.path.join(os.path.dirname(a.report), "track_cells_t31.csv"), index=False)
    if a.report:
        os.makedirs(os.path.dirname(a.report), exist_ok=True)
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
        if df is not None:
            df.to_csv(os.path.join(os.path.dirname(a.report), "track_cells.csv"), index=False)
        print(f"保存: {a.report}")


if __name__ == "__main__":
    main()
