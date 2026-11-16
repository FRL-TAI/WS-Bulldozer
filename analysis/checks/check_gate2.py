"""
関門2（記録の健全さ）のための追加の点検。collect_data の1回分の出力フォルダをまとめて調べる。

置き場所: src/bull_ope/analysis/checks/check_gate2.py
使い方:
  cd /workspaces/ws-bulldozer/src/bull_ope
  python3 analysis/checks/check_gate2.py <collect_data の出力フォルダ> [--report 結果.md]

check_recording.py（1ファイルごとの周期・欠損など）と check_collection.py（結果・開始位置・ラベル）で
見ていない、次の点を確かめる。対象は status が ok のエピソード。

  G1. 列の構成        すべての CSV で列の名前と順番が同じか
  G2. 行数の一致      episodes.jsonl の rows と CSV の行数が一致するか
  G3. メタ情報の一致  CSV の episode_name・seed・ラベル・ground_h0 が一定で、episodes.jsonl と一致するか
  G4. 時刻の整合      t が 0 から始まり、t = sim_time − 最初の sim_time になっているか
  G5. トピックの更新  走行中に global_pose と joint_states の値が止まらずに更新されているか（同じ値の連続、遅れ）。
                      実際の更新の頻度は参考値として表示する
  G6. 区間の長さ      下げる区間が LOWER_TIMEOUT 以内か、上げる区間が RAISE_TIME 分あるか
  G7. 繰り返しの差    同じエピソードを繰り返したとき、走行の行数・距離のばらつきが小さいか
                      （平均の 5% か、10 行・0.1 m の大きいほうまで許す）

判定は OK / WARN（要確認）/ NG（不合格）。
"""
import argparse
import collections
import json
import os

import numpy as np
import pandas as pd

PERIOD = 0.020             # 記録の周期 [s]
LOWER_TIMEOUT = 5.0        # config.LOWER_TIMEOUT [s]
RAISE_TIME = 3.0           # config.RAISE_TIME [s]
POSE_STALE_WARN = 0.10     # sim_time − pose_stamp の最大がこれを超えたら WARN [s]
STREAK_WARN = 5            # 同じ値が続いた行数の最大がこれ以上なら WARN（5 行 = 0.1 s）
STREAK_NG = 25             # 同じ値が続いた行数の最大がこれ以上なら NG（25 行 = 0.5 s。トピックが止まった）
# OperaSim の global_pose・joint_states は blade_state（毎ステップ）より少ない回数しか届かないため、
# 「何割の行で更新されたか」は判定に使わず、参考値（実際の更新の頻度）として表示する
REPEAT_TOL = 0.05          # 繰り返しのばらつきの許容（平均に対する割合）
REPEAT_ROWS_MIN = 10       # 行数のばらつきの許容の下限 [行]（短いエピソードで、制御周期の分のずれを許す）
REPEAT_DIST_MIN = 0.10     # 距離のばらつきの許容の下限 [m]

LABELS = ["label_c", "label_phi", "label_rho0", "label_swell", "label_E0"]


def load_rows(run_dir):
    rows = []
    with open(os.path.join(run_dir, "episodes.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def longest_streak(series):
    """同じ値が続いた行数の最大"""
    v = series.to_numpy()
    best = cur = 1
    for a, b in zip(v[:-1], v[1:]):
        cur = cur + 1 if a == b else 1
        best = max(best, cur)
    return best if len(v) else 0


def frac_changed(series):
    """前の行から値が変わった行の割合（最初の行は除く）"""
    v = series.to_numpy()
    if len(v) < 2:
        return float("nan")
    return float(np.mean(v[1:] != v[:-1]))


def check_episode(row, df, ref_cols):
    res = []   # (項目, 判定, 詳細)

    # G1. 列の構成
    cols = list(df.columns)
    if cols == ref_cols:
        res.append(("G1 列の構成", "OK", f"{len(cols)} 列（基準と同じ）"))
    else:
        missing = [c for c in ref_cols if c not in cols]
        extra = [c for c in cols if c not in ref_cols]
        detail = f"{len(cols)} 列。足りない: {missing or 'なし'} / 余分: {extra or 'なし'}"
        if not missing and not extra:
            detail += "（順番が違う）"
        res.append(("G1 列の構成", "NG", detail))

    # G2. 行数の一致
    want = row.get("rows")
    res.append(("G2 行数の一致", "OK" if want == len(df) else "NG",
                f"episodes.jsonl {want} 行 / CSV {len(df)} 行"))

    # G3. メタ情報の一致
    msgs, ok = [], True
    for col, key in [("episode_name", "episode_name"), ("seed", "seed"), ("episode_index", "episode_index")]:
        vals = df[col].dropna().unique() if col in df else []
        if len(vals) != 1 or str(vals[0]) != str(row.get(key)):
            msgs.append(f"{col}: CSV {list(vals)[:3]} / jsonl {row.get(key)}")
            ok = False
    for col in LABELS + ["ground_h0"]:
        if col not in df or row.get(col) is None:
            continue
        vals = df[col].dropna().unique()
        if len(vals) != 1 or abs(float(vals[0]) - float(row[col])) > 1e-6 * max(1.0, abs(float(row[col]))):
            msgs.append(f"{col}: CSV {vals[:3]} / jsonl {row[col]}")
            ok = False
    res.append(("G3 メタ情報の一致", "OK" if ok else "NG", "; ".join(msgs) or "すべて一致"))

    # G4. 時刻の整合
    t = df["t"].to_numpy()
    st = df["sim_time"].to_numpy()
    err = float(np.max(np.abs(t - (st - st[0])))) if len(t) else float("nan")
    ok = len(t) > 0 and abs(t[0]) < 1e-9 and err < 1e-6
    res.append(("G4 時刻の整合", "OK" if ok else "NG", f"t の最初 {t[0]:.6f} s、t と sim_time の差の最大 {err:.2e} s"))

    # G5. トピックの更新（走行中）
    run = df[df["phase"] == "running"]
    if len(run) < 10:
        res.append(("G5 トピックの更新", "WARN", f"走行中の行が {len(run)} 行のため判定しない"))
    else:
        details, judge = [], "OK"
        # global_pose：止まらずに更新されているか、どのくらい古いか
        if "pose_stamp" in run:
            upd = frac_changed(run["pose_stamp"])
            streak = longest_streak(run["pose_stamp"])
            stale = (run["sim_time"] - run["pose_stamp"]).to_numpy()
            details.append(f"global_pose 約 {upd / PERIOD:.0f} Hz（{upd * 100:.0f}% の行で更新）、同じ値の連続 最大 {streak} 行、"
                           f"遅れ 中央値 {np.median(stale) * 1000:.0f} ms・最大 {stale.max() * 1000:.0f} ms")
            if streak >= STREAK_NG:
                judge = "NG"
            elif streak >= STREAK_WARN or stale.max() > POSE_STALE_WARN:
                judge = "WARN"
        # joint_states：動いている間に履帯の位置が止まらずに更新されているか
        moving = run[run["cmd_vx"].abs() > 1e-6] if "cmd_vx" in run else run.iloc[0:0]
        if len(moving) >= 10 and "right_track_pos" in moving:
            upd_j = min(frac_changed(moving["right_track_pos"]), frac_changed(moving["left_track_pos"]))
            streak_j = max(longest_streak(moving["right_track_pos"]), longest_streak(moving["left_track_pos"]))
            details.append(f"joint_states 約 {upd_j / PERIOD:.0f} Hz（{upd_j * 100:.0f}% の行で更新）、同じ値の連続 最大 {streak_j} 行")
            if streak_j >= STREAK_NG:
                judge = "NG"
            elif streak_j >= STREAK_WARN and judge == "OK":
                judge = "WARN"
        else:
            details.append("joint_states は静止中のため判定しない")
        res.append(("G5 トピックの更新", judge, "、".join(details)))

    # G6. 区間の長さ
    n = df["phase"].value_counts()
    n_low, n_raise = int(n.get("lowering", 0)), int(n.get("raising", 0))
    low_ok = n_low <= LOWER_TIMEOUT / PERIOD + 5
    raise_ok = abs(n_raise - RAISE_TIME / PERIOD) <= 10
    res.append(("G6 区間の長さ", "OK" if low_ok and raise_ok else "WARN",
                f"下げる区間 {n_low} 行（上限 {LOWER_TIMEOUT / PERIOD:.0f}）、上げる区間 {n_raise} 行（目安 {RAISE_TIME / PERIOD:.0f}）"))

    return res


def check_repeats(oks, dfs):
    """G7. 同じエピソードの繰り返しのばらつき"""
    groups = collections.defaultdict(list)
    for r in oks:
        df = dfs[r["episode_index"]]
        groups[r["episode_name"]].append((int((df["phase"] == "running").sum()), float(r.get("run_distance") or 0.0)))
    res = []
    for name, vals in sorted(groups.items()):
        if len(vals) < 2:
            res.append((name, "WARN", f"{len(vals)} 回のため判定しない"))
            continue
        rows = np.array([v[0] for v in vals], float)
        dist = np.array([v[1] for v in vals], float)
        r_spread = (rows.max() - rows.min()) / max(rows.mean(), 1.0)
        d_spread = (dist.max() - dist.min()) / dist.mean() if dist.mean() > 0.1 else 0.0
        rows_ok = rows.max() - rows.min() <= max(REPEAT_TOL * rows.mean(), REPEAT_ROWS_MIN)
        dist_ok = dist.max() - dist.min() <= max(REPEAT_TOL * dist.mean(), REPEAT_DIST_MIN)
        judge = "OK" if rows_ok and dist_ok else "WARN"
        res.append((name, judge,
                    f"{len(vals)} 回。走行の行数 {int(rows.min())}〜{int(rows.max())}（差 {r_spread * 100:.1f}%）、"
                    f"距離 {dist.min():.2f}〜{dist.max():.2f} m（差 {d_spread * 100:.1f}%）"))
    return res


def main():
    ap = argparse.ArgumentParser(description="関門2（記録の健全さ）の追加の点検")
    ap.add_argument("run_dir")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル名")
    a = ap.parse_args()

    rows = load_rows(a.run_dir)
    oks = [r for r in rows if str(r.get("status")) == "ok"]
    lines = [f"# 関門2の点検 : {os.path.basename(os.path.normpath(a.run_dir))}", "",
             f"エピソード {len(rows)} 件（ok {len(oks)} 件。ok 以外は対象外）", ""]
    total = {"OK": 0, "WARN": 0, "NG": 0}

    def out(line=""):
        print(line)
        lines.append(line)

    dfs, ref_cols = {}, None
    for r in oks:
        df = pd.read_csv(os.path.join(a.run_dir, r["file"]))
        dfs[r["episode_index"]] = df
        if ref_cols is None:
            ref_cols = list(df.columns)

    out("## エピソードごと")
    out("")
    for r in oks:
        res = check_episode(r, dfs[r["episode_index"]], ref_cols)
        out(f"### {r['episode_index']}: {r['episode_name']}（{r['file']}）")
        out("")
        out("| 項目 | 判定 | 詳細 |")
        out("| --- | --- | --- |")
        for item, judge, detail in res:
            out(f"| {item} | {judge} | {detail} |")
            total[judge] += 1
        out("")

    out("## G7 繰り返しの差")
    out("")
    out("| エピソード | 判定 | 詳細 |")
    out("| --- | --- | --- |")
    for name, judge, detail in check_repeats(oks, dfs):
        out(f"| {name} | {judge} | {detail} |")
        total[judge] += 1
    out("")

    out(f"合計: OK {total['OK']} / WARN {total['WARN']} / NG {total['NG']}")
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"\nレポートを保存しました: {a.report}")


if __name__ == "__main__":
    main()