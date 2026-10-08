"""学習用データを収集する。

例：
  ros2 run soil_data_collector collect_data --list
  ros2 run soil_data_collector collect_data --episodes flat_constant flat_sine --num 20 --sampling lhs
  ros2 run soil_data_collector collect_data --episodes all --num 5 --run-name pilot

出力（<DATA_DIR>/<実行名>/）：
  config.json      実行時の設定
  episodes.jsonl   エピソードごとの条件・土質・結果（1エピソード終わるごとに追記）
  episodes.csv     同じ内容の表（全エピソード終了時に作成）
  ep0000_<名前>.csv  1行 = 1時刻（50 Hz）の時系列データ
"""
import argparse
import csv
import json
import os
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime

import numpy as np
import rclpy
from rclpy.executors import MultiThreadedExecutor

from . import config as C
from .episode_runner import EpisodeRunner, SkipEpisode
from .episodes import SoilParams, available_episodes


def lhs_soils(cls, n, rng):
    """ラテン超方格法で土質パラメータを n 組つくる（範囲は cls.SOIL_RANGES）"""
    cols = {}
    for key, (lo, hi) in cls.SOIL_RANGES.items():
        u = (rng.permutation(n) + rng.random(n)) / n
        cols[key] = lo + (hi - lo) * u
    return [SoilParams(**{k: float(v[i]) for k, v in cols.items()}) for i in range(n)]


def build_plan(names, num, seed, sampling):
    registry = available_episodes()
    if names == ["all"]:
        names = list(registry)
    unknown = [n for n in names if n not in registry]
    if unknown:
        raise SystemExit(f"不明なエピソード: {unknown}（--list で一覧を表示）")
    rng = np.random.default_rng(seed)
    plan = []
    for name in names:
        cls = registry[name]
        soils = lhs_soils(cls, num, rng) if sampling == "lhs" else [None] * num
        for soil in soils:
            plan.append(cls(seed=int(rng.integers(0, 2**31 - 1)), soil=soil))
    rng.shuffle(plan)   # 種類が偏らないよう順番を混ぜる
    return plan


def write_table(path, records):
    """エピソードの種類ごとに列が違うので、全列の和集合で表にする"""
    if not records:
        return
    keys = []
    for r in records:
        keys += [k for k in r if k not in keys]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, restval="")
        w.writeheader()
        w.writerows(records)


def main():
    ap = argparse.ArgumentParser(description="土質パラメータ推定用の学習データを収集する")
    ap.add_argument("--list", action="store_true", help="使えるエピソードの一覧を表示して終了")
    ap.add_argument("--episodes", nargs="+", default=["all"], help="実行するエピソード名（all で全種類）")
    ap.add_argument("--num", type=int, default=5, help="エピソードの種類ごとの実行回数")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sampling", choices=["uniform", "lhs"], default="lhs", help="土質パラメータの決め方")
    ap.add_argument("--out", default=C.DATA_DIR)
    ap.add_argument("--run-name", default="")
    a = ap.parse_args()

    if a.list:
        for name, cls in available_episodes().items():
            flag = "（要 AGX_GRID_CONTROL）" if cls.REQUIRES_GRID_CONTROL else ""
            print(f"{name:20s} {cls.description}{flag}")
        return

    plan = build_plan(a.episodes, a.num, a.seed, a.sampling)
    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S") + (f"_{a.run_name}" if a.run_name else "")
    run_dir = os.path.join(a.out, run_name)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "config.json"), "w") as f:
        cfg = {k: getattr(C, k) for k in dir(C) if k.isupper()}
        json.dump({"args": vars(a), "config": cfg, "num_episodes": len(plan)}, f, indent=2, ensure_ascii=False)

    rclpy.init()
    from .sim_interface import SimInterface
    iface = SimInterface()
    ex = MultiThreadedExecutor()
    ex.add_node(iface)
    threading.Thread(target=ex.spin, daemon=True).start()
    runner = EpisodeRunner(iface)
    log = iface.get_logger()

    jsonl_path = os.path.join(run_dir, "episodes.jsonl")
    records = []
    try:
        iface.wait_ready()
        t_start = time.monotonic()
        for i, ep in enumerate(plan):
            fname = f"ep{i:04d}_{ep.name}.csv"
            row = {"episode_index": i, "file": fname, **ep.metadata()}
            log.info(f"[{i + 1}/{len(plan)}] {ep.name} seed={ep.seed} soil={asdict(ep.soil)}")
            try:
                summary = runner.run(ep, i, len(plan), csv_path=os.path.join(run_dir, fname))
                row.update(summary, status="ok")
            except SkipEpisode as e:
                log.warn(f"スキップ: {e}")
                row.update(status=f"skipped: {e}")
            except Exception as e:  # 1つの失敗で全体を止めない
                log.error(f"失敗: {e}\n{traceback.format_exc()}")
                row.update(status=f"error: {e}")
                iface.stop_all()
            records.append(row)
            with open(jsonl_path, "a") as f:   # 途中で止まっても残るよう1件ずつ追記
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            elapsed = time.monotonic() - t_start
            log.info(f"経過 {elapsed / 60:.1f} 分、残り約 {elapsed / (i + 1) * (len(plan) - i - 1) / 60:.1f} 分")
    finally:
        write_table(os.path.join(run_dir, "episodes.csv"), records)
        iface.stop_all()
        iface.set_phase("finished")
        rclpy.shutdown()
    print(f"保存先: {run_dir}")


if __name__ == "__main__":
    main()
