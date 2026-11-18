"""
【フェーズ1：T12】maxDensity を ρ に比例させる案（案D）の確認と、膨張率の範囲の両端での動作確認

notes の decisions/2026-11-17_maxDensityをρに比例させる.md（maxDensity = 1.357·ρ）を確定してよいかを確かめる。
  - ex_maxdens_flat_cut_md2000・md2578：ρ 1,900 の flat_cut（9 cm・0.5 m/s・10 m）を maxDensity 2,000・2,578 で削る。
    削るときの力が maxDensity で変わらないか（関門5〜7 の高い ρ の結果がそのまま使えるか）。
  - ex_compaction_passes_md2000・md2578：ρ 1,900 で 8 m を4往復して履帯で踏む（ex_compaction_passes と同じ動き）。
    締固めの程度が 2,000 では 2000/1900 = 1.053 で頭打ちになり、2,578 では超えるか。
  - ex_swell_flat_cut_s110・s140、ex_swell_pile_push_s110・s140：膨張率 1.10・1.40（ほかは dirt_1）で動くか。
ρ 以外の土質は dirt_1（BASE_SOIL）。maxDensity 2,578 = 1.357 × 1,900（1.357 = 2000/1474、今の dirt_1 の maxDensity/ρ）。

maxDensity の上書きは、SoilParams に max_density を足した MaxDensitySoilParams で Unity に送る
（Unity の SimEpisodeManager.SoilSpec.max_density）。T13 で Unity の ApplySoil は、上書きがなければ
maxDensity = (2000/1474)·ρ にするようになった（案D）。runner の読み戻しの確認（_check_soil）は、上書きがあればその値、
なければ config.MAX_DENSITY_PER_DENSITY × ρ と比べる。

【T13】ex_maxdens_flat_cut_auto：ρ 1,900 で上書きをせず、Unity が maxDensity を 2000/1474 × 1,900 ≈ 2,578 にするかを確かめる。
"""
from dataclasses import asdict, dataclass
from typing import Optional

from .ex_compaction_passes import CompactionPasses
from .ex_ident_flat_cut import BASE_SOIL, _IdentFlatCut
from .ex_ident_pile_push import _IdentPilePush
from ..episode import SoilParams
from ..turnaround import PassesByProgressMixin

RHO_HIGH = 1900.0


@dataclass
class MaxDensitySoilParams(SoilParams):
    max_density: Optional[float] = None    # 締固めの上限の密度 maxDensity [kg/m^3]. None なら Unity 側の値のまま


class _MaxDensityMixin:
    """SOIL_RANGES（下限 = 上限）と MAX_DENSITY から土質を作る。
    collect_data は SOIL_RANGES から SoilParams を作って渡す（sample_soil を呼ばない）ので、
    渡された土質も MaxDensitySoilParams に詰め直して max_density を足す"""
    MAX_DENSITY: Optional[float] = None

    def __init__(self, seed, soil=None):
        if soil is not None and not isinstance(soil, MaxDensitySoilParams):
            soil = MaxDensitySoilParams(**asdict(soil), max_density=self.MAX_DENSITY)
        super().__init__(seed, soil)

    @classmethod
    def sample_soil(cls, rng):
        return MaxDensitySoilParams(**{k: float(lo) for k, (lo, hi) in cls.SOIL_RANGES.items()},
                                    max_density=cls.MAX_DENSITY)


def _soil(**change):
    s = dict(BASE_SOIL)
    s.update(change)
    return {k: (v, v) for k, v in s.items()}


# ---- (a) flat_cut、ρ 1,900、maxDensity 2,000・2,578 ----
class MaxDensFlatCut2000(_MaxDensityMixin, _IdentFlatCut):
    name = "ex_maxdens_flat_cut_md2000"
    description = "【T12】ρ 1,900・maxDensity 2,000 で、深さ 9 cm で 10 m 削る"
    SOIL_RANGES = _soil(density=RHO_HIGH)
    MAX_DENSITY = 2000.0
    POINT = "rho1900_md2000"


class MaxDensFlatCut2578(_MaxDensityMixin, _IdentFlatCut):
    name = "ex_maxdens_flat_cut_md2578"
    description = "【T12】ρ 1,900・maxDensity 2,578（1.357·ρ）で、深さ 9 cm で 10 m 削る"
    SOIL_RANGES = _soil(density=RHO_HIGH)
    MAX_DENSITY = 2578.0
    POINT = "rho1900_md2578"


class MaxDensFlatCutAuto(_IdentFlatCut):
    name = "ex_maxdens_flat_cut_auto"
    description = "【T13】ρ 1,900・maxDensity は上書きせず（Unity の案D で 2000/1474·ρ）、深さ 9 cm で 10 m 削る"
    SOIL_RANGES = _soil(density=RHO_HIGH)
    POINT = "rho1900_auto"


# ---- (b) 履帯で4往復、ρ 1,900、maxDensity 2,000・2,578 ----
class _PassesByEdgeX(_MaxDensityMixin, PassesByProgressMixin, CompactionPasses):
    """往復の折り返しを、開始位置からの直線距離ではなく、刃先の開始時の向きへの進みで判定する
    （T31 で共通の判定 turnaround.PassesByProgressMixin に置き換えた。T12 の記録は edge_x の進みで判定したもの）。
    ex_compaction_passes の判定（obs.distance <= 0.2）では、往復で向きが少しずつずれて横に 0.2 m 以上離れると
    開始位置に戻ったと判定されず、後退し続ける（ρ 1,900・maxDensity 2,578 の1回目で、4回目の後退で起きた）"""
    name = ""   # 一覧に出さない（共通部分）


class CompactionPasses2000(_PassesByEdgeX):
    name = "ex_compaction_passes_md2000"
    description = "【T12】ρ 1,900・maxDensity 2,000 で、排土板を上げたまま 8 m を4往復する"
    SOIL_RANGES = _soil(density=RHO_HIGH)
    MAX_DENSITY = 2000.0


class CompactionPasses2578(_PassesByEdgeX):
    name = "ex_compaction_passes_md2578"
    description = "【T12】ρ 1,900・maxDensity 2,578（1.357·ρ）で、排土板を上げたまま 8 m を4往復する"
    SOIL_RANGES = _soil(density=RHO_HIGH)
    MAX_DENSITY = 2578.0


# ---- (c) 膨張率 1.10・1.40（ほかは dirt_1）----
class SwellFlatCut110(_IdentFlatCut):
    name = "ex_swell_flat_cut_s110"
    description = "【T12】膨張率 1.10（ほかは dirt_1）で、深さ 9 cm で 10 m 削る"
    SOIL_RANGES = _soil(swell_factor=1.10)
    POINT = "swell_110"


class SwellFlatCut140(_IdentFlatCut):
    name = "ex_swell_flat_cut_s140"
    description = "【T12】膨張率 1.40（ほかは dirt_1）で、深さ 9 cm で 10 m 削る"
    SOIL_RANGES = _soil(swell_factor=1.40)
    POINT = "swell_140"


class SwellPilePush110(_IdentPilePush):
    RECORD_COMPACTION = True   # 山の締固めの程度が 1/膨張率 になっているかを、機体の中心の列で確かめる
    name = "ex_swell_pile_push_s110"
    description = "【T12】膨張率 1.10（ほかは dirt_1）で、3 m 先の山を深さ 2 cm で押す"
    SOIL_RANGES = _soil(swell_factor=1.10)
    POINT = "swell_110"


class SwellPilePush140(_IdentPilePush):
    RECORD_COMPACTION = True
    name = "ex_swell_pile_push_s140"
    description = "【T12】膨張率 1.40（ほかは dirt_1）で、3 m 先の山を深さ 2 cm で押す"
    SOIL_RANGES = _soil(swell_factor=1.40)
    POINT = "swell_140"
