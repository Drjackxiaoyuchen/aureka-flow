# Review BD FCS imports

Start with FCS files exported by the acquisition software. Aureka Flow currently provides file-based analysis; instrument control, live acquisition, proprietary experiment databases and automatic import of FACSChorus gates are not implemented.

FACSDiva experiment XML has a separate [preservation and reviewed gate-reconstruction workflow](BD_XML_IMPORT.md). It keeps the complete original export and can apply explicit, per-sample XML compensation; it does not imply support for the FACSChorus XML format.

You can now upload an ordinary `.zip` containing FCS files directly. Nested folders and Unicode member names are preserved in provenance. Only FCS samples are read; accompanying reports, macOS resource-fork files and nested archives are skipped, with a count shown after import. Keep the original archive: saved projects retain its name and SHA-256, each member's path/CRC32, and the SHA-256 of the actual FCS bytes, rather than embedding the archive.

Identical FCS bytes reuse one sample while retaining distinct archive memberships. Same-named members in different folders remain distinct when their bytes differ. The app reads selected members in memory and does not extract them to disk. Archive structure/limit errors reject that archive before importing its samples. Individual FCS read/parse errors identify the affected member; other valid samples can still load. Review the ready count and any errors before analysis.

ZIP intake supports stored/Deflate compression and complete, single-volume archives. Encrypted FCS members, links/special files, unsafe or duplicate member paths and ZIP64 directories are unsupported. Defaults are 100 MB per uploaded archive and expanded FCS member, 300 MB of expanded FCS per request, 24 FCS members per archive, and 256 total entries / 2 MB of central-directory metadata. Existing workspace/global input budgets also apply. Each sample can retain up to 24 distinct archive memberships. These are bounded file-import rules, not a live or watched-folder connection.

After uploading, the import review below the sample name shows the source-reported cytometer (`$CYT`), file creator (`CREATOR`, when supplied) and embedded-matrix status. **View source details** contains the acquisition date, clock fields and timestep, exact channel labels, one-based parameter numbers, matrix details and original metadata. File creator can name export software; it is not an independently verified acquisition-software version. Missing fields stay unknown. Saved projects and analysis ZIPs retain the review and source SHA-256.

Use the detector (`$PnN`) to identify a channel and the stain (`$PnS`) as its optional label. Two channels can have the same stain label. Aureka preserves detector identity and parameter order; it does not assign expression/binding roles from dye names or rename detectors to guess compatibility.

Browser uploads and native batch analysis now preserve literal primary-TEXT values: dollar characters in detector/stain names, escaped separators, UTF-8 labels and value whitespace. Legacy Latin-1 is a compatibility fallback. For example, `FITC$-A` and `FITC-A` remain two distinct detectors, with the original parameter/event order. Repeated keywords (including case variants) are rejected before loading, rather than silently choosing a value. Primary TEXT is limited to 16 MiB and 4,096 parameters. DATA offsets, decoding and supported formats still use the pinned reader's strict checks.

If an older project was saved with a detector name that lost a dollar character or retained an escaped separator, review/recreate the affected gate using the original FCS detector identity. No alias is guessed. These changes cover Aureka's browser/native import paths; optional external FlowJo workspace replay still needs its own matched-file validation. The original FCS bytes are never rewritten.

Before constructing a sample, browser and native analysis also require the decoded DATA value count to equal `$TOT × $PAR`. An inconsistent event declaration or partial event row stops that file with an `FCS DATA` diagnostic containing declared events/parameters and decoded values. Re-export the complete file; the app does not truncate, pad or change `$TOT` to make it load. Multi-file/ZIP intake reports the affected file and continues with valid samples. HEADER/TEXT-only inspection still reports declarations without claiming event validation.

**Source values** means no additional compensation by Aureka. These values include FlowKit's standard FCS gain/log/time preprocessing. They may already reflect processing performed before export. The presence or absence of an embedded matrix cannot by itself establish that history.

**Embedded FCS spillover** applies the usable embedded matrix to the source values. Confirm the acquisition/export settings first to avoid applying compensation twice. Conflicting `SPILL` and `SPILLOVER` matrices, non-finite coefficients and matrices that cannot be parsed/applied are unavailable, with an explicit error. Equivalent numeric representations of the same matrix are accepted. Source-value analysis remains available; choosing the unavailable matrix does not silently fall back to another mode.

An analysis ZIP can be downloaded before drawing gates. It retains source review, statistics and optional source events. `gates.xml` is included only when saved gates exist; `manifest.json` records `gatingml_included`. Direct GatingML export requires a saved population.

## Batch processing

The native `aureka-flow-workflow core analyze` and `run` paths use the same embedded-matrix checks as the browser. With `compensation.state` set to `embedded`, conflicting `SPILL`/`SPILLOVER`, non-finite coefficients, and malformed or unusable matrices stop analysis before output is created. Equivalent numeric representations of the same matrix remain acceptable.

For reproducibility, native measurements retain a SHA-256 for every accepted embedded-matrix keyword in `processing.embedded_matrix_keyword_sha256`. The existing `embedded_spillover_sha256` field still identifies the preferred keyword (SPILLOVER, otherwise SPILL). `source_compensation_state` remains `unverified` in every native mode. The config's `uncompensated` and `already_compensated` states are user declarations: they read source values with no additional compensation and do not require a usable embedded matrix.

## Evidence and remaining validation

The [BD FACSMelody user guide](https://www.bdbiosciences.com/content/dam/bdb/marketing-documents/FACSMelody-ug-ruo.pdf) (23-18120-03, March 2020, page 61) describes recording FCS data and exporting via Data Sources. The [quick reference](https://www.bdbiosciences.com/content/dam/bdb/marketing-documents/BD-FACSMelody-FACSChorus-Quick-Reference-Guide.pdf) covers FACSChorus 3.0. These documents establish an export route, not validation of this application's compatibility with every BD software version.

The public automated fixtures have synthetic events and BD-like metadata. A private FACSDiva 8.0.1/LSRFortessa export has now been checked locally through the XML adapter; details and limits are in the XML guide. No authentic FACSMelody/FACSChorus validation is claimed. Matched vendor population statistics and verified channel identities remain necessary for cross-software comparison; internal membership/round-trip agreement does not establish vendor equivalence.
