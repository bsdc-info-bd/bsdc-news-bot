"""bsdc news — entry point used by GitHub Actions (`python main.py`).

All logic lives in the ``bsdc_news`` package; see README.md.
Examples:
    python main.py                 # scheduled run
    python main.py --dry-run       # test everything without publishing
    python main.py doctor          # diagnose secrets and APIs
"""

import sys

from bsdc_news.cli import main

if __name__ == "__main__":
    sys.exit(main())
