"""Literal primary FCS TEXT adapter for the pinned FlowIO/FlowKit stack.

FlowIO 1.3.0 removes dollar characters from values and can retain doubled
separators in labels. Decode events with FlowIO, then supply the validated
literal metadata/labels through its public FlowData attributes before FlowKit
constructs channel mappings or preprocesses/compensates events.
"""
import io
from pathlib import Path
import re


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
            tokens.append(bytes(buf))
            buf.clear()
        else:
            buf.extend(char)
        i += 1
    if buf or len(tokens) % 2:
        raise ValueError("FCS TEXT: malformed key/value pairs")
    metadata = {}
    try:
        tokens = [token.decode("utf-8") for token in tokens]
    except UnicodeDecodeError:
        # Match the pinned reader's legacy whole-segment Latin-1 fallback.
        tokens = [token.decode("latin-1") for token in tokens]
    for key, value in zip(tokens[::2], tokens[1::2]):
        normalized = key.lstrip("$").lower()
        if not normalized or normalized in metadata:
            raise ValueError("FCS TEXT: empty or duplicate metadata key. Re-export unambiguous FCS metadata.")
        metadata[normalized] = value
    return metadata


def read_fcs_text(source):
    """Validate bounded primary HEADER/TEXT, retaining literal values and order."""
    with (io.BytesIO(source) if isinstance(source, bytes) else Path(source).open("rb")) as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(0)
        header = handle.read(58)
        if len(header) != 58 or header[:6] not in (b"FCS2.0", b"FCS3.0", b"FCS3.1"):
            raise ValueError("FCS HEADER: unsupported version or truncated 58-byte header")
        try:
            begin, end = int(header[10:18]), int(header[18:26])
        except ValueError as exc:
            raise ValueError("FCS HEADER: malformed TEXT offsets") from exc
        if begin < 58 or end < begin or end >= size or end - begin + 1 > 16 * 1024 * 1024:
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


def load_fcs_sample(source, **sample_options):
    """Use the same exact detector/keyword identities in browser and batch."""
    import flowio
    import flowkit

    _, metadata = read_fcs_text(source)
    data = flowio.FlowData(io.BytesIO(source) if isinstance(source, bytes) else str(source))
    # FlowIO has already decoded DATA using these fields. Refuse inconsistent
    # interpretations instead of attaching restored names to different events.
    decoding_keys = {"par", "tot", "datatype", "byteord", "mode", "begindata", "enddata", "nextdata"}
    decoding_keys.update(f"p{i}{suffix}" for i in range(1, int(metadata["par"]) + 1) for suffix in ("b", "r"))
    if any(data.text.get(key) != metadata.get(key) for key in decoding_keys):
        raise ValueError("FCS TEXT: inconsistent DATA-decoding metadata. Re-export the source FCS.")
    # FlowIO takes event_count from $TOT but decodes the whole DATA segment.
    # Validate before FlowKit reshapes/preprocesses events or uses that count
    # as a denominator. Never truncate, pad or rewrite an inconsistent source.
    count, channels = int(metadata["tot"]), int(metadata["par"])
    if len(data.events) != count * channels:
        raise ValueError(
            f"FCS DATA: $TOT declares {count} events x {channels} parameters "
            f"({count * channels} values), but decoded {len(data.events)} values. "
            "Re-export a complete FCS file with matching event metadata."
        )
    data.text = metadata
    for number, channel in data.channels.items():
        channel["PnN"] = metadata[f"p{number}n"]
        if f"p{number}s" in metadata:
            channel["PnS"] = metadata[f"p{number}s"]
    return flowkit.Sample(data, **sample_options)
