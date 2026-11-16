"""
関門4（時間のずれ）の点検。トピックの間の時刻のずれと、指令から応答までの遅れを測る。

置き場所: src/bull_ope/analysis/checks/check_timing.py
使い方:
  cd /workspaces/ws-bulldozer/src/bull_ope
  python3 analysis/checks/check_timing.py <collect_data の出力フォルダ、または CSV> [...] [--report 結果.md]

記録は blade_state の到着ごと（シミュレーション時刻で 20 ms ごと）に1行で、他のトピックはその時点の最新値。
blade_state の値（力・刃先・地面）は同じステップの値なので、ずれはない。ここでは次を測る。

  T1. global_pose の遅れ        sim_time − pose_stamp（位置が何 ms 前の値か）
  T2. 届く間隔                  global_pose・joint_states の値が変わる間隔（実際の更新の周期）
  T3. 速度の指令 → 車体の速度    cmd_vx が変わってから、v_forward が変化量の 10%・63%・90% に達するまでの時間
  T4. 排土板の指令 → 刃先の動き  cmd_lift と、刃先の上下の速度（edge_z の微分）の相互相関が最大になる遅れ
  T5. トピックの間の遅れ        同じ物理量を別のトピックで見たときの、相互相関が最大になる遅れ
        F_total_z（blade_state）→ lift_joint_effort（joint_states）
        v_forward（global_pose から計算）→ 履帯の回転速度（joint_states）

遅れは「後ろのものが前のものより何 ms 遅れているか」（正なら後ろが遅れている）。
判定はせず、値を並べる（関門4は、ずれを把握して前処理と時間窓を決めるための関門）。
"""
import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

DT = 0.020
MAX_LAG = 0.5        # 相互相関で探す遅れの範囲 [s]
HP_WINDOW = 1.0      # 相互相関の前に引く移動平均の幅 [s]（ゆっくりした変化を除く）


def list_targets(paths):
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


def highpass(x):
    s = pd.Series(np.asarray(x, float))
    return (s - s.rolling(int(HP_WINDOW / DT), center=True, min_periods=1).mean()).to_numpy()


def xcorr_lag(a, b):
    """b が a より何秒遅れているか（相互相関が最大の遅れ）と、そのときの相関係数"""
    a, b = highpass(a), highpass(b)
    if np.std(a) == 0 or np.std(b) == 0 or len(a) < 50:
        return float("nan"), float("nan")
    a = (a - a.mean()) / a.std()
    b = (b - b.mean()) / b.std()
    n = int(MAX_LAG / DT)
    best = (0, -np.inf, 0.0)
    for k in range(-n, n + 1):
        if k >= 0:
            c = np.mean(a[: len(a) - k] * b[k:])
        else:
            c = np.mean(a[-k:] * b[: len(b) + k])
        if abs(c) > best[1]:
            best = (k, abs(c), c)
    return best[0] * DT, best[2]


def update_intervals(series, t):
    """値が変わった時刻の間隔 [s]"""
    v = series.to_numpy()
    idx = np.where(v[1:] != v[:-1])[0] + 1
    return np.diff(t[idx]) if len(idx) > 1 else np.array([])


def step_responses(df):
    """cmd_vx が変わった時点ごとの、v_forward の応答の時間 [s]（10%、63%、90%）"""
    out = []
    cmd = df["cmd_vx"].to_numpy()
    v = df["v_forward"].to_numpy()
    t = df["sim_time"].to_numpy()
    for i in np.where(np.abs(np.diff(cmd)) > 0.1)[0] + 1:
        dc = cmd[i] - cmd[i - 1]
        v0 = v[i - 1]
        res = {"t": t[i] - t[0], "from": cmd[i - 1], "to": cmd[i]}
        for frac in (0.1, 0.63, 0.9):
            j = next((k for k in range(i, min(i + int(3.0 / DT), len(v)))
                      if (v[k] - v0) / dc >= frac), None)
            res[frac] = (t[j] - t[i]) if j is not None else float("nan")
        out.append(res)
    return out


def check_episode(df):
    lines, vals = [], {}
    t = df["sim_time"].to_numpy()
    run = df[df["phase"] == "running"]

    # T1. global_pose の遅れ
    lag = (df["sim_time"] - df["pose_stamp"]).to_numpy()
    vals["pose_lag_med"], vals["pose_lag_max"] = np.median(lag), lag.max()
    lines.append(f"T1 global_pose の遅れ：中央値 {np.median(lag) * 1000:.0f} ms、95% {np.percentile(lag, 95) * 1000:.0f} ms、最大 {lag.max() * 1000:.0f} ms")

    # T2. 届く間隔（動いているとき）
    mv = run[run["cmd_vx"].abs() > 1e-6] if len(run) else run
    if len(mv) > 50:
        ip = update_intervals(mv["pose_stamp"], mv["sim_time"].to_numpy())
        ij = update_intervals(mv["right_track_pos"], mv["sim_time"].to_numpy())
        if len(ip) and len(ij):
            vals["pose_int"], vals["joint_int"] = np.median(ip), np.median(ij)
            lines.append(f"T2 届く間隔：global_pose 中央値 {np.median(ip) * 1000:.0f} ms（最大 {ip.max() * 1000:.0f} ms）、"
                         f"joint_states 中央値 {np.median(ij) * 1000:.0f} ms（最大 {ij.max() * 1000:.0f} ms）")

    # T3. 速度の指令 → 車体の速度
    for r in step_responses(df):
        lines.append(f"T3 速度の指令 {r['from']:+.2f} → {r['to']:+.2f} m/s（t = {r['t']:.1f} s）："
                     f"10% {r[0.1] * 1000:.0f} ms、63% {r[0.63] * 1000:.0f} ms、90% {r[0.9] * 1000:.0f} ms")
        vals.setdefault("v10", []).append(r[0.1])
        vals.setdefault("v63", []).append(r[0.63])

    # T4. 排土板の指令 → 刃先の動き（指令が動いている区間全体）
    edge_v = np.gradient(df["edge_z"].to_numpy(), t)
    lag4, c4 = xcorr_lag(df["cmd_lift"].to_numpy(), edge_v)
    if not np.isnan(lag4):
        vals["lift_lag"] = lag4
        lines.append(f"T4 cmd_lift → 刃先の上下の速度：遅れ {lag4 * 1000:+.0f} ms（相関 {c4:+.2f}。LIFT_SIGN が負なので相関は負になるはず）")

    # T5. トピックの間の遅れ（走行中）
    if len(run) > 100:
        lag5, c5 = xcorr_lag(run["F_total_z"], run["lift_joint_effort"])
        if not np.isnan(lag5):
            vals["fz_effort_lag"] = lag5
            lines.append(f"T5 F_total_z → lift_joint_effort：遅れ {lag5 * 1000:+.0f} ms（相関 {c5:+.2f}）")
        trk = (run["right_track_vel"] + run["left_track_vel"]) / 2
        lag6, c6 = xcorr_lag(run["v_forward"], trk)
        if not np.isnan(lag6):
            vals["v_track_lag"] = lag6
            lines.append(f"T5 v_forward → 履帯の回転速度：遅れ {lag6 * 1000:+.0f} ms（相関 {c6:+.2f}）")
    return lines, vals


def fmt_ms(xs):
    xs = np.array([x for x in xs if not np.isnan(x)], float)
    if len(xs) == 0:
        return "—"
    return f"{np.median(xs) * 1000:+.0f} ms（{xs.min() * 1000:+.0f}〜{xs.max() * 1000:+.0f}、{len(xs)} 件）"


def main():
    ap = argparse.ArgumentParser(description="関門4（時間のずれ）の点検")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル名")
    a = ap.parse_args()

    out_lines = ["# 関門4の点検（時間のずれ）", ""]
    agg = {}

    def out(line=""):
        print(line)
        out_lines.append(line)

    for path in list_targets(a.paths):
        df = pd.read_csv(path)
        if "sim_time" not in df:
            continue
        name = str(df["episode_name"].iloc[0])
        lines, vals = check_episode(df)
        out(f"## {os.path.basename(path)}（{name}）")
        out("")
        for line in lines:
            out(f"- {line}")
        out("")
        for k, v in vals.items():
            agg.setdefault(k, []).extend(v if isinstance(v, list) else [v])

    out("## まとめ（中央値、範囲、件数）")
    out("")
    out("| 項目 | 値 |")
    out("| --- | --- |")
    labels = [("pose_lag_med", "T1 global_pose の遅れ（各エピソードの中央値）"),
              ("pose_lag_max", "T1 global_pose の遅れ（各エピソードの最大）"),
              ("pose_int", "T2 global_pose の届く間隔"), ("joint_int", "T2 joint_states の届く間隔"),
              ("v10", "T3 速度の指令 → 車体の速度 10%"), ("v63", "T3 速度の指令 → 車体の速度 63%"),
              ("lift_lag", "T4 cmd_lift → 刃先の上下の速度"),
              ("fz_effort_lag", "T5 F_total_z → lift_joint_effort"),
              ("v_track_lag", "T5 v_forward → 履帯の回転速度")]
    for key, label in labels:
        out(f"| {label} | {fmt_ms(agg.get(key, []))} |")
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines) + "\n")
        print(f"\nレポートを保存しました: {a.report}")


if __name__ == "__main__":
    main()