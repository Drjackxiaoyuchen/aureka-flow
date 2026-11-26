# FlowJo workflow review and Aureka Flow v0.4

Reviewed 5 November 2026 against official FlowJo documentation. These are established workflow features, not a usage-based popularity ranking. Aureka implements a focused subset for expression-versus-binding experiments; it is not a FlowJo replacement or a claim of numerical equivalence with every FlowJo workflow.

| Documented FlowJo feature | Why it helps yeast display | Added in Aureka Flow v0.4 |
| --- | --- | --- |
| [Backgating and ancestry](https://docs.flowjo.com/flowjo/graphical-reports/graph-options-and-annotation/) | Check where a selected expression/binding population lies on scatter or other detectors. | Purple selected events over a gray ancestor, on dot plots or shared-bin histograms. Full gate counts remain unchanged. Rare foreground populations are sampled independently of the background. |
| [Histogram overlays](https://docs.flowjo.com/flowjo/graphical-reports/graph-options-and-annotation/le-overlays/) and [Y scaling](https://flowjo.com/docs/flowjo10/graphical-reports/graph-options-and-annotation/le-graphdef) | Compare binding distributions among expressers across controls, rounds or clones. | Count, area and modal normalization; 32–512 shared bins; lines or fills; legends with finite-event counts; annotated PNG downloads. |
| [Batch analysis and tables](https://docs.flowjo.com/flowjo/getting-acquainted/fj-batching/) | Export recovery and frequency at every gate across multiple samples. | An all-populations table and CSV with paths, parent/total fractions, channel medians, source hashes and transform settings. The analysis ZIP can include this table. |

The app already applied one shared gate strategy across compatible samples, supported nested gates and quadrants, and exported projects, GatingML, event CSVs and statistics. The additions above make inspection and reporting easier without changing the numerical gate definitions.

## How the new displays are calculated

- **Backgating:** selected event membership comes from the saved FlowKit gate strategy. Context must be a strict ancestor. Dot plots show at most 25,000 finite pairs per layer; each layer is sampled independently. Counts and exports use all selected events. Histograms use full finite data with identical edges for foreground and ancestor; percentage bins use the finite ancestor as their denominator.
- **Overlay counts:** each bin contains its full event count. **Area:** `100 × bin count / finite population count`. **Modal:** `100 × bin count / largest bin count`. All samples share edges. Area/modal compare shapes and do not preserve absolute yield; no smoothing or automatic threshold fitting is applied.
- **All-population table:** each sample is analyzed independently using the shared saved strategy. A row's parent fraction uses its own saved parent, not the currently displayed population. Medians use the chosen channel transforms and exclude nonfinite channel values. Overlapping populations must not be summed as a partition.

The synthetic reference still returns 501, 7,357 and 15,795 double-positive events for the three demo samples. Tests additionally check rare-event backgating, valid ancestry, shared-bin normalization, table denominators, empty populations, CSV/ZIP contents and session isolation.

## Saved-gate editing, 24 November 2026

The current app adds **Edit** beside each saved population and **Undo gate / Redo gate** above the tree. Range/rectangle bounds and polygon vertices can be edited numerically in their saved coordinate system; a rename updates direct child references atomically. Parent, gate kind, detector names, transforms and compensation are retained. The updated strategy invalidates all sample result caches; descendants, statistics and exports are recomputed from full events. History stores only gate definitions, up to 20 changes within 2 MiB per session, and resets at project/XML imports or workspace clearing.

[FlowJo Editing Gates](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-gating/gw-gatechanging/) and [Graph Window undo/redo](https://docs.flowjo.com/flowjo/graphs-and-gating/gw-overview/) were functional references, accessed 24 November 2026. Original Aureka implementation; no FlowJo source/assets copied. This is numeric editing, not FlowJo's full graphical handle/drag interface. It does not establish cross-software gate equivalence.

## Useful future additions

Boolean AND/OR/NOT of saved sibling populations is now implemented with nested references, editable operands, dependency-aware rename/delete/undo and full-event project/GatingML replay. See the [Boolean guide](BOOLEAN_GATES.md) for parent/denominator rules and limitations. [FlowJo Boolean Gates](https://docs.flowjo.com/flowjo/graphs-and-gating/advanced-gates/ws-boolean/) was a functional reference, accessed 25 November 2026; this does not claim FlowJo event-level agreement.

1. **Extended Boolean workflows:** cross-parent combinations and optional generation of marker combinations need additional review and explicit scope rules.
2. **Named sample groups and per-sample gate overrides:** useful when an experiment needs different scatter/QC strategies. Current gates are shared across the entire browser workspace.
3. **Graphical saved-gate editing:** vertex/whole-gate dragging and explicit reparenting would complement the implemented numeric editor.

These candidates remain unfinished. See the [user guide](TUTORIAL.md) for the features available now.
