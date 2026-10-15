"""特定のエピソードを1回だけテスト走行し、取得したデータを点検する。

例：
  ros2 run bull_ope test_episode --list
  ros2 run bull_ope test_episode --calibrate          # 排土板の上げ下げの向きを確認
  ros2 run bull_ope test_episode flat_constant --seed 3
  ros2 run bull_ope test_episode flat_step --c 15000 --phi 30 --rho 1600
  ros2 run bull_ope test_episode flat_constant --no-record

記録した場合は <DATA_DIR>/test/ に CSV を保存し、終了後に列ごとの統計（欠損・定数列など）を表示する。
"""
import argparse
import csv
import math
import os
import threading
from datetime import datetime

import numpy as np
import rclpy
from rclpy.executors import MultiThreadedExecutor

from . import config as C
from .episode_runner import EpisodeRunner, SkipEpisode
from .episodes import SoilParams, available_episodes

# 点検結果で特に注目する列
KEY_COLUMNS = [
    "F_total_x", "F_total_y", "F_total_z", "F_pen_x", "F_sep_x", "F_def_x", "F_con_x",
    "edge_z", "blade_width", "blade_alpha_deg", "ground_ahead", "depth", "speed", "distance",
    "cut_volume", "front_soil_mass", "excavated_volume_step",
    "state_compaction_mean", "state_compaction_std", "state_compaction_n",
    "lift_joint_effort", "right_track_effort", "left_track_effort", "pitch", "slip_ratio",
]


def calibrate(iface):
    h0 = iface.blade["edge_z"]
    t0 = iface.now()
    while iface.now() - t0 < 2.0:
        iface.send_lift_velocity(+0.05)
        iface.sleep_sim(C.CONTROL_PERIOD)
    iface.stop_all()
    iface.sleep_sim(0.5)
    dh = iface.blade["edge_z"] - h0
    sign = 1 if dh > 0 else -1
    print(f"lift_joint に +0.05 を2秒送った → 刃先高さの変化 {dh:+.3f} m")
    print(f"config.py の LIFT_SIGN を {sign} にしてください（現在 {C.LIFT_SIGN}）")


def inspect_csv(path):
    """列ごとの統計を表示し、欠損・定数・未取得の列を指摘する"""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("データがありません")
        return
    run = [r for r in rows if r.get("phase") == "running"]
    print(f"\n==== データの点検: {os.path.basename(path)} ====")
    print(f"全 {len(rows)} 行（うち走行中 {len(run)} 行）")
    times = np.array([float(r["t"]) for r in rows])
    if len(times) > 1:
        dts = np.diff(times)
        print(f"サンプリング周期: 平均 {dts.mean() * 1000:.1f} ms, 最大 {dts.max() * 1000:.1f} ms "
              f"（50 Hz なら 20 ms）")

    target = run or rows
    print(f"\n{'列名':28s}{'欠損':>6s}{'最小':>13s}{'平均':>13s}{'最大':>13s}  判定")
    for col in rows[0].keys():
        vals = []
        for r in target:
            try:
                vals.append(float(r[col]))
            except (TypeError, ValueError):
                vals = None
                break
        if vals is None:
            continue
        v = np.array(vals)
        nan = int(np.sum(~np.isfinite(v)))
        fin = v[np.isfinite(v)]
        if len(fin) == 0:
            note = "未取得（すべて NaN）"
            mn = me = mx = float("nan")
        else:
            mn, me, mx = fin.min(), fin.mean(), fin.max()
            note = "一定" if np.allclose(fin, fin[0]) else ""
        if col in KEY_COLUMNS or note:
            print(f"{col:28s}{nan:6d}{mn:13.4g}{me:13.4g}{mx:13.4g}  {note}")

    # 深さの追従
    if run and "depth" in run[0]:
        print("\n走行中の切削深さ: 平均 {:.3f} m, 標準偏差 {:.3f} m".format(
            np.mean([float(r["depth"]) for r in run]), np.std([float(r["depth"]) for r in run])))


def main():
    ap = argparse.ArgumentParser(description="エピソードを1回テスト走行してデータを点検する")
    ap.add_argument("episode", nargs="?", help="エピソード名")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--calibrate", action="store_true", help="排土板の上げ下げの向きを確認する")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--c", type=float, help="粘着力 [Pa]（指定しなければ乱数）")
    ap.add_argument("--phi", type=float, help="内部摩擦角 [deg]")
    ap.add_argument("--rho", type=float, help="密度 [kg/m^3]")
    ap.add_argument("--swell", type=float, help="膨張率 [-]")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--out", default=os.path.join(C.DATA_DIR, "test"))
    a = ap.parse_args()

    registry = available_episodes()
    if a.list:
        for name, cls in registry.items():
            flag = "（要 AGX_GRID_CONTROL）" if cls.REQUIRES_GRID_CONTROL else ""
            print(f"{name:20s} {cls.description}{flag}")
        return
    if not a.calibrate and a.episode not in registry:
        raise SystemExit(f"エピソード名を指定してください: {list(registry)}")

    rclpy.init()
    from .sim_interface import SimInterface
    iface = SimInterface()
    ex = MultiThreadedExecutor()
    ex.add_node(iface)
    threading.Thread(target=ex.spin, daemon=True).start()
    try:
        iface.wait_ready()
        if a.calibrate:
            calibrate(iface)
            return

        cls = registry[a.episode]
        soil = None
        if any(v is not None for v in (a.c, a.phi, a.rho, a.swell)):
            base = cls.sample_soil(np.random.default_rng(a.seed))
            soil = SoilParams(cohesion=a.c if a.c is not None else base.cohesion,
                              friction_angle_deg=a.phi if a.phi is not None else base.friction_angle_deg,
                              density=a.rho if a.rho is not None else base.density,
                              swell_factor=a.swell)
        ep = cls(seed=a.seed, soil=soil)
        print(f"エピソード: {ep.name}  seed={ep.seed}")
        print(f"土質: {ep.soil}")
        print(f"操作パラメータ: {ep.params}")
        print(f"地形の加工: {len(ep.terrain_ops())} 件")

        csv_path = None
        if not a.no_record:
            os.makedirs(a.out, exist_ok=True)
            csv_path = os.path.join(a.out, datetime.now().strftime(f"%Y%m%d_%H%M%S_{ep.name}.csv"))

        last = {"t": -1.0}

        def on_tick(obs, cmd, err):
            if obs.t - last["t"] >= 0.5:   # 0.5 秒ごとに表示
                last["t"] = obs.t
                b = obs.blade
                print(f"t={obs.t:5.1f}s  dist={obs.distance:5.2f}m  v={obs.speed:4.2f}m/s  "
                      f"depth={obs.depth * 100:5.1f}cm (目標 {cmd.depth * 100 if cmd.depth else float('nan'):5.1f})  "
                      f"Fx={b.get('F_total_x', math.nan) / 1000:7.2f}kN  Fz={b.get('F_total_z', math.nan) / 1000:7.2f}kN")

        summary = EpisodeRunner(iface).run(ep, 0, 1, csv_path=csv_path, on_tick=on_tick)
        print(f"\n結果: {summary}")
        if csv_path:
            inspect_csv(csv_path)
    except SkipEpisode as e:
        print(f"実行できません: {e}")
    finally:
        iface.stop_all()
        iface.set_phase("idle")
        rclpy.shutdown()


if __name__ == "__main__":
    main()
