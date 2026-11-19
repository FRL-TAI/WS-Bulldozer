"""
予稿の図2：φ と締固め K3 の推定の不確かさの楕円（T47）。

notes decisions/2026-11-20_予稿の構成と図.md、handoff T47。

使い方（コンテナの中、ワークスペース直下）:
  python3 analysis/phase1/check_compaction_j35.py --report data/phase1/compaction_j/report_t47.md \\
      --dump-matrices data/phase1/compaction_j/matrices_t35.npz
  python3 analysis/phase1/plot_fig_ellipse.py [--npz data/phase1/compaction_j/matrices_t35.npz] [--out data/phase1/fig_ellipse]

行列（docs/phase1.md §8.8 の組み合わせの表と同じ記録・同じブートストラップ。J は割線〔±0.06〕）:
  (A) 地形だけ・3作業（φ・s・K の3つ同時）：水増しを引いた F の点推定の逆行列の (φ, K) の 2×2。
  (B) 地形 ＋ 力 (i)・3作業の5つ同時：偏りを引いたブートストラップの標本のうち正定値のものについて、
      F⁻¹ の (φ, K) の 2×2 を集め、要素ごとの中央値を取る。
  (A) の点推定が正定値でない場合は止める。

出力: <out>.pdf・<out>.png と、照らし合わせ用の値（標準出力）。
軸は範囲比（Δφ/25°、ΔK3/0.30）。1σ の楕円、中心は原点。
文字は Noto Sans CJK JP（数式は STIX）。コンテナの matplotlib 3.5 は TTC を Type 42 で埋め込めないので、PDF のフォントは Type 3。
"""
import argparse
import math

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SIDES = [(0, "緩い側（0.94）"), (2, "締まった側（1.06）")]   # check_compaction_j35 の SIDES の割線の2つ
COMBO_A, COMBO_B = 0, 3                                        # 地形だけ・3作業／地形 ＋ 力 (i)・5つ同時
MM = 1 / 25.4


def sub2(M, names):
    i, k = names.index("φ"), names.index("K")
    return M[np.ix_([i, k], [i, k])]


def matrices(d, si):
    out = {}
    for lab, ci in (("A", COMBO_A), ("B", COMBO_B)):
        key = f"{si}_{ci}"
        names = list(d[f"names_{key}"])
        F0 = d[f"F0_{key}"]
        S = d[f"samp_{key}"]
        S = S - (S.mean(axis=0) - F0)                      # ctc.summarize と同じ偏りの引き方
        pd = np.array([np.linalg.eigvalsh(x).min() > 0 for x in S])
        pd0 = np.linalg.eigvalsh(F0).min() > 0
        if lab == "A":
            if not pd0:
                raise SystemExit(f"(A) の点推定が正定値でない（{d['sides'][si]}）。作らずに止める。")
            C = sub2(np.linalg.inv(F0), names)
        else:
            subs = np.array([sub2(np.linalg.inv(x), names) for x in S[pd]])
            C = np.median(subs, axis=0)
            corr_med = float(np.median(subs[:, 0, 1] / np.sqrt(subs[:, 0, 0] * subs[:, 1, 1])))
            out["B_corr_median_of_samples"] = corr_med
            out["B_pdfrac"] = float(pd.mean())
        if np.linalg.eigvalsh(C).min() <= 0:
            raise SystemExit(f"({lab}) の 2×2 が正定値でない（{d['sides'][si]}）")
        out[lab] = C
    return out


def ellipse(C, n=200):
    t = np.linspace(0, 2 * np.pi, n)
    L = np.linalg.cholesky(C)
    return L @ np.vstack([np.cos(t), np.sin(t)])


def main():
    ap = argparse.ArgumentParser(description="予稿の図2：φ–K3 の不確かさの楕円（T47）")
    ap.add_argument("--npz", default="data/phase1/compaction_j/matrices_t35.npz")
    ap.add_argument("--out", default="data/phase1/fig_ellipse")
    ap.add_argument("--font", default="Noto Sans CJK JP")
    ap.add_argument("--fontsize", type=float, default=7.5)
    a = ap.parse_args()
    d = np.load(a.npz)

    plt.rcParams.update({
        "font.family": a.font, "font.size": a.fontsize, "axes.linewidth": 0.6,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "pdf.fonttype": 3, "axes.unicode_minus": True, "mathtext.fontset": "stix",
    })
    fig, axes = plt.subplots(1, 2, figsize=(82 * MM, 44 * MM), sharex=True, sharey=True)
    print("| 側 | 楕円 | φ の標準偏差 | K3 の標準偏差 | φ–K3 の相関 |")
    print("|---|---|---|---|---|")
    for ax, (si, title) in zip(axes, SIDES):
        m = matrices(d, si)
        for lab, ls, lw, name in (("A", (0, (3, 1.6)), 1.0, "地形だけ"), ("B", "-", 1.2, "地形＋力")):
            C = m[lab]
            x, y = ellipse(C)
            ax.plot(x, y, color="black", linestyle=ls, linewidth=lw, label=name)
            sd = np.sqrt(np.diag(C))
            print(f"| {title} | ({lab}) {name} | {sd[0]:.4f} | {sd[1]:.4f} | {C[0, 1] / (sd[0] * sd[1]):+.3f} |")
        print(f"| {title} | (B) 標本ごとの相関の中央値 | | | {m['B_corr_median_of_samples']:+.3f} |"
              f"（正定値の標本 {m['B_pdfrac']:.1%}）")
        ax.axhline(0, color="0.75", linewidth=0.4, zorder=0)
        ax.axvline(0, color="0.75", linewidth=0.4, zorder=0)
        ax.set_title(title, fontsize=a.fontsize, pad=3)
        ax.set_xlabel(r"$\Delta\phi$ / 25°")
    axes[0].set_ylabel(r"$\Delta K_3$ / 0.30")
    axes[0].set_xlim(-0.45, 0.45)
    axes[0].set_ylim(-0.04, 0.04)
    axes[0].set_xticks([-0.4, -0.2, 0, 0.2, 0.4])
    axes[0].set_yticks([-0.04, -0.02, 0, 0.02, 0.04])
    axes[0].legend(loc="upper left", frameon=False, handlelength=2.4, borderaxespad=0.3, labelspacing=0.3)
    fig.tight_layout(pad=0.3, w_pad=0.8)
    fig.savefig(a.out + ".pdf")
    fig.savefig(a.out + ".png", dpi=300)
    print(f"\n出力: {a.out}.pdf・{a.out}.png")


if __name__ == "__main__":
    main()
