"""Writes the backend's keys into skoda_mate/static/i18n/keys.json (scripts/dom-smoke/i18n_extract.mjs writes the
frontend's): the message templates, and the tables whose texts the dashboard passes through t().

    python scripts/i18n_backend.py            rewrite the backend section
    python scripts/i18n_backend.py --check    exit 1 if it is stale
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skoda_mate import automation, commands, demo, features, messages, stats  # noqa: E402

KEYS_FILE = ROOT / "skoda_mate" / "static" / "i18n" / "keys.json"
# How a data part is doing, as the Capabilities and System pages print it.
PART_STATES = ("present", "missing", "unsupported", "disabled", "unavailable", "unknown")


def build() -> dict[str, dict]:
    keys: dict[str, set[str]] = {}

    def add(file: str, *texts: str) -> None:
        for text in texts:
            if text:
                keys.setdefault(str(text), set()).add(file)

    add("messages.py", *messages.TEMPLATES)
    add("features.py", *features.PART_LABELS.values(), *features.PART_REASONS.values(), *PART_STATES,
        features.NOT_SUPPORTED, features.NOT_KNOWN_YET)
    for entry in features.UNAVAILABLE:
        add("features.py", entry["title"], entry["why"])
    for entry in features.DERIVED:
        add("features.py", entry["title"], entry["how"])
    for operation in features.OPERATIONS_CATALOGUE:
        add("features.py", *(operation.get(field, "") for field in ("label", "what", "params", "mate")))
    for label, fields in features.PART_FIELDS.values():
        add("features.py", label, *(field[1] for field in fields))
    add("commands.py", *(spec["label"] for spec in commands.COMMANDS.values()))
    add("automation.py", *(group for group, _ in automation.EVENT_GROUPS))
    add("stats.py", stats.CAPACITY_NOTE)
    add("demo.py", *(error["description"] for error in demo.API_ERRORS))
    return {key: {"files": sorted(files)} for key, files in keys.items()}


def serialise(all_keys: dict) -> str:
    """The layout of i18n_lib.mjs: sections and keys sorted, one key per line."""
    sections = []
    for name in ("backend", "frontend"):
        entries = all_keys.get(name, {})
        lines = ",\n".join(f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(entries[k], ensure_ascii=False, separators=(',', ':'))}"
                           for k in sorted(entries))
        sections.append(f' "{name}": {{' + (f"\n{lines}\n " if lines else "") + "}")
    return "{\n" + ",\n".join(sections) + "\n}\n"


def main() -> int:
    current = json.loads(KEYS_FILE.read_text(encoding="utf-8")) if KEYS_FILE.exists() else {"backend": {}, "frontend": {}}
    fresh = build()
    if "--check" in sys.argv:
        old = current.get("backend", {})
        for word, found in (("new", fresh.keys() - old.keys()), ("gone", old.keys() - fresh.keys()),
                            ("changed", {k for k in fresh.keys() & old.keys() if fresh[k] != old[k]})):
            for key in sorted(found):
                print(f"{word}: {key}")
        if fresh != old:
            print("keys.json is stale: run python scripts/i18n_backend.py")
            return 1
        print(f"keys.json is current ({len(fresh)} backend keys)")
        return 0
    KEYS_FILE.write_text(serialise({**current, "backend": fresh}), encoding="utf-8")
    print(f"{len(fresh)} backend keys written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
