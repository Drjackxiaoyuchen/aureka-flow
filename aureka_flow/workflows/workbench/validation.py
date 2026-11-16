"""Contract checks for plain JSON. No external schema package is needed."""

import json
import math
from pathlib import Path
import re


class ValidationError(ValueError):
    """Invalid input, with the offending field in the message."""


def fail(field, message):
    raise ValidationError(f"{field}: {message}")


def obj(value, field):
    if not isinstance(value, dict):
        fail(field, "expected an object")
    return value


def nonempty(value, field):
    if not isinstance(value, str) or not value.strip():
        fail(field, "expected a nonempty string")
    if value != value.strip():
        fail(field, "leading/trailing whitespace is not allowed")
    return value


def nullable_id(value, field):
    return None if value is None else nonempty(value, field)


def integer(value, field):
    if type(value) is not int or value < 0:
        fail(field, "expected a nonnegative integer (not boolean)")
    return value


def number(value, field):
    if type(value) not in (int, float):
        fail(field, "expected a finite number (not boolean)")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        fail(field, "expected a finite number")
    return value


def required(value, keys, field):
    for key in keys:
        if key not in value:
            fail(f"{field}.{key}", "required field is missing")


def finite_tree(value, field):
    """Reject non-finite numbers even in preserved, non-interpreted metadata."""
    if type(value) is float:
        number(value, field)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                fail(field, "object keys must be strings")
            finite_tree(item, f"{field}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            finite_tree(item, f"{field}[{index}]")
    elif value is not None and type(value) not in (int, str, bool):
        fail(field, "metadata must contain only JSON values")


def strings(value, field):
    if not isinstance(value, list):
        fail(field, "expected an array of strings")
    for index, item in enumerate(value):
        nonempty(item, f"{field}[{index}]")


def schema(document, name, field):
    obj(document, field)
    if document.get("schema_version") != name:
        fail(f"{field}.schema_version", f"expected {name!r}")
    value = document.get("samples")
    if not isinstance(value, list) or not value:
        fail(f"{field}.samples", "expected a nonempty array")
    finite_tree(document, field)
    return value


def unique_ids(samples, field):
    seen = set()
    for index, sample in enumerate(samples):
        prefix = f"{field}.samples[{index}]"
        obj(sample, prefix)
        sample_id = nonempty(sample.get("sample_id"), f"{prefix}.sample_id")
        if sample_id in seen:
            fail(f"{prefix}.sample_id", f"duplicate ID {sample_id!r}")
        seen.add(sample_id)
    return seen


def original_ranges(value, event_count, field):
    """Validate compressed zero-based original indices without expanding them."""
    if not isinstance(value, list):
        fail(field, "expected half-open event-index ranges")
    normalized = []
    count = 0
    for index, pair in enumerate(value):
        label = f"{field}[{index}]"
        if not isinstance(pair, list) or len(pair) != 2:
            fail(label, "expected [start_inclusive, end_exclusive]")
        low = integer(pair[0], label + ".start")
        high = integer(pair[1], label + ".end")
        if not low < high <= event_count:
            fail(label, "range must be nonempty and bounded by original event_count")
        if normalized and low < normalized[-1][1]:
            fail(label, "ranges must be sorted and nonoverlapping")
        if normalized and low == normalized[-1][1]:
            normalized[-1][1] = high
        else:
            normalized.append([low, high])
        count += high - low
    return normalized, count


def external_qc_selection(sample, events, selected, field):
    """Allow QC-only selection only when its full original-index receipt agrees."""
    processing = obj(sample["processing"], field + ".processing")
    mask = processing.get("external_qc_mask")
    if mask is None:
        return False
    prefix = field + ".processing.external_qc_mask"
    obj(mask, prefix)
    required(mask, ("method_attribution", "execution", "source_sha256", "original_event_count", "kept_event_count", "kept_original_event_ranges"), prefix)
    nonempty(mask["method_attribution"], prefix + ".method_attribution")
    if mask["execution"] != "external_not_executed_by_this_package":
        fail(prefix + ".execution", "expected explicit external-not-executed attribution")
    source = obj(sample.get("source"), field + ".source")
    digest = source.get("sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
        fail(field + ".source.sha256", "external QC receipt requires an input SHA-256")
    if mask["source_sha256"] != digest:
        fail(prefix + ".source_sha256", "must match the exact sample source SHA-256")
    if integer(mask["original_event_count"], prefix + ".original_event_count") != events:
        fail(prefix + ".original_event_count", "must match original event_count")
    kept = integer(mask["kept_event_count"], prefix + ".kept_event_count")
    mask_ranges, kept_from_ranges = original_ranges(mask["kept_original_event_ranges"], events, prefix + ".kept_original_event_ranges")
    if kept != kept_from_ranges:
        fail(prefix + ".kept_event_count", "must equal count of kept original indices")
    if processing.get("event_identity") != "zero_based_original_FCS_DATA_order" or processing.get("range_semantics") != "start_inclusive_end_exclusive":
        fail(field + ".processing", "external QC receipt requires explicit original event-index semantics")
    selected_ranges, selected_from_ranges = original_ranges(processing.get("selected_event_ranges"), events, field + ".processing.selected_event_ranges")
    if selected_from_ranges != selected:
        fail(field + ".selected_count", "must equal count of selected original indices")
    cursor = 0
    for low, high in selected_ranges:
        while cursor < len(mask_ranges) and mask_ranges[cursor][1] <= low:
            cursor += 1
        if cursor == len(mask_ranges) or low < mask_ranges[cursor][0] or high > mask_ranges[cursor][1]:
            fail(field + ".processing.selected_event_ranges", "selected indices must be a subset of external QC kept indices")
    stages = obj(processing.get("stage_counts"), field + ".processing.stage_counts")
    for name, expected in (("input", events), ("after_external_qc_mask", kept), ("after_supplied_rectangles", selected)):
        if integer(stages.get(name), field + ".processing.stage_counts." + name) != expected:
            fail(field + ".processing.stage_counts." + name, "does not match the event-index receipt")
    if sample["gate_status"] == "ungated":
        if selected != kept or selected_ranges != mask_ranges:
            fail(field + ".selected_count", "ungated QC-only selection must retain every externally kept event")
        if processing.get("selection") != "external_qc_mask_only" or processing.get("gates") != []:
            fail(field + ".processing", "ungated QC-only receipt must not claim fluorescence gates or all_events")
    elif processing.get("selection") != "external_qc_mask_intersected_with_supplied_rectangles":
        fail(field + ".processing.selection", "must declare the mask/rectangle intersection")
    return True


def measurements(document):
    samples = schema(document, "yeast-facs-measurements/v1", "measurements")
    if document.get("evidence_kind") not in ("synthetic", "user_data"):
        fail("measurements.evidence_kind", "expected synthetic or user_data")
    unique_ids(samples, "measurements")
    for index, sample in enumerate(samples):
        prefix = f"measurements.samples[{index}]"
        required(sample, ("event_count", "selected_count", "gate_status", "processing", "channels", "qc_flags"), prefix)
        events = integer(sample["event_count"], f"{prefix}.event_count")
        selected = integer(sample["selected_count"], f"{prefix}.selected_count")
        if selected > events:
            fail(f"{prefix}.selected_count", "cannot exceed event_count")
        if sample["gate_status"] not in ("ungated", "exploratory", "user_supplied_unvalidated"):
            fail(f"{prefix}.gate_status", "invalid gate status")
        has_external_qc = external_qc_selection(sample, events, selected, prefix)
        if sample["gate_status"] == "ungated" and selected != events and not has_external_qc:
            fail(f"{prefix}.selected_count", "ungated samples must retain all acquired events")
        obj(sample["processing"], f"{prefix}.processing")
        channels = obj(sample["channels"], f"{prefix}.channels")
        for detector, summary in channels.items():
            nonempty(detector, f"{prefix}.channels key")
            label = f"{prefix}.channels[{detector!r}]"
            obj(summary, label)
            required(summary, ("median", "finite_count"), label)
            finite = integer(summary["finite_count"], f"{label}.finite_count")
            if finite > selected:
                fail(f"{label}.finite_count", "cannot exceed selected_count")
            if finite == 0 and summary["median"] is not None:
                fail(f"{label}.median", "must be null when finite_count is zero")
            if finite > 0:
                number(summary["median"], f"{label}.median")
        strings(sample["qc_flags"], f"{prefix}.qc_flags")
        # A core producer must not expose a full input path in these fields.
        for key in ("input_basename", "source_basename"):
            if key in sample:
                basename = nonempty(sample[key], f"{prefix}.{key}")
                if "/" in basename or "\\" in basename or basename in (".", ".."):
                    fail(f"{prefix}.{key}", "expected a basename, not a path")
        if "source" in sample:
            source = obj(sample["source"], f"{prefix}.source")
            required(source, ("basename", "sha256"), f"{prefix}.source")
            basename = nonempty(source["basename"], f"{prefix}.source.basename")
            if "/" in basename or "\\" in basename or basename in (".", ".."):
                fail(f"{prefix}.source.basename", "expected a basename, not a path")
            digest = source["sha256"]
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None:
                fail(f"{prefix}.source.sha256", "expected a 64-character SHA-256 hex digest")
    return samples


MANIFEST_KEYS = {"sample_id", "condition", "biological_replicate", "batch_id", "plate", "well", "control_role", "concentration", "concentration_unit"}
MANIFEST_REQUIRED = MANIFEST_KEYS - {"concentration", "concentration_unit"}


def manifest(document):
    samples = schema(document, "yeast-facs-samples/v1", "manifest")
    extra_root = set(document) - {"schema_version", "samples", "evidence_kind", "description"}
    if extra_root:
        fail("manifest", f"unknown fields: {sorted(extra_root)!r}")
    if "evidence_kind" in document and document["evidence_kind"] not in ("synthetic", "user_data"):
        fail("manifest.evidence_kind", "expected synthetic or user_data")
    unique_ids(samples, "manifest")
    for index, sample in enumerate(samples):
        prefix = f"manifest.samples[{index}]"
        required(sample, sorted(MANIFEST_REQUIRED), prefix)
        extra = set(sample) - MANIFEST_KEYS
        if extra:
            fail(prefix, f"unknown fields: {sorted(extra)!r}")
        nonempty(sample["condition"], f"{prefix}.condition")
        for key in ("biological_replicate", "batch_id", "plate", "well"):
            nullable_id(sample[key], f"{prefix}.{key}")
        if sample["control_role"] not in ("negative", "positive", "sample", "reference"):
            fail(f"{prefix}.control_role", "expected negative, positive, sample or reference")
        if ("concentration" in sample) != ("concentration_unit" in sample):
            fail(prefix, "concentration and concentration_unit must be supplied together")
        if "concentration" in sample:
            if number(sample["concentration"], f"{prefix}.concentration") < 0:
                fail(f"{prefix}.concentration", "cannot be negative")
            nonempty(sample["concentration_unit"], f"{prefix}.concentration_unit")
    return samples


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail(f"JSON.{key}", "duplicate object key")
        result[key] = value
    return result


def _constant(value):
    fail("JSON", f"non-finite numeric token {value!r}")


def read_json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_pairs, parse_constant=_constant)
    except (OSError, UnicodeError, ValueError) as error:
        raise ValidationError(f"input JSON: {error}") from error
