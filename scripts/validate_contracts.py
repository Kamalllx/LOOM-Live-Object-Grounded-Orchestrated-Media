"""Validate every fixture (or given files) against its contract schema."""
import json, sys, pathlib
from jsonschema import Draft7Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAIRS = {name: ROOT / "contracts" / f"{name}.schema.json" for name in
         ["concept-graph", "learner-profile", "candidate-cut", "verified-cut", "session-log"]}


def validate(kind, doc):
    schema = json.loads(PAIRS[kind].read_text())
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in Draft7Validator(schema).iter_errors(doc)]


def main():
    failed = False
    for kind in PAIRS:
        fixture = ROOT / "fixtures" / f"{kind}.sample.json"
        errors = validate(kind, json.loads(fixture.read_text()))
        print(("FAIL " if errors else "ok   ") + fixture.name)
        for e in errors:
            print("     ", e)
        failed |= bool(errors)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
