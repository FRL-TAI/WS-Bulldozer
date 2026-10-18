"""
関門3（単位・座標・符号）の点検。collect_data の出力フォルダ（または test_episode の CSV）を調べる。

置き場所: src/bull_ope/analysis/checks/check_units.py
使い方:
  cd /workspaces/ws-bulldozer/src/bull_ope
  python3 analysis/checks/check_units.py <collect_data の出力フォルダ> [--report 結果.md]
  python3 analysis/checks/check_units.py <CSV> [<CSV> …] [--report 結果.md]

エピソードの種類に応じて、次を確かめる（判定は OK / WARN / NG、「参考」は判定しない）。

  U1. 空中の力          排土板を上げている間（val_static、val_air_run）、力の大きさが 100 N 未満か
  U2. 押土の力の向き    削っている間（val_constant_depth、val_depth_step）、F_total_x が負か。
                        左右の力 F_total_y が前後の力に比べて小さいか（車体の座標になっているか）
  U3. 深さの追従        削っている間、深さが目標深さに追従しているか（平均のずれ 1 cm 未満、95% が 2 cm 以内）
  U4. 刃先と地面        削っている間、刃先の真下の地面の高さ ground_below が刃先の高さ edge_z とほぼ同じか
  U5. 速度と距離        前方向の速度 v_forward の積分と、位置から求めた距離 distance が一致するか（3% 以内）。
                        速度が指令に追従しているか（参考）
  U6. 座標の整合        刃先（edge_*）が車体（x, y）の前方にあるか（同じ座標系か）。直進中に向きがずれないか
  U7. 値の範囲          排土板の幅・角度、ラベルの単位（φ が度、ρ が kg/m³ など）、ground_h0 が妥当な範囲か
  U8. 力の内訳          F_def・F_con の大きさの最大（参考。関門1・2では常に 0）
  U9. 記録の最初の状態  記録の最初の行の深さ・刃先・地面の高さ（参考。最初の深さが約 13 cm になる理由を調べる）

基準の値は暫定。関門3の結果を見て見直す。
"""
import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

PERIOD = 0.020
SETTLE = 1.5               # 走行の開始・目標深さの変化の後、追従の判定から除く時間 [s]
AIR_FORCE_MAX = 100.0      # U1：空中の力の大きさの上限 [N]
FY_RATIO_MAX = 0.20        # U2：|平均 Fy| / |平均 Fx| の上限
DEPTH_BIAS_MAX = 0.010     # U3：平均のずれの上限 [m]
DEPTH_P95_MAX = 0.020      # U3：ずれの絶対値の 95 パーセンタイルの上限 [m]
EDGE_GROUND_MAX = 0.020    # U4：|ground_below − edge_z| の中央値の上限 [m]
DIST_REL_MAX = 0.03        # U5：速度の積分と距離のずれの上限（割合）
YAW_DRIFT_MAX = 2.0        # U6：直進中の向きの変化の上限 [deg]
EDGE_LATERAL_MAX = 0.20    # U6：刃先の中点の、車体の中心線からの横のずれの上限 [m]

AIR = ("val_static", "val_air_run")
CUT = ("val_constant_depth", "val_depth_step")
STRAIGHT = ("val_air_run", "val_constant_depth", "val_depth_step")


def settled_mask(run):
    """走行の開始と目標深さの変化から SETTLE 秒以内の行を除く"""
    t = run["t"].to_numpy()
    tgt = run["target_depth"].to_numpy() if "target_depth" in run else np.zeros(len(run))
    last_change = np.empty(len(run))
    lc = t[0] if len(t) else 0.0
    for i in range(len(run)):
        if i > 0 and abs(tgt[i] - tgt[i - 1]) > 1e-9:
            lc = t[i]
        last_change[i] = lc
    return t - last_change >= SETTLE


def fmt(x, unit="", nd=1):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}{unit}"


def check_episode(name, df):
    res = []   # (項目, 判定, 詳細)
    run = df[df["phase"] == "running"].reset_index(drop=True)
    if len(run) < 10:
        return [("走行中の行", "WARN", f"{len(run)} 行のため点検しない")]
    ok_rows = run[settled_mask(run)]
    is_air, is_cut = name in AIR, name in CUT

    # U1. 空中の力
    if is_air:
        f = np.sqrt(run["F_total_x"] ** 2 + run["F_total_y"] ** 2 + run["F_total_z"] ** 2)
        res.append(("U1 空中の力", "OK" if f.max() < AIR_FORCE_MAX else "NG",
                    f"|F_total| の最大 {f.max():.1f} N（上限 {AIR_FORCE_MAX:.0f} N）"))

    # U2. 押土の力の向き
    if is_cut and len(ok_rows) > 10:
        fx, fy, fz = (ok_rows[c].mean() for c in ("F_total_x", "F_total_y", "F_total_z"))
        ratio = abs(fy) / abs(fx) if abs(fx) > 1e-9 else float("inf")
        judge = "OK" if fx < 0 and ratio <= FY_RATIO_MAX else "NG" if fx >= 0 else "WARN"
        res.append(("U2 押土の力の向き", judge,
                    f"平均 F_total = ({fx / 1000:.2f}, {fy / 1000:.2f}, {fz / 1000:.2f}) kN、"
                    f"|Fy|/|Fx| = {ratio:.2f}（上限 {FY_RATIO_MAX}）"))
        eff = ok_rows["left_track_effort"] + ok_rows["right_track_effort"] if "left_track_effort" in ok_rows else None
        if eff is not None and eff.std() > 0 and ok_rows["F_total_x"].std() > 0:
            r = np.corrcoef(ok_rows["F_total_x"], eff)[0, 1]
            res.append(("U2 履帯の駆動力との相関", "参考",
                        f"F_total_x と左右の履帯の力の和の相関係数 r = {r:.2f}（押す力が大きいほど駆動力も大きいはず）"))

    # U3. 深さの追従
    if is_cut and len(ok_rows) > 10 and "target_depth" in ok_rows:
        err = (ok_rows["depth"] - ok_rows["target_depth"]).to_numpy()
        bias, p95 = float(np.mean(err)), float(np.percentile(np.abs(err), 95))
        judge = "OK" if abs(bias) < DEPTH_BIAS_MAX and p95 < DEPTH_P95_MAX else "WARN"
        res.append(("U3 深さの追従", judge,
                    f"ずれ（深さ − 目標）平均 {bias * 100:+.2f} cm、絶対値の 95% {p95 * 100:.2f} cm、"
                    f"最大 {np.max(np.abs(err)) * 100:.2f} cm（{len(ok_rows)} 行）"))

        # U4. 刃先と地面（削った後の地面は刃先の後ろで測る。刃先の真下は土の山の表面になるため参考）
    if is_cut and len(ok_rows) > 10:
        if "ground_behind" in ok_rows:
            gap = (ok_rows["ground_behind"] - ok_rows["edge_z"]).to_numpy()
            med = float(np.median(gap))
            res.append(("U4 刃先と削った後の地面", "OK" if abs(med) < EDGE_GROUND_MAX else "WARN",
                        f"ground_behind − edge_z 中央値 {med * 100:+.2f} cm、範囲 {gap.min() * 100:+.1f}〜{gap.max() * 100:+.1f} cm"))
        if "ground_below" in ok_rows:
            gap = (ok_rows["ground_below"] - ok_rows["edge_z"]).to_numpy()
            res.append(("U4 刃先の真下の地面", "参考",
                        f"ground_below − edge_z 中央値 {np.median(gap) * 100:+.2f} cm（土の山の表面を含む）"))

    # U5. 速度と距離
    if name in STRAIGHT:
        dt = np.diff(run["sim_time"].to_numpy(), prepend=run["sim_time"].iloc[0])
        integ = float(np.sum(run["v_forward"].to_numpy() * dt))
        dist = float(run["distance"].iloc[-1] - run["distance"].iloc[0])
        rel = abs(integ - dist) / dist if dist > 0.1 else float("nan")
        res.append(("U5 速度と距離", "OK" if rel <= DIST_REL_MAX else "WARN",
                    f"v_forward の積分 {integ:.3f} m / 位置から求めた距離 {dist:.3f} m（ずれ {fmt(rel * 100, ' %')}）"))
        if len(ok_rows) > 10:
            v, cmd = ok_rows["v_forward"].mean(), ok_rows["cmd_vx"].mean()
            res.append(("U5 速度の追従", "参考",
                        f"平均 v_forward {v:.3f} m/s / 指令 {cmd:.3f} m/s（比 {v / cmd if cmd else float('nan'):.3f}）"))

    # U6. 座標の整合
    yaw = run["yaw"].to_numpy()
    if all(c in run for c in ("edge_x", "edge_y", "x", "y")):
        dx, dy = run["edge_x"] - run["x"], run["edge_y"] - run["y"]
        fwd = (dx * np.cos(yaw) + dy * np.sin(yaw)).to_numpy()
        lat = (-dx * np.sin(yaw) + dy * np.cos(yaw)).to_numpy()
        judge = "OK" if np.median(fwd) > 0 and abs(np.median(lat)) < EDGE_LATERAL_MAX else "NG"
        res.append(("U6 刃先の位置", judge,
                    f"刃先の中点は車体の位置から 前方 {np.median(fwd):.2f} m・左方 {np.median(lat):+.2f} m（中央値）"))
    if name in STRAIGHT:
        drift = float(np.degrees(np.angle(np.exp(1j * (yaw[-1] - yaw[0])))))
        res.append(("U6 直進中の向き", "OK" if abs(drift) <= YAW_DRIFT_MAX else "WARN",
                    f"走行中の向きの変化 {drift:+.2f}°、横の速度 v_lateral の平均 {run['v_lateral'].mean():+.3f} m/s"))

    # U7. 値の範囲
    msgs, ok = [], True
    checks = [("blade_width", 2.0, 4.0, "m", 2), ("blade_alpha_deg", 30.0, 120.0, "°", 1),
              ("label_phi", 1.0, 89.0, "°", 2), ("label_rho0", 800.0, 2500.0, " kg/m³", 0),
              ("label_E0", 1e5, 1e9, " Pa", 0), ("ground_h0", -0.05, 0.05, " m", 4)]
    for col, lo, hi, unit, nd in checks:
        if col not in df:
            continue
        v = float(df[col].median())
        inside = lo <= v <= hi
        ok &= inside
        msgs.append(f"{col} {v:.{nd}f}{unit}" + ("" if inside else f"（範囲外：{lo}〜{hi}）"))
    res.append(("U7 値の範囲", "OK" if ok else "WARN", "、".join(msgs)))

    # U8. 力の内訳
    parts = []
    for p in ("pen", "sep", "def", "con"):
        cols = [f"F_{p}_{a}" for a in "xyz"]
        if all(c in run for c in cols):
            parts.append(f"F_{p} {np.sqrt((run[cols] ** 2).sum(axis=1)).max() / 1000:.2f} kN")
    res.append(("U8 力の内訳（最大）", "参考", "、".join(parts)))

    # U9. 記録の最初の状態
    first = df.iloc[0]
    items = [f"phase {first['phase']}", f"depth {first['depth'] * 100:.1f} cm", f"edge_z {first['edge_z']:.3f} m"]
    for col in ("ground_below", "ground_ahead", "ground_h0", "pitch"):
        if col in df:
            val = np.degrees(first[col]) if col == "pitch" else first[col]
            items.append(f"{col} {val:.3f}" + ("°" if col == "pitch" else " m"))
    res.append(("U9 記録の最初の状態", "参考", "、".join(items)))
    return res


def list_targets(paths):
    """フォルダなら episodes.jsonl の ok のエピソード、ファイルならそのまま"""
    out = []
    for p in paths:
        if os.path.isdir(p):
            with open(os.path.join(p, "episodes.jsonl"), encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line) if line.strip() else None
                    if r and str(r.get("status")) == "ok":
                        out.append(os.path.join(p, r["file"]))
        else:
            out += sorted(glob.glob(p))
    return out


def main():
    ap = argparse.ArgumentParser(description="関門3（単位・座標・符号）の点検")
    ap.add_argument("paths", nargs="+", help="collect_data の出力フォルダ、または CSV")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル名")
    a = ap.parse_args()

    lines = ["# 関門3の点検（単位・座標・符号）", ""]
    total = {"OK": 0, "WARN": 0, "NG": 0, "参考": 0}

    def out(line=""):
        print(line)
        lines.append(line)

    for path in list_targets(a.paths):
        df = pd.read_csv(path)
        if "sim_time" not in df:
            continue
        name = str(df["episode_name"].iloc[0])
        out(f"## {os.path.basename(path)}（{name}）")
        out("")
        out("| 項目 | 判定 | 詳細 |")
        out("| --- | --- | --- |")
        for item, judge, detail in check_episode(name, df):
            out(f"| {item} | {judge} | {detail} |")
            total[judge] += 1
        out("")

    out(f"合計: OK {total['OK']} / WARN {total['WARN']} / NG {total['NG']}（参考 {total['参考']}）")
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"\nレポートを保存しました: {a.report}")


if __name__ == "__main__":
    main()