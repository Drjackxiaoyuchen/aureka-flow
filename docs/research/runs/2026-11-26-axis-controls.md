# 26 November 2026: flexible X/Y display controls

The user requested flexible control over X/Y axes. Read the latest receipt, repository guides/roadmap and verified Git/GitHub state. PR #8 has since merged; main is `ce9889fc5ddf040f4087a1c57589a425f0bfc830`, PR #9 now targets main, and PR #10 remains based on #9. Created isolated `codex/axis-controls` from latest development `a9170fbd45098bb538502eef9c401ac7d5f930ee`. Existing source checkouts and servers at 8879/8892 are preserved.

Added visible X/Y display range cards with independent Min/Max, per-axis Auto and Auto both axes. Validation accepts finite ordered bounds/scientific notation and validates both axes before mutation. Range fields identify the actual rendered coordinates, so pending transform edits cannot silently change the interpretation of an old plot. Values use the selected transformed scale.

Added an explicit Zoom toolbar tool beside Pan and enabled native wheel zoom where Plotly receives pointer input. Navigation bypasses the gate drawing overlay and synchronizes exact ranges through `plotly_relayout`. In-memory display ranges persist across compatible sample/population redraws; detector, scale/active transform parameters, compensation, axis orientation and histogram/overlay normalization define their scope. A 64-entry bound avoids unbounded UI history. Page reload clears display ranges; project JSON remains analytical gate definitions and source provenance. Current plot/overlay PNG exports retain the plotted window.

## Functional reference

Accessed 26 November 2026: official [Plotly axis ranges](https://plotly.com/javascript/axes/) and [relayout events](https://plotly.com/javascript/plotlyjs-events/). Used the existing installed Plotly public range/autorange and event interfaces; no new dependency, external code or assets adopted. These are display settings, not gate/biological inference.

## Validation and browser evidence

411 Python tests and 351 subtests passed, no skips, with the existing Starlette TestClient warning. Node intake, gate and new axis-range checks passed. Meaningful references cover invalid/overflow bounds, channel/transform/compensation identity, independent axes, captured array/indexed relayout payloads, automatic resets, bounded history, navigation without gate creation, and drawing geometry after changed display ranges. CI now runs the new axis checks and module syntax check.

Browser inspection used three known synthetic samples and the prior four-gate drawing/copy project. The older tab still showed cached plots, but its newly downloaded project had zero samples/gates; no cause was assumed. Recovered the last verified saved synthetic project into a separate preview at **127.0.0.1:8894**, leaving the old tab/server intact.

Verified manual X `0.3–0.8` / Y `0.2–0.9`, persistence on a saved population and across samples, rejection of X Min > Max without a plot change, and Auto X retaining Y. Actual rectangle zoom and pan updated both fields. Histogram count Y `0–100` stayed separate from percentage units. Overlay X `0.2–0.9` / Y `0–10%` survived a 100-to-32-bin redraw. Saved gate counts remained 17,676/11,063 in synthetic binding and 571/335 in control; original/copied branches still agree. A fresh browser-exported project had exactly the prior gate definitions and source hashes, checked outside Git.

The final preview is left open with the four restored gates and manual scatter ranges. Screenshot, project and local verification receipt are in ignored/local artifact directories. No experimental files or sample identifiers were committed. Numerical import/gating code did not change; the previous frozen public result remains 5/14 stored FlowJo counts, with hardware/vendor equivalence still unqualified. This UI change does not claim a fresh vendor qualification run.

## Next priority

Reconcile stacked PRs #9/#10 and this UI change through normal review. Preserve the new 8894 app/worktree while the user tries it, along with 8879/8892. Named sample groups/per-sample overrides and permitted version-bound BD reference fixtures remain separate priorities. Keep the user's whole-branch gate-copy default.
