"""Load either a SciencePal export or a normalized local team library."""

import json

from . import reaction_profiles, schema_v2
from .comparison import pair_state
from .rules import ValidationError, validate
from .sciencepal import import_sciencepal_bytes


def _local_match(record, records):
    """Match the pinned local library, which only contains Suzuki precedent rows.

    Matching is done on the engine-facing projection, i.e. only when the record
    is in the Suzuki profile; an out-of-profile reaction never claims a
    substrate-pair hit from a Suzuki library.
    """
    view = reaction_profiles.legacy_view(record)
    if view is None:
        return []
    substrates = view["reaction"]["substrates"]
    return [item for item in records
            if pair_state(substrates, (item.get("reaction") or {}).get("substrates")) == "same"]


def load_sources(text, experiment):
    if not isinstance(text, str):
        raise ValidationError("sciencepal_text", "expected original JSON text")
    if not text.strip():
        return [], {"mode": "provided_records", "input_record_count": 0, "record_count": 0, "live_retrieval_performed": False}
    record = validate(experiment, [])
    parsed = json.loads(text.lstrip("\ufeff"))
    if isinstance(parsed, dict) and parsed.get("schema_version") == "chemcritic.precedents.v0.1":
        records = parsed.get("records")
        validate(record, records)
        in_scope = reaction_profiles.scope(record)["in_scope"]
        matched = _local_match(record, records)
        retrieval = {"mode": "local_library_exact_pair" if in_scope else "local_library_out_of_engine_scope",
                     "input_record_count": len(records), "record_count": len(matched),
                     "no_match": not matched, "live_retrieval_performed": False,
                     "engine_scope": in_scope}
        return matched, retrieval
    records = import_sciencepal_bytes(text.encode("utf-8"))
    return records, {"mode": "sciencepal_file_import", "input_record_count": len(records),
                     "record_count": len(records), "live_retrieval_performed": False}
