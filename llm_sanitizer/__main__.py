"""`python3 -m llm_sanitizer` 入口:委托给 CLI。"""

import sys

from llm_sanitizer.cli import main

if __name__ == "__main__":
    sys.exit(main())
