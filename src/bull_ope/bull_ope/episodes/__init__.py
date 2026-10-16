"""エピソードの一覧。episodes/ 以下の Episode のサブクラスを自動で集める。"""
import importlib
import inspect
import pkgutil

from .episode import Command, Episode, Observation, SoilParams, TerrainOp

__all__ = ["Episode", "SoilParams", "TerrainOp", "Observation", "Command", "available_episodes"]


def episode_group(cls):
    """エピソードのグループ（dataset / sandbox / validation）をモジュールの場所から求める"""
    root = __name__ + "."                                # "bull_ope.episodes."
    return cls.__module__[len(root):].split(".")[0]      # "dataset"、"sandbox"、"validation"


def available_episodes(group=None):
    """{エピソード名: クラス} を返す。group を指定すると、そのフォルダのものだけ"""
    found = {}
    for info in pkgutil.walk_packages(__path__, prefix=__name__ + "."):
        module = importlib.import_module(info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (issubclass(cls, Episode) and cls.name and not inspect.isabstract(cls)
                    and cls.__module__ == module.__name__):
                if group is not None and episode_group(cls) != group:
                    continue
                if cls.name in found and found[cls.name] is not cls:
                    raise ValueError(f"エピソード名が重複しています: {cls.name}")
                found[cls.name] = cls
    return dict(sorted(found.items()))
