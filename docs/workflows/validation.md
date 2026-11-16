> Imported from yeast-facs-workflow at `19e3aa5`. For current installation and integration, start with the [Aureka Flow workflow guide](README.md). Historical software versions and validation results below describe the original repository.

# v0.1 validation record

Initial workflow verification: **2026-10-01**. The later gallery-extension checks are recorded separately below.

| Check | Observed result |
| --- | --- |
| Full suite in a newly created Python 3.13 environment with the `flow` extra | **168 tests passed; no skips, failures or errors** |
| Standard-library environment without the optional native runtime | **157 passed; 11 native tests explicitly skipped** |
| Optional runtime | FlowKit 1.3.2, FlowIO 1.4.0, FlowUtils 1.2.2, NumPy 2.5.3 |
| Package build/install and CLI entry point | Passed |
| Installed dependency consistency (`pip check`) | Passed |
| Synthetic demo | All six modules connected; fresh outputs and receipt hashes checked |
| Desktop browser inspection | Landing page, links, sort-seq table and SVG marker-report layout inspected |
| Publication hygiene | Inspected intended source/docs/tests; no private laboratory files, machine paths or credentials found |

Test groups: 40 core, 42 workbench, 27 sort-seq linkage, 28 orchestration, 17 native-pipeline/selection-contract and 14 SVG-report tests. Native tests generate their own FCS files; none comes from a laboratory acquisition. Some negative tests deliberately print expected rejection errors while the suite passes.

Fresh-environment installation used the package's declared dependency constraints; transitive versions were resolved at installation time. This record is not a lockfile or a promise of compatibility with every future dependency release.

The [GitHub Actions runs](https://github.com/Drjackxiaoyuchen/yeast-facs-workflow/actions) provide the live hosted-CI status; this record does not substitute for that status.

## Synthetic gallery extension

Verified on 2026-10-01 in the isolated Python 3.13 environment with both `flow` and `gallery` extras: **193 tests passed, with no skips, failures or errors**. The extension adds 13 simulation/contract tests and 12 rendering/provenance tests to the original 168.

Four PNG/SVG figures were regenerated from seed `20261001`, visually inspected, and checked through their local gallery page. The exact default simulation totals are **27,000 input events → 23,994 after the predefined time mask → 20,634 after the supplied expression rectangle**. These are invented-event bookkeeping results, not measured recovery rates.

The rendering checks use a smaller 100-event-per-sample fixture and verify PNG dimensions, parseable SVG, visible synthetic labeling, numerical consistency, original-array hashes, complete output manifests, valid local links and fresh-output protection. A dedicated CI job installs the optional plotting dependencies, runs the gallery tests, and regenerates the default gallery. No raw laboratory files enter these checks.

The gallery demonstrates the existing array-summary, metadata-join and count-linkage interfaces. It does not test native FCS decoding, discover a QC interval or derive the toy variant counts from event fluorescence. Native decoding remains covered separately by the original generated-FCS integration tests.

## Rationale and review-guide extension

Verified on 2026-10-01 in the same isolated Python 3.13 environment: **198 tests passed, with no skips, failures or errors**. Five offline documentation checks cover repository-relative links, Markdown anchors, accessible static SVG structure, diagram PNG dimensions and the worked review example's agreement with the committed synthetic summary. These checks do not automatically assess scientific claims or visual layout.

The six-stage rationale and [review guide](workflow-review.md) were cross-checked against the implementation and generated synthetic outputs. Manual review distinguished rejected input contracts, warning-only QC diagnostics, interpretation restrictions and researcher responsibilities. The new workflow diagram was visually inspected at full size and README scale; its [renderer](../../scripts/render_workflow_diagram.py) retains editable SVG text and a high-resolution PNG. Hosted gallery CI also regenerates this documentation diagram. No analysis algorithm or raw-data input was changed by this documentation update.

## Published-data extension

Verified on 2026-10-01 in the same Python 3.13 environment with `flow` and `gallery`: **242 tests passed, with no skips, failures or errors**; `pip check` passed. The 44 added checks comprise 4 padded-TEXT regressions, 15 published-table extraction/schema checks, 8 paper-figure rendering/provenance checks and 17 public-archive safeguards. The ordinary suite uses invented archive bytes for its negative checks and never downloads the SI.

Separately, the explicitly downloaded, hash-verified Ross (2021) supplementary FCS files passed both `inspect_fcs` and `analyze_fcs`: **13,899 buffer-blank events and 65,689 events from the E. coli acquisition**, with all events retained. Counts and selected-channel medians matched the native FlowKit arrays used for plotting. This is authentic-file compatibility for two bacterial acquisitions, not a yeast benchmark or an independent decoder-accuracy test. No FlowGateNIST gating/calibration algorithm ran.

The Adams et al. (2016) publisher Table 1 extraction was independently compared against its source HTML using a second parser: all 19 rows, 38 affinity records, replicate counts and source hashes matched. Nine approximate-bound records across five clones retain their qualifiers and null SEM; the other 14 clones form the fully quantified method comparison. These are published estimates, not new fits.

All three PNG/SVG figure pairs were regenerated and visually inspected; output hashes and source provenance are committed beside them. Dataset-specific CC-BY attribution is separate from the code's MIT license. No raw FCS binaries, private measurements or author implementation code were included. The gallery CI job now also checks and regenerates the published-table figures offline; it does not run the downloaded-SI example. See the [paper-data gallery](paper-data-gallery.md) for commands and the exact evidence boundaries.

## Not established

No biological assay validation, real-data performance benchmark, gate accuracy estimate, calibration qualification, reproducibility across instruments, complete security audit or comprehensive transitive-license audit. The upstream catalog is source-reviewed; its 34 projects have not all been executed or integrated.
