"""A worker process for tests/test_worker_crash.py: processes one batch, and inside the reader for the file
whose content contains PAUSE_ON, touches the file named STARTED and sleeps, so the test can kill or freeze
the process right there.

    python -m tests.crash_worker <batch id>
"""

import asyncio
import os
import sys
import time
from pathlib import Path

from app.services import jobs
from app.services.extraction import pipeline

_real_extract = pipeline._extract


def _pausing_extract(content_type, data, kind=None):
    if os.environ["PAUSE_ON"].encode() in data:
        Path(os.environ["STARTED"]).touch()
        time.sleep(float(os.environ.get("PAUSE_SECONDS", "60")))
    return _real_extract(content_type, data, kind)


pipeline._extract = _pausing_extract

if __name__ == "__main__":
    print(asyncio.run(jobs._process_batch_job(sys.argv[1])), flush=True)
