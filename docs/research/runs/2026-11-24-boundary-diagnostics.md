# 24 November 2026: diagnose stored-count disagreement without changing gates

## Source and integration state

Read the latest shared JSON receipt and verified both local remotes, worktree heads, recent commits, instructions, README, feature review, roadmap, ledgers, open PRs and current CI. PR #5 remained open at `a9d47ae0062954296955a9fab0dbc460ce13b498`. Main had advanced to `535b697d0ceb5be51afd892578317b54982f0d40`, adding FACSDiva XML preservation/reconstruction. Integrated that main into the indicated isolated validation branch, preserving both roadmap entries. The primary checkout, running app and original cloud-backed checkout were untouched. No private sample was read or uploaded in this run.

## Delivered improvement

Added optional `--diagnostics` to the workspace comparison command. Its local JSON binds the workspace and FCS hashes to complete gate paths, parent denominators and membership fingerprints in original event order. For supported rectangles it records literal bounds, imported transform parameters, the effective matrix identity, occupancy below/on/above boundaries and up to 20 excluded source event indices. Counts and membership checks use all events; the index preview is explicitly limited.

The diagnostic uses a separate NumPy matrix solve and interval arithmetic. It reuses FlowKit's imported transforms and replayed parents. Derived dimensions, inferred aliases, embedded `FCS` compensation references and nonrectangle geometry are explicitly undiagnosed. It does not emulate FlowJo binning/clipping or provide independent FlowJo masks. The frozen qualifier now requires all nine expected rectangles to be diagnosed with zero membership differences, in addition to its existing strict import/count checks. No numerical production engine or browser UI behavior changed today.

## Locally reproduced public-data evidence

Reused the pinned FlowKit 1.2.3 public FCS/WSP already acquired outside the repository; input hashes remain unchanged. All five import checks passed, as before. All nine literal rectangle masks matched the FlowKit masks event for event. The remaining five gate geometries were not independently checked by this new diagnostic.

The first count discrepancy is Time: 290,172 stored versus 290,166 replayed. Source indices 0–5 fall below the imported Time minimum (approximately 1.28 after FCS Time preprocessing; their source values span approximately 1.251–1.277). Neither Time boundary has exact hits. Every event passes the associated FSC-A bounds. Exact-boundary strictness therefore cannot explain this first discrepancy. This localizes the replay exclusions; it does not establish why the stored FlowJo count includes more events or prove that the stored statistics used identical source bytes/settings.

Count qualification remains **failed**, with **5/14** exact matches, maximum difference **690 events** and maximum parent-frequency difference **0.2360868659 percentage points**. The command returned **1** and retained `qualification_passed: false`. The committed observed report was refreshed from this actual run and its recorded source-code hashes verified. Gates, source counts and acceptance tolerances were not adjusted.

## Influential public sources

Accessed 24 November 2026. External material was evidence only; no new package, model or dataset was adopted.

| Primary source | Finding and decision |
| --- | --- |
| [FlowKit issue #280](https://github.com/whitews/FlowKit/issues/280), opened 2 June 2026; reporter uses FlowKit 1.2.3 / FlowJo 10.10.1 | Reports disagreement for gates extending past chart edges. Maintainer discusses binning and the difficulty of reliably inferring plot edges. Added transparent bound/occupancy evidence instead of guessing clipping rules. This other dataset does not establish this fixture's cause. |
| [FlowKit issue #113](https://github.com/whitews/FlowKit/issues/113), maintainer explanation 17 June 2022 | Describes polygon/ellipse binning using a synthetic line example. Candidate for a future controlled geometry comparison; not locally reproduced here. No binning workaround adopted. Installed 1.2.3 source was inspected for exact lower-inclusive/upper-exclusive rectangle behavior; BSD-3-Clause attribution is already retained. |
| [FlowJo transform documentation](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-transform-overview/) | Distinguishes lookup-table Biex from equation-based Logicle/Asinh and describes compensation-linked transforms. Retained explicit transform identities and restricted the independence claim to matrix/interval arithmetic. |
| [ISAC Gating-ML 2.0 paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC4874733/) and [Gating-ML methods paper](https://doi.org/10.1002/cyto.a.20637) | Mathematical gate and transform definitions motivate explicit boundary semantics. No standards-compliance claim is added by this diagnostic. |
| [Bioconductor flowWorkspace](https://bioconductor.org/packages/release/bioc/html/flowWorkspace.html) and [CytoML](https://bioconductor.org/packages/release/bioc/html/CytoML.html) | Accessed pages report 4.24.0 and 2.24.0, AGPL-3.0-only. Independent R replay could be useful corroboration, but is still another computed reference, not a FlowJo membership export. No dependency or source code incorporated; no R results claimed. |
| [Hugging Face spectral-myeloid card](https://huggingface.co/datasets/frankimm/spectral-myeloid-phenotyping-data) | Revisited specifically for event-membership evidence: card describes indexed memberships, separate checksum files and CC-BY-4.0 Cytek Aurora material. Its different instrument/sample identity cannot resolve these LSRII events. No download or model adoption. |

FlowRepository's Gating-ML support page returned a gateway error during access; it was not treated as newly verified evidence. Public source explanations are distinct from the reproduced observations above.

## Validation

**357 Python tests and 351 subtests passed**, no skips, with one existing Starlette TestClient deprecation warning. Thirteen new synthetic cases cover exact/open boundaries, nonfinite and empty parents, named compensation direction, transforms, complements, ancestry, bounded index previews, unsupported cases, direct CLI imports and source-bound report output. A deliberate equal-count/different-membership case verifies that count agreement cannot hide changed event identities.

Node intake/gating tests and all four current CI JavaScript syntax checks passed. Synthetic reference counts remain **501 / 7,357 / 15,795**. A fresh workflow demo and `pip check` passed. `git diff --check` passed. No UI change required browser inspection. Hosted checks are tracked on the exact published PR head; final commit/tree identities are recorded in the shared run receipt.

## Next priority

Obtain independent FlowJo event memberships and verify the source/settings lineage for this reference before attributing discrepancies. Replaying through another library is corroboration, not vendor ground truth. FACSMelody/FACSChorus fixtures with known export versions/settings remain unverified, and the separate private Diva example still needs usable vendor statistics/channel review. If those references are unavailable, progress the saved-gate editing/undo queue while keeping the failed qualification visible.
