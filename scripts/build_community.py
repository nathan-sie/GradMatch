"""Compile all pinned public tracker fields for preliminary exploration."""
import argparse
import json
from pathlib import Path

from gradmatch.community import COMMUNITY_FILE, compile_community
from gradmatch.directory import INDEX


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=COMMUNITY_FILE)
    args = parser.parse_args()
    index = json.loads(INDEX.read_text(encoding='utf-8'))
    document = compile_community(args.input.read_bytes(), index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Imported {len(document['rows'])} preliminary records; no official rules or recommendations changed.")


if __name__ == '__main__':
    main()
