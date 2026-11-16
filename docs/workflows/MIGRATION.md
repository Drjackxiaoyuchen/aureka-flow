# Consolidation record

On 2026-11-16, the useful code, tests, documentation, reproducible examples and attributed public figures from `Drjackxiaoyuchen/yeast-facs-workflow` were incorporated into Aureka Flow. Source commit: `19e3aa587c4534bde833db34924136c4889f62e6`.

| Source capability | Decision in Aureka Flow |
| --- | --- |
| Bounded FCS inspection, source hashes and explicit processing | Retained under `aureka_flow.workflows.core`; adapted to the existing FlowKit 1.2.3 dependency. |
| Time/non-finite diagnostics and hash-bound external event masks | Retained in batch tools; acquisition diagnostics also available beside browser source details. |
| Metadata joins, replicate identities, batch restrictions and reports | Retained and connected to exact browser gate membership through the experiment-report ZIP. |
| Sort-bin to decoded variant-count linkage | Retained through `aureka-flow-workflow sortseq`; original identity and denominator contracts preserved. |
| Native FCS, failure-path, reporting, linkage and public-example tests | Migrated into `tests/workflow` and included in the normal test suite. |
| Synthetic and published-data figures, source values and scripts | Retained under `docs/workflows` and `examples/workflows` with original attribution. |
| A separate package, separate installation and separate GitHub project | Replaced by one Aureka Flow distribution and the `aureka-flow-workflow` command. |
| FlowKit 1.3.2 and optional gallery dependency pins | Not added. The adapter uses Aureka Flow's pinned FlowKit 1.2.3, and plotting uses its existing `docs` extra. |
| Automatic QC/biological gating, affinity fits and NGS inference | Not claimed or introduced; these were not implemented in the original repository. |

Legacy `yeast-facs-*/v1` JSON schema identifiers are retained for input and output compatibility. Producers now identify Aureka Flow. Original code retains its MIT license, including the copyright notice; the rest of Aureka Flow retains its existing license.

Before retirement, a full mirror and verified Git bundle preserved every advertised Git ref and history locally. The source had one branch, no tags, no issues/pull requests, no releases, and no forks at inspection. Historical documentation is retained in [the imported overview](legacy-overview.md); current instructions start in the [workflow guide](README.md).
