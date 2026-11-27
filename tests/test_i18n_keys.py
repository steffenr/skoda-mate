import json
import subprocess
import sys
from pathlib import Path

from skoda_mate import automation, features, messages

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "skoda_mate" / "static"


def backend_keys():
    return json.loads((STATIC / "i18n" / "keys.json").read_text(encoding="utf-8"))["backend"]


def test_the_backend_section_of_the_key_list_is_current():
    check = subprocess.run([sys.executable, str(ROOT / "scripts" / "i18n_backend.py"), "--check"], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr


def test_the_key_list_has_every_text_the_backend_sends_for_translation():
    keys = backend_keys()
    wanted = set(messages.TEMPLATES)
    wanted |= set(features.PART_REASONS.values()) | set(features.PART_LABELS.values())
    wanted |= {u[field] for u in features.UNAVAILABLE for field in ("title", "why")}
    wanted |= {d[field] for d in features.DERIVED for field in ("title", "how")}
    wanted |= {o[field] for o in features.OPERATIONS_CATALOGUE for field in ("label", "what")}
    wanted |= {label for label, fields in features.PART_FIELDS.values()} | {f[1] for _, fields in features.PART_FIELDS.values() for f in fields}
    wanted |= {group for group, _ in automation.EVENT_GROUPS}
    assert not sorted(wanted - set(keys))
    assert all(entry["files"] for entry in keys.values())


def test_every_catalog_has_every_backend_key():
    keys = set(backend_keys())
    for path in (STATIC / "i18n").glob("*.json"):
        if path.stem != "keys":
            assert not sorted(keys - set(json.loads(path.read_text(encoding="utf-8")))), path.name
