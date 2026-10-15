"""【土質】5つの土質パラメータをすべて乱数で決める（collect_data ではラテン超方格法になる）。"""
from ..episode import Command, Episode


class ExSoilRandomAll(Episode):
    name = "ex_soil_random_all"
    description = "【土質】5つの土質パラメータをすべて範囲内の乱数で決めて 10 m 削る"
    SOIL_RANGES = {
        "cohesion": (0.0, 30000.0),
        "friction_angle_deg": (20.0, 45.0),
        "density": (1200.0, 1900.0),
        "swell_factor": (1.05, 1.40),
        "youngs_modulus": (2.0e6, 1.0e7),
    }

    def sample_params(self, rng):
        return {"depth": float(rng.uniform(0.03, 0.10)), "speed": float(rng.uniform(0.3, 1.0))}

    def operation(self, obs):
        return Command(speed=self.params["speed"], depth=self.params["depth"])
