"""Original measurement adapter; no upstream cytometry implementation is vendored."""

from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import re

SCHEMA = "yeast-facs-measurements/v1"
CONFIG_SCHEMA = "yeast-facs-analysis-config/v1"


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: expected nonempty string")
    return value


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field}: expected finite number")
    return value


def _keys(obj, required, optional, field):
    if not isinstance(obj, dict):
        raise ValueError(f"{field}: expected object")
    missing = set(required) - obj.keys()
    extra = obj.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f"{field}: missing {sorted(missing)}, unknown {sorted(extra)}")


def validate_config(config):
    """Reject misspelled/ambiguous settings instead of silently applying defaults."""
    _keys(config, ("schema_version", "sample_id", "evidence_kind", "channels", "compensation"),
          ("rectangle_gates",), "config")
    if config["schema_version"] != CONFIG_SCHEMA:
        raise ValueError("config.schema_version: unsupported version")
    _text(config["sample_id"], "config.sample_id")
    if config["evidence_kind"] not in ("synthetic", "user_data"):
        raise ValueError("config.evidence_kind: expected synthetic or user_data")
    channels = config["channels"]
    if not isinstance(channels, list) or not channels:
        raise ValueError("config.channels: expected nonempty list")
    for channel in channels:
        _text(channel, "config.channels[]")
    if len(set(channels)) != len(channels):
        raise ValueError("config.channels: duplicate detector")
    comp = config["compensation"]
    _keys(comp, ("state", "reason"), (), "config.compensation")
    if comp["state"] not in ("uncompensated", "embedded", "already_compensated"):
        raise ValueError("config.compensation.state: expected uncompensated, embedded or already_compensated")
    _text(comp["reason"], "config.compensation.reason")
    if "rectangle_gates" not in config:
        return config
    gates = config["rectangle_gates"]
    if not isinstance(gates, list) or not gates:
        raise ValueError("config.rectangle_gates: omit for ungated; supplied list must not be empty")
    ids = set()
    for i, gate in enumerate(gates):
        field = f"config.rectangle_gates[{i}]"
        _keys(gate, ("gate_id", "scope", "reference_status", "bounds"), (), field)
        gid = _text(gate["gate_id"], field + ".gate_id")
        if gid in ids:
            raise ValueError(field + ".gate_id: duplicate")
        ids.add(gid)
        if gate["scope"] not in ("exploratory", "user_supplied_unvalidated"):
            raise ValueError(field + ".scope: only exploratory or user_supplied_unvalidated supported")
        _text(gate["reference_status"], field + ".reference_status")
        bounds = gate["bounds"]
        if not isinstance(bounds, dict) or not bounds:
            raise ValueError(field + ".bounds: expected nonempty object")
        for channel, limits in bounds.items():
            if channel not in channels:
                raise ValueError(field + f".bounds.{channel}: must be in config.channels")
            if channel.lower().startswith(("fsc", "ssc")) or channel.lower() == "time":
                raise ValueError(field + f".bounds.{channel}: only supplied fluorescence rectangles supported")
            _keys(limits, ("min", "max"), (), field + f".bounds.{channel}")
            low, high = limits["min"], limits["max"]
            if low is None and high is None:
                raise ValueError(field + f".bounds.{channel}: at least one finite boundary required")
            if low is not None:
                _number(low, field + f".bounds.{channel}.min")
            if high is not None:
                _number(high, field + f".bounds.{channel}.max")
            if low is not None and high is not None and low >= high:
                raise ValueError(field + f".bounds.{channel}: min must be less than max")
    return config


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_text(segment):
    # Some real FCS exports include ASCII-space padding inside the declared
    # TEXT offsets. Accept only this bounded compatibility case after the final
    # delimiter; do not strip value whitespace or arbitrary trailing bytes.
    if segment and segment[:1] != b" " and segment[0] != segment[-1]:
        unpadded = segment.rstrip(b" ")
        if unpadded.endswith(segment[:1]):
            segment = unpadded
    if not segment or segment[0] != segment[-1]:
        raise ValueError("FCS TEXT: missing matching delimiter")
    delim = segment[:1]
    tokens, buf, i = [], bytearray(), 1
    while i < len(segment):
        char = segment[i:i + 1]
        if char == delim:
            if i + 1 < len(segment) and segment[i + 1:i + 2] == delim:
                buf.extend(delim)
                i += 2
                continue
            tokens.append(buf.decode("latin-1"))
            buf.clear()
        else:
            buf.extend(char)
        i += 1
    if buf or len(tokens) % 2:
        raise ValueError("FCS TEXT: malformed key/value pairs")
    metadata = {}
    for key, value in zip(tokens[::2], tokens[1::2]):
        normalized = key.lstrip("$").lower()
        if not normalized or normalized in metadata:
            raise ValueError("FCS TEXT: empty or duplicate metadata key")
        metadata[normalized] = value
    return metadata


def _read_header(path):
    path = Path(path)
    with path.open("rb") as handle:
        header = handle.read(58)
        if len(header) != 58 or header[:6] not in (b"FCS2.0", b"FCS3.0", b"FCS3.1"):
            raise ValueError("FCS HEADER: unsupported version or truncated 58-byte header")
        try:
            begin, end = int(header[10:18]), int(header[18:26])
        except ValueError as exc:
            raise ValueError("FCS HEADER: malformed TEXT offsets") from exc
        if begin < 58 or end < begin or end >= path.stat().st_size or end - begin + 1 > 16 * 1024 * 1024:
            raise ValueError("FCS HEADER: invalid/out-of-file/oversize TEXT offsets (16 MiB limit)")
        handle.seek(begin)
        metadata = _parse_text(handle.read(end - begin + 1))
    for field in ("tot", "par"):
        if not re.fullmatch(r"\d+", metadata.get(field, "")):
            raise ValueError(f"FCS TEXT ${field.upper()}: expected nonnegative integer")
    if not 1 <= int(metadata["par"]) <= 4096:
        raise ValueError("FCS TEXT $PAR: must be between 1 and 4096")
    labels = [metadata.get(f"p{i}n") for i in range(1, int(metadata["par"]) + 1)]
    if any(not label for label in labels) or len(set(labels)) != len(labels):
        raise ValueError("FCS TEXT $PnN: missing or duplicate detector names")
    return header[:6].decode(), metadata


def inspect_fcs(path):
    """Read bounded HEADER/TEXT and file hash, not event DATA. Export a whitelist."""
    version, meta = _read_header(path)
    channels = []
    for i in range(1, int(meta["par"]) + 1):
        channels.append({"number": i, "detector": meta[f"p{i}n"],
                         "range": meta.get(f"p{i}r"), "gain": meta.get(f"p{i}g"),
                         "amplification": meta.get(f"p{i}e"), "voltage": meta.get(f"p{i}v")})
    return {"schema_version": "yeast-facs-inspection/v1", "inspection_scope": "HEADER_TEXT_only_not_event_validation",
            "source": {"basename": Path(path).name, "sha256": sha256_file(path)},
            "fcs_version": version, "event_count_declared": int(meta["tot"]),
            "data_type": meta.get("datatype"), "mode": meta.get("mode"), "channels": channels,
            "acquisition": {k: meta.get(k) for k in ("date", "btim", "etim", "timestep")},
            "embedded_spillover_present": any(meta.get(k) for k in ("spillover", "spill"))}


def _seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?", value):
        raise ValueError("expected HH:MM:SS[.fraction]")
    hour, minute, second = map(float, value.split(":"))
    if hour >= 24 or minute >= 60 or second >= 60:
        raise ValueError("invalid clock component")
    return hour * 3600 + minute * 60 + second


def time_qc(values, metadata, *, preprocessed):
    """Compare Time span with clock span. No automatic event exclusion or repair."""
    flags, detail = [], {"scope": "all_input_events", "event_exclusion": "none"}
    if values is None:
        return ["time_channel_missing"], detail
    finite = [float(v) for v in values if math.isfinite(v)]
    if len(finite) != len(values):
        flags.append("time_nonfinite_values")
    if not finite:
        return flags + ["time_no_finite_values"], detail
    backwards = sum(1 for a, b in zip(values, values[1:]) if math.isfinite(a) and math.isfinite(b) and b < a)
    detail["backward_steps"] = backwards
    if backwards:
        flags.append("time_backward_steps")
    try:
        step = float(metadata["timestep"])
        if not math.isfinite(step) or step <= 0:
            raise ValueError("invalid timestep")
    except (KeyError, ValueError, TypeError):
        flags.append("time_timestep_missing_or_invalid")
        step = None
    span = max(finite) - min(finite)
    if not math.isfinite(span):
        raise ValueError("Time observed span: finite numeric range exceeded")
    detail["observed_span"] = span
    detail["time_values_preprocessed"] = preprocessed
    # FlowKit preprocess=True applies $TIMESTEP once; do not apply it twice.
    span_seconds = span if preprocessed and step is not None else (span * step if step is not None else None)
    if span_seconds is not None and not math.isfinite(span_seconds):
        raise ValueError("Time scaled span: finite numeric range exceeded")
    detail["time_span_seconds"] = span_seconds
    try:
        elapsed = _seconds(metadata.get("etim")) - _seconds(metadata.get("btim"))
        if elapsed < 0:
            elapsed += 86400
            flags.append("time_clock_midnight_wrap_assumed")
        detail["clock_span_seconds"] = elapsed
        if elapsed == 0:
            flags.append("time_clock_zero_span")
        elif span_seconds is not None and abs(span_seconds - elapsed) > max(1.0, elapsed * 0.05):
            flags.append("time_scale_clock_mismatch")
    except (ValueError, TypeError):
        flags.append("time_clock_metadata_missing_or_invalid")
    return flags, detail


def _ranges(indices):
    result = []
    for i in indices:
        if result and result[-1][1] == i:
            result[-1][1] += 1
        else:
            result.append([i, i + 1])
    return result


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    low, high = ordered[middle - 1], ordered[middle]
    # Same-sign midpoint avoids overflow without underflowing identical subnormals.
    return low + (high - low) / 2 if (low >= 0) == (high >= 0) else low / 2 + high / 2


def validate_qc_mask(mask, *, source_sha256, event_count):
    """Validate an externally supplied mask; this does not execute its named method."""
    _keys(mask, ("schema_version", "source_sha256", "event_count", "kept_original_event_indices", "method"), (), "qc_mask")
    if mask["schema_version"] != "yeast-facs-qc-mask/v1":
        raise ValueError("qc_mask.schema_version: unsupported version")
    if mask["source_sha256"] != source_sha256:
        raise ValueError("qc_mask.source_sha256: does not match the exact input file")
    if isinstance(mask["event_count"], bool) or not isinstance(mask["event_count"], int) or mask["event_count"] != event_count:
        raise ValueError("qc_mask.event_count: must equal the decoded original event count")
    _text(mask["method"], "qc_mask.method")
    indices = mask["kept_original_event_indices"]
    if not isinstance(indices, list):
        raise ValueError("qc_mask.kept_original_event_indices: expected list")
    for index in indices:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < event_count:
            raise ValueError("qc_mask.kept_original_event_indices: expected bounded, zero-based original integer indices")
    if len(set(indices)) != len(indices):
        raise ValueError("qc_mask.kept_original_event_indices: duplicate index")
    return set(indices)


def summarize_events(events, detectors, config, *, source, metadata=None,
                     time_preprocessed=False, engine="stdlib_synthetic", compensation_applied=False, qc_mask=None):
    """Summarize selected detector values, retaining negative and finite-count evidence."""
    validate_config(config)
    if not isinstance(detectors, (list, tuple)) or not detectors or any(not isinstance(d, str) or not d for d in detectors) or len(set(detectors)) != len(detectors):
        raise ValueError("detectors: expected unique ordered names")
    if any(channel not in detectors for channel in config["channels"]):
        raise ValueError("config.channels: requested detector is missing from event data")
    if config["compensation"]["state"] == "embedded" and not compensation_applied:
        raise ValueError("compensation: embedded processing requested but not applied")
    _keys(source, ("basename", "sha256"), (), "source")
    if not isinstance(source["basename"], str) or not source["basename"] or any(s in source["basename"] for s in ("/", "\\")) or source["basename"] in (".", ".."):
        raise ValueError("source.basename: filename only, not a path")
    if not isinstance(source["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"]):
        raise ValueError("source.sha256: expected lowercase SHA-256 hex")
    qc_kept = None if qc_mask is None else validate_qc_mask(qc_mask, source_sha256=source["sha256"], event_count=len(events))
    gates = config.get("rectangle_gates", [])
    positions = {channel: detectors.index(channel) for channel in config["channels"]}
    gate_status = "ungated" if not gates else ("exploratory" if all(g["scope"] == "exploratory" for g in gates) else "user_supplied_unvalidated")
    selected, values = [], {channel: [] for channel in config["channels"]}
    nonfinite_input = {channel: 0 for channel in config["channels"]}
    for index, row in enumerate(events):
        if len(row) != len(detectors):
            raise ValueError(f"events[{index}]: detector count mismatch")
        for value in row:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"events[{index}]: expected numeric measurement, not boolean/string")
        for channel, pos in positions.items():
            nonfinite_input[channel] += not math.isfinite(row[pos])
        keep = qc_kept is None or index in qc_kept
        for gate in gates:
            for channel, bounds in gate["bounds"].items():
                value = row[positions[channel]]
                keep = keep and math.isfinite(value) and (bounds["min"] is None or value >= bounds["min"]) and (bounds["max"] is None or value < bounds["max"])
        if keep:
            selected.append(index)
            for channel, pos in positions.items():
                if math.isfinite(row[pos]):
                    values[channel].append(float(row[pos]))
    flags = []
    if len(events) == 0:
        flags.append("empty_event_input")
    if not selected:
        flags.append("no_selected_events")
    if qc_mask is not None:
        flags.append("external_qc_mask_user_supplied_not_independently_validated")
    if config["compensation"]["state"] == "uncompensated":
        flags.append("fluorescence_uncompensated")
    elif config["compensation"]["state"] == "already_compensated":
        flags.append("already_compensated_is_user_assertion")
    if any(nonfinite_input.values()):
        flags.append("nonfinite_input_measurements")
    if any(len(v) != len(selected) for v in values.values()):
        flags.append("channel_finite_denominators_differ_from_selected_count")
    time_index = next((i for i, name in enumerate(detectors) if name.lower() == "time"), None)
    time_values = None if time_index is None else [float(row[time_index]) for row in events]
    time_flags, time_detail = time_qc(time_values, metadata or {}, preprocessed=time_preprocessed)
    flags.extend(time_flags)
    sample = {"sample_id": config["sample_id"], "event_count": len(events), "selected_count": len(selected),
              "gate_status": gate_status, "source": source,
              "processing": {"engine": engine, "event_identity": "zero_based_original_FCS_DATA_order",
                  "selected_event_ranges": _ranges(selected), "range_semantics": "start_inclusive_end_exclusive",
                  "selection": ("external_qc_mask_intersected_with_supplied_rectangles" if gates else "external_qc_mask_only") if qc_mask is not None else ("intersection_of_supplied_rectangles" if gates else "all_events"),
                  "rectangle_boundary_semantics": "min_inclusive_max_exclusive",
                  "gates": gates, "compensation": config["compensation"],
                  "summary_denominator": "selected_count; medians use per-channel finite_count",
                  "negative_values": "preserved", "transformation": "none",
                  "automatic_qc_exclusion": False, "biological_population_identity": "not_established",
                  "external_qc_mask": None if qc_mask is None else {
                      "method_attribution": qc_mask["method"], "execution": "external_not_executed_by_this_package",
                      "source_sha256": qc_mask["source_sha256"], "original_event_count": len(events),
                      "kept_event_count": len(qc_kept), "kept_original_event_ranges": _ranges(sorted(qc_kept))},
                  "stage_counts": {"input": len(events), "after_external_qc_mask": len(events) if qc_kept is None else len(qc_kept),
                                   "after_supplied_rectangles": len(selected)},
                  "input_nonfinite_counts": nonfinite_input, "time_qc": time_detail},
              "channels": {channel: {"median": _median(v),
                              "finite_count": len(v), "negative_count": sum(x < 0 for x in v)} for channel, v in values.items()},
              "qc_flags": flags}
    return {"schema_version": SCHEMA, "evidence_kind": config["evidence_kind"], "samples": [sample]}


def analyze_fcs(path, config, *, qc_mask=None):
    """Optional native FlowKit adapter; no compensation/gates inferred from data."""
    validate_config(config)
    inspection = inspect_fcs(path)
    try:
        import flowkit
    except ImportError as exc:
        raise ValueError("analyze requires optional FlowKit: install Aureka Flow and its pinned dependencies") from exc
    try:
        sample = flowkit.Sample(str(path), sample_id=config["sample_id"])
    except Exception as exc:
        raise ValueError(f"FCS event decoding: FlowKit rejected input ({type(exc).__name__}: {exc})") from exc
    if len(set(sample.pnn_labels)) != len(sample.pnn_labels):
        raise ValueError("FCS detectors: duplicate labels")
    for gate in config.get("rectangle_gates", []):
        for channel in gate["bounds"]:
            if channel not in sample.pnn_labels or sample.pnn_labels.index(channel) not in sample.fluoro_indices:
                raise ValueError(f"rectangle_gates.bounds.{channel}: not a recognized fluorescence detector")
    embedded = config["compensation"]["state"] == "embedded"
    if embedded:
        spill = sample.metadata.get("spillover") or sample.metadata.get("spill")
        if not spill:
            raise ValueError("config.compensation.state: embedded spillover requested but absent")
        try:
            sample.apply_compensation(spill)
        except Exception as exc:
            raise ValueError(f"config.compensation: FlowKit rejected embedded matrix ({type(exc).__name__}: {exc})") from exc
    events = sample.get_events(source="comp" if embedded else "raw")
    if len(events) != inspection["event_count_declared"]:
        raise ValueError("FCS event_count: decoded count differs from header")
    result = summarize_events(events, sample.pnn_labels, config, source=inspection["source"],
                              metadata=sample.metadata, time_preprocessed=True,
                              engine=f"FlowKit/{flowkit.__version__}", compensation_applied=embedded, qc_mask=qc_mask)
    result["samples"][0]["processing"]["FCS_preprocessing"] = "FlowKit 1.2.3 default preprocessing: parameter amplification, gain and Time scaling per metadata"
    result["samples"][0]["processing"]["detector_settings"] = inspection["channels"]
    if embedded:
        result["samples"][0]["processing"]["embedded_spillover_sha256"] = hashlib.sha256(spill.encode()).hexdigest()
    if sha256_file(path) != inspection["source"]["sha256"]:
        raise ValueError("source.sha256: input changed during analysis; result discarded")
    return result


def demo():
    """Three small, explicitly synthetic samples; never derived from lab data."""
    result = {"schema_version": SCHEMA, "evidence_kind": "synthetic", "samples": []}
    for sample_id, events in (
        ("synthetic-negative", [[-2, -1, 0], [0, 2, 1], [2, 0, 2], [4, 1, 3]]),
        ("synthetic-positive", [[20, 30, 0], [25, 40, 1], [30, 50, 2], [35, 60, 3]]),
        ("synthetic-pool", [[-1, -2, 0], [12, 0, 1], [22, 35, 2], [32, 55, 3]]),
    ):
        encoded = (json.dumps(events, separators=(",", ":")) + "\n").encode()
        config = {"schema_version": CONFIG_SCHEMA, "sample_id": sample_id, "evidence_kind": "synthetic",
                  "channels": ["FITC-A", "APC-A"], "compensation": {"state": "uncompensated", "reason": "Synthetic detector values; no spillover model simulated"}}
        payload = summarize_events(events, ["FITC-A", "APC-A", "Time"], config,
                                   source={"basename": sample_id + ".json", "sha256": hashlib.sha256(encoded).hexdigest()},
                                   metadata={"btim": "12:00:00", "etim": "12:00:03", "timestep": "1"})
        payload["samples"][0]["processing"]["synthetic_input"] = {"detectors": ["FITC-A", "APC-A", "Time"], "events": events,
            "source_hash_serialization": "UTF-8 json.dumps(events,separators=(',',':')) plus newline"}
        result["samples"].extend(payload["samples"])
    return result
