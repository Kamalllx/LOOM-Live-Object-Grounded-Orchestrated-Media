"""Contract validation: every producer validates its output against /contracts before handing it on."""
import functools
import json

from jsonschema import Draft7Validator

from .config import CONTRACTS_DIR, FIXTURES_DIR

KINDS = ("concept-graph", "learner-profile", "candidate-cut", "verified-cut", "session-log")


class ContractError(ValueError):
    pass


@functools.lru_cache(maxsize=None)
def _validator(kind):
    return Draft7Validator(json.loads((CONTRACTS_DIR / f"{kind}.schema.json").read_text()))


def errors(kind, doc):
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in _validator(kind).iter_errors(doc)]


def validate(kind, doc):
    errs = errors(kind, doc)
    if errs:
        raise ContractError(f"{kind} violates contract: " + "; ".join(errs[:5]))
    return doc


def fixture(kind):
    return json.loads((FIXTURES_DIR / f"{kind}.sample.json").read_text())
