import sys
from pathlib import Path

# Dynamically resolve and inject the local src/ directory into the import path
src_path = Path(__file__).resolve().parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from yt_download_enterprise.main import run

if __name__ == "__main__":
    run()
