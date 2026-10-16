from ..episode import Command, Episode


class FlatConstantDepth(Episode):
    name = "flat_constant"
    description = "平らな地形を、一定の切削深さ・一定の速度で直進する"

    def sample_params(self, rng):
        return {
            "depth": float(rng.uniform(0.03, 0.12)),   # m
            "speed": float(rng.uniform(0.3, 1.0)),     # m/s
        }

    def operation(self, obs):
        return Command(speed=self.params["speed"], depth=self.params["depth"])
