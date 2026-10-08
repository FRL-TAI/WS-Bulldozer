"""エピソードの一覧。specific/ 以下の Episode のサブクラスを自動で集める。"""
import importlib
import inspect
import pkgutil

from . import specific
from .episode import Command, Episode, Observation, SoilParams, TerrainOp

__all__ = ["Episode", "SoilParams", "TerrainOp", "Observation", "Command", "available_episodes"]


def available_episodes():
    """{エピソード名: クラス} を返す"""
    found = {}
    for info in pkgutil.iter_modules(specific.__path__):
        module = importlib.import_module(f"{specific.__name__}.{info.name}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, Episode) and cls is not Episode and cls.name:
                if cls.name in found and found[cls.name] is not cls:
                    raise ValueError(f"エピソード名が重複しています: {cls.name}")
                found[cls.name] = cls
    return dict(sorted(found.items()))
