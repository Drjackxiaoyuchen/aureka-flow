# Combine saved populations

Under **Saved populations**, choose **Combine gates · AND / OR / NOT**. Select the parent, enter a name, check the saved populations to combine and save. All operands must share that parent. Draw the source gates first; no positive, viability or singlet boundaries are inferred.

- **AND** selects events present in every checked population.
- **OR** selects events present in any checked population; overlapping events count once.
- **NOT** takes exactly one population and selects events in its parent that are outside it. It never adds events from outside that parent.

Counts and percentages use the complete source event arrays, independently of display sampling. Percent of parent uses the chosen Boolean parent; percent of total uses all parsed source events. A result can be selected, backgated, compared and plotted on any display channels, or used as the parent of a new geometric gate.

Each input retains its own saved transforms and compensation. A Boolean result has no additional compensation pass or geometric boundary; project schema 4 records its compensation as `null`. Selecting it keeps the current plotting axes and value display settings. Those display settings determine plotted values/medians, not the saved membership.

## Edit and undo

Click **Edit** beside a Boolean population to change its name, operation or operands. Its parent stays fixed. Only earlier saved populations with the same parent are offered, preventing forward references and cycles. Existing Boolean populations can themselves be operands, so larger expressions can be built in steps. AND/OR support 2–16 distinct inputs; NOT supports one.

Renaming an input updates every Boolean reference to it and its children's parent links. Editing any source gate invalidates all sample result caches; Boolean dependents and descendants recalculate from complete events. An incompatible sample reports an error rather than receiving a guessed channel mapping.

Deleting an input also deletes Boolean populations that depend on it, their dependents and their children. The confirmation lists affected populations. **Undo gate / Redo gate** restores/reapplies the entire change within the existing 20-step/2-MiB session history. Save a project before replacing source/compensation contexts; imports reset history.

## Save, export and scope

Projects containing Boolean populations use **schema 4**; schemas 1–3 remain supported for their existing geometric workflows. Load schema 4 with this version or newer. Projects retain full input definitions and source hashes, while event data stay in the original FCS files. GatingML exports remap both gate names and Boolean references to XML-safe IDs. Synthetic round trips through FlowKit 1.2.3 reproduce every tested original event membership for AND, OR, NOT, nested logic and geometric children, including reviewed XML compensation.

Event/statistics downloads use the selected membership. Experiment measurement exports include all required operand definitions and ancestors, not only the result's parent chain. Source event indices stay zero-based in the original DATA order. These tests establish Aureka/FlowKit export replay for the supported gates; they do not establish event-level FlowJo equivalence or vendor instrument compatibility. The separate [public stored-count qualification](PUBLIC_REFERENCE_VALIDATION.md) remains failed.

Arbitrary cross-parent combinations, XOR as a primitive, automatic generation of all marker combinations and direct FlowJo workspace writing are outside this first version. More complex expressions can use intermediate sibling Boolean populations. Fluorescence/binding selections remain assay-specific and do not infer affinity or cellular function.
