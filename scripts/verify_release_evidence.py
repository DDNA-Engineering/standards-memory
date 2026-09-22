from __future__ import annotations

import sys

from release_evidence import main


if __name__ == "__main__":
    raise SystemExit(main(["verify", *sys.argv[1:]]))
