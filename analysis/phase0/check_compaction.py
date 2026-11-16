"""
CompactionProbe の CSV（compaction_*.csv）を読み、履帯による締固めの起き方を要約する。

使い方：
  python3 check_compaction.py <compaction_*.csv> [オプション]

オプション：
  --x0, --x1   集計に使う前後の範囲 [m]（開始位置からの距離）。既定は 0.5〜7.5 m
  --cell       地形のマスの大きさ [m]（沈下量の予測に使う）。既定は 0.3125
  --z-offset   地形のローカル座標の高さ 0 のワールドの高さ [m]（Terrain の Transform の y）。既定は 0
  --surface-fill  地表のボクセルに土が入っている割合を固定する（0〜1）。既定は高さから計算
  --avg-depth  深さ方向の平均を取る範囲 [m]（最初の記録の地表から）。既定は 0.5
  --dh-scale   沈下量からの推定で、実測の沈下量に掛ける倍率。既定は 1.0
  --timeline   記録の時刻ごとの表も表示する（旧版の出力）
  --out DIR    表を CSV に保存するフォルダ（passes.csv、depth.csv、along_x.csv、columns.csv、column_average.csv）
  --plot       図を PNG に保存する（--out が必要。matplotlib があるときだけ）

出力：
  1. 通過ごとの表     machine_x の折り返しから通過を判定し、各通過の終わりの締固めの程度・沈下量と、
                      最終値に対する到達率を列ごとに示す
  2. 深さ方向の分布   2a：最初と最後の記録の、深さ方向のボクセルごとの締固めの程度の平均
                      2b：深さ方向の締固めの程度の変化から質量保存で予測した沈下量と、実測の沈下量の比較
                          （地表のボクセルは土が入っている割合を考慮。ボクセルごとの寄与も示す）
  3. 前後方向の分布   最後の記録の、マスの前後位置ごとの締固めの程度と沈下量（マスの大きさの倍数にまとめる）
  4. 列ごとの値       履帯の幅の中の列（track_L-0.16 など）ごとの最初と最後の値（複数の列を記録したときだけ）
  5. 深さ方向の平均   地表から --avg-depth までの土の、質量で重み付けした平均の締固めの程度（真値）と、
                      沈下量だけから計算した推定値の比較。沈下量の倍率 k の当てはめと、通過ごとの推移

列の名前が "track_L+0.15" のように付いている場合は、先頭の基本の名前（track_L、track_R、center、control）で
まとめて集計する（CompactionProbe で履帯の幅の中の複数の列を記録したとき用）。
"""
import argparse
import csv
import math
import os
import re
from collections import defaultdict

import numpy as np

BASE_LANE = re.compile(r"^(track_L|track_R|center|control)")
LANE_ORDER = ["track_L", "track_R", "center", "control"]


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return math.nan


def lane_group(name):
    m = BASE_LANE.match(name)
    return m.group(1) if m else name


def sorted_groups(groups):
    return sorted(groups, key=lambda g: (LANE_ORDER.index(g) if g in LANE_ORDER else len(LANE_ORDER), g))


# ---------------------------------------------------------------- 読み込み
def load(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("データがありません")
    for r in rows:
        r["_t"] = to_float(r["sim_time"])
        r["_x"] = to_float(r["x"])
        r["_mx"] = to_float(r["machine_x"])
        r["_c"] = to_float(r["c_surface"])
        r["_h"] = to_float(r["height"])
        r["_group"] = lane_group(r["lane"])
        r["_cell"] = (r["lane"], r["unity_ix"], r["unity_iy"])
    return rows


def depth_columns(rows):
    cols = sorted([c for c in rows[0] if re.fullmatch(r"c_z\d+", c)], key=lambda c: int(c[3:]))
    has = bool(cols) and any(math.isfinite(to_float(r[cols[0]])) for r in rows)
    return cols, has


# ---------------------------------------------------------------- 通過の判定
def snapshots(rows):
    """記録の時刻ごとの (時刻, 機体の位置, phase) を時刻順に返す"""
    seen = {}
    for r in rows:
        if r["_t"] not in seen:
            seen[r["_t"]] = (r["_t"], r["_mx"], r["phase"])
    return [seen[t] for t in sorted(seen)]


def detect_passes(snaps, eps=0.05):
    """machine_x の向きが変わるところで区切り、通過のリスト [(番号, 向き, 開始時刻, 終了時刻)] を返す。
    向きは前進が +1、後退が -1。|Δx| < eps の間（停止中）は前の向きを引き継ぐ。"""
    run = [s for s in snaps if s[2] == "running"]
    if len(run) < 2:
        return []
    passes = []
    cur_dir, start_t = 0, run[0][0]
    for (t0, x0, _), (t1, x1, _) in zip(run[:-1], run[1:]):
        dx = x1 - x0
        d = 0 if abs(dx) < eps else (1 if dx > 0 else -1)
        if d == 0:
            continue
        if cur_dir == 0:
            cur_dir = d
        elif d != cur_dir:
            passes.append((cur_dir, start_t, t0))   # 折り返しの直前の記録で前の通過を閉じる
            cur_dir, start_t = d, t0
    if cur_dir != 0:
        passes.append((cur_dir, start_t, run[-1][0]))
    return [(i + 1, d, ts, te) for i, (d, ts, te) in enumerate(passes)]


# ---------------------------------------------------------------- 集計の補助
def in_range(rows, x0, x1):
    return [r for r in rows if x0 <= r["_x"] <= x1]


def by_time(rows):
    d = defaultdict(list)
    for r in rows:
        d[r["_t"]].append(r)
    return d


def nearest_time(times, t):
    return min(times, key=lambda s: abs(s - t))


def summarize(rows_t, group, h0):
    """ある時刻の、ある列の (締固めの程度の平均, 沈下量の平均 [mm], マスの数)"""
    g = [r for r in rows_t if r["_group"] == group]
    if not g:
        return math.nan, math.nan, 0
    c = np.array([r["_c"] for r in g])
    dh = np.array([r["_h"] - h0.get(r["_cell"], math.nan) for r in g])
    return float(np.nanmean(c)), float(np.nanmean(dh) * 1000.0), len(g)


def surface_fill(h, cell, z_offset, fixed=None):
    """地表のボクセルに土が入っている割合（0〜1）。
    AGX では高さ 0（地形のローカル座標）がボクセルの中心にあたるので、ボクセルの下端は (k - 0.5) × cell。
    fixed を指定したらその値を使う。"""
    if fixed is not None:
        return fixed
    u = (h - z_offset) / cell + 0.5          # ボクセルの下端から測った高さ（マスの大きさ単位）
    f = u - math.floor(u)
    return 1.0 if f < 1e-6 else f            # ちょうど上端なら満杯とみなす


def predict_settlement(r, r0, cols, cell, z_offset, fill_fixed=None):
    """深さ方向の締固めの程度の変化から、質量保存で沈下量 [m] を予測する。

    各ボクセルの土の質量は変わらない（ボクセルの間で土は移動しない）と仮定すると、
    締固めの程度（密度に比例）が c_old → c_new に変わったボクセルの土の厚さは t × c_old / c_new になる。
        Δh = Σ_k t_k × (c_old,k / c_new,k − 1)
    t_k は最初の記録での土の厚さで、地表のボクセルだけ cell × (土が入っている割合)、それより下は cell。

    ボクセルは surface_z（地表のボクセルの番号）で対応づけるので、地表のボクセルが下に移った場合も
    同じボクセルどうしを比べる。最初の地表のボクセルが空になった場合は計算できないので NaN を返す。

    戻り値: (Δh の合計, [ボクセルごとの寄与]) [m]。寄与は最初の記録の z0, z1, ... の順
    """
    zs0, zs1 = to_float(r0.get("surface_z")), to_float(r.get("surface_z"))
    if not (math.isfinite(zs0) and math.isfinite(zs1)):
        return math.nan, []
    old = {int(zs0) - k: to_float(r0[c]) for k, c in enumerate(cols)}
    new = {int(zs1) - k: to_float(r[c]) for k, c in enumerate(cols)}
    if int(zs1) < int(zs0):
        return math.nan, []                  # 最初の地表のボクセルが空になった
    contrib = []
    for k in range(len(cols)):
        idx = int(zs0) - k
        c_old, c_new = old.get(idx, math.nan), new.get(idx, math.nan)
        if not (math.isfinite(c_old) and math.isfinite(c_new) and c_new > 0):
            contrib.append(math.nan)
            continue
        t = cell * surface_fill(r0["_h"], cell, z_offset, fill_fixed) if k == 0 else cell
        contrib.append(t * (c_old / c_new - 1.0))
    total = float(np.nansum(contrib)) if any(math.isfinite(v) for v in contrib) else math.nan
    return total, contrib


def column_average(r, r0, cols, cell, z_offset, depth, fill_fixed=None):
    """地表から深さ depth [m] までの土（最初の記録の時点の土）の、質量で重み付けした平均の締固めの程度。

    締固めの程度は密度に比例するので、ボクセル k の土の質量は t_k × c_k（t_k は最初の記録での土の厚さ）。
    同じ土の質量 M = Σ t_k × c_old,k が、いまは厚さ T_new = Σ t_k × c_old,k / c_new,k を占めているので、
        平均の締固めの程度（最初） = M / T_old、 T_old = Σ t_k
        平均の締固めの程度（いま） = M / T_new
    対象の土は最初の記録で地表から depth までにあった土に固定する（沈下しても同じ土を追う）。
    地表のボクセルの t は cell × 土が入っている割合、最後のボクセルは depth に収まる分だけ。

    戻り値: (最初の平均, いまの平均, M, T_old)。計算できなければ NaN
    """
    nan4 = (math.nan, math.nan, math.nan, math.nan)
    zs0, zs1 = to_float(r0.get("surface_z")), to_float(r.get("surface_z"))
    if not (math.isfinite(zs0) and math.isfinite(zs1)) or int(zs1) < int(zs0):
        return nan4
    old = {int(zs0) - k: to_float(r0[c]) for k, c in enumerate(cols)}
    new = {int(zs1) - k: to_float(r[c]) for k, c in enumerate(cols)}
    remaining, M, T_old, T_new = depth, 0.0, 0.0, 0.0
    for k in range(len(cols)):
        if remaining <= 1e-9:
            break
        idx = int(zs0) - k
        c_old, c_new = old.get(idx, math.nan), new.get(idx, math.nan)
        if not (math.isfinite(c_old) and math.isfinite(c_new) and c_new > 0):
            return nan4
        t = cell * surface_fill(r0["_h"], cell, z_offset, fill_fixed) if k == 0 else cell
        t = min(t, remaining)
        remaining -= t
        M += t * c_old
        T_old += t
        T_new += t * c_old / c_new
    if remaining > 1e-6:
        return nan4                        # 記録したボクセルだけでは depth に届かない
    return M / T_old, M / T_new, M, T_old


# ---------------------------------------------------------------- 各表
def report_passes(rows, snaps, passes, groups, h0, t_first):
    tb = by_time(rows)
    times = sorted(tb)
    t_last = times[-1]
    final = {g: summarize(tb[t_last], g, h0) for g in groups}
    base = {g: summarize(tb[t_first], g, h0) for g in groups}

    print("\n" + "=" * 78)
    print("1. 通過ごとの表（各通過の終わりの値。到達率 = 最初からの増加 ÷ 最後までの増加）")
    print("=" * 78)
    if not passes:
        print("通過を判定できませんでした（running の記録が少ないか、machine_x が変化していません）")
        return []

    table = []
    for g in groups:
        c_b, dh_b, _ = base[g]
        c_f, dh_f, _ = final[g]
        total = c_f - c_b
        print(f"\n== {g} ==")
        print(f"{'通過':>4s} {'向き':>4s} {'終了時刻':>8s} {'c_surf':>8s} {'増加':>8s} {'到達率':>7s} {'dh_mm':>8s}")
        print(f"{'開始':>4s} {'':>4s} {t_first:8.1f} {c_b:8.4f} {'':>8s} {'':>7s} {dh_b:8.2f}")
        prev = c_b
        for k, d, ts, te in passes:
            t = nearest_time(times, te)
            c, dh, _ = summarize(tb[t], g, h0)
            frac = (c - c_b) / total if abs(total) > 1e-6 else math.nan
            frac_s = f"{frac * 100:6.1f}%" if math.isfinite(frac) else f"{'-':>7s}"
            print(f"{k:4d} {'前進' if d > 0 else '後退':>4s} {t:8.1f} {c:8.4f} {c - prev:+8.4f} {frac_s} {dh:8.2f}")
            table.append({"lane": g, "pass": k, "direction": "forward" if d > 0 else "backward",
                          "t_end": t, "c_surf": c, "dc": c - prev, "fraction": frac, "dh_mm": dh})
            prev = c
    return table


def report_depth(rows, groups, cols, cell, t_first, z_offset, fill_fixed=None):
    tb = by_time(rows)
    t_last = max(tb)
    first = {r["_cell"]: r for r in tb[t_first]}
    last = {r["_cell"]: r for r in tb[t_last]}

    print("\n" + "=" * 78)
    print("2. 深さ方向の分布と、質量保存による沈下量の確認")
    print("=" * 78)

    # ---- 2a. ボクセルごとの締固めの程度 ----
    print("\n2a. ボクセルごとの締固めの程度の平均（z0 が地表のボクセル。最初と最後の記録）")
    print(f"{'列':>8s} {'時刻':>6s} " + " ".join(f"{c:>7s}" for c in cols))
    table = []
    for g in groups:
        for label, t in (("最初", t_first), ("最後", t_last)):
            g_rows = [r for r in tb[t] if r["_group"] == g]
            if not g_rows:
                continue
            means = [float(np.nanmean([to_float(r[c]) for r in g_rows])) for c in cols]
            print(f"{g:>8s} {label:>6s} " + " ".join(f"{v:7.4f}" for v in means))
            row = {"lane": g, "when": "first" if label == "最初" else "last", "t": t}
            row.update({c: v for c, v in zip(cols, means)})
            table.append(row)

    # ---- 2b. 質量保存による予測沈下と実測沈下 ----
    fills = [surface_fill(r["_h"], cell, z_offset, fill_fixed) for r in tb[t_first]]
    print("\n2b. 予測沈下と実測沈下（最初の記録 → 最後の記録、マスごとに計算して平均）")
    print(f"    予測沈下 = Σ 土の厚さ × (最初の c ÷ 最後の c − 1)。地表のボクセルの土の厚さ = {cell} m × 土が入っている割合")
    print(f"    地表のボクセルに土が入っている割合: 平均 {np.mean(fills):.3f}"
          f"（{'指定値' if fill_fixed is not None else f'高さから計算、z_offset = {z_offset} m'}）")
    print(f"{'列':>8s} {'マス数':>6s} " + " ".join(f"{c + 'mm':>8s}" for c in cols)
          + f" {'予測mm':>8s} {'実測mm':>8s} {'差mm':>7s} {'比':>6s} {'相関':>6s} {'地表移動':>8s}")
    for g in groups:
        preds, meas, contribs, moved = [], [], [], 0
        for key, r in last.items():
            if r["_group"] != g or key not in first:
                continue
            r0 = first[key]
            if to_float(r.get("surface_z")) != to_float(r0.get("surface_z")):
                moved += 1
            p, c = predict_settlement(r, r0, cols, cell, z_offset, fill_fixed)
            if not math.isfinite(p):
                continue
            preds.append(p)
            meas.append(r["_h"] - r0["_h"])
            contribs.append(c)
        if not preds:
            continue
        preds, meas = np.array(preds), np.array(meas)
        cmean = np.nanmean(np.array(contribs), axis=0) * 1000.0
        p_mm, m_mm = preds.mean() * 1000.0, meas.mean() * 1000.0
        ratio = p_mm / m_mm if abs(m_mm) > 1e-6 else math.nan
        corr = float(np.corrcoef(preds, meas)[0, 1]) if len(preds) > 2 and preds.std() > 0 and meas.std() > 0 else math.nan
        print(f"{g:>8s} {len(preds):6d} " + " ".join(f"{v:8.2f}" for v in cmean)
              + f" {p_mm:8.2f} {m_mm:8.2f} {p_mm - m_mm:7.2f} {ratio:6.3f} {corr:6.3f} {moved:8d}")
        row = {"lane": g, "when": "check", "n_cells": len(preds), "pred_dh_mm": p_mm, "meas_dh_mm": m_mm,
               "diff_mm": p_mm - m_mm, "ratio": ratio, "corr": corr, "surface_moved": moved}
        row.update({f"{c}_mm": v for c, v in zip(cols, cmean)})
        table.append(row)
    print("    差 = 予測 − 実測、比 = 予測 ÷ 実測、相関 = マスごとの予測と実測の相関係数、"
          "地表移動 = 地表のボクセルの番号が変わったマスの数")
    return table


def report_along_x(rows, groups, h0, cell):
    tb = by_time(rows)
    t_last = max(tb)
    last = tb[t_last]

    print("\n" + "=" * 78)
    print(f"3. 前後方向の分布（最後の記録 t = {t_last:.1f} s。x はマスの大きさ {cell} m ごとにまとめた位置）")
    print("=" * 78)

    # 列ごとにマスの x がわずかにずれるので、マスの大きさの倍数にまとめて列どうしをそろえる
    def x_bin(x):
        return round(round(x / cell) * cell, 4)

    data = defaultdict(dict)   # x -> {group: (c, dh_mm)}
    for g in groups:
        per_x = defaultdict(list)
        for r in last:
            if r["_group"] == g:
                per_x[x_bin(r["_x"])].append(r)
        for x, rs in per_x.items():
            c = float(np.nanmean([r["_c"] for r in rs]))
            dh = float(np.nanmean([r["_h"] - h0.get(r["_cell"], math.nan) for r in rs])) * 1000.0
            data[x][g] = (c, dh)

    head = f"{'x [m]':>7s} " + " ".join(f"{g + ' c':>11s} {g + ' dh':>11s}" for g in groups)
    print(head)
    table = []
    for x in sorted(data):
        cells = []
        row = {"x": x}
        for g in groups:
            c, dh = data[x].get(g, (math.nan, math.nan))
            cells.append(f"{c:11.4f} {dh:11.2f}")
            row[f"{g}_c"] = c
            row[f"{g}_dh_mm"] = dh
        print(f"{x:7.2f} " + " ".join(cells))
        table.append(row)
    return table


def report_column_average(rows, groups, cols, cell, t_first, passes, z_offset, depth,
                          dh_scale=1.0, fill_fixed=None):
    """5. 深さ方向の平均の締固めの程度と、沈下量からの推定"""
    tb = by_time(rows)
    times = sorted(tb)
    t_last = times[-1]
    first = {r["_cell"]: r for r in tb[t_first]}

    print("\n" + "=" * 78)
    print(f"5. 深さ方向の平均の締固めの程度（最初の記録で地表から {depth} m までにあった土の、質量で重み付けした平均）")
    print("=" * 78)
    print("   真値   = 各ボクセルの締固めの程度から計算した平均")
    print("   推定値 = 沈下量だけから計算した平均（質量 M が厚さ T_old + Δh を占めるとして M / (T_old + Δh)）")
    print(f"   Δh には実測の沈下量 × {dh_scale} を使う（--dh-scale）")

    def cells_at(t):
        """時刻 t の (真値, 推定値, 地表の締固めの程度, 実測の沈下量) を列ごとに集める"""
        out = defaultdict(list)
        for r in tb[t]:
            r0 = first.get(r["_cell"])
            if r0 is None:
                continue
            _, c_true, M, T_old = column_average(r, r0, cols, cell, z_offset, depth, fill_fixed)
            if not math.isfinite(c_true):
                continue
            dh = r["_h"] - r0["_h"]
            c_hat = M / (T_old + dh_scale * dh)
            out[r["_group"]].append((c_true, c_hat, r["_c"], dh))
        return out

    # ---- 5a. 最後の記録での比較 ----
    last = cells_at(t_last)
    print("\n5a. 最後の記録（マスごとに計算して平均）")
    print(f"{'列':>8s} {'マス数':>6s} {'真値':>8s} {'推定値':>8s} {'誤差':>8s} {'RMSE':>8s} "
          f"{'相関':>6s} {'沈下と地表c':>11s} {'沈下と真値':>10s}")
    table = []
    for g in groups:
        v = last.get(g)
        if not v:
            continue
        a = np.array(v)
        c_true, c_hat, c_surf, dh = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
        err = c_hat - c_true

        def corr(x, y):
            return float(np.corrcoef(x, y)[0, 1]) if len(x) > 2 and x.std() > 0 and y.std() > 0 else math.nan
        r_est = corr(c_hat, c_true)
        r_surf = corr(-dh, c_surf)    # 沈下（下向きを正）と地表の締固めの程度の相関
        r_col = corr(-dh, c_true)     # 沈下と深さ方向の平均の相関
        print(f"{g:>8s} {len(a):6d} {c_true.mean():8.4f} {c_hat.mean():8.4f} {err.mean():+8.4f} "
              f"{math.sqrt((err ** 2).mean()):8.4f} {r_est:6.3f} {r_surf:11.3f} {r_col:10.3f}")
        table.append({"lane": g, "when": "last", "n_cells": len(a), "c_true": c_true.mean(),
                      "c_hat": c_hat.mean(), "bias": err.mean(), "rmse": math.sqrt((err ** 2).mean()),
                      "corr_est": r_est, "corr_dh_surface": r_surf, "corr_dh_column": r_col})
    print("    誤差 = 推定値 − 真値（平均）、相関 = マスごとの推定値と真値の相関、")
    print("    沈下と地表c・沈下と真値 = マスごとの沈下量との相関（どちらが沈下量とよく対応するか）")

    # ---- 5b. 沈下量の倍率の当てはめ ----
    print("\n5b. 予測沈下 = k × 実測沈下 となる k（原点を通る最小二乗、マスごと）")
    for g in groups:
        preds, meas = [], []
        for r in tb[t_last]:
            if r["_group"] != g or r["_cell"] not in first:
                continue
            p, _ = predict_settlement(r, first[r["_cell"]], cols, cell, z_offset, fill_fixed)
            m = r["_h"] - first[r["_cell"]]["_h"]
            if math.isfinite(p) and abs(m) > 1e-6:
                preds.append(p)
                meas.append(m)
        if len(meas) > 2:
            pm, mm = np.array(preds), np.array(meas)
            k = float((pm * mm).sum() / (mm * mm).sum())
            print(f"{g:>8s}  k = {k:.4f}（マス数 {len(mm)}）")
            table.append({"lane": g, "when": "fit", "k": k, "n_cells": len(mm)})
    print("    --dh-scale にこの k を指定すると、推定値の系統的な誤差を補正できる")

    # ---- 5c. 通過ごとの推移 ----
    if passes:
        print("\n5c. 通過ごとの真値と推定値（各通過の終わり）")
        track_groups = [g for g in groups if g.startswith("track")]
        print(f"{'通過':>4s} {'時刻':>7s} " + " ".join(f"{g + ' 真値':>13s} {g + ' 推定':>13s}" for g in track_groups))
        for k, d, ts, te in passes:
            t = nearest_time(times, te)
            v = cells_at(t)
            cells = []
            for g in track_groups:
                a = np.array(v.get(g, [(math.nan,) * 4]))
                cells.append(f"{np.nanmean(a[:, 0]):13.4f} {np.nanmean(a[:, 1]):13.4f}")
                table.append({"lane": g, "when": f"pass{k}", "t": t,
                              "c_true": float(np.nanmean(a[:, 0])), "c_hat": float(np.nanmean(a[:, 1]))})
            print(f"{k:4d} {t:7.1f} " + " ".join(cells))
    return table


def report_columns(rows, h0, t_first):
    """履帯の幅の中の列（track_L-0.16 など）ごとの、最初と最後の値。列が1つしかない走路は省略する"""
    tb = by_time(rows)
    t_last = max(tb)
    lanes = sorted({r["lane"] for r in rows if r["lane"] != r["_group"]})
    if not lanes:
        return []

    print("\n" + "=" * 78)
    print("4. 履帯の幅の中の列ごとの値（列の名前の数値は、履帯の中心線からのマスの中心の位置 [m]、左方が正）")
    print("=" * 78)
    print(f"{'列':>16s} {'マス数':>6s} {'c 最初':>8s} {'c 最後':>8s} {'dh_mm 最後':>11s}")
    table = []
    for lane in sorted(lanes, key=lambda s: (lane_group(s), to_float(s[len(lane_group(s)):]))):
        first = [r for r in tb[t_first] if r["lane"] == lane]
        last = [r for r in tb[t_last] if r["lane"] == lane]
        if not last:
            continue
        c0 = float(np.nanmean([r["_c"] for r in first])) if first else math.nan
        c1 = float(np.nanmean([r["_c"] for r in last]))
        dh = float(np.nanmean([r["_h"] - h0.get(r["_cell"], math.nan) for r in last])) * 1000.0
        print(f"{lane:>16s} {len(last):6d} {c0:8.4f} {c1:8.4f} {dh:11.2f}")
        table.append({"lane": lane, "n_cells": len(last), "c_first": c0, "c_last": c1, "dh_mm_last": dh})
    return table


def report_timeline(rows, groups, h0, cols, has_depth):
    tb = by_time(rows)
    print("\n" + "=" * 78)
    print("（参考）記録の時刻ごとの表")
    print("=" * 78)
    for g in groups:
        print(f"\n== {g} ==")
        print(f"{'sim_time':>9s} {'phase':>9s} {'machine_x':>9s} {'c_surf':>8s} {'dh_mm':>8s} {'z_depth':>7s}")
        for t in sorted(tb):
            gr = [r for r in tb[t] if r["_group"] == g]
            if not gr:
                continue
            c, dh, _ = summarize(tb[t], g, h0)
            zd = ""
            if has_depth:
                depths = []
                for r in gr:
                    vals = [to_float(r[col]) for col in cols]
                    over = [k for k, v in enumerate(vals) if math.isfinite(v) and v > 1.001]
                    depths.append(max(over) + 1 if over else 0)
                zd = f"{max(depths):7d}"
            print(f"{t:9.1f} {gr[0]['phase']:>9s} {gr[0]['_mx']:9.2f} {c:8.4f} {dh:8.2f} {zd:>7s}")


# ---------------------------------------------------------------- 保存
def write_csv(path, table):
    if not table:
        return
    keys = list(table[0].keys())
    for row in table[1:]:
        keys += [k for k in row if k not in keys]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(table)
    print(f"保存: {path}")


# center と control はどちらも変化しないことが多く、線が重なる。control を破線にして center を見えるようにする
STYLE = {"control": dict(linestyle="--", zorder=3), "center": dict(linestyle="-", linewidth=3, zorder=2)}


def plot(out, pass_table, along_table, groups):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib がないため、図は作りません（pip install matplotlib）")
        return

    if pass_table:
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        for g in groups:
            pts = [p for p in pass_table if p["lane"] == g]
            if not pts:
                continue
            k = [p["pass"] for p in pts]
            st = STYLE.get(g, {})
            axes[0].plot(k, [p["c_surf"] for p in pts], marker="o", label=g, **st)
            axes[1].plot(k, [p["dh_mm"] for p in pts], marker="o", label=g, **st)
        axes[0].set_xlabel("pass")
        axes[0].set_ylabel("surface compaction [-]")
        axes[1].set_xlabel("pass")
        axes[1].set_ylabel("settlement [mm]")
        for ax in axes:
            ax.grid(True, alpha=0.3)
            ax.legend()
        fig.tight_layout()
        p = os.path.join(out, "passes.png")
        fig.savefig(p, dpi=150)
        print(f"保存: {p}")

    if along_table:
        fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
        xs = [r["x"] for r in along_table]
        for g in groups:
            st = STYLE.get(g, {})
            axes[0].plot(xs, [r.get(f"{g}_c", math.nan) for r in along_table], marker=".", label=g, **st)
            axes[1].plot(xs, [r.get(f"{g}_dh_mm", math.nan) for r in along_table], marker=".", label=g, **st)
        axes[0].set_ylabel("surface compaction [-]")
        axes[1].set_ylabel("settlement [mm]")
        axes[1].set_xlabel("x [m]")
        for ax in axes:
            ax.grid(True, alpha=0.3)
            ax.legend()
        fig.tight_layout()
        p = os.path.join(out, "along_x.png")
        fig.savefig(p, dpi=150)
        print(f"保存: {p}")


# ---------------------------------------------------------------- 本体
def main():
    ap = argparse.ArgumentParser(description="CompactionProbe の CSV を要約する")
    ap.add_argument("csv")
    ap.add_argument("--x0", type=float, default=0.5)
    ap.add_argument("--x1", type=float, default=7.5)
    ap.add_argument("--cell", type=float, default=0.3125)
    ap.add_argument("--z-offset", type=float, default=0.0,
                    help="地形のローカル座標の高さ 0 のワールドの高さ [m]（Terrain の Transform の y）")
    ap.add_argument("--surface-fill", type=float, default=None,
                    help="地表のボクセルに土が入っている割合を固定する（0〜1）。指定しなければ高さから計算")
    ap.add_argument("--avg-depth", type=float, default=0.5,
                    help="深さ方向の平均を取る範囲 [m]（最初の記録の地表から）")
    ap.add_argument("--dh-scale", type=float, default=1.0,
                    help="沈下量からの推定で、実測の沈下量に掛ける倍率（5b の k を指定すると補正できる）")
    ap.add_argument("--timeline", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()

    rows_all = load(a.csv)
    cols, has_depth = depth_columns(rows_all)
    snaps = snapshots(rows_all)
    t_first = snaps[0][0]

    # 最初の記録の高さ（マスごと）。沈下量の基準
    h0 = {r["_cell"]: r["_h"] for r in rows_all if r["_t"] == t_first}

    rows = in_range(rows_all, a.x0, a.x1)
    groups = sorted_groups({r["_group"] for r in rows})
    passes = detect_passes(snaps)

    print(f"ファイル: {a.csv}")
    print(f"集計の範囲: x = {a.x0}〜{a.x1} m、記録の回数: {len(snaps)}、"
          f"深さ方向: {'あり（' + str(len(cols)) + ' 層）' if has_depth else 'なし（NaN）'}、通過: {len(passes)} 回")
    lanes = sorted({r["lane"] for r in rows})
    print(f"列: {', '.join(lanes)}")

    pass_table = report_passes(rows, snaps, passes, groups, h0, t_first)
    depth_table = report_depth(rows, groups, cols, a.cell, t_first,
                                                 a.z_offset, a.surface_fill) if has_depth else []
    if not has_depth:
        print("\n2. 深さ方向の分布：深さ方向の値がないため省略")
    along_table = report_along_x(rows, groups, h0, a.cell)
    column_table = report_columns(rows, h0, t_first)
    avg_table = (report_column_average(rows, groups, cols, a.cell, t_first, passes, a.z_offset,
                                       a.avg_depth, a.dh_scale, a.surface_fill) if has_depth else [])
    if a.timeline:
        report_timeline(rows, groups, h0, cols, has_depth)

    if a.out:
        os.makedirs(a.out, exist_ok=True)
        print()
        write_csv(os.path.join(a.out, "passes.csv"), pass_table)
        write_csv(os.path.join(a.out, "depth.csv"), depth_table)
        write_csv(os.path.join(a.out, "along_x.csv"), along_table)
        write_csv(os.path.join(a.out, "columns.csv"), column_table)
        write_csv(os.path.join(a.out, "column_average.csv"), avg_table)
        if a.plot:
            plot(a.out, pass_table, along_table, groups)
    elif a.plot:
        print("--plot には --out が必要です")


if __name__ == "__main__":
    main()