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
    # __path__ と __name__ はこのパッケージ（episodes）自身のもの。サブフォルダも含めてすべて探す
    for info in pkgutil.walk_packages(__path__, prefix=__name__ + "."):
        module = importlib.import_module(info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (issubclass(cls, Episode) and cls.name and not inspect.isabstract(cls)
                    and cls.__module__ == module.__name__):   # import しただけのクラスは数えない
                if cls.name in found and found[cls.name] is not cls:
                    raise ValueError(f"エピソード名が重複しています: {cls.name}")
                found[cls.name] = cls
    return dict(sorted(found.items()))
