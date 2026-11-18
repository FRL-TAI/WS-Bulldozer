"""
粒子を含む高さ場から求める山の体積（pile_volume_vis・pile_volume_vis_wide）を、V_pile・cut_volume・膨張率 s と比べる（T24）。

置き場所: analysis/phase1/check_pile_volume_vis.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/phase1/check_pile_volume_vis.py data/phase1/pile_volume_vis/run_<日時>_t24 [--report 結果.md]

記録の列（BladeStatePublisher.cs の PileVolume。notes decisions/2026-11-18_地形の経路の観測は粒子を含む高さ場から求める体積にする.md）:
  pile_volume_vis      : V_pile と同じ範囲（排土板の上端〜刃先の前 2.0 m・±1.48 m）の Σ max(粒子を含む高さ − h0, 0)·A [m3]
  pile_volume_vis_wide : 同じ計算を刃先の後ろ 1 m〜前 3 m・±2 m で [m3]
  pile_volume          : V_pile（粒子の分は 質量 ÷ (ρ/s)。s はラベルの値）

エピソード名 ex_ident_<作業>_<点>（作業 flat_cut・pile_push、点 base・s_m0p06・s_p0p06）。s は label_swell。

出すもの:
  1. エピソードごと：深さのずれの 95% 点、区切りの平均の比 vis ÷ V_pile・vis_wide ÷ V_pile、vis、vis ÷ cut_volume、NaN の行
  2. 作業 × s ごと：上の量の平均と、エピソードを選び直すブートストラップの標準誤差
  3. s に対する傾き（エピソードごとの値を s に直線で当てはめる）と標準誤差（最小二乗の式とブートストラップ）、傾き ÷ 標準誤差
  4. 区切りごとの vis ÷ V_pile（作業 × s の平均。走行距離に沿った変化）

区切りは 0.625 m（check_physics.BIN）、走り出し・目標の変化から 1.5 秒を除いた走行中の行（settled_cut_rows）。
作業ごとに、すべてのエピソードにあり、V_pile の区切りの平均が MIN_PILE 以上の区切りだけを使う（エピソードどうしで同じ区切りを比べる）。
vis ÷ cut_volume は、さらに cut_volume が MIN_CUT 以上の区切りだけで求める（pile_push の cut_volume は積んだ山を含まない）。
"""
import argparse
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "validation"))
from check_physics import BIN, list_targets, settled_cut_rows  # noqa: E402

MIN_PILE = 0.1      # [m3]
MIN_CUT = 0.2       # [m3]
NBOOT = 2000
NAME_RE = re.compile(r"ex_ident_(flat_cut|pile_push)_(base|s_m0p06|s_p0p06)")


def episode(path):
    df = pd.read_csv(path)
    m = NAME_RE.search(str(df["episode_name"].iloc[0]))
    if not m:
        return None
    rows = settled_cut_rows(df)
    if rows is None:
        return None
    dev95 = float(np.percentile(np.abs(rows["depth"] - rows["target_depth"]), 95))
    k = np.floor(rows["distance"] / BIN).astype(int)
    b = rows.assign(k=k).groupby("k")[["pile_volume", "pile_volume_vis", "pile_volume_vis_wide", "cut_volume"]].mean()
    nan_rows = int(df[["pile_volume_vis", "pile_volume_vis_wide"]].isna().any(axis=1).sum())
    return dict(task=m.group(1), point=m.group(2), s=float(df["label_swell"].iloc[0]), file=os.path.basename(path),
                dev95=dev95, bins=b, nan=nan_rows, rows=len(df))


def metrics(e, bins):
    b = e["bins"].loc[bins]
    out = {"vis÷V_pile": float((b["pile_volume_vis"] / b["pile_volume"]).mean()),
           "vis_wide÷V_pile": float((b["pile_volume_vis_wide"] / b["pile_volume"]).mean()),
           "vis [m³]": float(b["pile_volume_vis"].mean()),
           "vis_wide [m³]": float(b["pile_volume_vis_wide"].mean()),
           "V_pile [m³]": float(b["pile_volume"].mean())}
    bc = b[b["cut_volume"] >= MIN_CUT]
    out["vis÷cut_volume"] = float((bc["pile_volume_vis"] / bc["cut_volume"]).mean()) if len(bc) else np.nan
    out["vis_wide÷cut_volume"] = float((bc["pile_volume_vis_wide"] / bc["cut_volume"]).mean()) if len(bc) else np.nan
    return out


def slope(x, y):
    """最小二乗の傾きと、その標準誤差（残差から）"""
    x, y = np.asarray(x, float), np.asarray(y, float)
    X = np.column_stack([np.ones_like(x), x])
    beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ beta
    dof = len(x) - 2
    s2 = float(r @ r) / dof if dof > 0 else np.nan
    se = np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    return float(beta[1]), float(se)


def main():
    ap = argparse.ArgumentParser(description="粒子を含む高さ場から求める山の体積の確認（T24）")
    ap.add_argument("paths", nargs="+", help="collect_data の出力フォルダ、または CSV")
    ap.add_argument("--report")
    a = ap.parse_args()
    eps = [e for e in (episode(p) for p in list_targets(a.paths)) if e is not None]
    rng = np.random.default_rng(0)
    out = []
    p = out.append
    p("# 粒子を含む高さ場から求める山の体積（T24）\n")
    p(f"区切り {BIN} m、settled_cut_rows の行。作業ごとに、すべてのエピソードにあり V_pile ≥ {MIN_PILE} m³ の区切りを使う。"
      f"÷ cut_volume は cut_volume ≥ {MIN_CUT} m³ の区切りだけ。標準誤差はエピソードを選び直すブートストラップ（{NBOOT} 回）。\n")
    keys = ["vis÷V_pile", "vis_wide÷V_pile", "vis [m³]", "vis_wide [m³]", "V_pile [m³]", "vis÷cut_volume", "vis_wide÷cut_volume"]
    for task in ("flat_cut", "pile_push"):
        te = [e for e in eps if e["task"] == task]
        if not te:
            continue
        common = set.intersection(*(set(e["bins"].index[e["bins"]["pile_volume"] >= MIN_PILE]) for e in te))
        bins = sorted(common)
        for e in te:
            e["m"] = metrics(e, bins)
        p(f"## {task}（区切り {bins[0]}〜{bins[-1]}、{len(bins)} 個）\n")
        p("### 1. エピソードごと\n")
        p("| 記録 | s | 深さのずれ 95% [cm] | NaN の行 | " + " | ".join(keys) + " |")
        p("|---|---|---|---|" + "---|" * len(keys))
        for e in sorted(te, key=lambda e: (e["s"], e["file"])):
            p(f"| {e['file']} | {e['s']:.2f} | {e['dev95'] * 100:.2f} | {e['nan']}/{e['rows']} | " + " | ".join(f"{e['m'][k]:.3f}" for k in keys) + " |")
        p("\n### 2. s ごとの平均 ± 標準誤差\n")
        p("| s | 本数 | 深さのずれ 95% [cm]（最大） | " + " | ".join(keys) + " |")
        p("|---|---|---|" + "---|" * len(keys))
        levels = sorted({e["s"] for e in te})
        for s in levels:
            g = [e for e in te if e["s"] == s]
            cells = []
            for k in keys:
                v = np.array([e["m"][k] for e in g])
                bs = [rng.choice(v, len(v)).mean() for _ in range(NBOOT)]
                cells.append(f"{v.mean():.3f} ± {np.std(bs, ddof=1):.3f}")
            p(f"| {s:.2f} | {len(g)} | {max(e['dev95'] for e in g) * 100:.2f} | " + " | ".join(cells) + " |")
        p("\n### 3. s に対する傾き（エピソードごとの値を直線で当てはめる）\n")
        p("傾きは s が 1 増えたときの変化。標準誤差は最小二乗の式（残差から）と、s の点ごとにエピソードを選び直すブートストラップ。"
          "相対の傾き = 傾き ÷ 基準（s = 1.28）の平均（s に比例すれば 1/1.28 = 0.78）。\n")
        p("| 量 | 傾き | 標準誤差（式） | 標準誤差（ブートストラップ） | 傾き ÷ 標準誤差（大きいほうの標準誤差） | 2 倍を超えるか | 相対の傾き [1/s] |")
        p("|---|---|---|---|---|---|---|")
        x = np.array([e["s"] for e in te])
        for k in keys:
            y = np.array([e["m"][k] for e in te])
            sl, se = slope(x, y)
            bsl = []
            for _ in range(NBOOT):
                idx = np.concatenate([rng.choice(np.flatnonzero(x == s), (x == s).sum()) for s in levels])
                bsl.append(slope(x[idx], y[idx])[0])
            seb = float(np.std(bsl, ddof=1))
            sem = max(se, seb)
            base = y[np.isclose(x, 1.28)].mean()
            p(f"| {k} | {sl:+.4f} | {se:.4f} | {seb:.4f} | {sl / sem:+.2f} | {'はい' if abs(sl) > 2 * sem else 'いいえ'} | {sl / base:+.3f} |")
        p("\n### 4. 区切りごとの vis ÷ V_pile（s ごとの平均）\n")
        p("| 区切り | " + " | ".join(f"s = {s:.2f}" for s in levels) + " |")
        p("|---|" + "---|" * len(levels))
        for kb in bins:
            cells = []
            for s in levels:
                g = [e for e in te if e["s"] == s]
                cells.append(f"{np.mean([e['bins'].loc[kb, 'pile_volume_vis'] / e['bins'].loc[kb, 'pile_volume'] for e in g]):.3f}")
            p(f"| {kb} | " + " | ".join(cells) + " |")
        p("")
    text = "\n".join(out)
    print(text)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
