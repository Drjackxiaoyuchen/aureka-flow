> Imported from yeast-facs-workflow at `19e3aa5`. For current installation and integration, start with the [Aureka Flow workflow guide](README.md). Historical software versions and validation results below describe the original repository.

# Cross-check the workflow, one handoff at a time

This guide explains why each stage exists, what the current code actually checks, and what a researcher must still review. It is a **manual review guide**, not a new automated approval system. A complete output directory means the software executed; it does not mean the assay or its interpretation is valid.

[Back to the README](legacy-overview.md) · [Detailed workflow diagram](figures/workflow-overview.svg) · [Input contracts](input-formats.md) · [Upstream rationale](integrations.md)

## Before the run: establish what the measurements mean

Record the biological question, experimental units, detector-to-marker assignments, controls, acquisition settings and rationale for compensation and selection. These are researcher responsibilities. The current software does not design a plate, optimize a titration, qualify controls or infer marker identity from a detector name.

Supply a `run.json`, per-acquisition processing configurations and an explicit sample manifest. Supply a separately reviewed original-event mask only if one exists. If sequencing follows sorting, also supply the bin map and already decoded variant counts. Preserve the source configurations and control evidence alongside your run: the output receipt is **not** a complete byte-for-byte archive of every original configuration file.

The six stages below are logical responsibilities. Native preprocessing and optional compensation occur before event summarization. Acquisition diagnostics and mask/rectangle selection are computed within the same summarizer; the diagram is not a claim of six separate processing executables.

## 1 · Establish acquisition identity

**Why:** a scientifically plausible plot can still describe the wrong sample or count a renamed export twice. The workflow starts with explicit identity rather than guessing from filenames.

**What runs:** the bounded inspector reads FCS HEADER/TEXT and hashes the source bytes. The optional FlowKit adapter decodes events, applies its metadata-driven preprocessing and checks decoded versus declared event count. The batch runner rejects duplicate resolved paths and identical FCS contents; the source is hashed again after analysis to detect changes during the read.

**Inspect in `measurements.json → samples[]`:**

- `sample_id`, `source.basename`, `source.sha256` and `event_count`.
- For native FCS runs, `processing.engine`, `processing.FCS_preprocessing` and `processing.detector_settings`.
- Match each `sample_id` to the intended record in `samples.json`. The code checks an exact join, not whether your tube was correctly labeled.

**Researcher checkpoint:** confirm acquisition identity, detector/marker mapping and instrument context. A source hash establishes the identity of bytes; it does not validate a sample annotation. HEADER/TEXT inspection alone does not validate event DATA.

**Code and tests:** [`inspect_fcs` / `analyze_fcs`](../../aureka_flow/workflows/core/core.py), [`collect_run`](../../aureka_flow/workflows/pipeline.py), [`test_duplicate_fcs_content_rejected_even_with_different_paths_and_ids`](../../tests/workflow/test_pipeline.py).

## 2 · Review acquisition quality without silently removing events

**Why:** an acquisition-time inconsistency and an interesting biological population are different explanations. The first should not be hidden inside the second.

**What runs:** original Time diagnostics examine all input events for missing or non-finite Time, backward steps, invalid timestep metadata and disagreement with acquisition-clock duration. Non-finite counts are retained for requested channels. These diagnostics do **not** discover an exclusion interval, repair Time or automatically filter an acquisition.

If you supply an external mask, the workflow validates the exact source hash, original event count and unique zero-based original indices. It then applies that selection. Naming PeacoQC or another method in the mask does not mean this package executed or verified that method.

**Inspect in each measurement:**

- `qc_flags`, `processing.time_qc` and `processing.input_nonfinite_counts`.
- `processing.external_qc_mask`: `method_attribution`, `execution`, `source_sha256`, `original_event_count`, `kept_event_count` and `kept_original_event_ranges`.
- `processing.stage_counts.input` versus `after_external_qc_mask`.

**Researcher checkpoint:** review acquisition traces, the reason for each exclusion and the external tool's index convention. R one-based positions must be explicitly converted if appropriate; do not reuse subset-relative indices. Mask provenance must match the same unmodified file. An empty supplied mask deliberately retains no events.

**Behavior:** invalid mask bindings/indices reject; ordinary QC flags remain warnings. A valid file contract does not establish an appropriate biological selection.

**Code and tests:** [`time_qc`, `validate_qc_mask`, `summarize_events`](../../aureka_flow/workflows/core/core.py), [mask/selection-contract tests](../../tests/workflow/test_native_pipeline.py).

## 3 · Check compensation, gate coordinates and denominators together

**Why:** a median is interpretable only for a specified processing state and selected population. A display-space threshold is not interchangeable with a raw or compensated detector threshold.

**What runs:** configuration explicitly chooses `embedded`, `uncompensated` or `already_compensated`. Only `embedded` asks FlowKit to apply the FCS spillover matrix; a missing or unusable requested matrix rejects. `already_compensated` is a recorded user assertion, not independently detected processing.

Optional supplied fluorescence rectangles are intersected with each other and with any external mask. Bounds use **linear detector values after FlowKit preprocessing and the chosen compensation**: lower-inclusive, upper-exclusive. No logicle/asinh transformation is applied by the analysis gate engine. The separate gallery uses display transforms only.

**Inspect in each measurement:**

- `processing.compensation`, `processing.gates`, `processing.selection` and `gate_status`.
- Native embedded-compensation runs additionally record `processing.embedded_spillover_sha256`.
- `processing.stage_counts`, `selected_count`, `processing.selected_event_ranges` and their start-inclusive/end-exclusive semantics.
- `channels[detector].median`, `.finite_count` and `.negative_count`.

Check the bookkeeping relationship:

```text
input events ≥ events after the external mask ≥ selected events ≥ channel finite count
```

With no external mask, the first two counts are equal. With no rectangle, selection retains the mask-kept events. Each median uses its own channel's finite values. Finite negative fluorescence is retained; non-finite measurements are not replaced with zero. A channel with no finite selected values has `median: null`.

**Researcher checkpoint:** verify matrix suitability and the control evidence for your chosen population. This alpha does not provide FSC/SSC/Time rectangles, hierarchical yeast/singlet/viability gates, or automatic expression/binding thresholds. An illustrative gallery cutoff is never a recommended laboratory cutoff.

**Code and tests:** [`analyze_fcs` / `summarize_events`](../../aureka_flow/workflows/core/core.py), [compensation, boundary and finite-denominator tests](../../tests/workflow/test_core.py), [native end-to-end test](../../tests/workflow/test_native_pipeline.py).

## 4 · Check the experimental unit before comparing samples

**Why:** more events or repeat exports do not create more independent biological replicates. Apparent condition differences may also be inseparable from batch or processing differences.

**What runs:** exact sample-ID joins combine the measurements with declared condition, biological-replicate, batch, plate/well and control-role metadata. The workbench counts distinct declared biological identities and preserves per-acquisition summaries. It does not pool events for statistical inference, normalize batches, test significance or estimate affinity.

**Inspect `05-report/experiment.json`:**

- `samples[]` for the joined metadata and original measurement fields.
- `condition_summaries` for acquisition counts versus distinct declared biological-replicate counts.
- `warnings` for missing metadata, repeated biological identity, condition–batch confounding, QC flags and processing/channel differences.
- `comparison_status`, interpreted as follows:

| Status | Current rule | What it means for review |
| --- | --- | --- |
| `cross_batch_blocked` | More than one known batch | Biological cross-batch comparison is restricted. Reports and linkage still run; reference labels do not establish calibration. |
| `metadata_limited` | Otherwise, missing batch/biological identity or fewer than two declared biological identities in any condition | The declared experimental structure is insufficient for the intended comparison. Do not invent missing identities. |
| `exploratory_only` | Neither rule above applies | Descriptive output only. Other warnings can remain; this is not a scientific approval. |

`processing_differs` compares the **whole processing object**, including sample-specific event ranges and QC metadata. It is a prompt to inspect differences, not proof that compensation settings or gate definitions differ.

**Researcher checkpoint:** verify true independence, control roles, confounding, instrument units and population comparability. Repeated acquisitions of one biological replicate must retain the same replicate ID. Consistent metadata cannot substitute for assay validation.

**Code and tests:** [`analyze`](../../aureka_flow/workflows/workbench/analysis.py), [replicate/status tests](../../tests/workflow/test_workbench.py), [`test_cross_batch_restriction_propagates_to_sortseq`](../../tests/workflow/test_native_pipeline.py).

## 5 · Trace the report back to its evidence

**Why:** figures should expose assumptions and denominators, not disconnect them from a visually convincing result.

**What runs:** the original report renders individual sample-median SVG plots, complete metadata/denominator tables and warnings from the experiment JSON. The default dot plots show at most the first 50 sample records with a truncation notice; the table remains complete. The four event-density/distribution figures in the gallery are separately generated synthetic demonstrations, not automatically produced real-data plots.

**Inspect:**

- `05-report/report.html` alongside `05-report/experiment.json`: a plotted point must match its sample's channel median and finite denominator.
- `index.html`: verify whether the optional sort-seq branch ran.
- `run-receipt.json`: module execution labels, `comparison_status`, `biological_validation` and `files[].{path,sha256}`.

The receipt hashes produced files **excluding itself**. Original FCS hashes are carried in measurements; the receipt does not directly hash every original config/run-file byte. Keep those original inputs for a full audit trail. Hash matching detects output changes; it does not certify a method, authorize sharing or establish biological correctness.

**Researcher checkpoint:** review all warnings and sensitive labels before sharing. Native outputs can contain filenames, sample metadata and instrument settings; they are not automatically anonymized. A fresh output directory is required, so a rerun cannot silently overwrite a reviewed result.

**Code and tests:** [`render_report`](../../aureka_flow/workflows/workbench/report.py), [`write_run`](../../aureka_flow/workflows/pipeline.py), [report tests](../../tests/workflow/test_report_plot.py), [receipt/integrity tests](../../tests/workflow/test_pipeline.py).

## 6 · Preserve the meaning of sort-seq counts

**Why:** a fluorescence acquisition, a sorter counter and a sequencing library measure different things. Joining them should not silently equate their denominators.

**What runs:** the optional bridge joins experiment sample IDs to explicit bins, one sequencing-sample ID per bin mapping, and already decoded variant-count rows. Several bins may refer to one FCS sample. Supply both the bin map and count input to run this branch, or neither to omit it; supplying only one rejects the run.

**Inspect `06-sortseq/linked_counts.json`:**

- `bins[]`: source `sample_id`, `bin_id`, `sequencing_sample_id`, `gate_definition_id`, declared `sorted_events`, `count_status` and `total_reads`.
- `linked_counts[]`: each supplied `read_count` and `total_reads_in_sequencing_sample`.
- `read_fraction_within_sequencing_sample` is `read_count / sum of supplied counts for that sequencing sample`. `sorted_events` is **not** this denominator.
- `upstream_comparison_status`, `upstream_warnings` and local `warnings`: joining counts does not resolve upstream problems.

Absent rows remain missing; explicit zeros remain zero. An explicitly zero-total sample has undefined (`null`) fractions. The default fewer-than-10-reads flag is advisory, not a validated detection threshold or automatic exclusion. A partial library table produces fractions relative to that supplied table, not necessarily the entire sequenced library.

**Researcher checkpoint:** verify library/barcode identity, complete bin accounting, sampling/collection factors and the provenance of decoded counts. The bridge does not decode FASTQ, validate barcodes, estimate cell fractions, calculate enrichment against input, fit Tite-Seq affinity or select the next experiment. Those require separate methods and evidence.

**Code and tests:** [`link_experiment`](../../aureka_flow/workflows/sortseq/linkage.py), [join and missing-versus-zero tests](../../tests/workflow/test_linkage.py).

## Worked audit: one invented acquisition

Reproduce the default [gallery](demo-gallery.md) using seed `20261001` and 3,000 events per sample. Under `outputs/gallery`, inspect `summary.json` and the `workflow/` subdirectory. The committed [summary](gallery/summary.json) lets you check the published numerical values without running the generator.

| Handoff | Expected value in this synthetic example | What it demonstrates—not a biological result |
| --- | --- | --- |
| Source identity | `synthetic-shift-b-r1`; 3,000 invented events | Its source hash describes the documented event-array JSON serialization, **not an FCS file**. |
| External time mask | 2,666 retained; ranges `[0,1333)` and `[1667,3000)` | The 80–100 s interval is predetermined by the simulation, not detected by a QC algorithm. |
| Supplied rectangle | 2,283 selected after FITC-A ≥ 400 | An illustrative cutoff in linear units; there is no binding-channel gate or validated cell-population claim. |
| Sample summary | APC-A median **976.0061384395848**, finite count **2,283** | The displayed value rounds to 976.01 arbitrary units and remains attached to this selected population. |
| Experiment | `exploratory_only`; invented replicate identities; QC/processing warnings remain | The status exercises metadata logic. The simulation contains **zero real biological replicates**. |
| Bin-to-count linkage | Bin 1: 9,311 reads for variant 01 / 24,000 supplied reads = **38.7958%**; a separate declared sort counter is **8,000** | Toy counts are independently invented, not derived from the FACS events. Neither 8,000 nor 2,283 is the fraction denominator. |

Across all nine invented acquisitions, the same bookkeeping yields **27,000 → 23,994 → 20,634** events. The [gallery tests](../../tests/workflow/test_gallery_data.py) and [render/provenance tests](../../tests/workflow/test_gallery_render.py) check the generated numerical connections. The separate [native integration tests](../../tests/workflow/test_native_pipeline.py) generate FCS fixtures to test actual decoding and compensation.

## What a reviewed result should let you answer

1. Which exact file and declared sample produced this result?
2. Which events were excluded, by which rule, and with which controls or external evidence?
3. Which processing state, population and finite-value denominator produced each summary?
4. Which biological units are genuinely independent, and which comparisons remain restricted?
5. Can every report value be traced to retained JSON, and have sensitive labels been reviewed?
6. If counts are linked, are acquisition events, sort counters and sequencing reads still distinguishable?

Unresolved answers remain unresolved evidence. They should not be converted into an automated “ready” label.
