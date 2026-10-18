"""
1つのエピソードの CSV が、きちんと記録されているかを確認する。

使い方:
  python3 check_recording.py <CSV> [<CSV> …]
  python3 check_recording.py data/validation/stress/<実行日時>/A/*.csv --report 結果.md

各 CSV について次を確認し、OK / WARN ( 要確認 ) / NG ( 不合格 ) で表示する。
  1. 記録の周期        2. 時刻の単調性・重複   3. 欠損 ( NaN ) 
  4. 一定の列          5. ラベル              6. 進行状況の順番     7. 走行時間

エラーで途中終了したエピソードの CSV も点検できる ( 途中で切れていないか、NaN がないかの確認 ) 
"""
import argparse
import os

import numpy as np
import pandas as pd

# ---- 判定の基準 ----
PERIOD_TARGET = 0.020        # 記録の周期の目標 [s] ( 50 Hz ) 
PERIOD_TOL = 0.002           # 平均周期の許容誤差 [s]
GAP_LIMIT = 0.050            # これより長い間隔を「取りこぼし」とみなす [s]

# 今は NaN で正常な列 ( API を有効にするまで取得しない、または設定値がないと計算しない ) 
EXPECTED_NAN = {"front_soil_mass", "excavated_volume_step",
                "state_compaction_mean", "state_compaction_std", "slip_ratio"}

# エピソード中に一定で正常な列
EXPECTED_CONST_PREFIX = ("label_",)
EXPECTED_CONST = {"episode_index", "episode_name", "seed", "phase", "leg", "ground_h0",
                  "blade_width", "state_compaction_n", "target_depth", "depth_clipped"}

# 走行時間の目安 [s] ( ここにないエピソードは判定しない ) 
EXPECTED_RUN_TIME = {
    "val_static": 10.0, "val_air_run": 20.0, "val_constant_depth": 20.0, "val_depth_step": 18.0,
    "stress_short": 2.0, "stress_spin": 15.0, "stress_nan_depth": 2.0,
}

PHASE_ORDER = ["lowering", "running", "raising"]


def check_file(path, soil):
    df = pd.read_csv(path)
    res = []   # (項目, 判定, 詳細)
    name = str(df["episode_name"].iloc[0]) if "episode_name" in df and len(df) else "?"

    if len(df) == 0:
        return name, df, [("行数", "NG", "データが 0 行")]

    # 1. 記録の周期
    t = df["sim_time"].to_numpy()
    dt = np.diff(t)
    if len(dt) == 0:
        res.append(("記録の周期", "NG", "行が1行だけ"))
    else:
        gaps = int(np.sum(dt > GAP_LIMIT))
        ok = abs(dt.mean() - PERIOD_TARGET) <= PERIOD_TOL and gaps == 0
        res.append(("記録の周期", "OK" if ok else "WARN",
                    f"平均 {dt.mean() * 1000:.1f} ms, 最大 {dt.max() * 1000:.1f} ms, "
                    f"{GAP_LIMIT * 1000:.0f} ms 超の間隔 {gaps} 回"))

    # 2. 時刻の単調性・重複
    n_back = int(np.sum(dt < 0)) if len(dt) else 0
    n_dup = int(np.sum(dt == 0)) if len(dt) else 0
    res.append(("時刻の単調性・重複", "OK" if n_back == 0 and n_dup == 0 else "NG",
                f"逆戻り {n_back} 回, 重複 {n_dup} 回"))

    # 3. 欠損 ( 数値の列のみ ) 
    num = df.select_dtypes(include=[np.number])
    nan_cols = {c: int(num[c].isna().sum()) for c in num.columns if num[c].isna().any()}
    unexpected = {c: n for c, n in nan_cols.items() if c not in EXPECTED_NAN}
    expected = sorted(c for c in nan_cols if c in EXPECTED_NAN)
    detail = "想定外の NaN: " + (", ".join(f"{c}({n}行)" for c, n in unexpected.items()) or "なし")
    detail += " / 想定どおりの NaN: " + (", ".join(expected) or "なし")
    res.append(("欠損", "OK" if not unexpected else "NG", detail))

    # 4. 一定の列 ( 走行中のみで判定。走行中の行がなければ判定しない ) 
    run = df[df["phase"] == "running"] if "phase" in df else df
    if len(run) < 2:
        res.append(("一定の列 ( 走行中 ) ", "WARN", f"走行中の行が {len(run)} 行のため判定しない"))
    else:
        const = [c for c in run.columns
                 if run[c].nunique(dropna=False) <= 1
                 and c not in EXPECTED_CONST and not c.startswith(EXPECTED_CONST_PREFIX)
                 and c not in EXPECTED_NAN]
        res.append(("一定の列 ( 走行中 ) ", "OK" if not const else "WARN",
                    "想定外に一定: " + (", ".join(const) or "なし")))

    if soil is None:
        res.append(("ラベル", "OK", "確認しない（--no-label）"))
    else:
        # 5. ラベル
        msgs, ok = [], True
        for col, want, tol in [("label_c", soil["c"], 1.0), ("label_phi", soil["phi"], 0.01),
                            ("label_rho0", soil["rho"], 0.5)]:
            if col not in df:
                msgs.append(f"{col} なし")
                ok = False
                continue
            vals = df[col].dropna().unique()
            if len(vals) != 1:
                msgs.append(f"{col} が一定でない ( {len(vals)} 種類 ) ")
                ok = False
            elif want is not None and abs(vals[0] - want) > tol:
                msgs.append(f"{col}={vals[0]:g} ( 指定 {want:g} ) ")
                ok = False
            else:
                msgs.append(f"{col}={vals[0]:g}")
        res.append(("ラベル", "OK" if ok else "NG", ", ".join(msgs)))

    # 6. 進行状況の順番
    if "phase" in df:
        phases = df["phase"].tolist()
        seq = [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]]
        counts = df["phase"].value_counts().to_dict()
        judge = "OK" if seq == PHASE_ORDER else "WARN"     # エラーで途中終了した場合は raising がない
        res.append(("進行状況の順番", judge,
                    " → ".join(seq) + " ( " + ", ".join(f"{p} {counts.get(p, 0)}行" for p in PHASE_ORDER) + " ) "))
    else:
        res.append(("進行状況の順番", "NG", "phase 列がない"))

    # 7. 走行時間
    run_time = len(run) * PERIOD_TARGET
    exp = EXPECTED_RUN_TIME.get(name)
    if exp is None:
        res.append(("走行時間", "OK", f"{run_time:.1f} s ( {len(run)} 行、目安なし ) "))
    else:
        ok = 0.7 * exp <= run_time <= 1.5 * exp
        res.append(("走行時間", "OK" if ok else "WARN",
                    f"{run_time:.1f} s ( {len(run)} 行、目安 {exp:.0f} s ) "))

    return name, df, res


def main():
    ap = argparse.ArgumentParser(description="1つのエピソードの CSV の記録を確認する")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--c", type=float, default=2100.0, help="指定した粘着力 [Pa] ( ラベルの確認用 ) ")
    ap.add_argument("--phi", type=float, default=39.98, help="指定した内部摩擦角 [deg]")
    ap.add_argument("--rho", type=float, default=1474.0, help="指定した密度 [kg/m^3]")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル名")
    ap.add_argument("--no-label", action="store_true", help="ラベルの確認を飛ばす（土質が毎回違うデータ用）")
    a = ap.parse_args()
    soil = {"c": a.c, "phi": a.phi, "rho": a.rho}

    lines = ["# 記録の確認結果", ""]
    total = {"OK": 0, "WARN": 0, "NG": 0}
    for path in a.csv:
        if "sim_time" not in pd.read_csv(path, nrows=0).columns:   # episodes.csv など、時系列データでないものは飛ばす
            print(f"\n==== {os.path.basename(path)} : 時系列データではないので飛ばす ====")
            continue
        name, df, res = check_file(path, soil if not a.no_label else None)
        print(f"\n==== {os.path.basename(path)} ( {name}, {len(df)} 行, {len(df.columns)} 列 ) ====")
        lines += [f"## {os.path.basename(path)} ( {name} ) ", "", "| 項目 | 判定 | 詳細 |", "| --- | --- | --- |"]
        for item, judge, detail in res:
            print(f"  [{judge:4s}] {item}: {detail}")
            lines.append(f"| {item} | {judge} | {detail} |")
            total[judge] += 1
        lines.append("")

    summary = f"合計: OK {total['OK']} / WARN {total['WARN']} / NG {total['NG']}"
    print(f"\n{summary}")
    lines += [summary, ""]
    if a.report:
        with open(a.report, "w") as f:
            f.write("\n".join(lines))
        print(f"レポートを保存しました: {a.report}")


if __name__ == "__main__":
    main()