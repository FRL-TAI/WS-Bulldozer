"""
1つのエピソードの CSV が、きちんと記録されているかを確認する。

使い方:
  python3 check_recording.py <CSV> [<CSV> …]
  python3 check_recording.py data/validation/stress/<実行日時>/A/*.csv --report 結果.md

各 CSV について次を確認し、OK / WARN ( 要確認 ) / NG ( 不合格 ) で表示する。
  1. 記録の周期        2. 時刻の単調性・重複   3. 欠損 ( NaN ) 
  4. 一定の列          5. ラベル              6. 進行状況の順番     7. 走行時間
  8. 折り返し（往復するエピソード ex_compaction_passes*・ex_compaction_then_cut* だけ）
  9. 締固めの記録（締固めの記録を取る設定のエピソードだけ）

折り返しでは、次のどれかに当たる記録を NG にする
( notes の decisions/2026-11-18_折り返しは進みの判定の別名版と失敗の検出で直す.md ) 。
  - 安全停止（またはエラー）で終わった：進行状況に raising がない
  - 後退の回数（cmd_vx < 0 が続く区間の数）が ROUND_TRIPS（そのエピソードとシードの param）と違う
  - 後退の区間の、折り返しの判定に使う量の最小値が判定の値（0.2 m）を超えた（開始位置に戻ったと判定されなかった）
    判定に使う量は、直線距離の版（ex_compaction_passes・ex_compaction_then_cut）では記録の distance、
    進みの版（_v2・T12 の _md*）では刃先の開始時の向きへの進み p（edge_x・edge_y から bull_ope と同じ方法で求める）

欠損では、削っていない行 ( state_cut_compaction_n が 0 ) の state_cut_compaction_mean/min/max の NaN は
想定どおりとする。あとから足した列 ( NEW_COLS ) がない記録、front_soil_mass・excavated_volume_step が
全行 NaN の記録は「旧形式」と表示し、NG にしない ( 一定の列の判定からも外す ) 。

一定の列では、前方の地面の高さの列 ( GROUND_AHEAD_PREFIX ) が走行中に一定で、その値が ground_h0 と一致する
( 差が GROUND_CONST_TOL 以内 ) 場合は、手つかずの平らな地面を読んでいるので正常とする。
それ以外の値で一定な場合は、これまでどおり WARN にする
( notes の decisions/2026-11-17_粒子を含む高さの列とground_profileの扱い.md ) 。

締固めの記録では、同じフォルダの episodes.jsonl で、その CSV の行の record_compaction が true なら
「取る設定」とし、compaction_rows が 0（または値がない）か compaction_final が false なら NG にする。
collect_data は Unity から締固めの記録が届かなくても status を ok にするため
( notes の decisions/2026-11-18_T30・T31の未解決の扱い.md ) 。
エピソードのクラスの RECORD_COMPACTION は使わない（T31 で ex_ident_* を True に変えたので、それより前の記録を誤って NG にする）。
episodes.jsonl がない、その CSV の行がない、または record_compaction の値がない（旧形式）の記録は判定しない。

エラーで途中終了したエピソードの CSV も点検できる ( 途中で切れていないか、NaN がないかの確認 ) 
"""
import argparse
import json
import math
import os
import re

import numpy as np
import pandas as pd

# ---- 判定の基準 ----
PERIOD_TARGET = 0.020        # 記録の周期の目標 [s] ( 50 Hz ) 
PERIOD_TOL = 0.002           # 平均周期の許容誤差 [s]
GAP_LIMIT = 0.050            # これより長い間隔を「取りこぼし」とみなす [s]

# 今は NaN で正常な列 ( 設定値がないと計算しない ) 
# front_soil_mass・excavated_volume_step は AGX の API で取るようにしたので外した（それより前の記録では NaN になる）
EXPECTED_NAN = {"state_compaction_mean", "state_compaction_std", "slip_ratio"}

# 削っていない行 ( 削っている層のマスがない行。CUT_N_COL == 0 ) だけ NaN で正常な列
# 削っている行 ( CUT_N_COL > 0 ) の NaN は、今までどおり想定外とする
CUT_NAN_COLS = {"state_cut_compaction_mean", "state_cut_compaction_min", "state_cut_compaction_max"}
CUT_N_COL = "state_cut_compaction_n"

# あとから足した列。古い記録では列がない ( 旧形式 ) 
NEW_COLS = ["label_maxDensity",                                                # T13
            "front_soil_mass", "front_soil_mass_deform", "front_dynamic_mass",  # T14
            "front_inner_volume", "front_dead_load_fraction", "excavated_volume_step"]
# T14 より前の記録では、列はあるが全行 NaN ( 旧形式 ) 。一部の行だけ NaN なら想定外
OLD_ALL_NAN_COLS = {"front_soil_mass", "excavated_volume_step"}

# エピソード中に一定で正常な列
EXPECTED_CONST_PREFIX = ("label_",)
EXPECTED_CONST = {"episode_index", "episode_name", "seed", "phase", "leg", "ground_h0",
                  "blade_width", "state_compaction_n", "target_depth", "depth_clipped",
                  "front_inner_volume", "front_soil_mass_deform",
                  # T24：常に 0 の力（関門3）、換算の ρ/s（エピソード中は一定）、一定の指令
                  "F_def_x", "F_def_y", "F_def_z", "F_con_x", "F_con_y", "F_con_z",
                  "pile_bulk_density", "cmd_vx", "cmd_wz"}

# 走行中に一定でも、値が ground_h0 と一致すれば正常な列 ( 前方の地面の高さ。刃先の前 1〜1.25 m より先は手つかずの平らな地面 ) 
GROUND_AHEAD_PREFIX = ("ground_ahead", "ground_profile_", "ground_terrain_", "ground_vis_", "ground_ptop_")
# ground_h0 との差の許容 [m]。ground_h0 は Unity の TerrainData から、ground_terrain_*・ground_vis_*・
# ground_ptop_* は AGX の高さから読むので、平らな地面でも 0.46 mm ずれる（T23）。1 mm までを一致とみなす
GROUND_CONST_TOL = 1e-3

# 走行時間の目安 [s] ( ここにないエピソードは判定しない ) 
EXPECTED_RUN_TIME = {
    "val_static": 10.0, "val_air_run": 20.0, "val_constant_depth": 20.0, "val_depth_step": 18.0,
    "stress_short": 2.0, "stress_spin": 15.0, "stress_nan_depth": 2.0,
}

PHASE_ORDER = ["lowering", "running", "raising"]

# 8. 折り返し
TURN_PREFIX = ("ex_compaction_passes", "ex_compaction_then_cut")
TURN_RETURN = 0.2      # 開始位置に戻ったとみなす値 [m]（エピソードの判定と同じ）
TURN_TOL = 0.02        # 記録の周期（50 Hz）と制御の周期のずれの許容 [m]
TURN_DIR = 0.5         # 進みの版で、開始時の向きを決める刃先の移動距離 [m]（bull_ope.episodes.turnaround と同じ）


def expected_round_trips(name, seed):
    """エピソードのクラスから ROUND_TRIPS（シードで変わるものは param の round_trips）を求める。分からなければ None"""
    try:
        from bull_ope.episodes import available_episodes
        cls = available_episodes().get(name)
        if cls is None:
            return None
        ep = cls(int(seed))
        return int(ep.params.get("round_trips", getattr(cls, "ROUND_TRIPS", None)))
    except Exception:
        return None


def progress_series(df):
    """刃先の開始時の向きへの進み p（bull_ope.episodes.turnaround.ProgressTracker と同じ）"""
    ex, ey = df["edge_x"].to_numpy(), df["edge_y"].to_numpy()
    dx, dy = ex - ex[0], ey - ey[0]
    r = np.hypot(dx, dy)
    k = np.argmax(r >= TURN_DIR) if (r >= TURN_DIR).any() else None
    if k is None:
        return r
    u = (dx[k] / r[k], dy[k] / r[k])
    p = dx * u[0] + dy * u[1]
    p[:k] = r[:k]
    return p


def check_turnaround(df, name):
    """往復するエピソードの折り返しの失敗を検出する。戻り値 (判定, 詳細)"""
    problems = []
    if "raising" not in set(df["phase"]):
        problems.append("安全停止またはエラーで終わった（raising がない）")
    run = df[df["phase"] == "running"].reset_index(drop=True)
    by_progress = bool(re.search(r"_v2|_md\d+", name))
    metric = progress_series(run) if by_progress else run["distance"].to_numpy()
    back = (run["cmd_vx"] < 0).to_numpy()
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
    mins = [float(np.nanmin(metric[a:b])) for a, b in legs]
    want = expected_round_trips(name, df["seed"].iloc[0]) if "seed" in df else None
    if want is not None and len(legs) != want:
        problems.append(f"後退の回数 {len(legs)} が ROUND_TRIPS {want} と違う")
    over = [m for m in mins if m > TURN_RETURN + TURN_TOL]
    if over:
        problems.append(f"後退の区間の最小値が {TURN_RETURN} m を超えた（{', '.join(f'{m:.3f}' for m in over)} m）")
    detail = (f"判定 {'進み p' if by_progress else '直線距離'}、後退 {len(legs)} 回（ROUND_TRIPS {want if want is not None else '不明'}）、"
              f"後退ごとの最小値 " + ("・".join(f"{m:.3f}" for m in mins) if mins else "—") + " m")
    if problems:
        return "NG", "；".join(problems) + "。" + detail
    return ("OK" if want is not None else "WARN"), detail


_JSONL_CACHE = {}


def episode_summary(path):
    """CSV と同じフォルダの episodes.jsonl から、その CSV の行を返す。なければ None"""
    d = os.path.dirname(os.path.abspath(path))
    if d not in _JSONL_CACHE:
        rows = {}
        jp = os.path.join(d, "episodes.jsonl")
        if os.path.exists(jp):
            with open(jp) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("file"):
                        rows[r["file"]] = r
        _JSONL_CACHE[d] = rows
    return _JSONL_CACHE[d].get(os.path.basename(path))


def check_compaction_record(path):
    """締固めの記録を取る設定のエピソードで、Unity から記録が届いたかを確かめる。対象外なら None"""
    r = episode_summary(path)
    if r is None or r.get("record_compaction") is not True:
        return None
    rows, final = r.get("compaction_rows"), r.get("compaction_final")
    detail = f"compaction_rows {rows}、compaction_final {final}"
    problems = []
    if not rows:
        problems.append("締固めの記録が届いていない（compaction_rows が 0 または値がない）")
    if final is not True:
        problems.append("締固めの最後の記録が届いていない（compaction_final が true でない）")
    if problems:
        return "NG", "；".join(problems) + "。" + detail
    return "OK", detail


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
    old_missing = [c for c in NEW_COLS if c not in df]                          # 旧形式 ( 列なし ) 
    old_all_nan = [c for c in NEW_COLS
                   if c in OLD_ALL_NAN_COLS and c in nan_cols and nan_cols[c] == len(df)]  # 旧形式 ( 全行 NaN ) 
    not_cutting = (df[CUT_N_COL] == 0) if CUT_N_COL in df else pd.Series(False, index=df.index)
    unexpected, expected = {}, []
    for c, n in nan_cols.items():
        if c in EXPECTED_NAN:
            expected.append(c)
        elif c in old_all_nan:
            continue
        elif c in CUT_NAN_COLS:
            n_cut = int((num[c].isna() & ~not_cutting).sum())      # 削っている行の NaN だけ数える
            if n_cut:
                unexpected[c] = n_cut
            else:
                expected.append(f"{c}(削っていない {n}行)")
        else:
            unexpected[c] = n
    detail = "想定外の NaN: " + (", ".join(f"{c}({n}行)" for c, n in unexpected.items()) or "なし")
    detail += " / 想定どおりの NaN: " + (", ".join(sorted(expected)) or "なし")
    if old_missing:
        detail += " / 旧形式（列なし）: " + ", ".join(old_missing)
    if old_all_nan:
        detail += " / 旧形式（全行 NaN）: " + ", ".join(old_all_nan)
    res.append(("欠損", "OK" if not unexpected else "NG", detail))

    # 4. 一定の列 ( 走行中のみで判定。走行中の行がなければ判定しない ) 
    run = df[df["phase"] == "running"] if "phase" in df else df
    if len(run) < 2:
        res.append(("一定の列 ( 走行中 ) ", "WARN", f"走行中の行が {len(run)} 行のため判定しない"))
    else:
        const = [c for c in run.columns
                 if run[c].nunique(dropna=False) <= 1
                 and c not in EXPECTED_CONST and not c.startswith(EXPECTED_CONST_PREFIX)
                 and c not in EXPECTED_NAN and c not in old_all_nan]
        # 前方の地面の高さで、一定の値が ground_h0 と一致する列は正常とする
        h0 = run["ground_h0"].iloc[0] if "ground_h0" in run else np.nan
        flat = [c for c in const if c.startswith(GROUND_AHEAD_PREFIX)
                and np.isfinite(h0) and abs(float(run[c].iloc[0]) - float(h0)) <= GROUND_CONST_TOL]
        const = [c for c in const if c not in flat]
        detail = "想定外に一定: " + (", ".join(const) or "なし")
        if flat:
            detail += " / ground_h0 と一致して一定 ( 正常 ) : " + ", ".join(flat)
        res.append(("一定の列 ( 走行中 ) ", "OK" if not const else "WARN", detail))

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
        phases = df["phase"].fillna("(欠損)").astype(str).tolist()   # 途中で切れた CSV では最後の行が欠ける
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

    # 8. 折り返し
    if name.startswith(TURN_PREFIX) and "phase" in df and "cmd_vx" in df:
        res.append(("折り返し", *check_turnaround(df, name)))

    # 9. 締固めの記録
    comp = check_compaction_record(path)
    if comp is not None:
        res.append(("締固めの記録", *comp))

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