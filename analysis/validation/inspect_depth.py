"""
関門3の U3（深さの追従）・U4（刃先と地面）・U9（記録の最初の状態）の WARN を調べる。

置き場所: analysis/validation/inspect_depth.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/validation/inspect_depth.py <CSV> [<CSV> …] [--plot]

各 CSV について次を表示する。--plot を付けると、CSV と同じ場所に <CSV名>_depth.png を保存する
（matplotlib が必要。ない場合は pip install matplotlib）。

  1. 深さのずれの揺れ方：標準偏差、揺れの周期と、その間に進む距離、
     ずれと「ピッチの変化」「F_total_x」「lift_joint の速度指令」との相関
  2. 刃先と地面：ground_below − edge_z を、走行中の距離ごと（1 m 刻み）に平均
  3. 下げる区間：記録の最初と最後の刃先・地面の高さ、下げる区間で出た力の最大
"""
import argparse
import os

import numpy as np
import pandas as pd

SETTLE = 1.5      # 走行の開始・目標深さの変化の後、除く時間 [s]


def settled(run):
    t = run["t"].to_numpy()
    tgt = run["target_depth"].to_numpy()
    keep = np.zeros(len(run), bool)
    lc = t[0]
    for i in range(len(run)):
        if i > 0 and abs(tgt[i] - tgt[i - 1]) > 1e-9:
            lc = t[i]
        keep[i] = t[i] - lc >= SETTLE
    return run[keep]


def corr(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def dominant_period(x, dt):
    """平均を引いた信号の、最も大きい周波数成分の周期 [s]"""
    x = np.asarray(x, float) - np.mean(x)
    if len(x) < 32:
        return float("nan")
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freq = np.fft.rfftfreq(len(x), dt)
    k = 1 + int(np.argmax(spec[1:]))
    return 1.0 / freq[k] if freq[k] > 0 else float("nan")


def inspect(path, plot):
    df = pd.read_csv(path)
    name = str(df["episode_name"].iloc[0])
    print(f"\n==== {os.path.basename(path)}（{name}） ====")
    run = df[df["phase"] == "running"].reset_index(drop=True)
    low = df[df["phase"] == "lowering"]

    # 3. 下げる区間
    if len(low):
        f = np.sqrt(low["F_total_x"] ** 2 + low["F_total_y"] ** 2 + low["F_total_z"] ** 2)
        a, b = low.iloc[0], low.iloc[-1]
        print(f"  下げる区間 {len(low)} 行：edge_z {a['edge_z']:+.3f} → {b['edge_z']:+.3f} m、"
              f"ground_below {a['ground_below']:+.3f} → {b['ground_below']:+.3f} m、力の最大 {f.max() / 1000:.2f} kN")

    if len(run) < 50 or run["target_depth"].max() <= 0:
        print("  （削るエピソードではないので、深さの揺れは調べない）")
    else:
        s = settled(run)
        err = (s["depth"] - s["target_depth"]).to_numpy()
        dt = float(np.median(np.diff(s["sim_time"]))) if len(s) > 1 else 0.02
        period = dominant_period(err, dt)
        v = float(s["v_forward"].mean())
        dpitch = np.degrees(s["pitch"] - run["pitch"].iloc[0])

        # 1. 深さのずれの揺れ方
        print(f"  深さのずれ：平均 {err.mean() * 100:+.2f} cm、標準偏差 {err.std() * 100:.2f} cm、"
              f"揺れの周期 {period:.2f} s（その間に {period * v:.2f} m 進む）")
        print(f"  ずれとの相関：ピッチの変化 r = {corr(err, dpitch):+.2f}、F_total_x r = {corr(err, s['F_total_x']):+.2f}、"
              f"lift の速度指令 r = {corr(err, s['cmd_lift']):+.2f}")
        print(f"  ピッチの変化：{dpitch.min():+.2f}〜{dpitch.max():+.2f}°（刃先は車体の約 2.8 m 前なので、1° で約 5 cm 上下する）")

        # 2. 刃先と地面（距離ごと）
        gap = s["ground_below"] - s["edge_z"]
        bins = np.floor(s["distance"]).astype(int)
        table = gap.groupby(bins).mean() * 100
        print("  ground_below − edge_z（1 m ごとの平均 [cm]）：" +
              "、".join(f"{d}〜{d + 1} m {g:+.1f}" for d, g in table.items()))
        cut = (s["ground_h0"] - s["ground_below"]) * 100
        print(f"  刃先の真下の地面の深さ（ground_h0 − ground_below）：中央値 {cut.median():.1f} cm "
              f"/ 刃先の深さ（depth）：中央値 {s['depth'].median() * 100:.1f} cm")

    if plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("  matplotlib がないため図は作らない（pip install matplotlib）")
            return
        fig, ax = plt.subplots(4, 1, figsize=(10, 10), sharex=True)
        t = df["t"]
        ax[0].plot(t, df["depth"] * 100, label="depth")
        ax[0].plot(t, df["target_depth"] * 100, "--", label="target_depth")
        ax[0].set_ylabel("depth [cm]")
        ax[1].plot(t, np.degrees(df["pitch"]), label="pitch")
        ax[1].set_ylabel("pitch [deg]")
        ax[2].plot(t, df["edge_z"], label="edge_z")
        ax[2].plot(t, df["ground_below"], label="ground_below")
        ax[2].plot(t, df["ground_ahead"], label="ground_ahead")
        ax[2].set_ylabel("height [m]")
        ax[3].plot(t, df["F_total_x"] / 1000, label="F_total_x")
        ax[3].plot(t, df["F_total_z"] / 1000, label="F_total_z")
        ax[3].set_ylabel("force [kN]")
        ax[3].set_xlabel("t [s]")
        for a in ax:
            for ph, c in (("lowering", "0.9"), ("raising", "0.8")):
                m = df["phase"] == ph
                if m.any():
                    a.axvspan(t[m].min(), t[m].max(), color=c, zorder=0)
            a.legend(loc="upper right", fontsize=8)
            a.grid(alpha=0.3)
        fig.suptitle(f"{os.path.basename(path)} ({name})")
        out = os.path.splitext(path)[0] + "_depth.png"
        fig.tight_layout()
        fig.savefig(out, dpi=100)
        plt.close(fig)
        print(f"  図を保存しました: {out}")


def main():
    ap = argparse.ArgumentParser(description="深さの追従と刃先・地面の関係を調べる")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--plot", action="store_true", help="図を保存する")
    a = ap.parse_args()
    for p in a.csv:
        inspect(p, a.plot)


if __name__ == "__main__":
    main()