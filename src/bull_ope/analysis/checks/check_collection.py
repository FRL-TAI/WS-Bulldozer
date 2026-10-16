"""
collect_data の1回分の実行結果をまとめて点検する ( 関門1 : スクリプトの不具合探し )

使い方:
  python3 check_collection.py <collect_data の出力フォルダ> [--report 結果.md]

確認すること:
  1. 結果 : 各エピソードの結果 ( ok / error / skipped )が想定どおりか
  2. 開始位置 : ok のエピソードが毎回同じ位置・向きから始まっているか（シーンの読み込み直しが効いているか）
  3. ラベル : AGX から読み戻した土質が、要求した土質と一致しているか（前の土質が残っていないか）
  4. 時系列データ : 行数、sim_time の逆戻り、主な列や指令の NaN
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

# エピソードごとの想定の結果（ここにないものは "ok" を想定）
EXPECTED_STATUS = {
    "stress_error_midrun": "error",    # エピソードのコードで例外
    "stress_none_command": "error",    # operation() が None を返す
    "stress_runaway": "error",         # SAFE_RADIUS で停止
}

# NaN があってはいけない列（指令の NaN は、NaN が OperaSim に送られたことを意味する）
KEY_COLUMNS = ["F_total_x", "F_total_z", "edge_z", "depth", "speed", "x", "y", "pitch",
               "lift_joint_effort", "cmd_vx", "cmd_lift"]

START_POS_TOL = 0.02     # 開始位置のばらつきの許容 [m]
START_YAW_TOL = 0.5      # 開始の向きのばらつきの許容 [deg]

LABEL_PAIRS = [("label_c", "soil_cohesion", 1.0), ("label_phi", "soil_friction_angle_deg", 0.01),
               ("label_rho0", "soil_density", 0.5), ("label_swell", "soil_swell_factor", 1e-3),
               ("label_E0", "soil_youngs_modulus", 1.0)]


def status_kind(status):
    return (status or "?").split(":")[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル名")
    a = ap.parse_args()

    out = []   # 画面とレポートの両方に出す行

    def p(line=""):
        print(line)
        out.append(line)

    jsonl = os.path.join(a.run_dir, "episodes.jsonl")
    with open(jsonl) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    p(f"# 実行結果の点検 : {os.path.basename(a.run_dir.rstrip('/'))}")
    p(f"\nエピソード {len(rows)} 件")
    problems = 0

    # ---- 1. 結果 ----
    p("\n## 1. 結果（想定との比較）\n")
    p("| 番号 | エピソード | 結果 | 想定 | 判定 | 詳細 |")
    p("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        kind = status_kind(r.get("status"))
        want = EXPECTED_STATUS.get(r["episode_name"], "ok")
        ok = kind == want
        problems += not ok
        detail = (r.get("status") or "").split(":", 1)[-1].strip()[:80] if kind != "ok" else ""
        p(f"| {r['episode_index']} | {r['episode_name']} | {kind} | {want} | {'OK' if ok else '想定外'} | {detail} |")

    ok_rows = [r for r in rows if status_kind(r.get("status")) == "ok" and "start_x" in r]

    # ---- 2. 開始位置 ----
    p("\n## 2. 開始位置・向き（全エピソードで同じはず）\n")
    if ok_rows:
        xs = np.array([r["start_x"] for r in ok_rows])
        ys = np.array([r["start_y"] for r in ok_rows])
        yaws = np.array([r["start_yaw_deg"] for r in ok_rows])
        dev = np.hypot(xs - xs[0], ys - ys[0])
        good = dev.max() < START_POS_TOL and np.ptp(yaws) < START_YAW_TOL
        problems += not good
        p(f"- 位置のばらつき : 最大 {dev.max() * 100:.2f} cm（許容 {START_POS_TOL * 100:.0f} cm）")
        p(f"- 向きのばらつき : 最大 {np.ptp(yaws):.3f}°（許容 {START_YAW_TOL}°）")
        p(f"- 判定 : {'OK' if good else '要確認（毎回同じ状態から始まっていない）'}")
    else:
        p("- ok のエピソードがないため確認できません")

    # ---- 3. ラベル ----
    p("\n## 3. ラベルと要求した土質の一致\n")
    n_bad = 0
    for r in ok_rows:
        for lab, req, tol in LABEL_PAIRS:
            want = r.get(req)
            if want is None:          # 要求していない（Unity 側の値のまま）
                continue
            got = r.get(lab)
            if got is None or abs(got - want) > tol + 1e-6 * abs(want):
                n_bad += 1
                p(f"- エピソード {r['episode_index']} : {lab} = {got}（要求 {want}）")
    problems += n_bad > 0
    p(f"- 一致しないもの : {n_bad} 件")

    # ---- 4. 時系列データ ----
    p("\n## 4. 時系列データ\n")
    p("| 番号 | エピソード | 行数 | 走行中 | sim_time 開始 | 深さの範囲 [m] | 問題 |")
    p("| --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        path = os.path.join(a.run_dir, r.get("file", ""))
        if not os.path.exists(path):
            p(f"| {r['episode_index']} | {r['episode_name']} | - | - | - | - | CSV なし |")
            continue
        df = pd.read_csv(path)
        issues = []
        if len(df) == 0:
            issues.append("0 行")
            p(f"| {r['episode_index']} | {r['episode_name']} | 0 | 0 | - | - | 0 行 |")
            continue
        dt = np.diff(df["sim_time"].to_numpy())
        if (dt <= 0).any():
            issues.append(f"sim_time の逆戻り・重複 {int((dt <= 0).sum())} 回")
        for c in KEY_COLUMNS:
            if c in df and df[c].isna().any():
                issues.append(f"{c} に NaN {int(df[c].isna().sum())} 行")
        n_run = int((df["phase"] == "running").sum()) if "phase" in df else 0
        depth = f"{df['depth'].min():.3f}〜{df['depth'].max():.3f}" if "depth" in df else "-"
        problems += bool(issues)
        p(f"| {r['episode_index']} | {r['episode_name']} | {len(df)} | {n_run} | "
          f"{df['sim_time'].iloc[0]:.1f} | {depth} | {'、'.join(issues) or 'なし'} |")

    p(f"\n## まとめ\n\n想定外・要確認の項目 : {problems} 件")

    if a.report:
        with open(a.report, "w") as f:
            f.write("\n".join(out) + "\n")
        print(f"\nレポートを保存しました: {a.report}")


if __name__ == "__main__":
    main()
