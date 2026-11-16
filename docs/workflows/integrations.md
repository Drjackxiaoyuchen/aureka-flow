> Imported from yeast-facs-workflow at `19e3aa5`. For current installation and integration, start with the [Aureka Flow workflow guide](README.md). Historical software versions and validation results below describe the original repository.

# Why these tools, and how they fit together

**The integration target is a traceable analysis, not a collection of installed packages.** Yeast FACS work needs more than a decoder or attractive plot: an acquisition must stay connected to its sample identity, event-selection decisions, comparison conditions and, where relevant, sorted material and sequencing counts. This project adds those connections while reusing a bounded upstream cytometry runtime.

Source review date: **2026-10-01**. The [34-repository catalog](upstream-catalog.json) records source snapshots, potential roles and licensing caveats. It is a research and attribution record, **not 34 implemented integrations, a compatibility matrix or a performance benchmark**. Pinned source commits describe what was reviewed; they are separate from the FlowKit 1.3.2 package version used by the optional runtime.

## Read the status before reading the tool name

| Status | What it means here | Examples |
| --- | --- | --- |
| **Native runtime — implemented** | Our code calls the package's public API, with synthetic integration tests | FlowKit; its FlowIO/FlowUtils dependency stack |
| **File contract — implemented** | Our code validates a supplied artifact; it does not execute the program that produced it | Hash-bound original-event QC masks; explicit sample manifests; decoded variant counts |
| **Adapter candidate — not implemented** | A potential future connection needs execution, interoperability, scientific and license checks | PeacoQC, FlowGateNIST, FlowCal, wellmap, dms_variants |
| **Methodological or alternative-workflow reference** | Useful for understanding an assay or another software architecture; no adapter or method is claimed | 16_titeseq, ggcyto, the R cytometry stack |

The workflow's original contributions are configuration validation, exact identity joins, event-denominator accounting, evidence restrictions, reporting, run receipts and sort-count linkage. No third-party implementation or dataset is copied into this distribution.

## Six stages, one chain of evidence

The stages below describe the workflow's responsibilities, not six separate software installations. They share [versioned contracts](architecture.md) and a single run receipt. The order is conceptual: for example, FlowKit preprocessing and the selected compensation happen before the wrapper summarizes events; QC mask retention and rectangle selection are then counted separately.

### 1. Ingest and identify — know which acquisition belongs to which sample

**Why it exists.** Correct fluorescence values attached to the wrong condition still produce a wrong analysis. The input boundary therefore keeps file identity and experimental identity distinct and joins them explicitly.

**Upstream role.** [FlowKit's reviewed README](https://github.com/whitews/FlowKit/blob/f2159043b6a56e527d4baacf97490caf8354618e/README.md) documents FCS loading and compensation. The native adapter calls `flowkit.Sample(..., preprocess=True)` for event decoding and metadata-based preprocessing. [FlowIO](https://github.com/whitews/FlowIO) and [FlowUtils](https://github.com/whitews/FlowUtils) are runtime dependencies, not separately reimplemented decoders. The workflow's own bounded HEADER/TEXT inspection and hashing are an input audit, not a replacement FCS event reader.

**Our design choice.** Require explicit `sample_id` joins, retain the exact input SHA-256, and reject repeated paths or identical input content in one composed run. [wellmap](https://github.com/kalekundert/wellmap/blob/be4a0533fa9ddbdcab81e82d78b63cf8638b68a3/README.rst) offers a human-readable TOML plate-layout format, making it a useful future metadata adapter. It is **not currently imported**; folder names and well positions are not guessed into biological identities.

**Cross-check.** Match the file hash and detector names to the intended acquisition; review the explicit condition, batch, control and replicate declarations in the sample manifest. Software can check agreement between identifiers, not whether the wet-lab label was correct.

### 2. Acquisition QC — explain every event removed

**Why it exists.** An event-selection decision must remain reviewable after later plots and medians are produced. A filtered event count alone cannot establish what was discarded or why.

**Upstream role.** [PeacoQC's reviewed README](https://github.com/saeyslab/PeacoQC/blob/1c0ff6d3123840c7fff198864b99a9421ab5a897/README.md) describes detection/removal of unstable acquisition events and visual QC. It is a candidate for an external QC producer, not an algorithm bundled here. flowAI and flowCut are alternative reviewed QC references, not additional filters silently stacked into the pipeline.

**Our design choice.** Implement time/non-finite diagnostics and a narrow `yeast-facs-qc-mask/v1` file contract. A supplied mask must match the input hash and decoded event count, and retain unique, bounded, zero-based original indices. Its named method is attribution only: the workflow does not execute that method or verify its scientific appropriateness. Native R invocation and mask export require a future tested adapter.

**Cross-check.** Inspect the time trace and external QC report, reconcile retained/removed counts, and confirm that the mask refers to the unmodified acquisition. No mask means no automatic acquisition-QC exclusion. A structurally valid mask is not a QC acceptance verdict.

### 3. Compensation and selection — make the measurement definition explicit

**Why it exists.** A selected-population median is only interpretable when its compensation state, coordinates, boundaries and denominator are known.

**Upstream role.** FlowKit applies an embedded spillover matrix when explicitly requested. We reuse that implementation rather than write another compensation engine. The present wrapper does **not** expose FlowKit's full gate hierarchy, transforms or workspace import: it implements an intersection of supplied fluorescence rectangles itself.

**Our design choice.** Require a declared compensation state and reason. Apply supplied bounds in linear values after preprocessing and the selected compensation, retain negative values, and record the selected original-event ranges. `already_compensated` remains a user assertion. [FlowGateNIST](https://github.com/djross22/flowgatenist/blob/2b5e6b2095422a656b458a867e677ff7a68f9b9b/README.md) is especially relevant to small-cell workflows because it describes blank-referenced cell discrimination, pulse-shape singlet selection and bead calibration. [FlowCal](https://github.com/taborlab/FlowCal/blob/0212f417a53b2fc76658d83b751b892f2d05f175/README.rst) provides density gating and bead-based calibration. Both are **future candidates**, not currently executed features.

**Cross-check.** Review compensation controls, detector units, negative values and the exact gate boundary semantics. Independently establish yeast, singlet, viability or expression-population identity with appropriate controls; a rectangle and a label do not establish those identities. Calibration needs measured controls and correct bead reference information, not merely an installed package.

### 4. Experiment comparison — distinguish a sample from its events

**Why it exists.** Many events do not create many independent biological replicates. Different acquisition settings or batches also do not become comparable merely because their values fit into one table.

**Upstream role.** wellmap can potentially translate a declared plate layout into metadata. [CytoNorm's reviewed workflow](https://github.com/saeyslab/CytoNorm/blob/278f352d8edffd7a5d3e6b0b76c402d991a1e7a9/README.md) illustrates why reference-based batch normalization is a distinct modeling step: its recommended workflow carries controls across batches and uses separate validation samples. Neither tool is executed here.

**Our design choice.** Preserve acquisition identity, condition, biological-replicate, control and batch declarations; report per-channel finite denominators; and propagate comparison restrictions. Repeated acquisitions retain the same biological-replicate ID rather than becoming new independent replicates. Cross-batch biological comparison is restricted without stopping report generation; no normalization is applied. Missing biological-replicate metadata remains visible. Statistical inference and experimental-layout optimization are outside this alpha.

**Cross-check.** Identify the true experimental unit, inspect differences in processing/settings, and decide whether the displayed samples answer the same question. Do not interpret pooled event counts as biological sample size or treat a successful metadata join as validated experimental design.

### 5. Reporting — expose decisions, not just attractive results

**Why it exists.** A shareable figure should make it possible to inspect its denominator, sample identity and processing decisions. Otherwise it is difficult to reproduce or challenge the result.

**Upstream role.** [ggcyto](https://github.com/RGLab/ggcyto/blob/2484d0d88328e9ff72d36f422dd4eaef9755b571/README.md) is an alternative R plotting approach for gated and annotated cytometry objects. It is credited as a reviewed option, **not used or copied** in this project's report generator. FlowKit also has plotting capabilities; the wrapper does not currently expose them.

**Our design choice.** Generate original self-contained HTML/SVG sample-median plots, denominator tables, warnings and JSON evidence. The optional NumPy/Matplotlib [synthetic gallery](demo-gallery.md) adds reproducible event-density and distribution examples; those gallery plots are not automatic real-FCS report features. The receipt hashes generated outputs for integrity checking, not for scientific certification.

**Cross-check.** Trace a plotted point to its measurement record, finite count, selection and sample metadata. Review warnings before sharing. Local outputs can retain filenames and labels and are not automatically anonymized.

### 6. Sort-seq linkage — connect counts without inventing affinity

**Why it exists.** A sort-bin label, a sequencing-sample ID and a variant count table refer to different parts of the experiment. They must be linked before any assay-specific inference can be justified.

**Upstream role.** [dms_variants](https://github.com/jbloomlab/dms_variants/blob/4e943d0417d19a347c51ae6f19c827f0f4023aa4/README.rst) analyzes barcoded deep-mutational-scanning variants and supports global-epistasis models. [16_titeseq](https://github.com/jbkinney/16_titeseq/blob/54130c8fc6081bbfa8301c41e1afcfa6a5d79590/README.md) supplies study-specific Tite-Seq analysis, including separate sort counts, titration data and an affinity-inference algorithm. These show why a descriptive count join is not an affinity estimator. Neither analysis is executed here; 16_titeseq is a methodological reference only.

**Our design choice.** Join an analyzed acquisition to an explicit sort-bin/sequence-sample map and already-decoded variant counts. Preserve missing entries as missing, keep declared sorted-event counters separate from sequencing-read totals, calculate within-sample read fractions, and carry upstream evidence restrictions forward. No FASTQ decoding, enrichment model, dose-response fit or Kd inference is hidden behind the bridge.

**Cross-check.** Reconcile sample IDs, complete bin accounting, count denominators and library mapping. An inference extension would additionally need concentrations/units where relevant, sampling and selection factors, appropriate replication, a specified assay model and fit diagnostics. Read fractions alone are not cell fractions or affinity.

## Why defer other capable packages?

Deferral is a scope decision, not a ranking of scientific quality. This alpha favors one tested native cytometry runtime and explicit file boundaries over installing several stacks whose outputs have not been shown to agree for the intended assay.

| Candidate or alternative | Why the adapter is deferred | Evidence needed to add it |
| --- | --- | --- |
| PeacoQC / other acquisition-QC engines | Native execution and original-index export are not implemented | Pinned execution, transformations/settings, exact mask alignment and review of removed intervals |
| FlowGateNIST / FlowCal | Automated population selection and calibration introduce assay-specific assumptions | Appropriate blanks/pulse channels/beads, retained event identities, numeric interoperability tests and yeast/instrument qualification |
| wellmap | The current contract starts at explicit sample records, not a plate-layout language | Tested TOML-to-manifest conversion, well/sample uniqueness and exact joins |
| openCyto / flowWorkspace / CytoML | An additional R/Bioconductor stack and richer gate/workspace semantics | Native runtime, coordinate/transform fidelity, source-engine event-count comparison and distribution/service license review |
| CytoNorm | Normalization is a model, not a metadata correction | Suitable shared references, declared assumptions and independent checks that biological shifts remain interpretable |
| dms_variants / drc | Count/sequence analysis and dose-response fitting require additional contracts and models | Library mapping or concentration units, complete counts, replication, model diagnostics and separate scientific validation |

Adapters should meet the [extension contract](architecture.md#adding-an-upstream-adapter) and have numerical tests before their status changes to implemented. Synthetic tests establish software behavior; real-data assay qualification is a separate requirement. No candidate algorithm is silently approximated by this project.

## Licensing and credit

- FlowKit, FlowIO and FlowUtils use BSD-3-Clause; the wrapper calls public APIs and copies no implementation. Optional dependencies retain their own licenses.
- PeacoQC's reviewed license is GPL-3.0-or-later. flowWorkspace, CytoML and openCyto have AGPL licenses in the catalog. Any future integration needs a review appropriate to its actual distribution and execution, not an assumption that a file boundary settles all obligations.
- FlowGateNIST has government-work notice/disclaimer conditions; these are not interchangeable with this project's MIT license. FlowCal and wellmap have MIT licenses in the reviewed snapshots.
- CytoNormPy and FACSPy had conflicting license signals in the reviewed snapshots: GPLv3 license/readme versus MIT packaging classifiers. Keep them reference-only pending clarification.
- No explicit license was found for 16_titeseq in the reviewed snapshot. It remains a methodological reference; this project redistributes none of its code or data.
- Downloading source does not authorize relicensing, embedding or public redistribution under this project's MIT license. The catalog is not a legal opinion or a complete transitive-license audit.

Upstream authors retain their credit and licenses. This project neither replaces their scientific methods nor claims their endorsement. Consult each pinned catalog entry and upstream license before extending or redistributing an integration.
