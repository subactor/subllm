from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path(os.environ["SUBLLM_TEST_CHILD_PID_FILE"]).write_text(str(child.pid), encoding="utf-8")
time.sleep(60)
