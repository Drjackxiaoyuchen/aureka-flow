# Experiment workflows in Aureka Flow

Aureka Flow v0.5 combines interactive gating with the useful parts of the former `yeast-facs-workflow` repository. One installation now provides acquisition QC, explicit sample metadata, experiment reports, reproducible batch processing, and optional linkage to decoded sequencing counts.

## In the browser

1. Upload FCS files and save your populations as usual.
2. Use **Acquisition QC** beside **View source details** to inspect Time consistency, backward steps and non-finite detector values. These diagnostics do not remove events.
3. In **Compare samples**, check the samples and choose a population.
4. Under **Experiment report**, download the sample manifest. Edit condition, biological-replicate and batch identities in its JSON, then load the edited file. The stable `sample_id` is the original FCS SHA-256. Keep it unchanged. Leave unknown identities `null`.
5. Download the report ZIP, extract it, and open `index.html`.

Without a manifest, condition is `Unspecified` and replicate/batch identities remain unknown. The report flags missing metadata, repeated biological identities, processing differences, insufficient replicates, and cross-batch comparisons. These are descriptive restrictions, not assay validation.

The ZIP includes `measurements.json`, `samples.json`, `05-report/experiment.json`, an offline HTML/SVG report, `project.json` and a file-hash receipt. `measurements.json` records exact selected original-event ranges, source hashes, full gate ancestry, compensation and per-channel finite denominators. It does not embed FCS events. Keep the sources.

**Report medians use linear, FlowKit-preprocessed detector values with the requested compensation.** They can differ from the transformed medians shown in the comparison table. Saved gates retain their original transforms and compensation when determining membership. The report uses the chosen X/Y detector summaries. Synthetic demo samples and uploaded samples must be reported separately.

## Local batch commands

Install [Aureka Flow](../../README.md#quick-start) once, then run:

```sh
aureka-flow-workflow demo --output exports/workflow-demo
aureka-flow-workflow modules
aureka-flow-workflow core --help
aureka-flow-workflow workbench --help
aureka-flow-workflow sortseq --help
```

The same CLI is available as `python -m aureka_flow workflow` or `python -m aureka_flow.workflows`. The browser launcher remains `aureka-flow`.

For real FCS inputs, supply an explicit processing configuration per acquisition and a sample/run manifest, following the retained [input formats](input-formats.md):

```sh
aureka-flow-workflow run --manifest /path/to/run.json --output exports/my-run
```

Relative paths resolve against the run manifest. Outputs require a fresh directory. Duplicate acquisitions, ambiguous joins and source/mask hash mismatches are rejected. External QC masks are accepted only against the original event count and source hash; the named external QC method is not executed by Aureka Flow.

The batch adapter supports supplied fluorescence rectangles in linear detector units. Use the browser for polygon, scatter, histogram-range and nested gates. Browser report exports feed their exact gate membership into the same experiment-report engine; they do not rerun the simpler batch rectangle adapter.

Optional sort-seq linkage joins explicit FCS sample, sort-bin, sequencing-sample and variant IDs. It preserves missing-versus-zero counts and keeps read fractions separate from sorted-event counters. For a browser-exported report:

```sh
aureka-flow-workflow sortseq link --experiment extracted/05-report/experiment.json \
  --sort-bins /path/to/sort-bins.json --counts /path/to/counts.json \
  --output exports/linked-counts
```

Use source SHA-256 sample IDs from the report in the bin map. There is no raw-read decoding, enrichment correction or affinity fitting.

## Examples, evidence and provenance

The [synthetic gallery](demo-gallery.md), [published-data gallery](paper-data-gallery.md), [review guide](workflow-review.md), [architecture](architecture.md), and [upstream catalog](upstream-catalog.json) remain available. Their original scientific values and attribution are preserved. Historical validation/version statements are labeled as such; the current runtime is Aureka Flow's **FlowKit 1.2.3**. Generated native fixtures test this adapter under that version.

Install `python -m pip install '.[docs]'` to reproduce the figures:

```sh
python examples/workflows/gallery/build_gallery.py --output exports/workflow-gallery
python examples/workflows/papers/build_paper_gallery.py --output exports/paper-gallery
```

The original [MIT license](../../aureka_flow/workflows/LICENSE) covers the imported workflow code. Published data retain their [separate attribution and licenses](papers/ATTRIBUTION.md). See the [consolidation record](MIGRATION.md) for the source commit and adoption decisions. Fluorescence, gate fractions and sequencing-read fractions remain distinct from solution affinity and cellular function.
