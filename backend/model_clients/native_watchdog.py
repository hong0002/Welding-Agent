"""Parity supervisor deadlines; these do not alter the native SDK's timeouts/retries."""
from dataclasses import dataclass
import re
from threading import Lock
import time


@dataclass(frozen=True)
class WatchdogPolicy:
    setup: float = 60
    retrieval: float = 120
    model_stage: float = 240


class NativeWatchdog:
    def __init__(self, overall, policy=None, *, clock=time.monotonic):
        self.policy = policy or WatchdogPolicy()
        self.clock = clock
        self.lock = Lock()
        self.overall_deadline = clock() + overall
        self.stage_deadline = clock() + self.policy.setup
        self.stage = "setup"

    def output(self, line):
        # Exactly the parity reset points. RETRIEVED/artifacts/RESULT do not reset a deadline.
        if line.startswith("[RETRIEVE]"):
            stage, seconds = "retrieval", self.policy.retrieval
        elif line.startswith(("[GPT]", "[REFINE]")):
            camera = re.search(r"\bcamera=(B|F|L|R|S1|S2|S3|S4|T)\b", line)
            stage = "view_" + camera[1] if camera else "model_stage"
            seconds = self.policy.model_stage
        else:
            return
        with self.lock:
            self.stage, self.stage_deadline = stage, self.clock() + seconds

    def remaining(self):
        with self.lock:
            now = self.clock()
            total, stage = self.overall_deadline - now, self.stage_deadline - now
            return min(total, stage), "overall" if total <= stage else self.stage
