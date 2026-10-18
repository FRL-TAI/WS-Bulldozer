from ...episode import Command
from ..base import ValidationEpisode


class ValidationConstantDepth(ValidationEpisode):
    """一定の深さ・一定の速度で削りながら直進する。

    確かめること：前後の力の符号（負になるか）、確認用ウィンドウとの大きさの一致、
    深さの追従、削っている間 ground_below ≒ edge_z になるか。再現性の確認（段階5）にも使う
    """
    name = "val_constant_depth"
    description = "【検証】深さ 6 cm・速度 0.5 m/s で 10 m 削る"
    DEPTH = 0.06             # m
    SPEED = 0.5              # m/s
    MAX_DISTANCE = 10.0      # m
    PARAM_NAMES = ("DEPTH", "SPEED", "MAX_DISTANCE")

    def operation(self, obs):
        return Command(speed=self.SPEED, depth=self.DEPTH)


class ValidationConstantDepth3(ValidationConstantDepth):
    """val_constant_depth の深さを 3 cm にしたもの（関門5：深さと力の関係）"""
    name = "val_constant_depth_3cm"
    description = "【検証】深さ 3 cm・速度 0.5 m/s で 10 m 削る"
    DEPTH = 0.03


class ValidationConstantDepth9(ValidationConstantDepth):
    """val_constant_depth の深さを 9 cm にしたもの（関門5：深さと力の関係）"""
    name = "val_constant_depth_9cm"
    description = "【検証】深さ 9 cm・速度 0.5 m/s で 10 m 削る"
    DEPTH = 0.09


class ValidationConstantDepth12(ValidationConstantDepth):
    """val_constant_depth の深さを 12 cm にしたもの（関門5：深さと力の関係）"""
    name = "val_constant_depth_12cm"
    description = "【検証】深さ 12 cm・速度 0.5 m/s で 10 m 削る"
    DEPTH = 0.12