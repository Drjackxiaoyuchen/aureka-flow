# Review BD FCS imports

Start with FCS files exported by the acquisition software. Aureka Flow currently provides file-based analysis; instrument control, live acquisition, proprietary experiment databases and automatic import of FACSChorus gates are not implemented.

After uploading, the import review below the sample name shows the source-reported cytometer (`$CYT`), file creator (`CREATOR`, when supplied) and embedded-matrix status. **View source details** contains the acquisition date, clock fields and timestep, exact channel labels, one-based parameter numbers, matrix details and original metadata. File creator can name export software; it is not an independently verified acquisition-software version. Missing fields stay unknown. Saved projects and analysis ZIPs retain the review and source SHA-256.

Use the detector (`$PnN`) to identify a channel and the stain (`$PnS`) as its optional label. Two channels can have the same stain label. Aureka preserves detector identity and parameter order; it does not assign expression/binding roles from dye names or rename detectors to guess compatibility.

**Source values** means no additional compensation by Aureka. These values include FlowKit's standard FCS gain/log/time preprocessing. They may already reflect processing performed before export. The presence or absence of an embedded matrix cannot by itself establish that history.

**Embedded FCS spillover** applies the usable embedded matrix to the source values. Confirm the acquisition/export settings first to avoid applying compensation twice. Conflicting `SPILL` and `SPILLOVER` matrices, non-finite coefficients and matrices that cannot be parsed/applied are unavailable, with an explicit error. Equivalent numeric representations of the same matrix are accepted. Source-value analysis remains available; choosing the unavailable matrix does not silently fall back to another mode.

An analysis ZIP can be downloaded before drawing gates. It retains source review, statistics and optional source events. `gates.xml` is included only when saved gates exist; `manifest.json` records `gatingml_included`. Direct GatingML export requires a saved population.

## Evidence and remaining validation

The [BD FACSMelody user guide](https://www.bdbiosciences.com/content/dam/bdb/marketing-documents/FACSMelody-ug-ruo.pdf) (23-18120-03, March 2020, page 61) describes recording FCS data and exporting via Data Sources. The [quick reference](https://www.bdbiosciences.com/content/dam/bdb/marketing-documents/BD-FACSMelody-FACSChorus-Quick-Reference-Guide.pdf) covers FACSChorus 3.0. These documents establish an export route, not validation of this application's compatibility with every BD software version.

The automated import fixtures have synthetic events and synthetic BD-like metadata. They verify source preservation, detector/stain mapping, matrix failure handling and exports. No real FACSMelody/FACSChorus or FACSDiva file was tested in this change. Validation still needs permitted source files tied to known instrument/software/export versions and matched reference analysis. No cross-software or event-membership equivalence is claimed.
