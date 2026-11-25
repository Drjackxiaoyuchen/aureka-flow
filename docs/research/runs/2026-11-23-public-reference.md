# 23 November 2026: frozen public-reference qualification

## Scope and source state

Read the latest shared run receipt, verified remotes, instructions, roadmap, prior ledgers, open PRs and current main. Main advanced from `78fd274de58eb3da54d7b465f7b19a6c97bb3d95` to `5c2e6351f36e7d15624be0eeb59ab71b0ee4f746` during this run as another run completed PR #3's ZIP integration. Preserved that published integration and used a separate `codex/public-bd-reference-validation` worktree based on the updated main. The existing primary checkout and user's running workspace were not changed. The original cloud-backed checkout was preserved.

## Source scout and acquisition

Accessed 23 November 2026:

- Inspected the [FlowKit 1.2.3 repository](https://github.com/whitews/FlowKit/tree/f1c3726c85cf312b9fdc12670a2783b2ef33ab25/data/8_color_data_set), its BSD-3-Clause license and exact Git blob identities. Retrieved one FCS and its WSP into a separate local reference directory. Verified sizes, Git blob SHA-1s and SHA-256s. Only hashes, provenance and aggregate comparison results are committed; no FCS/WSP binaries are redistributed.
- The [official Workspace tutorial](https://flowkit.readthedocs.io/en/latest/notebooks/flowkit-tutorial-part06-workspace-class.html) identifies the example's three samples and 14-gate workflow. The latest rendered tutorial describes a different FlowKit version; execution stayed pinned to installed FlowKit **1.2.3**. Only one explicitly selected sample was used, with the two unloaded samples retained in the report.
- Revisited the [Hugging Face spectral-myeloid-phenotyping-data card](https://huggingface.co/datasets/frankimm/spectral-myeloid-phenotyping-data) for independent event-reference suitability. Its card describes Cytek Aurora data and per-event references under CC-BY-4.0; those references cannot resolve membership differences for this LSRII example. No HF data/model was downloaded or adopted.

The selected public file reports `CYT=LSRII`, FCS 3.1, 290,172 events and 15 channels; `CREATOR` is absent and the filename ends `_clean.fcs`. The WSP reports FlowJo 10.6.2. These are source-reported fields, not independently verified instrument/export lineage. This does not establish authentic FACSMelody/FACSChorus or direct FACSDiva compatibility.

## Actual results

All source-import checks passed: full-array byte decoding/order after the file's Time scaling, additional matrix arithmetic, native batch counts/event ranges and fluorescence medians, and source hashes. Raw and additionally compensated array checks each had maximum absolute difference **0.0** against the independent NumPy references for this fixture.

Exact gate-count qualification failed: **5/14** stored counts matched, with maximum absolute difference **690 events** and maximum percent-of-parent difference **0.2360868659 percentage points**. CD8+/IL2+ differed by one event (11 stored versus 10 replayed), or **9.09% relative count**. The cause remains undetermined. No gates or source counts were tuned; no independent FlowJo event-membership masks were available. These are locally reproduced observations, not a software-equivalence or biological validation claim.

## Delivered improvement and checks

Added `scripts/qualify_public_reference.py`, a frozen input manifest and a complete observed report. The command makes no network requests, rejects wrong/extra/missing or changed inputs, preserves existing reports and records source-code hashes and software versions. An independent fixed-file decoder and matrix solve check numerical import behavior. Exact count acceptance remains strict: completed-but-failed qualification exits **1**, invalid input exits **2**. The observed public-data command returned **1**, with `qualification_passed: false`, as required by the count disagreement.

The software regression suite passed **332 Python tests and 351 subtests**, no skips; one existing Starlette TestClient deprecation warning. Eleven new offline cases check byte/order/Time handling, detector identity, reference-matrix rejection, complete/nonempty count evidence, immutable inputs, unrelated-file exclusion and CLI exit semantics. Node intake/gating tests and all three JavaScript syntax checks passed. The synthetic reference retained counts 501 / 7,357 / 15,795; workflow demo and `pip check` passed. No browser UI changed. Hosted CI is tracked separately on the PR.

## Next priority

Investigate the stored-count/replay differences with independent event memberships and explicit transform/boundary/export provenance. Do not infer the cause from the count pattern or relax acceptance to make the reference pass. Continue seeking a permitted FACSMelody export with known FACSChorus version/settings; validate other BD software families separately. Feature work on saved-gate editing remains in the existing queue.
