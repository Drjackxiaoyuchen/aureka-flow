> Imported from yeast-facs-workflow at `19e3aa5`. For current installation and integration, start with the [Aureka Flow workflow guide](../README.md). Historical software versions and validation results below describe the original repository.

# Published-data assets: attribution and license

The repository's MIT license covers its original code. It does **not** relicense the third-party data described here. The following curated data and dataset-derived figures/receipts are supplied under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/) ([legal terms](https://creativecommons.org/licenses/by/4.0/legalcode)). Retain credit, a license link and an indication of modifications when sharing. No endorsement by the authors is implied.

## Adams et al. (2016)

**Credit:** Rhys M Adams, Thierry Mora, Aleksandra M Walczak and Justin B Kinney. *Measuring the sequence-affinity landscape of antibodies with massively parallel titration curves.* eLife 5:e23156. Copyright holder: Adams et al.

**Source:** [Article](https://elifesciences.org/articles/23156), [Table 1](https://doi.org/10.7554/eLife.23156.018), [publisher JSON](https://api.elifesciences.org/articles/23156). Publisher copyright metadata states CC-BY-4.0; retrieved 2026-10-01.

**Covered assets:**

- [adams-2016-table1.json](../../../examples/workflows/papers/data/adams-2016-table1.json)
- [01-published-method-comparison.png](01-published-method-comparison.png) and [SVG](01-published-method-comparison.svg)
- [02-published-clone-intervals.png](02-published-clone-intervals.png) and [SVG](02-published-clone-intervals.svg)
- [adams-summary.json](adams-summary.json)

**Changes:** extracted clone IDs, replicate counts and affinity expressions from the publisher's HTML; omitted sequence columns; represented exponents/SEM numerically in log10 molar units; retained approximate-bound qualifiers; created new layouts, labels, plots and provenance receipts. No new affinity estimates were fitted. Source-byte and source-table hashes accompany the curated data. The publisher's license is not asserted to cover the separate author GitHub repository.

## Ross (2021)

**Credit:** David Ross. *Automated analysis of bacterial flow cytometry data with FlowGateNIST.* PLOS ONE 16:e0250753.

**Source:** [Paper](https://doi.org/10.1371/journal.pone.0250753), [supplementary dataset](https://doi.org/10.1371/journal.pone.0250753.s001), [dataset metadata](https://api.figshare.com/v2/articles/15210195). The dataset deposit states CC BY 4.0; checked 2026-10-01. This is distinct from the article's CC0 declaration.

**Covered assets:** [03-public-fcs-qc.png](03-public-fcs-qc.png), [SVG](03-public-fcs-qc.svg), and [flowgatenist-summary.json](flowgatenist-summary.json).

**Changes:** selected the buffer blank and E. coli Figure 2 acquisitions; decoded with FlowKit metadata preprocessing; retained every event without gating or compensation; applied documented display transforms; created new descriptive plots, summaries and provenance hashes. No FlowGateNIST algorithm or fitted gate was reproduced. The source archive and raw FCS binaries are not redistributed here.

## Original implementation

The [extractor](../../../examples/workflows/papers/extract_adams_table.py), [table renderer](../../../examples/workflows/papers/build_paper_gallery.py) and [raw-FCS demo](../../../examples/workflows/papers/build_fcs_si_demo.py) are original MIT-licensed project code. No upstream implementation was copied. Dependencies retain their own licenses. [Gallery and reproduction instructions](../paper-data-gallery.md).
