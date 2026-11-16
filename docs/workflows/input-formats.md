> Imported from yeast-facs-workflow at `19e3aa5`. For current installation and integration, start with the [Aureka Flow workflow guide](README.md). Historical software versions and validation results below describe the original repository.

# Input formats

Examples below are invented syntax examples, not biological recommendations. Use your actual detector names and reviewed processing choices. All inputs are read-only; output directories must be new.

## Batch run: `run.json`

```json
{
  "schema_version": "yeast-facs-run/v1",
  "files": [
    {"fcs": "raw/sample-001.fcs", "config": "config/sample-001.json"}
  ],
  "sample_manifest": "samples.json"
}
```

Add `"qc_mask": "qc/sample-001.json"` to a file entry only when an external mask exists. Add both `"sort_bins": "sort-bins.json"` and `"variant_counts": "counts.json"` at the root to run module 6. All relative paths resolve from this run file's directory.

## Per-file processing configuration

```json
{
  "schema_version": "yeast-facs-analysis-config/v1",
  "sample_id": "sample-001",
  "evidence_kind": "user_data",
  "channels": ["FITC-A", "APC-A"],
  "compensation": {
    "state": "embedded",
    "reason": "Explicit request to replay the embedded matrix; its control evidence still requires review"
  }
}
```

Choose one compensation state deliberately:

| State | Behavior |
| --- | --- |
| `embedded` | Require and apply embedded SPILLOVER/SPILL via FlowKit; fail if absent or unusable |
| `uncompensated` | Leave fluorescence uncompensated and record a warning |
| `already_compensated` | Do not compensate again; record that this is a user assertion |

`evidence_kind` is a caller assertion (`synthetic` or `user_data`), not an automatic provenance classifier. Mixed evidence kinds are rejected within a run. Never relabel private data synthetic to publish it.

Optional `rectangle_gates` is a nonempty list. Omit it for no fluorescence gate:

```json
[
  {
    "gate_id": "example-rectangle",
    "scope": "user_supplied_unvalidated",
    "reference_status": "Syntax example only; replace with the reviewed gate provenance",
    "bounds": {"FITC-A": {"min": 100, "max": null}}
  }
]
```

The number 100 is **not a recommended threshold**. Bounds are lower-inclusive, upper-exclusive, in linear detector units **after FlowKit gain/amplification/Time preprocessing and chosen compensation**. Do not use plotted logicle coordinates. All rectangles are intersected. FSC/SSC/Time rectangles are intentionally unsupported; this interface cannot establish a yeast, singlet or viability population. A nonfinite gate value fails the gate; finite negative values are retained when inside bounds.

## Explicit sample metadata

```json
{
  "schema_version": "yeast-facs-samples/v1",
  "evidence_kind": "user_data",
  "samples": [
    {
      "sample_id": "sample-001",
      "condition": "condition-A",
      "biological_replicate": null,
      "batch_id": "batch-001",
      "plate": null,
      "well": null,
      "control_role": "sample"
    }
  ]
}
```

Required metadata fields must be present. Unknown biological replicate, batch, plate or well identities should be `null`, not invented. `control_role` is `negative`, `positive`, `sample` or `reference`. Optional `concentration` (nonnegative number) and `concentration_unit` must appear together; no unit conversion or affinity inference occurs.

All measured sample IDs must match this manifest exactly. Multiple acquisitions from one biological replicate must retain the same biological-replicate ID. Merely labeling a sample `reference` does not calibrate a batch. v0.1 blocks biological cross-batch comparison whenever more than one known batch is present.

## External acquisition-QC mask

```json
{
  "schema_version": "yeast-facs-qc-mask/v1",
  "source_sha256": "REPLACE_WITH_64_CHARACTER_LOWERCASE_INPUT_FCS_SHA256",
  "event_count": 4,
  "kept_original_event_indices": [0, 2, 3],
  "method": "User-reviewed external selection; record tool version and parameters"
}
```

The placeholder hash must be replaced. Indices are **zero-based into the original FCS DATA event order**, not into a previous subset. The input hash and original count must match exactly. Duplicate, boolean, fractional and out-of-range indices fail validation. An empty list is allowed and produces no selected events.

An external mask is intersected with any supplied fluorescence rectangles. Time diagnostics continue to describe all original events. Mask-stage and selected-event ranges/counts remain in provenance. An ungated record means no fluorescence rectangles; an explicit external acquisition mask may still reduce its denominator. The `method` string is attribution supplied by the user, not proof that this package ran the named tool. Convert R one-based positions explicitly; do not guess an external tool's index convention.

## Sort bins and decoded counts

```json
{
  "schema_version": "yeast-sort-bins/v1",
  "evidence_kind": "user_data",
  "bins": [
    {
      "bin_id": "bin-01",
      "sample_id": "sample-001",
      "sequencing_sample_id": "seq-bin-01",
      "sorted_events": 1000,
      "gate_definition_id": "reviewed-sort-gate-01"
    }
  ]
}
```

```json
{
  "schema_version": "yeast-variant-counts/v1",
  "evidence_kind": "user_data",
  "counts": [
    {"sequencing_sample_id": "seq-bin-01", "variant_id": "variant-A", "read_count": 30},
    {"sequencing_sample_id": "seq-bin-01", "variant_id": "variant-B", "read_count": 70}
  ]
}
```

These artificial values illustrate a 30%/70% read composition, not variant abundance or binding. `sorted_events` is a declared sort counter, independent of the event count in a diagnostic FCS aliquot. It is not used to silently normalize read counts. Each bin and sequencing-sample ID must map unambiguously; duplicate count keys fail. Multiple bins may point to one FCS sample.

Missing rows remain missing. An explicitly supplied zero is retained; when a sample's total supplied reads equal zero, its read fractions are undefined (`null`). The denominator is the sum of all supplied variant counts for that sequencing sample, which may be an incomplete view of the library. No correction for collection fraction, amplification bias or unequal sampling is applied.

## Measurement and output conventions

- `event_count`: all decoded input events.
- `selected_count`: after an external QC mask, if supplied, and the intersection of supplied rectangles.
- `channels[detector].finite_count`: actual finite-value denominator for that channel's median.
- `median: null`: no finite selected values; never replace with zero.
- Original-event ranges: zero-based, start-inclusive, end-exclusive.
- Input SHA-256: original FCS bytes; synthetic array demo uses its documented JSON serialization instead.
- Comparison status: `cross_batch_blocked`, `metadata_limited` or `exploratory_only`; none establishes biological validation.

Output JSON retains original processing metadata and source basenames, so it must be reviewed for sensitive information before sharing.
