"""
JSON に書き込む前に、NumPy の型などを Python の普通の型に変換する
"""
import dataclasses
import math

import numpy as np


def to_jsonable(obj):
    """dict・list の中まで再帰的にたどって、JSON にできる型に変換する。

    - np.int64 など        → int
    - np.float64 など      → float(NaN・無限大は None)
    - np.bool_             → bool
    - np.ndarray           → list
    - dataclass            → dict
    - それ以外の未知の型    → 文字列（記録が止まるのを防ぐため）
    """
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return to_jsonable(dataclasses.asdict(obj))
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if obj is None or isinstance(obj, (int, str)):
        return obj
    return str(obj)