"""
エピソードの抽象クラス

1つのエピソードは次の4つで定義される。
  - name            : エピソード名
  - soil            : 土質パラメータ(SoilParams)
  - terrain_ops()   : 地形データ（リセット後の地形に加える加工。既定は平らな地形のまま）
  - operation(obs)  : 操作（各時刻の観測から、車速と目標切削深さを返す）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class SoilParams:
    """土質パラメータ（エピソード中は一定の材料パラメータ）"""
    cohesion: float                         # 粘着力 c [Pa]
    friction_angle_deg: float               # 内部摩擦角 φ [deg]（地山の状態での基本値）
    density: float                          # 地山の密度 ρ0 [kg/m^3]
    swell_factor: Optional[float] = None    # 膨張率 [-]. None なら Unity 側の値のまま
    youngs_modulus: Optional[float] = None  # ヤング率 E0 [Pa]. None なら Unity 側の値のまま

    def to_msg_dict(self) -> dict:
        # Unity 側では負の値を「変更しない」と解釈する
        return {k: (-1.0 if v is None else float(v)) for k, v in asdict(self).items()}


@dataclass
class TerrainOp:
    """地形の加工。エピソード座標系で指定する。

    エピソード座標系：開始時の刃先中点を原点とし、x が車体の前方、y が左方 [m]。

    type:
      "compaction_rect"  : 範囲内の地表から depth [m] までの締固めの程度を value にする
      "loose_layer_rect" : 範囲内に厚さ value [m] の緩い土の層（締固め 1/膨張率）を積む
    """
    type: str
    x_start: float
    x_end: float
    y_min: float
    y_max: float
    value: float = 1.0
    depth: float = 0.0

    def to_msg_dict(self) -> dict:
        return asdict(self)


@dataclass
class Observation:
    """operation() に渡す観測"""
    t: float          # 走行開始からの経過時間 [s]
    distance: float   # 開始位置からの走行距離 [m]
    speed: float      # 車速 [m/s]
    edge_z: float     # 刃先の高さ（ワールド）[m]
    ground_h0: float  # 開始時に測った元の地面の高さ [m]
    depth: float      # 現在の切削深さ = ground_h0 - edge_z [m]
    blade: dict       # blade_state の最新値（名前 → 値）


@dataclass
class Command:
    """operation() が返す操作"""
    speed: float              # 前進速度 [m/s]
    depth: Optional[float]    # 目標切削深さ [m]（元の地面基準）。None なら排土板を上げる
    yaw_rate: float = 0.0     # 旋回の角速度 [rad/s]。正で左旋回（反時計回り）


class Episode(ABC):
    # ---- サブクラスで設定する ----
    name: str = ""
    description: str = ""
    # 土質パラメータを乱数で決めるときの範囲（SoilParams のフィールド名 → (下限, 上限)）
    SOIL_RANGES: Dict[str, Tuple[float, float]] = {
        "cohesion": (0.0, 20000.0),
        "friction_angle_deg": (25.0, 45.0),
        "density": (1300.0, 1900.0),   # Maximum Density（2000）を超えないこと
    }
    REQUIRES_GRID_CONTROL = False   # terrain_ops で締固めを操作するなら True
    MAX_DISTANCE = 10.0             # 走行距離 [m]
    TIMEOUT = 60.0                  # 走行時間の上限 [s]

    def __init__(self, seed: int, soil: Optional[SoilParams] = None):
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.soil = soil if soil is not None else self.sample_soil(self.rng)
        self.params = self.sample_params(self.rng)

    # ---- 土質パラメータ ----
    @classmethod
    def sample_soil(cls, rng: np.random.Generator) -> SoilParams:
        return SoilParams(**{k: float(rng.uniform(lo, hi)) for k, (lo, hi) in cls.SOIL_RANGES.items()})

    # ---- 操作のパラメータ（深さ・速度など）----
    def sample_params(self, rng: np.random.Generator) -> dict:
        return {}

    # ---- 地形データ ----
    def terrain_ops(self) -> List[TerrainOp]:
        return []

    # ---- 操作 ----
    @abstractmethod
    def operation(self, obs: Observation) -> Command:
        pass

    def is_done(self, obs: Observation) -> bool:
        return obs.distance >= self.MAX_DISTANCE or obs.t >= self.TIMEOUT

    # ---- 記録用 ----
    def metadata(self) -> dict:
        d = {"episode_name": self.name, "seed": self.seed}
        d.update({f"soil_{k}": v for k, v in asdict(self.soil).items()})
        d.update({f"param_{k}": v for k, v in self.params.items()})
        d["n_terrain_ops"] = len(self.terrain_ops())
        return d
