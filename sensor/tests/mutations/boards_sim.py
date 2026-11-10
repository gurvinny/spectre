"""Simulator lock shared by step() and the API's send()."""
TARGET = "spectre/sim/generate.py"
TESTS = "tests/test_boards.py"

MUTATIONS = [
    ("send-skips-lock",
     "        with self.lock:\n            self.feed(self.sim.command(text))",
     "        if True:\n            self.feed(self.sim.command(text))",
     "test_send_waits_for_the_step_lock"),
    ("step-skips-lock",
     "    def step(self) -> None:\n        with self.lock:\n            self._step()",
     "    def step(self) -> None:\n        self._step()",
     "test_step_takes_the_lock"),
    ("boards-get-own-locks",
     "                                            pipeline, self.lock)",
     "                                            pipeline)",
     "test_send_waits_for_the_step_lock"),
]
SURVIVORS = {}
