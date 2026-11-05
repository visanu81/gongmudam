"""Read one uploaded file for personal details in its own process.

Reading a large document on the 1 GB shared server left memory behind in the
service process until it was killed (2026-11-05). A short-lived process returns
all of it on exit, and if it runs out of memory only this file fails.

usage: python -X utf8 -m app.public_scan <path>  (prints the kinds found as JSON)
"""
import json
import sys
from pathlib import Path

from . import project_text, public_privacy


def main(path):
    units = project_text.extract(Path(path)).get('units') or []
    print(json.dumps(list(public_privacy.found('\n'.join(u['text'] for u in units))), ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])
