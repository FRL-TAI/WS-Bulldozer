"""
関門5（物理的な妥当性）の点検。AGX の反力を、土の力学の式（FEE）や力のつり合いと比べる。

置き場所: analysis/validation/check_physics.py
使い方:
  cd /workspaces/ws-bulldozer
  python3 analysis/validation/check_physics.py <collect_data の出力フォルダ、または CSV> [...] [--report 結果.md] [--plot 図.png]

削るエピソード（目標深さが正の走行）について、走行中の行を距離 BIN（既定 0.625 m = 地形のマス2つ分）ごとに平均し、
地形のマスによる揺れを除いてから、次を調べる。

  P1. 土の山の重さと押す力   F_x = a + b × V（V：それまでに削った体積 cut_volume [m³]）で近似し、
                            傾き b を「土の山を地面の上で押す」ときの力 ρ g tanφ と比べる
  P2. 削り始めの力と FEE     切片 a（土の山がないときの前後の力）を、FEE（McKyes の式）の予測と比べる
  P3. 深さとの関係           深さの違うエピソードの切片 a を並べ、FEE の深さの依存性（c d と γ d² の項）と比べる
  P4. 上下の力の向き         F_z / F_x の比を、FEE の予測 cot(α + δ) と比べる
  P5. 履帯の駆動力とのつり合い  履帯の駆動力（関節の力 ÷ 起動輪の半径）が、排土板を押す力 −F_x と転がり抵抗の和になっているか
  P6. 排土板を支える力        lift_joint_effort が F_z とともに変わるか

FEE の土と排土板の間の摩擦角 δ と付着力 ca は未知なので、δ = 0、φ/3、φ/2、2φ/3、ca = 0 の範囲で予測を示す。
判定はしない（値と比を並べる）。関門5は、AGX の反力がどの程度 FEE に合うか・合わないかを把握するための関門。
"""
import argparse
import glob
import json
import math
import os

import numpy as np
import pandas as pd

G = 9.81
BIN = 0.625          # 距離の区切り [m]（地形のマス 0.3125 m × 2）
SETTLE = 1.5         # 走行の開始・目標深さの変化の後、除く時間 [s]


# ---------------------------------------------------------------- FEE（McKyes）
def fee(d, w, alpha_deg, gamma, c, phi_deg, delta_deg, q=0.0, ca=0.0):
    """幅 w の排土板が深さ d を削るときの、土から受ける力の水平・鉛直成分 [N]（McKyes の式）。

    alpha_deg：排土板の面と、前方の地面のなす角（鉛直で 90°、上端が後ろに傾くと 90° より大きい）
    返り値：(H, V, beta_deg)。H は進行方向と逆向きを正、V は下向きを正とする
    """
    a, ph, dl = map(math.radians, (alpha_deg, phi_deg, delta_deg))
    best = None
    for b_deg in np.arange(5.0, 85.0, 0.25):           # 破壊面の角度 β を探す（力が最小になる β）
        b = math.radians(b_deg)
        den = math.cos(a + dl) + math.sin(a + dl) / math.tan(b + ph)
        if den <= 0:
            continue
        cot_a, cot_b = 1 / math.tan(a), 1 / math.tan(b)
        n_g = (cot_a + cot_b) / (2 * den)
        n_c = (1 + cot_b / math.tan(b + ph)) / den
        n_q = (cot_a + cot_b) / den
        n_a = (1 - cot_a / math.tan(b + ph)) / den
        f = w * (gamma * d ** 2 * n_g + c * d * n_c + q * d * n_q + ca * d * n_a)
        if f > 0 and (best is None or f < best[0]):
            best = (f, b_deg)
    if best is None:
        return float("nan"), float("nan"), float("nan")
    f, b_deg = best
    h = f * math.sin(a + dl) + ca * d * w * math.cos(a)
    v = -(f * math.cos(a + dl) - ca * d * w * math.sin(a))   # 下向きを正
    return h, v, b_deg


# ---------------------------------------------------------------- データ
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


def settled_cut_rows(df):
    run = df[df["phase"] == "running"].reset_index(drop=True)
    if len(run) < 100 or run["target_depth"].max() <= 0:
        return None
    t, tgt = run["t"].to_numpy(), run["target_depth"].to_numpy()
    keep, lc = np.zeros(len(run), bool), t[0]
    for i in range(len(run)):
        if i > 0 and abs(tgt[i] - tgt[i - 1]) > 1e-9:
            lc = t[i]
        keep[i] = t[i] - lc >= SETTLE and tgt[i] > 0
    return run[keep]


def binned(rows):
    """距離 BIN ごとの平均（目標深さが変わる所では別の区切りにする）"""
    key = (np.floor(rows["distance"] / BIN)).astype(int).astype(str) + "_" + rows["target_depth"].round(4).astype(str)
    trk = (rows["right_track_effort"] + rows["left_track_effort"])
    omega = (rows["right_track_vel"] + rows["left_track_vel"]) / 2
    df = pd.DataFrame({"key": key, "d": rows["depth"], "tgt": rows["target_depth"], "V": rows["cut_volume"],
                       "Fx": rows["F_total_x"], "Fz": rows["F_total_z"], "Fpen": rows["F_pen_x"], "Fsep": rows["F_sep_x"],
                       "eff": trk, "omega": omega, "v": rows["v_forward"], "lift": rows["lift_joint_effort"],
                       "alpha": rows["blade_alpha_deg"], "w": rows["blade_width"]})
    return df.groupby("key", sort=False).mean(numeric_only=True)


def linfit(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or np.std(x) == 0:
        return float("nan"), float("nan"), float("nan")
    b, a = np.polyfit(x, y, 1)
    r = np.corrcoef(x, y)[0, 1]
    return a, b, r


# ---------------------------------------------------------------- 本体
def main():
    ap = argparse.ArgumentParser(description="関門5（物理的な妥当性）の点検")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--report", help="結果を Markdown で保存するファイル名")
    ap.add_argument("--plot", help="図を保存するファイル名（matplotlib が必要）")
    a = ap.parse_args()

    lines = ["# 関門5の点検（物理的な妥当性）", ""]

    def out(s=""):
        print(s)
        lines.append(s)

    eps = []
    for path in list_targets(a.paths):
        df = pd.read_csv(path)
        rows = settled_cut_rows(df) if "sim_time" in df else None
        if rows is None:
            continue
        bins = binned(rows)
        eps.append((os.path.basename(path), str(df["episode_name"].iloc[0]), df.iloc[0], rows, bins))

    if not eps:
        out("削るエピソードがありません")
        return

    out("## エピソードごと（距離 %.3f m ごとに平均してから近似）" % BIN)
    out("")
    out("| エピソード | 深さ [cm] | P1 F_x = a + b V：a [kN] / b [kN/m³] / r | F_z = a + b V：a [kN] / b [kN/m³] | P4 平均 F_z/F_x | P5 半径 r [m] / 傾き / 転がり抵抗 [kN] / 相関 | P6 lift_effort と F_z の相関 |")
    out("| --- | --- | --- | --- | --- | --- | --- |")
    summary = []
    for fname, name, first, rows, b in eps:
        ax, bx, rx = linfit(b["V"], b["Fx"])
        az, bz, _ = linfit(b["V"], b["Fz"])
        ratio = b["Fz"].mean() / b["Fx"].mean()
        # P5：起動輪の半径を v / ω から求め、駆動力 = 関節の力の和 / 半径
        valid = b["omega"].abs() > 1e-3
        radius = float(np.median(b["v"][valid] / b["omega"][valid])) if valid.any() else float("nan")
        drive = b["eff"] / radius if radius and not np.isnan(radius) else b["eff"] * np.nan
        r0, slope, rd = linfit(-b["Fx"], drive)
        _, _, rl = linfit(b["Fz"], b["lift"])
        depth = float(rows["target_depth"].median())
        if rows["target_depth"].nunique() > 1:
            name += "（深さが変わる。P1・P2 は参考）"
        out(f"| {fname}（{name}） | {depth * 100:.0f} | {ax / 1000:+.2f} / {bx / 1000:+.1f} / {rx:+.2f} | {az / 1000:+.2f} / {bz / 1000:+.1f} | "
            f"{ratio:.2f} | {radius:.3f} / {slope:.2f} / {r0 / 1000:+.1f} / {rd:+.2f} | {rl:+.2f} |")
        summary.append(dict(name=name, depth=depth, ax=ax, bx=bx, az=az, bz=bz, ratio=ratio, radius=radius,
                            slope=slope, r0=r0, rd=rd, rl=rl,
                            c=float(first["label_c"]), phi=float(first["label_phi"]), rho=float(first["label_rho0"]),
                            alpha=float(b["alpha"].mean()), w=float(b["w"].mean()), bins=b, rows=rows))
    out("")

    # P1：土の山を押す力の目安
    s0 = summary[0]
    rho, phi, c = s0["rho"], s0["phi"], s0["c"]
    drag = rho * G * math.tan(math.radians(phi))
    bxs = np.array([s["bx"] for s in summary])
    out("## P1 土の山の重さと押す力")
    out("")
    out(f"- 傾き b（削った体積 1 m³ あたりの、前後の力の増え方）：中央値 {np.median(-bxs) / 1000:.1f} kN/m³（{np.min(-bxs) / 1000:.1f}〜{np.max(-bxs) / 1000:.1f}）")
    out(f"- 土の山を地面の上で押す力の目安 ρ g tanφ = {rho:.0f} × {G} × tan({phi:.1f}°) = {drag / 1000:.1f} kN/m³")
    out(f"- 比（AGX ÷ 目安）：{np.median(-bxs) / drag:.2f}")
    out("")

    # P2・P3・P4：FEE
    alpha_face = 180.0 - s0["alpha"]     # blade_alpha_deg は後ろ向きの水平からの角度。前方の地面となす角に直す
    gamma = rho * G
    out("## P2・P3 削り始めの前後の力（切片 a）と FEE")
    out("")
    out(f"FEE の条件：幅 {s0['w']:.2f} m、排土板の面と前方の地面のなす角 α = 180° − {s0['alpha']:.1f}° = {alpha_face:.1f}°、"
        f"γ = {gamma:.0f} N/m³、c = {c:.0f} Pa、φ = {phi:.1f}°、ca = 0、土の山なし（q = 0）")
    out("")
    deltas = [0.0, phi / 3, phi / 2, 2 * phi / 3]
    out("| 深さ [cm] | AGX の切片 a [kN]（件数） | " + " | ".join(f"FEE δ = {dl:.0f}° [kN]" for dl in deltas) + " |")
    out("| --- | --- | " + " | ".join("---" for _ in deltas) + " |")
    by_depth = {}
    for s in summary:
        if s["rows"]["target_depth"].nunique() == 1:     # 深さが途中で変わるエピソード（val_depth_step）は P2・P3 に使わない
            by_depth.setdefault(round(s["depth"], 3), []).append(-s["ax"])
    for d in sorted(by_depth):
        preds = [fee(d, s0["w"], alpha_face, gamma, c, phi, dl)[0] for dl in deltas]
        vals = by_depth[d]
        out(f"| {d * 100:.0f} | {np.median(vals) / 1000:.2f}（{len(vals)}） | " + " | ".join("成立しない" if np.isnan(p) else f"{p / 1000:.2f}" for p in preds) + " |")
    out("")
    out("## P4 上下の力と前後の力の比")
    out("")
    ratios = np.array([s["ratio"] for s in summary])
    out(f"- AGX：F_z / F_x の平均 {np.median(ratios):.2f}（{ratios.min():.2f}〜{ratios.max():.2f}）。どちらも負なので、F_z は下向き")
    pile = np.array([s["bz"] / s["bx"] for s in summary if s["bx"] != 0])
    cutp = np.array([s["az"] / s["ax"] for s in summary if s["rows"]["target_depth"].nunique() == 1 and abs(s["ax"]) > 500])
    out(f"  - 土の山の分（傾きの比 b_z / b_x）：中央値 {np.median(pile):.2f}（{pile.min():.2f}〜{pile.max():.2f}）")
    if len(cutp):
        out(f"  - 削り始めの分（切片の比 a_z / a_x、|a_x| > 0.5 kN のもの）：中央値 {np.median(cutp):.2f}（{len(cutp)} 件）")
    out("- FEE（土の山なし、ca = 0）：V / H = −cot(α + δ)（正で下向き）")
    for dl in deltas:
        h, v, beta = fee(0.06, s0["w"], alpha_face, gamma, c, phi, dl)
        if np.isnan(h):
            out(f"  - δ = {dl:.0f}°：式が成立しない（α + δ が大きすぎ、土が排土板の面を滑り上がるくさびができない）")
        else:
            out(f"  - δ = {dl:.0f}°：V / H = {v / h:+.2f}（破壊面の角度 β = {beta:.1f}°）")
    out("")
    out("## P5・P6 実機相当の信号とのつり合い")
    out("")
    out(f"- 起動輪の半径（v_forward ÷ 履帯の回転速度）：中央値 {np.median([s['radius'] for s in summary]):.3f} m")
    out(f"- 駆動力 = 傾き × (−F_x) + 転がり抵抗：傾き 中央値 {np.median([s['slope'] for s in summary]):.2f}、"
        f"転がり抵抗 中央値 {np.median([s['r0'] for s in summary]) / 1000:+.1f} kN、相関 中央値 {np.median([s['rd'] for s in summary]):+.2f}")
    out(f"- lift_joint_effort と F_z の相関：中央値 {np.median([s['rl'] for s in summary]):+.2f}")

    if a.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib がないため図は作らない")
        else:
            fig, ax = plt.subplots(1, 3, figsize=(15, 4.5))
            for s in summary:
                b = s["bins"]
                lab = f"{s['name']} {s['depth'] * 100:.0f}cm"
                ax[0].plot(b["V"], -b["Fx"] / 1000, "o", ms=3, label=lab)
                ax[1].plot(-b["Fx"] / 1000, -b["Fz"] / 1000, "o", ms=3, label=lab)
                if not np.isnan(s["radius"]):
                    ax[2].plot(-b["Fx"] / 1000, b["eff"] / s["radius"] / 1000, "o", ms=3, label=lab)
            vv = np.linspace(0, max(s["bins"]["V"].max() for s in summary), 10)
            ax[0].plot(vv, (np.median([-s["ax"] for s in summary]) + drag * vv) / 1000, "k--", label="a + rho g tan(phi) V")
            ax[0].set_xlabel("cut_volume V [m³]")
            ax[0].set_ylabel("-F_total_x [kN]")
            ax[1].set_xlabel("-F_total_x [kN]")
            ax[1].set_ylabel("-F_total_z [kN] (downward)")
            ax[2].set_xlabel("-F_total_x [kN]")
            ax[2].set_ylabel("track drive force [kN]")
            for x in ax:
                x.grid(alpha=0.3)
                x.legend(fontsize=7)
            fig.tight_layout()
            fig.savefig(a.plot, dpi=100)
            print(f"\n図を保存しました: {a.plot}")

    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"レポートを保存しました: {a.report}")


if __name__ == "__main__":
    main()