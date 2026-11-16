"""Self-contained, escaped HTML; no JavaScript or remote resources."""

from html import escape
import json
import math


def text(value):
    return escape("Unknown" if value is None else str(value), quote=True)


def median(value):
    return "Unavailable" if value is None else text(format(value, ".6g"))


def table(headers, rows):
    head = "".join(f"<th scope='col'>{text(item)}</th>" for item in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<div class='table-scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def median_dot_plot(samples, detector):
    """Plot at most 50 individual medians; never pool, normalize or infer units.

    Normalize coordinates by the largest absolute *displayed* value before
    subtracting endpoints. This preserves negative/subnormal values and avoids
    overflowing a raw max-minus-min span such as 1e308 - (-1e308).
    """
    shown = samples[:50]
    values = []
    for sample in shown:
        channel = sample["channels"].get(detector)
        value = None if channel is None else channel["median"]
        if value is not None:
            if type(value) not in (int, float):
                raise ValueError("median plot: expected finite numeric medians or null")
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("median plot: expected finite numeric medians or null")
            values.append(value)
    scale = max((abs(value) for value in values), default=0)
    # All-zero/all-missing plots have only a zero tick, not invented +/-1 units.
    low = min([0] + values)
    high = max([0] + values)
    scaled_low, scaled_high = (low / scale, high / scale) if scale else (-1.0, 1.0)
    left, right = 260.0, 775.0

    def x_coordinate(value):
        scaled_value = value / scale if scale else 0.0
        fraction = (scaled_value - scaled_low) / (scaled_high - scaled_low)
        return left + (right - left) * min(1.0, max(0.0, fraction))

    axis_y = 76 + max(0, len(shown) - 1) * 34
    height = axis_y + 72
    zero_x = x_coordinate(0)
    title = f"{detector}: individual sample medians; no pooled estimates or calibrated units"
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{text(title)}" viewBox="0 0 1100 {height}" width="1100" height="{height}" style="font-family:system-ui,sans-serif;font-size:12px;color:#17313e">',
        f"<title>{text(title)}</title>",
        "<desc>Dots represent individual supplied sample medians. Zero is a numerical reference, not a biological threshold. No error bars, pooling or batch normalization. The full data table follows.</desc>",
        '<text x="18" y="22" fill="#566775">Sample</text>',
        '<text x="803" y="22" fill="#566775">Median</text>',
        '<text x="950" y="22" fill="#566775">Finite / selected</text>',
        f'<line class="zero-reference" x1="{zero_x:.3f}" x2="{zero_x:.3f}" y1="34" y2="{axis_y}" stroke="#80939c" stroke-dasharray="4 4"/>',
    ]
    for index, sample in enumerate(shown):
        y = 48 + index * 34
        label = sample["sample_id"]
        short_label = label if len(label) <= 29 else label[:28] + "…"
        channel = sample["channels"].get(detector)
        value = None if channel is None else channel["median"]
        finite_count = "not supplied" if channel is None else str(channel["finite_count"])
        count_label = f"{finite_count} / {sample['selected_count']}"
        median_label = "Not supplied" if channel is None else median(value)
        elements.append(f'<line x1="260" x2="775" y1="{y}" y2="{y}" stroke="#e5ecef"/>')
        elements.append(f'<text x="18" y="{y + 4}" fill="#17313e"><title>{text(label)}</title>{text(short_label)}</text>')
        elements.append(f'<text x="803" y="{y + 4}" fill="#17313e">{median_label}</text>')
        elements.append(f'<text x="950" y="{y + 4}" fill="#566775">{text(count_label)}</text>')
        if value is not None:
            point_title = f"{label}: median {format(value, '.6g')}; finite / selected {count_label}"
            elements.append(f'<circle class="sample-median" cx="{x_coordinate(value):.3f}" cy="{y}" r="5" fill="#087f80" stroke="#ffffff" stroke-width="1.5"><title>{text(point_title)}</title></circle>')
    elements.append(f'<line x1="260" x2="775" y1="{axis_y}" y2="{axis_y}" stroke="#80939c"/>')
    ticks = sorted({low, 0, high}) if scale else [0]
    for value in ticks:
        x = x_coordinate(value)
        elements.append(f'<line x1="{x:.3f}" x2="{x:.3f}" y1="{axis_y}" y2="{axis_y + 5}" stroke="#80939c"/>')
        anchor = "start" if x == left else "end" if x == right else "middle"
        elements.append(f'<text x="{x:.3f}" y="{axis_y + 21}" text-anchor="{anchor}" fill="#566775">{median(value)}</text>')
    elements.append(f'<text x="517.5" y="{axis_y + 47}" text-anchor="middle" fill="#566775">Supplied median values · linear layout · units not inferred</text>')
    elements.append("</svg>")
    if len(samples) > 50:
        scope = f"Plot truncated: first 50 of {len(samples)} sample records in input order. Axis uses displayed rows only; the complete table follows."
    else:
        scope = f"{len(shown)} individual sample records; the complete table follows."
    if not values:
        scope += " No finite medians in displayed rows; zero is a reference only."
    elif not scale:
        scope += " All displayed finite medians are zero."
    scope += " Zero is not a biological cutoff. Shared plotting coordinates do not establish comparable detector units, gates or batches."
    return '<figure class="median-figure"><div class="plot-scroll">' + "".join(elements) + f'</div><figcaption class="muted">{text(scope)}</figcaption></figure>'


def render_report(experiment):
    samples = experiment["samples"]
    summary = experiment["summary"]
    cards = "".join(f"<div class='card'><strong>{text(value)}</strong><span>{text(label)}</span></div>" for label, value in (
        ("Sample records", summary["sample_record_count"]),
        ("Declared conditions", summary["condition_count"]),
        ("Known batches", summary["known_batch_count"]),
        ("Acquired-event sum", summary["acquired_event_count_sum"]),
        ("Selected-event sum", summary["selected_event_count_sum"]),
    ))
    warning_items = "".join(f"<li><b>{text(warning['code'])}</b> — {text(warning['message'])}" + (f" <span class='muted'>[{text(', '.join(warning['sample_ids']))}]</span>" if warning.get("sample_ids") else "") + "</li>" for warning in experiment["warnings"])
    warning_html = f"<ul>{warning_items}</ul>" if warning_items else "<p>No metadata warnings were generated. This is not confirmation of biological comparability.</p>"
    identity_rows = []
    for sample in samples:
        concentration = f"{text(sample['concentration'])} {text(sample['concentration_unit'])}" if "concentration" in sample else "Not supplied"
        identity_rows.append([text(sample["sample_id"]), text(sample["condition"]), text(sample["biological_replicate"]), text(sample["batch_id"]), text(sample["plate"]), text(sample["well"]), text(sample["control_role"]), concentration])
    identity_table = table(["Sample", "Condition", "Biological replicate", "Batch", "Plate", "Well", "Declared control role", "Concentration"], identity_rows)
    count_table = table(["Sample", "Acquired events", "Selected / acquired", "Gate status", "Upstream QC flags"], [
        [text(s["sample_id"]), text(s["event_count"]), f"{text(s['selected_count'])} / {text(s['event_count'])}", text(s["gate_status"]), text(", ".join(s["qc_flags"]) or "None supplied")]
        for s in samples
    ])
    marker_sections = []
    for detector in sorted({key for sample in samples for key in sample["channels"]}):
        rows = []
        for sample in samples:
            channel = sample["channels"].get(detector)
            rows.append([text(sample["sample_id"]), text(sample["condition"]), text(sample["batch_id"]), text(sample["biological_replicate"]), median(channel["median"]) if channel else "Not supplied", f"{text(channel['finite_count'])} / {text(sample['selected_count'])}" if channel else "Not supplied"])
        marker_sections.append(f"<section class='marker'><h3>{text(detector)}</h3><p class='muted'>Supplied detector median; units, transformation and calibration are not inferred. Rows are displayed individually, without pooled estimates.</p>" + median_dot_plot(samples, detector) + table(["Sample", "Condition", "Batch", "Biological replicate", "Median", "Finite values / selected events"], rows) + "</section>")
    condition_table = table(["Condition", "Sample records", "Distinct declared biological IDs", "Missing biological IDs", "Known batches"], [
        [text(c["condition"]), text(c["sample_record_count"]), text(c["declared_biological_replicate_count"]), text(c["missing_biological_replicate_count"]), text(", ".join(c["batch_ids"]) or "Unknown")]
        for c in experiment["condition_summaries"]
    ])
    limits = "".join(f"<li>{text(item)}</li>" for item in experiment["limits"])
    metadata = escape(json.dumps({"samples": samples, "measurement_metadata": experiment["measurement_metadata"], "manifest_metadata": experiment["manifest_metadata"]}, indent=2, ensure_ascii=False, allow_nan=False))
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Yeast FACS — exploratory workbench</title>
<style>
:root{--ink:#17313e;--muted:#566775;--line:#dce5e9;--teal:#087f80;--paper:#fff;--bg:#f2f6f7}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1220px;margin:auto;padding:36px 28px 70px}header{padding:28px 0 24px;border-bottom:2px solid var(--teal)}h1{font-size:36px;line-height:1.15;letter-spacing:-1px;margin:10px 0}h2{font-size:23px;margin:0 0 14px}h3{font-size:18px;margin:4px 0}
.eyebrow{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--teal);font-weight:700}.muted,small{color:var(--muted)}.badge{display:inline-block;background:#dceeee;border-radius:5px;padding:3px 10px;font-weight:650;font-size:12px;margin-right:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:24px 0}.card{background:white;border:1px solid var(--line);border-radius:9px;padding:16px}.card strong{display:block;font-size:25px;overflow-wrap:anywhere}.card span{font-size:12px;color:var(--muted)}
section.panel{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:24px;margin:22px 0}.notice{border-left:4px solid #bd8130;background:#fff8e9;padding:14px 18px;margin:20px 0}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;background:#eaf2f3;padding:10px;white-space:nowrap}td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}tr:last-child td{border-bottom:0}.marker{margin:24px 0 32px}li{margin:8px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#f4f7f8;padding:16px;border-radius:6px}summary{cursor:pointer;font-weight:600}footer{font-size:12px;color:var(--muted)}
.median-figure{margin:18px 0 24px;padding:12px 0;border:1px solid var(--line);border-radius:8px;background:#fbfdfd}.plot-scroll{overflow-x:auto}.plot-scroll svg{display:block;max-width:none}.median-figure figcaption{font-size:12px;padding:10px 16px 0}
@media(max-width:600px){main{padding:20px 14px}h1{font-size:28px}section.panel{padding:16px}}
@media print{body{background:white}main{padding:0}.panel,.marker{break-inside:avoid}details{display:none}}
</style></head><body><main>
<header><div class="eyebrow">Yeast FACS workbench · software alpha</div><h1>Measurements in context</h1>
<p>Explicit sample identity, visible denominators, and descriptive detector comparisons.</p>""" + f"<span class='badge'>Evidence: {text(experiment['evidence_kind'])}</span><span class='badge'>{text(experiment['comparison_status'])}</span></header>" + f"<div class='cards'>{cards}</div>" + "<div class='notice'><b>Exploratory summaries only.</b> Event counts are not biological replicates. Fluorescence is not affinity. No biological percent-positive claims, significance tests or automatic normalization are produced.</div>" + f"<section class='panel'><h2>Review before comparison</h2>{warning_html}</section><section class='panel'><h2>Sample identity</h2>{identity_table}</section><section class='panel'><h2>Counts and selection denominators</h2><p class='muted'>{text(summary['count_scope'])} Selected events are not assumed to be live singlets.</p>{count_table}</section><section class='panel'><h2>Marker median comparisons</h2><p>Sample-wise descriptive display only. Different batches, gates, transformations or detector units may be incomparable.</p>{''.join(marker_sections) or '<p>No marker summaries were supplied.</p>'}</section><section class='panel'><h2>Declared replicate structure</h2>{condition_table}</section><section class='panel'><h2>Interpretation limits</h2><ul>{limits}</ul><details><summary>Preserved input summaries and processing metadata</summary><pre>{metadata}</pre></details></section><footer>Aureka Flow · yeast-facs-experiment/v1 · local report; no external assets or scripts</footer></main></body></html>"
