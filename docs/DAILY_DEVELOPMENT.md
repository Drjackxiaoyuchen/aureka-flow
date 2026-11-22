# Daily development

Continue from the latest [run ledger](research/runs/), current source, recent commits and open PRs. Inspect repository instructions first. Keep each run focused on a useful implementation with reproducible validation and a short source-linked record. Preserve unfinished work and use a `codex/` branch. Do not repeat completed research unless new evidence affects the current priority.

The dedicated local checkout was recovered from the verified GitHub main commit on 21 November 2026. The original cloud-backed checkout was not modified. Keep experimental FCS files, workspaces, generated outputs and credentials out of commits.

## Completed in the current development branch

- Import review with source-reported instrument/creator/acquisition fields and parameter identities.
- Explicitly unknown source-compensation history, plus safeguards against conflicting or non-finite embedded matrices.
- Import-only analysis ZIP export without a misleading empty GatingML document.

## Next priorities

1. Obtain a small, permitted FACSMelody/FACSChorus fixture tied to a known export version and settings. Keep private files local; record hashes and provenance. Validate channel mapping, event order, preprocessing and compensation against an independent reference. Repeat for FACSDiva exports; do not assume equivalence between software families.
2. Assess robust multi-file import from an explicitly selected export folder, including incomplete writes, duplicates, clear errors and preservation of original files. Do not describe a folder import as live instrument integration.
3. Add saved-gate editing with undo/redo and descendant recalculation, then Boolean gates, named sample groups and per-sample overrides. Keep analysis settings and export semantics explicit.
4. Improve reusable plot layouts, annotations and vector exports while preserving the current purple/mint interface. Keep full-event statistics independent from display sampling.

Research GitHub, Hugging Face and other relevant primary public sources for the next chosen priority. Check licenses, versions, methods and evaluation evidence. Introduce models only when a defensible benchmark supports a useful benefit. Separate reported findings, synthetic checks and reproduced public-data results.

## Validation

Use the current CI commands in `.github/workflows/tests.yml`. Install the validation extra when running the complete plotting/reference suite. Add meaningful analytical reference tests for changed behavior and inspect the browser after UI changes. Publish a small, tested PR with exact validation results and material limits. Follow the user's current merge/release instructions.
