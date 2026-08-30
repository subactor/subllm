from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


class LocalAgentOptions:
    def __init__(self, **_kwargs):
        pass


class AgentOptions:
    def __init__(self, **_kwargs):
        pass


class _Run:
    def wait(self):
        time.sleep(60)


class _Session:
    def __enter__(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(os.environ["SUBLLM_TEST_CHILD_PID_FILE"]).write_text(str(child.pid), encoding="utf-8")
        return self

    def __exit__(self, *_args):
        return None

    def send(self, _prompt: str):
        return _Run()


class Agent:
    @staticmethod
    def create(_options):
        return _Session()
