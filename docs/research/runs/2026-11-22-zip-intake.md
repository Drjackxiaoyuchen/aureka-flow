> Historical ZIP-intake run, integrated with current main on 23 November; see [the integration record](2026-11-23.md).

# 22 November 2026: direct FCS ZIP import

## Starting state and scope

Verified the remote and a clean local checkout at `8f649109d42af21e822b3f698273bb10e6c4348b`. Main remains `adf7849557dc437b2a0c57e12f99899397b4932c`; PR #2 is still open. Used a separate `codex/fcs-zip-intake` worktree based on PR #2, keeping the existing checkout and running user workspace separate. This is a stacked change targeting PR #2's branch.

The next priority remains validation against permitted real FACSMelody/FACSChorus and FACSDiva exports. No verified real fixture was selected in this run. Chose the next concrete intake improvement: uploading ZIP-contained FCS without a separate extraction step.

## Public-source scout

Accessed 22 November 2026; source claims below are not locally reproduced instrument results.

| Source | Finding and decision |
| --- | --- |
| [Python 3.11 zipfile documentation](https://docs.python.org/3.11/library/zipfile.html#decompression-pitfalls) | Documents CRC/compression failures and resource pitfalls. Used the standard reader with prechecked directory limits, selected-member reads, expanded-data caps and no filesystem extraction. No external archive package added. |
| [PKWARE APPNOTE 6.3.10](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT), section 4.3.16 | Checked the ordinary end-of-central-directory fields for a small preallocation budget check. Used stored/Deflate ordinary ZIP only. Linked the specification without copying or redistributing it. |
| [FlowKit 1.3.2 release](https://github.com/whitews/FlowKit/releases/tag/1.3.2), commit `f215904`, BSD-3-Clause | Reports a FlowJo 10 workspace fix for a missing spectral attribute. Queued version-specific replay regression work; kept the already-tested FlowKit 1.2.3 for this archive-only change. No dependency upgrade. |
| [FlowJo 11.0.2 release notes](https://www.flowjo.com/docs/flowjo11/welcome-version-11/release-notes/version-1102-release-notes) | This particular version lists FACSMelody loading and matrix-normalization limitations. Future reference comparisons must record the exact software version. Did not generalize those issues to current FlowJo releases or claim Aureka equivalence. |

Targeted public GitHub/Hugging Face and web searches did not yield a verified, licensed FACSMelody fixture selected for this run. Cornell's facility page could not be retrieved (502/DNS); no current page content was used as compatibility evidence. No public dataset or model was downloaded or integrated.

## Implemented and tested

- ZIP upload works through the existing analyzer and validation-page file picker/drop workflow. Nested FCS members retain their identity; non-FCS content is skipped with an explicit count.
- Preserved archive SHA-256/name and member path/CRC32 alongside each FCS byte hash, including multiple archive memberships for a deduplicated sample. Original event order and values remain intact in synthetic reference cases.
- Added directory, entry-count and expanded-data limits before parsing, plus rejection of unsupported structures. Resource-fork files and nested archives are not interpreted as samples. Member-level errors preserve valid imports and release budget reservations.

Local validation: **310 Python tests and 351 subtests passed**, no skips; one existing Starlette TestClient deprecation warning. Node intake/gating tests and app/experiment/report-intake syntax checks passed. The synthetic walkthrough retained the 501 / 7,357 / 15,795 reference counts; the workflow demo passed. Browser inspection uploaded one synthetic ZIP, loaded three 30,000-event samples and visibly reported one skipped non-FCS item. Tests cover Unicode/nested paths, duplicate hashes, identity/order/provenance round trips, global/expanded budgets, malformed/CRC/encryption/compression failures, unsafe/duplicate paths and metadata allocation limits. CI results remain on the PR, separately from these local checks.

## Limits and next step

Validation used generated ZIP/FCS fixtures, not actual BD exports. ZIP support is a file-intake convenience; exact Chorus/Diva export versions, preprocessing and compensation still require real fixtures and independent comparison. Next: obtain that evidence, then assess explicit folder intake or gate editing according to the current queue. PR #2 remains a separate review prerequisite for this stacked change.
