> Imported from yeast-facs-workflow at `19e3aa5`. For current installation and integration, start with the [Aureka Flow workflow guide](README.md). Historical software versions and validation results below describe the original repository.

# Six modules, one workflow

See the [workflow diagram](figures/workflow-overview.svg), [design rationale](legacy-overview.md#why-this-exists) and [stage-by-stage review guide](workflow-review.md) for the scientific questions, manual checkpoints and inspectable output fields behind this structure.

The public distribution is one installable repository. Three internal component packages separate responsibilities without requiring sibling checkouts, network services or machine-specific paths:

| Module | API location | Contract |
| --- | --- | --- |
| 1. Ingest | `aureka_flow.workflows.core.ingest` | FCS HEADER/TEXT inspection and source hashes |
| 2. QC | `aureka_flow.workflows.core.qc` | Time diagnostics and reviewed external masks |
| 3. Gating | `aureka_flow.workflows.core.gating` | `yeast-facs-measurements/v1` |
| 4. Experiment | `aureka_flow.workflows.workbench.analysis` | `yeast-facs-experiment/v1` |
| 5. Report | `aureka_flow.workflows.workbench.report` | Self-contained HTML/SVG plus JSON |
| 6. Sort-seq | `aureka_flow.workflows.sortseq.linkage` | `yeast-sortseq-linked/v1` |

The small core facade modules expose functions whose shared implementation lives in `core.py`. `aureka_flow.workflows.pipeline` composes all six modules and produces `yeast-facs-run-receipt/v1`. Output hashes cover the produced files, not the receipt itself. A successful run establishes software execution, not scientific validity.

## Validation boundaries

1. Reject malformed schemas, duplicate JSON keys, invalid numeric values and ambiguous identities.
2. Preserve acquisition identity through input SHA-256 and zero-based original-event ranges.
3. Record explicit preprocessing, compensation and gate decisions. Do not silently manufacture them.
4. Join sample metadata exactly; fail on missing, duplicate or unmatched sample IDs.
5. Keep comparison restrictions and warnings in downstream count-linkage outputs.
6. Write new output directories only; never modify raw input FCS files.

The workflow is strict about its own decision-bearing configuration fields. Some measurement metadata is preserved for extensibility rather than interpreted. Accepted caller-provided metadata is not independently verified evidence.

## Adding an upstream adapter

A new adapter must define the executable and version, its input/output coordinate systems, a license/distribution boundary, and synthetic numerical tests. Include a real-data validation plan separately; passing synthetic tests is insufficient.

For acquisition filters, retain exact original indices and prove that exported masks refer to the same unmodified FCS file. For gating, declare compensation, transformation, population hierarchy and controls. For calibration, record bead lot/reference values, batch identity and qualification criteria. For sort-seq inference, establish library mapping, complete bin accounting, selection/sampling factors and an appropriate assay model before interpreting fitted parameters.

Planned adapters must remain visibly `not implemented` until their native execution and interoperability tests exist. Do not give them success statuses because a compatible file could theoretically be supplied.

## Deliberately outside v0.1

Automatic cell/singlet/viability gates; FlowJo workspace import; automatic batch correction; wellmap TOML import; raw FASTQ decoding; variant sequence validation; Tite-Seq affinity fitting; experimental-layout optimization; autonomous biological decisions. These require distinct implementations and evidence, not a renamed report.
