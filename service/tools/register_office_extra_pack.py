"""Add reviewed supplemental office knowledge sources."""
import argparse
import json
from pathlib import Path

from app import office_knowledge as office
from tools.register_office_pack import register as register_pack


def register(db_path=None, *, apply=False):
    return register_pack(
        db_path,
        apply=apply,
        base=office.EXTRA_BASE,
        collection='office-extra-20261025',
        name='서무 세부기준 · 개인정보 권리·기록·정보공개',
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(register(args.db, apply=args.apply), ensure_ascii=False, indent=2))
