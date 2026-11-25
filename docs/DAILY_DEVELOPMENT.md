# Daily development

Continue from the latest [run ledger](research/runs/), current source, recent commits and open PRs. Inspect repository instructions first. Keep each run focused on a useful implementation with reproducible validation and a short source-linked record. Preserve unfinished work and use a `codex/` branch. Do not repeat completed research unless new evidence affects the current priority.

The dedicated local checkout was recovered from the verified GitHub main commit on 21 November 2026. The original cloud-backed checkout was not modified. Keep experimental FCS files, workspaces, generated outputs and credentials out of commits.

## Completed

- Boolean AND/OR/NOT of saved sibling populations, nested logical references, dependency-safe rename/delete/undo and project/GatingML replay; see the [Boolean guide](BOOLEAN_GATES.md).

- Import review with source-reported instrument/creator/acquisition fields and parameter identities.
- Explicitly unknown source-compensation history, plus safeguards against conflicting or non-finite embedded matrices.
- Import-only analysis ZIP export without a misleading empty GatingML document.
- Direct ZIP intake with expanded-data limits, per-member errors, skip reporting and archive/member provenance; synthetic fixtures verified.
- Consistent browser/native-batch rejection of conflicting or non-finite embedded matrices, with per-keyword hashes and explicit source-history uncertainty in native measurements.
- Lossless FACSDiva XML preservation, reviewed Diva 8.0/8.0.1 gate reconstruction, per-sample XML compensation and hash-bound replay; a streaming explicit-directory command supports larger experiments. See the [XML import guide](BD_XML_IMPORT.md).
- Optional full-event rectangle diagnostics with explicit bounds, transforms, matrix identities, parent denominators and source event indices. The frozen public reference's nine rectangles agree with literal replay arithmetic; stored FlowJo counts still fail qualification.
- Reviewed public-reference integration: a source-value detector also named in an active matrix now requires compensation review instead of being silently diagnosed; source scatter outside that matrix remains supported. The public example still has only 5/14 matching stored counts. See the [25 November integration record](research/runs/2026-11-25.md).
- Saved range/rectangle/polygon boundary editing and renaming, atomic descendant reparenting on rename, full-tree recalculation, and bounded session undo/redo for gate creation, edits, deletion and quadrants. Source/compensation imports reset history; final definitions replay through project/GatingML exports. See the [24 November record](research/runs/2026-11-24.md).

## Next priorities

The opt-in [public LSRII-reference check](PUBLIC_REFERENCE_VALIDATION.md) separates successful byte/preprocessing/compensation checks from failed exact stored FlowJo-count agreement (5/14 matches). Boundary diagnostics locate six early events below the imported Time minimum; exact-boundary strictness cannot explain that difference. Obtain independent FlowJo memberships and verify source/settings lineage before attributing the discrepancy or claiming equivalence; polygon geometry and upstream binning remain unverified. Keep the distinct FACSMelody/Diva validation priority below.

1. Obtain a small, permitted FACSMelody/FACSChorus fixture tied to a known export version and settings. Keep private files local; record hashes and provenance. For the now-available private Diva 8.0.1 example, obtain matching nonzero vendor population statistics and verify height/width identities before claiming count equivalence. Keep software families separate.
2. Consider browser folder selection and incomplete-write handling only if useful. ZIP intake and explicit local directory analysis are implemented; watched folders and live instrument integration remain separate work.
3. Add named sample groups and reviewed per-sample overrides. Boolean populations and numeric saved-gate editing/undo are implemented. Graphical vertex/whole-gate dragging, cross-parent Boolean combinations and explicit reparenting remain future extensions. Keep analysis settings and export semantics explicit.
4. Improve reusable plot layouts, annotations and vector exports while preserving the current purple/mint interface. Keep full-event statistics independent from display sampling.

Research GitHub, Hugging Face and other relevant primary public sources for the next chosen priority. Check licenses, versions, methods and evaluation evidence. Introduce models only when a defensible benchmark supports a useful benefit. Separate reported findings, synthetic checks and reproduced public-data results.

## Validation

Use the current CI commands in `.github/workflows/tests.yml`. Install the validation extra when running the complete plotting/reference suite. Add meaningful analytical reference tests for changed behavior and inspect the browser after UI changes. Publish a small, tested PR with exact validation results and material limits. Follow the user's current merge/release instructions.
