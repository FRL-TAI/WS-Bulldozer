"""
【実験B3】締固めの範囲（幅方向・深さ方向）と程度を変えた帯を、一定の深さで横切って削るエピソード

ex_compaction_bands（実験B1）と同じく、地山の帯と締固めの帯を交互に並べ（地山 → A → 地山 → B → 地山）、
一定の深さ・速さで削る。締固めは地形の加工で設定するので、地面の高さは変わらない（沈下しない）。

エピソードは2つ。どちらもシードで A・B の組み合わせ（とその順番）を切り替える。

  ex_compaction_patterns（締固めの範囲を変える。B1 と B2 の違いの原因を切り分ける）
      seed % 8 = 0: 全幅      → 履帯2本      4: 履帯2本  → 中央
                 1: 履帯2本   → 全幅          5: 中央     → 履帯2本
                 2: 中央      → 全幅・浅い    6: 全幅     → 全幅・浅い
                 3: 全幅・浅い → 中央          7: 全幅・浅い → 全幅
      全幅：排土板の幅全体（|y| ≤ 2.0 m）、深さ 0.8 m
      履帯2本：左右の履帯の位置（|y| = 0.56〜1.16 m）、深さ 0.8 m
      中央：排土板の中央（|y| ≤ 0.6 m。履帯2本と同じ面積）、深さ 0.8 m
      全幅・浅い：排土板の幅全体、深さ 0.3 m
      締固めの程度はすべて 1.16（実験A で履帯で踏み固めた地表の値）

  ex_compaction_levels（締固めの程度を増やす。履帯で踏んだときの追加の沈下と、締固めの程度の関係を作る）
      seed % 4 = 0: 1.04 → 1.12     2: 0.90 → 1.20
                 1: 1.12 → 1.04     3: 1.20 → 0.90
      すべて全幅・深さ 0.8 m。ex_compaction_bands の 0.78（緩み）・1.08・1.16 と合わせて使う

y はエピソード座標の左方（開始時の刃先の中点が原点）。排土板は機体の左右の中央にあるとし、
履帯の中心線は CompactionProbe の記録から ±0.86 m とした。

解析：
  check_cut_bands.py      ：帯ごとの切削抵抗（bands() の4番目の要素を帯の名前として使う）
  check_track_settlement.py：CompactionProbe の記録から、削った後の地面を履帯が踏んだときの追加の沈下

名前が "ex_compaction" で始まるので、Unity 側の CompactionProbe も記録する。AGX_GRID_CONTROL が必要。
"""
from ..episode import Command, Episode, TerrainOp

SOIL = {"cohesion": 2100.0, "friction_angle_deg": 39.98, "density": 1474.0}
DEFAULT_SWELL = 1.28

FULL, TRACKS, CENTER = "full", "tracks", "center"
LATERAL_NAME = {FULL: "全幅", TRACKS: "履帯2本", CENTER: "中央"}


def spec(value, lateral=FULL, depth=0.8):
    """締固めの帯の指定（締固めの程度、幅方向の範囲、深さ [m]）"""
    return {"value": value, "lateral": lateral, "depth": depth}


class _CompactionBandsBase(Episode):
    """地山 → A → 地山 → B → 地山 の帯を一定の深さで削るエピソードの共通部分（name が空なので一覧には出ない）"""
    SOIL_RANGES = {k: (v, v) for k, v in SOIL.items()}
    REQUIRES_GRID_CONTROL = True
    RECORD_COMPACTION = True

    BAND_START = 1.0        # 最初の帯の始まり [m]（刃先の開始位置から）
    BAND_LENGTH = 2.0       # 帯の長さ [m]
    FULL_HALF_WIDTH = 2.0   # 全幅の帯の左右の幅の半分 [m]（排土板の幅 2.96 m より広く）
    TRACK_CENTER = 0.86     # 履帯の中心線の位置 [m]（左右対称）
    TRACK_WIDTH = 0.6       # 履帯の幅 [m]
    DEPTH = 0.08            # 切削深さ [m]
    SPEED = 0.5             # 前進の速さ [m/s]
    MAX_DISTANCE = 13.5     # 走行距離 [m]。刃先は機体の約 2.8 m 前、履帯の後端は約 1.1 m 後ろにあるので、
                            # 最後の締固めの帯（刃先の座標で 9 m まで）の上を履帯が通り切るには約 13 m 必要

    VARIANTS = []           # [(A の指定, B の指定), ...]。サブクラスで決める

    def sample_params(self, rng):
        v = int(self.seed % len(self.VARIANTS))
        a, b = self.VARIANTS[v]
        return {"variant": v, "band_a": self.label(a), "band_b": self.label(b),
                "depth": self.DEPTH, "speed": self.SPEED}

    # ---- 帯の指定 ----
    def specs(self):
        """5本の帯の指定（地山は None）"""
        a, b = self.VARIANTS[self.params["variant"]]
        return [None, a, None, b, None]

    def value_of(self, s):
        if s["value"] == "loose":
            return 1.0 / (self.soil.swell_factor or DEFAULT_SWELL)
        return float(s["value"])

    def label(self, s):
        if s is None:
            return "地山"
        v = self.value_of(s) if s["value"] != "loose" else 1.0 / DEFAULT_SWELL
        return f"{LATERAL_NAME[s['lateral']]} {v:.2f} 深{s['depth']:.1f}m"

    def lateral_ranges(self, lateral):
        """幅方向の範囲 [(y_min, y_max)]（左方が正）"""
        if lateral == FULL:
            return [(-self.FULL_HALF_WIDTH, self.FULL_HALF_WIDTH)]
        if lateral == TRACKS:
            lo, hi = self.TRACK_CENTER - 0.5 * self.TRACK_WIDTH, self.TRACK_CENTER + 0.5 * self.TRACK_WIDTH
            return [(lo, hi), (-hi, -lo)]
        if lateral == CENTER:
            return [(-self.TRACK_WIDTH, self.TRACK_WIDTH)]   # 幅 1.2 m（履帯2本と同じ面積）
        raise ValueError(f"不明な幅方向の範囲: {lateral}")

    # ---- 地形データ ----
    def terrain_ops(self):
        ops = []
        for i, s in enumerate(self.specs()):
            if s is None:
                continue
            x0 = self.BAND_START + i * self.BAND_LENGTH
            for y0, y1 in self.lateral_ranges(s["lateral"]):
                ops.append(TerrainOp("compaction_rect", x0, x0 + self.BAND_LENGTH, y0, y1,
                                     value=self.value_of(s), depth=s["depth"]))
        return ops

    def bands(self):
        """解析用：[(開始, 終わり, 締固めの程度, 帯の名前)]。地山の帯は締固めの程度 1.0"""
        out = []
        for i, s in enumerate(self.specs()):
            x0 = self.BAND_START + i * self.BAND_LENGTH
            out.append((x0, x0 + self.BAND_LENGTH, 1.0 if s is None else self.value_of(s), self.label(s)))
        return out

    # ---- 操作 ----
    def operation(self, obs):
        return Command(speed=self.SPEED, depth=self.DEPTH)


class CompactionPatterns(_CompactionBandsBase):
    name = "ex_compaction_patterns"
    description = "【実験B3】締固めの範囲（全幅・履帯2本・中央・浅い）を変えた帯を一定の深さで削る"
    _FULL = spec(1.16, FULL, 0.8)
    _TRACKS = spec(1.16, TRACKS, 0.8)
    _CENTER = spec(1.16, CENTER, 0.8)
    _SHALLOW = spec(1.16, FULL, 0.3)
    VARIANTS = [
        (_FULL, _TRACKS), (_TRACKS, _FULL),
        (_CENTER, _SHALLOW), (_SHALLOW, _CENTER),
        (_TRACKS, _CENTER), (_CENTER, _TRACKS),
        (_FULL, _SHALLOW), (_SHALLOW, _FULL),
    ]


class CompactionLevels(_CompactionBandsBase):
    name = "ex_compaction_levels"
    description = "【実験B3】締固めの程度（0.90・1.04・1.12・1.20）を変えた全幅の帯を一定の深さで削る"
    VARIANTS = [
        (spec(1.04), spec(1.12)), (spec(1.12), spec(1.04)),
        (spec(0.90), spec(1.20)), (spec(1.20), spec(0.90)),
    ]