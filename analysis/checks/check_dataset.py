"""
段階7（試験的な収集）の点検。学習データとしての使いやすさと、本番の収集の見積もりを出す。

置き場所: src/bull_ope/analysis/checks/check_dataset.py（check_physics.py・check_sensitivity.py と同じ場所）
使い方:
  cd /workspaces/ws-bulldozer/src/bull_ope
  python3 analysis/checks/check_dataset.py <collect_data の出力フォルダ> [...] [--target 本番のエピソード数] [--report 結果.md]

  D1. 結果の内訳      ok / error / skipped の件数。error の理由と、そのときの土質・深さ・速度
  D2. 土質の広がり    ラベル（AGX から読み戻した値）の最小・最大と、範囲を5等分したときの件数（偏りがないか）
  D3. 関門5・6の関係が、土質を同時に変えても成り立つか（dataset_flat_cut の ok のエピソード）
        Fpen   = a + b c                   （関門6：b ≒ 0.65 kN/kPa）
        Fz_sat = a + b ρ + b' c            （関門6：b ≒ 7.1 N/(kg/m³)）
        Fx_sat = a + b ρ tanφ + b' c + b'' v（関門5・6）
  D4. 見積もり        1エピソードの実時間（CSV の保存時刻の間隔）、CSV の大きさ、本番の所要時間と容量
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_sensitivity import features   # noqa: E402

LABELS = [("label_c", "c [Pa]"), ("label_phi", "φ [°]"), ("label_rho0", "ρ [kg/m³]")]


def load_runs(paths):
    rows = []
    for p in paths:
        with open(os.path.join(p, "episodes.jsonl"), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    r["_dir"] = p
                    rows.append(r)
    return rows


def ols(X, y, names):
    """最小二乗。係数、決定係数を返す"""
    X = np.column_stack([np.ones(len(y))] + list(X))
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coef
    r2 = 1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
    return dict(zip(["切片"] + names, coef)), r2


def main():
    ap = argparse.ArgumentParser(description="段階7（試験的な収集）の点検")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--target", type=int, default=1000, help="本番のエピソード数（見積もり用）")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル名")
    a = ap.parse_args()

    lines = ["# 段階7の点検（試験的な収集）", ""]

    def out(s=""):
        print(s)
        lines.append(s)

    rows = load_runs(a.paths)
    st = pd.Series([str(r.get("status", "")).split(":")[0] for r in rows])

    # D1. 結果の内訳
    out("## D1. 結果の内訳")
    out("")
    out(f"- エピソード {len(rows)} 件：" + "、".join(f"{k} {v} 件" for k, v in st.value_counts().items()))
    for r in rows:
        s = str(r.get("status", ""))
        if not s.startswith("ok"):
            p = {k[6:]: v for k, v in r.items() if k.startswith("param_")}
            out(f"  - {r.get('episode_name')}（{r.get('file')}）：{s}｜c {r.get('soil_cohesion', 0):.0f} Pa、"
                f"φ {r.get('soil_friction_angle_deg', 0):.1f}°、ρ {r.get('soil_density', 0):.0f}、操作 {p}")
    out("")

    # 特徴量
    recs, sizes, mtimes = [], [], []
    for r in rows:
        if not str(r.get("status", "")).startswith("ok"):
            continue
        path = os.path.join(r["_dir"], r["file"])
        sizes.append(os.path.getsize(path))
        mtimes.append(os.path.getmtime(path))
        df = pd.read_csv(path)
        f = features(df) or {}
        f.update(name=r["episode_name"], file=r["file"], c=r.get("label_c"), phi=r.get("label_phi"), rho=r.get("label_rho0"),
                 run_time=r.get("run_time"), rows=r.get("rows"))
        recs.append(f)
    t = pd.DataFrame(recs)

    # D2. 土質の広がり
    out("## D2. 土質の広がり（ok のエピソードのラベル）")
    out("")
    out("| ラベル | 最小 | 最大 | 範囲を5等分したときの件数 |")
    out("| --- | --- | --- | --- |")
    for col, label in [("c", "c [Pa]"), ("phi", "φ [°]"), ("rho", "ρ [kg/m³]")]:
        v = t[col].astype(float)
        hist, _ = np.histogram(v, bins=5, range=(v.min(), v.max()))
        out(f"| {label} | {v.min():.1f} | {v.max():.1f} | {' / '.join(str(h) for h in hist)} |")
    out("")

    # D3. 関門5・6の関係
    fc = t[t["name"].isin(["dataset_flat_cut", "flat_cut"])].dropna(subset=["Fpen"])   # flat_cut は名前を変える前のデータ
    out(f"## D3. 関門5・6の関係（dataset_flat_cut の ok のエピソード {len(fc)} 件）")
    out("")
    if len(fc) >= 5:
        c_kpa = fc["c"].astype(float) / 1000
        coef, r2 = ols([c_kpa], fc["Fpen"].to_numpy(), ["c [kPa]"])
        out(f"- Fpen [kN] = {coef['切片']:.2f} + {coef['c [kPa]']:.3f} × c [kPa]（決定係数 {r2:.2f}。関門6：0.93 + 0.65 c）")
        sat = fc.dropna(subset=["Fz_sat", "Fx_sat"])
        if len(sat) >= 5:
            coef, r2 = ols([sat["rho"].astype(float), sat["c"].astype(float) / 1000], sat["Fz_sat"].to_numpy(), ["ρ", "c [kPa]"])
            out(f"- Fz_sat [kN] = {coef['切片']:.2f} + {coef['ρ'] * 1000:.2f} × ρ [N/(kg/m³)] + {coef['c [kPa]']:.3f} × c [kPa]（決定係数 {r2:.2f}）")
            rt = sat["rho"].astype(float) * np.tan(np.radians(sat["phi"].astype(float)))
            coef, r2 = ols([rt / 1000, sat["c"].astype(float) / 1000, sat["speed"].astype(float)], sat["Fx_sat"].to_numpy(),
                           ["ρtanφ [t/m³]", "c [kPa]", "v [m/s]"])
            out(f"- Fx_sat [kN] = {coef['切片']:.2f} + {coef['ρtanφ [t/m³]']:.2f} × ρtanφ [t/m³] + {coef['c [kPa]']:.3f} × c [kPa]"
                f" + {coef['v [m/s]']:.2f} × v [m/s]（決定係数 {r2:.2f}）")
            out(f"- 頭打ちの特徴が取れたエピソード：{len(sat)} / {len(fc)} 件")
        else:
            out("- 頭打ちの特徴（削った体積 2 m³ 以上）が取れたエピソードが少ないため、Fz_sat・Fx_sat の関係は調べない")
    else:
        out("- エピソードが少ないため調べない")
    out("")

    # D4. 見積もり
    out("## D4. 本番の収集の見積もり")
    out("")
    if len(mtimes) >= 3:
        m = np.sort(np.array(mtimes))
        gaps = np.diff(m)
        gaps = gaps[gaps < 600]          # 別々の実行の間の大きな間隔は除く
        per_ep = float(np.median(gaps)) if len(gaps) else float("nan")
        out(f"- 1エピソードの実時間（CSV の保存時刻の間隔の中央値）：{per_ep:.0f} 秒（走行 {t['run_time'].median():.0f} 秒）")
        out(f"- CSV の大きさ：平均 {np.mean(sizes) / 1e6:.2f} MB、行数 平均 {t['rows'].mean():.0f}")
        ok_rate = (st == "ok").mean()
        total_eps = a.target / ok_rate if ok_rate > 0 else float("nan")
        out(f"- ok の割合：{ok_rate * 100:.0f}%")
        out(f"- 本番 {a.target} 件（ok）に必要な実行：約 {total_eps:.0f} 件、所要時間 約 {total_eps * per_ep / 3600:.1f} 時間、"
            f"容量 約 {a.target * np.mean(sizes) / 1e9:.2f} GB")
    out("")

    out("## エピソードごとの特徴量")
    out("")
    out("| ファイル | エピソード | c [Pa] | φ [°] | ρ | 速度 | Fpen | Fx_sat | Fz_sat |")
    out("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for _, r in t.iterrows():
        def g(k, nd=2):
            v = r.get(k)
            return "—" if v is None or pd.isna(v) else f"{v:.{nd}f}"
        out(f"| {r['file']} | {r['name']} | {g('c', 0)} | {g('phi', 1)} | {g('rho', 0)} | {g('speed')} | {g('Fpen')} | {g('Fx_sat')} | {g('Fz_sat')} |")

    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"\nレポートを保存しました: {a.report}")


if __name__ == "__main__":
    main()