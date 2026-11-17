"""
実験B（締固めと切削抵抗）の解析。

test_episode が記録した CSV（<DATA_DIR>/test/<日時>_ex_compaction_bands.csv など）を読み、
刃先の位置で帯（締固めの程度が同じ区間）に分けて、帯ごとの切削抵抗を比べる。

使い方：
  python3 check_cut_bands.py <CSV> [<CSV> ...] [オプション]
  例）python3 analysis/phase0/check_cut_bands.py data/test/*_ex_compaction_bands.csv \\
          --out data/compaction/cut_bands --plot
  例）python3 analysis/phase0/check_cut_bands.py data/test/*_ex_compaction_then_cut.csv \
          --out data/compaction/then_cut --plot

  bull_ope をビルドして source install/setup.bash した端末で実行する（エピソードのクラスから帯の範囲を得るため）。

帯の決め方：
  1. エピソードのクラスに bands() があれば、記録のエピソード名とシードからクラスを作り直して帯の範囲を得る
     （ex_compaction_bands、ex_compaction_patterns、ex_compaction_levels。帯の範囲はエピソード座標：
       開始時の刃先の中点が原点、x が前方。bands() の4番目の要素があれば帯の名前として使い、名前ごとに集計する）
  2. ex_compaction_then_cut は、同じ刃先の位置どうしで「踏み固めあり（偶数のシード）」と「対照（奇数のシード）」の
     記録を比べる（5 の表）。両方の記録を一緒に指定する
  3. どちらでもなければ、記録の state_compaction_mean（刃先の前 0〜1 m の締固めの程度）から
     「踏み固めた区間」と「地山の区間」を判定する。--from-state で 3 を強制できる

切削抵抗は「排土板が土から受ける力」の前後成分の符号を反転した値（押土中に正）：
  R_sep = −F_sep_x（分離抵抗、押土中に支配的）、R_pen = −F_pen_x（貫入抵抗）、R_total = −F_total_x

出力：
  1. 帯ごとの表       帯の内側（両端から --trim [m] を除く）の平均。比抵抗 = R_sep ÷（排土板の幅 × 深さ）[kPa]
  2. 隣の地山との比較 締固めた帯の値 − 両隣の地山の帯の値の平均（土塊の成長による増え方の影響を打ち消すため）
  3. 回帰             R_sep = b0 + b1·深さ + b2·V + b3·V² + Σ g_k·[帯の種類 k]（V は削った体積の積算）
                      g_k が「地山と比べた、その締固めの程度による切削抵抗の差」[N]
  4. 複数の記録のまとめ（2 の差・比の平均と標準偏差）
  5. 踏み固めありと対照の比較（ex_compaction_then_cut。刃先の位置 --bin [m] ごとの差と比、区間ごとの平均）

注意：
  - 深さは開始時の地面を基準にした値（CSV の depth）。締固めの設定や踏み固めで地面が下がっていると、
    その帯では実際にはその分浅く削っている。地面の高さは CompactionProbe の記録で確かめる
  - 時系列の値は互いに独立ではないので、3 の標準誤差は小さめに出る。判断には 2 と 4 を主に使う
"""
import argparse
import csv
import math
import os
from collections import defaultdict

import numpy as np

BANK_TOL = 1e-6


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return math.nan


# ---------------------------------------------------------------- 読み込み
def load(path):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"データがありません: {path}")
    keys = ["edge_x", "edge_y", "edge_z", "yaw", "depth", "target_depth", "cmd_vx", "v_forward",
            "F_sep_x", "F_pen_x", "F_total_x", "F_total_z", "state_compaction_mean", "cut_volume",
            "blade_width", "distance", "t", "x", "y"]
    for r in rows:
        for k in keys:
            r["_" + k] = to_float(r.get(k))
    return rows


def cut_rows(rows):
    """削っている行：走行中・目標深さが正・前進の指令・実際に前進している"""
    out = [r for r in rows if r.get("phase") == "running" and r["_target_depth"] > 0
           and r["_cmd_vx"] > 0.05 and r["_v_forward"] > 0.05]
    return out


def add_station(rows, cut):
    """刃先の位置を、開始時の刃先の位置と向きを基準にした前方の距離 s [m] にする。
    あわせて、機体の位置を開始時の機体の位置からの前方の距離 s_pose [m] にする"""
    r0 = rows[0]
    ux, uy = math.cos(r0["_yaw"]), math.sin(r0["_yaw"])
    for r in cut:
        r["_s"] = (r["_edge_x"] - r0["_edge_x"]) * ux + (r["_edge_y"] - r0["_edge_y"]) * uy
        # 機体の位置（開始時の機体の位置からの前方の距離）。踏み固めありと対照を比べるときに使う
        r["_s_pose"] = (r["_x"] - r0["_x"]) * ux + (r["_y"] - r0["_y"]) * uy
        r["_R_sep"] = -r["_F_sep_x"]
        r["_R_pen"] = -r["_F_pen_x"]
        r["_R_total"] = -r["_F_total_x"]


# ---------------------------------------------------------------- 帯
_IMPORT_WARNED = False


def get_episode(rows):
    """記録のエピソード名とシードからエピソードを作り直す。できなければ None"""
    global _IMPORT_WARNED
    name, seed = rows[0].get("episode_name"), rows[0].get("seed")
    try:
        from bull_ope.episodes import available_episodes
    except ImportError:
        if not _IMPORT_WARNED:
            print("  bull_ope を読み込めません（source install/setup.bash した端末で実行してください）")
            _IMPORT_WARNED = True
        return None
    cls = available_episodes().get(name)
    if cls is None:
        return None
    return cls(seed=int(float(seed)))


def bands_from_episode(ep):
    """エピソードの bands() から [(開始, 終わり, 締固めの程度)] を得る。得られなければ None"""
    if ep is None or not hasattr(ep, "bands"):
        return None
    out = []
    for band in ep.bands():
        a, b, v = (float(x) for x in band[:3])
        out.append((a, b, v, band[3] if len(band) > 3 else level_name(v)))
    return out


def auto_threshold(values, threshold=None):
    """踏み固めた区間とみなすしきい値。指定がなければ、1.0 と上位 10% の値の中間にする
    （刃先の前 0〜1 m の平均なので、境目では値がなだらかに変わる。中間で切ると境目の位置がずれにくい）"""
    if threshold is not None:
        return threshold
    v = np.array([x for x in values if math.isfinite(x)])
    if len(v) == 0:
        return math.inf
    top = float(np.percentile(v, 90))
    return 1.0 + 0.5 * (top - 1.0) if top - 1.0 > 0.005 else math.inf


def bands_from_state(cut, threshold=None, min_length=0.5):
    """state_compaction_mean（刃先の前 0〜1 m の平均）から区間を判定する。
    刃先が s にあるときの値は s + 0.5 の位置の締固めの程度とみなし、s ごとに補間して区間に分ける"""
    pts = sorted((r["_s"] + 0.5, r["_state_compaction_mean"]) for r in cut
                 if math.isfinite(r["_state_compaction_mean"]))
    if len(pts) < 2:
        return []
    xs, cs = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    s_all = np.array(sorted(r["_s"] for r in cut))
    c_at = np.interp(s_all, xs, cs)
    threshold = auto_threshold(cs, threshold)
    flags = c_at > threshold
    bands, start = [], 0
    for i in range(1, len(s_all) + 1):
        if i == len(s_all) or flags[i] != flags[start]:
            a, b = s_all[start], s_all[i - 1]
            if b - a >= min_length:
                level = float(np.mean(c_at[start:i])) if flags[start] else 1.0
                bands.append((float(a), float(b), level))
            start = i
    return bands


def level_name(v):
    if abs(v - 1.0) < BANK_TOL:
        return "地山 1.000"
    if v < 1.0:
        return f"緩み {v:.3f}"
    return f"締固め {v:.3f}"


def is_bank(v):
    return abs(v - 1.0) < BANK_TOL


# ---------------------------------------------------------------- 集計
def band_stats(cut, bands, trim):
    stats = []
    for i, (a, b, v, lab) in enumerate(bands):
        inner = [r for r in cut if a + trim <= r["_s"] <= b - trim]
        # 締固めの程度の確認用：刃先の前 0.5 m の位置が帯の内側にある行
        check = [r["_state_compaction_mean"] for r in cut if a + trim <= r["_s"] + 0.5 <= b - trim]
        if not inner:
            stats.append({"band": i, "s0": a, "s1": b, "level": v, "label": lab, "n": 0})
            continue

        def m(key):
            return float(np.nanmean([r[key] for r in inner]))
        depth, width = m("_depth"), m("_blade_width")
        R = m("_R_sep")
        stats.append({
            "band": i, "s0": a, "s1": b, "level": v, "label": lab, "n": len(inner),
            "state_c": float(np.nanmean(check)) if check else math.nan,
            "depth_m": depth, "R_sep_N": R, "R_pen_N": m("_R_pen"), "R_total_N": m("_R_total"),
            "F_z_N": m("_F_total_z"), "cut_volume_m3": m("_cut_volume"),
            "specific_kPa": R / (width * depth) / 1000.0 if depth > 0 else math.nan,
        })
    return stats


def paired_effects(stats):
    """締固めた（緩めた）帯について、両隣の地山の帯との差と比"""
    out = []
    for i, s in enumerate(stats):
        if is_bank(s["level"]) or s.get("n", 0) == 0:
            continue
        nb = [stats[j] for j in (i - 1, i + 1)
              if 0 <= j < len(stats) and is_bank(stats[j]["level"]) and stats[j].get("n", 0) > 0]
        if not nb:
            continue
        e = {"band": s["band"], "level": s["level"], "label": s["label"], "n_neighbors": len(nb)}
        for key in ("R_sep_N", "R_pen_N", "specific_kPa", "depth_m"):
            ref = float(np.mean([x[key] for x in nb]))
            e[f"{key}_band"] = s[key]
            e[f"{key}_ref"] = ref
            e[f"{key}_diff"] = s[key] - ref
            e[f"{key}_ratio"] = s[key] / ref if abs(ref) > 1e-9 else math.nan
        out.append(e)
    return out


def regression(cut, bands, trim):
    """R_sep = b0 + b1·深さ + b2·V + b3·V² + Σ g_k·[帯の種類 k]"""
    levels = sorted({lab for _, _, v, lab in bands if not is_bank(v)})
    X, y = [], []
    for r in cut:
        for a, b, v, lab in bands:
            if a + trim <= r["_s"] <= b - trim:
                d, V = r["_depth"], r["_cut_volume"]
                if not all(math.isfinite(z) for z in (d, V, r["_R_sep"])):
                    break
                X.append([1.0, d, V, V * V] + [1.0 if lab == L else 0.0 for L in levels])
                y.append(r["_R_sep"])
                break
    if len(y) < len(levels) + 6:
        return []
    X, y = np.array(X), np.array(y)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(1, len(y) - X.shape[1])
    sigma2 = float(resid @ resid) / dof
    se = np.sqrt(np.abs(np.diag(sigma2 * np.linalg.pinv(X.T @ X))))
    names = ["切片", "深さ", "V", "V^2"] + list(levels)
    r2 = 1.0 - float(resid @ resid) / float(((y - y.mean()) ** 2).sum())
    return [{"term": n, "coef": float(b), "se": float(s), "n": len(y), "r2": r2}
            for n, b, s in zip(names, beta, se)]


def compare_runs(entries, bin_width, threshold=None):
    """踏み固めありと対照の記録を、同じ刃先の位置（bin_width ごと）どうしで比べる（ex_compaction_then_cut）。
    entries: [(ファイル名, 削った行, 踏み固めありか)]"""
    def binned(cut):
        # 機体の位置で区切る（どちらの記録も同じ位置から始まり、削っている間は刃先と機体の位置関係も同じ）
        d = defaultdict(list)
        for r in cut:
            d[math.floor(r["_s_pose"] / bin_width)].append(r)
        out = {}
        for k, rs in d.items():
            out[k] = {key: float(np.nanmean([r[key] for r in rs]))
                      for key in ("_R_sep", "_R_pen", "_depth", "_state_compaction_mean", "_cut_volume")}
        return out

    per_variant = {True: [], False: []}
    for _, cut, comp in entries:
        per_variant[comp].append(binned(cut))
    if not per_variant[True] or not per_variant[False]:
        return []

    def avg(variant, k, key):
        v = [b[k][key] for b in per_variant[variant] if k in b]
        return float(np.mean(v)) if v else math.nan

    keys = sorted(set().union(*[b.keys() for b in per_variant[True]]) & set().union(*[b.keys() for b in per_variant[False]]))
    # 締固めの程度は刃先の前 0〜1 m の平均なので、位置を 0.5 m 前にずらして見る
    state_by_bin = {k: avg(True, k, "_state_compaction_mean") for k in keys}
    thr = auto_threshold(state_by_bin.values(), threshold)

    print("\n" + "=" * 78)
    print(f"5. 踏み固めありと対照の比較（刃先の位置 {bin_width} m ごと。"
          f"踏み固めあり {len(per_variant[True])} 本、対照 {len(per_variant[False])} 本の平均）")
    print("=" * 78)
    print("   state_c は踏み固めありの記録の、刃先の前 0〜1 m の締固めの程度。区間 = 踏み固め（state_c > "
          f"{thr:.4f}）か地山か")
    print("   s は機体の位置（開始位置からの前方の距離）。刃先はその前方の一定の距離にある")
    print(f"{'s [m]':>11s} {'state_c':>8s} {'区間':>6s} {'深さcm あり/対照':>17s} {'R_sep kN あり/対照':>19s} "
          f"{'差 kN':>7s} {'比':>6s} {'R_pen差kN':>9s} {'V m3 あり/対照':>15s}")
    table = []
    for k in keys:
        st = state_by_bin[k]
        region = "踏固め" if st > thr else "地山"
        Rc, Rn = avg(True, k, "_R_sep"), avg(False, k, "_R_sep")
        Pc, Pn = avg(True, k, "_R_pen"), avg(False, k, "_R_pen")
        dc, dn = avg(True, k, "_depth"), avg(False, k, "_depth")
        Vc, Vn = avg(True, k, "_cut_volume"), avg(False, k, "_cut_volume")
        print(f"{k * bin_width:5.2f}-{(k + 1) * bin_width:5.2f} {st:8.4f} {region:>6s} {dc * 100:8.2f}/{dn * 100:6.2f} "
              f"{Rc / 1000:9.2f}/{Rn / 1000:7.2f} {(Rc - Rn) / 1000:+7.2f} {Rc / Rn if Rn else math.nan:6.3f} "
              f"{(Pc - Pn) / 1000:+9.2f} {Vc:7.2f}/{Vn:5.2f}")
        table.append({"s0": k * bin_width, "s1": (k + 1) * bin_width, "state_c": st, "region": region,
                      "depth_comp": dc, "depth_ctrl": dn, "R_sep_comp": Rc, "R_sep_ctrl": Rn,
                      "R_sep_diff": Rc - Rn, "R_pen_diff": Pc - Pn, "V_comp": Vc, "V_ctrl": Vn})

    print("\n   区間ごとの平均（差 = 踏み固めあり − 対照）")
    for region in ("踏固め", "地山"):
        rs = [t for t in table if t["region"] == region]
        if not rs:
            continue
        d = np.array([t["R_sep_diff"] for t in rs]) / 1000
        ratio = np.array([t["R_sep_comp"] / t["R_sep_ctrl"] for t in rs if t["R_sep_ctrl"]])
        print(f"   {region}：{len(rs)} 区間、R_sep の差 {d.mean():+.2f} kN（標準偏差 {d.std():.2f}）、比 {ratio.mean():.3f}")
    return table


def plot_compare(out, table):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    x = [0.5 * (t["s0"] + t["s1"]) for t in table]
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    axes[0].plot(x, [t["R_sep_comp"] / 1000 for t in table], marker=".", label="compacted")
    axes[0].plot(x, [t["R_sep_ctrl"] / 1000 for t in table], marker=".", label="control")
    axes[0].set_ylabel("R_sep [kN]")
    axes[0].legend()
    axes[1].plot(x, [t["R_sep_diff"] / 1000 for t in table], marker=".", color="tab:red")
    axes[1].axhline(0, color="k", lw=0.5)
    axes[1].set_ylabel("difference [kN]")
    axes[2].plot(x, [t["state_c"] for t in table], marker=".", color="tab:purple")
    axes[2].set_ylabel("compaction ahead [-]")
    axes[2].set_xlabel("machine position s [m]")
    for ax in axes:
        for t in table:
            if t["region"] == "踏固め":
                ax.axvspan(t["s0"], t["s1"], color="tab:orange", alpha=0.12, lw=0)
        ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p = os.path.join(out, "compare.png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    print(f"保存: {p}")


# ---------------------------------------------------------------- 表示
def print_file_report(path, rows, cut, bands, source, stats, effects, reg, trim):
    print("\n" + "#" * 78)
    print(f"# {os.path.basename(path)}")
    print(f"# エピソード: {rows[0].get('episode_name')}  seed={rows[0].get('seed')}  "
          f"削った行: {len(cut)}  帯の決め方: {source}  両端の除外: {trim} m")
    print("#" * 78)

    print("\n1. 帯ごとの表（帯の内側の平均。state_c は記録の締固めの程度で、設定値との確認用）")
    print(f"{'帯':>3s} {'範囲 [m]':>13s} {'種類':>18s} {'行数':>5s} {'state_c':>8s} {'深さcm':>7s} "
          f"{'R_sep kN':>9s} {'R_pen kN':>9s} {'R_tot kN':>9s} {'比抵抗kPa':>10s} {'V m3':>6s}")
    for s in stats:
        if s.get("n", 0) == 0:
            print(f"{s['band']:3d} {s['s0']:6.2f}-{s['s1']:5.2f} {s['label']:>18s} {0:5d}  （刃先が通っていない）")
            continue
        print(f"{s['band']:3d} {s['s0']:6.2f}-{s['s1']:5.2f} {s['label']:>18s} {s['n']:5d} "
              f"{s['state_c']:8.4f} {s['depth_m'] * 100:7.2f} {s['R_sep_N'] / 1000:9.2f} {s['R_pen_N'] / 1000:9.2f} "
              f"{s['R_total_N'] / 1000:9.2f} {s['specific_kPa']:10.2f} {s['cut_volume_m3']:6.2f}")

    print("\n2. 両隣の地山の帯との比較（帯の値 − 両隣の地山の平均、比 = 帯の値 ÷ 両隣の地山の平均）")
    if not effects:
        print("   比べられる帯がありません")
    for e in effects:
        print(f"   帯 {e['band']}（{e['label']}、地山 {e['n_neighbors']} 帯と比較）："
              f"R_sep {e['R_sep_N_diff'] / 1000:+.2f} kN（比 {e['R_sep_N_ratio']:.3f}）、"
              f"R_pen {e['R_pen_N_diff'] / 1000:+.2f} kN（比 {e['R_pen_N_ratio']:.3f}）、"
              f"比抵抗 {e['specific_kPa_diff']:+.2f} kPa（比 {e['specific_kPa_ratio']:.3f}）、"
              f"深さ {e['depth_m_diff'] * 100:+.2f} cm")

    print("\n3. 回帰 R_sep = b0 + b1·深さ + b2·V + b3·V² + Σ g·[帯の種類]（帯の種類の係数が地山との差 [N]）")
    if not reg:
        print("   データが少ないため省略")
    else:
        print(f"   行数 {reg[0]['n']}、決定係数 {reg[0]['r2']:.3f}（標準誤差は時系列の相関のため小さめに出る）")
        for t in reg:
            print(f"   {t['term']:>14s}: {t['coef']:12.1f} ± {t['se']:10.1f}")


def print_summary(all_effects):
    if len({e["file"] for e in all_effects}) < 2:
        return
    print("\n" + "=" * 78)
    print("4. 複数の記録のまとめ（2 の差と比。種類ごとの平均 ± 標準偏差、記録の数）")
    print("=" * 78)
    groups = defaultdict(list)
    for e in all_effects:
        groups[e["label"]].append(e)
    print(f"{'種類':>18s} {'数':>3s} {'R_sep 差 kN':>16s} {'R_sep 比':>15s} {'R_pen 比':>15s} {'比抵抗 比':>15s}")
    for lv in sorted(groups, key=lambda k: (groups[k][0]["level"], k)):
        es = groups[lv]

        def ms(key, scale=1.0):
            v = np.array([e[key] for e in es]) * scale
            return f"{v.mean():7.3f} ± {v.std(ddof=1) if len(v) > 1 else 0.0:5.3f}"
        print(f"{lv:>18s} {len(es):3d} {ms('R_sep_N_diff', 1e-3):>16s} {ms('R_sep_N_ratio'):>15s} "
              f"{ms('R_pen_N_ratio'):>15s} {ms('specific_kPa_ratio'):>15s}")


# ---------------------------------------------------------------- 保存・図
def write_csv(path, table):
    if not table:
        return
    keys = []
    for row in table:
        keys += [k for k in row if k not in keys]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(table)
    print(f"保存: {path}")


def plot_file(out, path, cut, bands):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib がないため、図は作りません（pip install matplotlib）")
        return
    s = np.array([r["_s"] for r in cut])
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    axes[0].plot(s, [r["_R_sep"] / 1000 for r in cut], lw=0.8, label="R_sep")
    axes[0].plot(s, [r["_R_pen"] / 1000 for r in cut], lw=0.8, label="R_pen")
    axes[0].set_ylabel("resistance [kN]")
    axes[1].plot(s, [r["_depth"] * 100 for r in cut], lw=0.8, color="tab:gray")
    axes[1].set_ylabel("depth [cm]")
    axes[2].plot(s + 0.5, [r["_state_compaction_mean"] for r in cut], lw=0.8, color="tab:purple")
    axes[2].set_ylabel("compaction ahead [-]")
    axes[2].set_xlabel("blade edge position s [m]")
    for ax in axes:
        for a, b, v, _ in bands:
            if not is_bank(v):
                ax.axvspan(a, b, color="tab:orange" if v > 1 else "tab:blue", alpha=0.15)
        ax.grid(True, alpha=0.3)
    axes[0].legend()
    fig.suptitle(os.path.basename(path))
    fig.tight_layout()
    p = os.path.join(out, os.path.splitext(os.path.basename(path))[0] + ".png")
    fig.savefig(p, dpi=150)
    plt.close(fig)
    print(f"保存: {p}")


# ---------------------------------------------------------------- 本体
def main():
    ap = argparse.ArgumentParser(description="実験B：帯ごとの切削抵抗を比べる")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--trim", type=float, default=0.5, help="帯の両端から除く長さ [m]")
    ap.add_argument("--from-state", action="store_true", help="帯を state_compaction_mean から判定する")
    ap.add_argument("--state-threshold", type=float, default=None,
                    help="踏み固めた区間とみなす締固めの程度（既定は 1.0 と上位 10%% の値の中間）")
    ap.add_argument("--bin", type=float, default=0.5, help="踏み固めありと対照を比べるときの区切りの長さ [m]")
    ap.add_argument("--out")
    ap.add_argument("--plot", action="store_true")
    a = ap.parse_args()
    if a.out:
        os.makedirs(a.out, exist_ok=True)

    all_stats, all_effects, all_reg, compare_entries = [], [], [], []
    for path in a.csv:
        rows = load(path)
        cut = cut_rows(rows)
        if not cut:
            print(f"\n{path}: 削っている行がありません（phase・target_depth・前進を確認）")
            continue
        add_station(rows, cut)
        ep = get_episode(rows)

        # 踏み固めありと対照の比較に回す記録（ex_compaction_then_cut）
        if not a.from_state and ep is not None and "compacted" in ep.params:
            compare_entries.append((os.path.basename(path), cut, bool(ep.params["compacted"])))
            print(f"{os.path.basename(path)}: {ep.name} seed={ep.seed}"
                  f"（{'踏み固めあり' if ep.params['compacted'] else '対照'}）、削った行 {len(cut)}")
            continue

        bands = None if a.from_state else bands_from_episode(ep)
        source = "エピソードの bands()"
        if bands is None:
            bands = [(x0, x1, v, level_name(v)) for x0, x1, v in bands_from_state(cut, a.state_threshold)]
            source = "state_compaction_mean"
        if not bands:
            print(f"\n{path}: 帯を決められませんでした")
            continue
        stats = band_stats(cut, bands, a.trim)
        effects = paired_effects(stats)
        reg = regression(cut, bands, a.trim)
        print_file_report(path, rows, cut, bands, source, stats, effects, reg, a.trim)

        name = os.path.basename(path)
        all_stats += [dict(file=name, **s) for s in stats]
        all_effects += [dict(file=name, **e) for e in effects]
        all_reg += [dict(file=name, **t) for t in reg]
        if a.out and a.plot:
            plot_file(a.out, path, cut, bands)

    print_summary(all_effects)

    compare_table = []
    if compare_entries:
        variants = {c for _, _, c in compare_entries}
        if variants == {True, False}:
            compare_table = compare_runs(compare_entries, a.bin, a.state_threshold)
            if a.out and a.plot and compare_table:
                plot_compare(a.out, compare_table)
        else:
            print("\n踏み固めありと対照の両方の記録が必要です（シードを偶数と奇数の両方で実行してください）")

    if a.out:
        print()
        write_csv(os.path.join(a.out, "bands.csv"), all_stats)
        write_csv(os.path.join(a.out, "effects.csv"), all_effects)
        write_csv(os.path.join(a.out, "regression.csv"), all_reg)
        write_csv(os.path.join(a.out, "compare.csv"), compare_table)
    elif a.plot:
        print("--plot には --out が必要です")


if __name__ == "__main__":
    main()