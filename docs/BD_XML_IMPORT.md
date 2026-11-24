# Preserve and analyze FACSDiva experiment XML

Upload matching FCS files, then choose **Import gates · XML** in the browser. Select the worksheet and review the sample links. **Preserve original XML only** retains the complete source without applying instrument gates. **Reconstruct gates for analysis** replaces the current strategy after explicit review of channel identities, source compensation and reconstruction limits. Save the existing project first. Both actions replace the gate strategy; preservation-only leaves it empty.

The original XML is retained byte for byte with its SHA-256, including gate hierarchy, original vertices, scale flags/values, compensation coefficients, disabled/composite records, worksheet settings and sample references. **Download original XML**, project JSON schema 3, and analysis ZIPs preserve that source. Project JSON contains XML metadata, not FCS events; keep downloaded projects private. A saved XML project can be restored before its FCS files; re-uploading identical FCS bytes restores their matrix bindings even if the filename changes.

Initial binding uses one exact XML `data_filename` basename per FCS file and checks the FCS tube name when present. The FCS SHA-256 is then recorded for subsequent replay. XML GUIDs and FCS GUIDs are not assumed identical. Ambiguous names, duplicate bindings, missing channels and unbound FCS hashes cannot silently receive a strategy. Detector names are never swapped or guessed. Tube-specific worksheets cannot be applied globally, and conflicting tube overrides block global reconstruction.

## Reconstruction contract

The initial analytical adapter supports **FACSDiva 8.0/8.0.1** `bdfacs` experiment exports with region classifiers: polygons, rectangles and one-channel intervals. It recognizes an ordinary four-child quadrant binner, preserves its original record, and reconstructs disjoint, open-ended quadrant populations under the original parent. Other composites, Boolean/ellipse classifiers, disabled non-quadrant gates and unscaled logarithmic coordinates remain preservable but block reconstruction. Other BD software families, including FACSChorus, are separate formats.

Linear scaled coordinates map from 4,096 display units to 262,144 detector units. Scaled logarithmic coordinates use gate-specific normalized Logicle axes: `T=262144`, `M=4.5`, `A=0`; the published reconstruction sets `W=max(0,(M-log10(T/r))/2)` for positive scale value `r`, and `W=0` for zero. Original scale fields remain in the XML. This convention is described in [CytoML's FACSDiva adapter](https://github.com/RGLab/CytoML/blob/2a0502e7ae8c859b8a686536b6d9742cb9191c34/R/diva2GatingSet.R). Its source was consulted as an interoperability reference; no CytoML code or dependency was incorporated (AGPL-3.0-only).

**Reconstructed gates are not vendor-validated gates.** Diva uses its own display implementation. The adapter evaluates each polygon in its preserved gate-specific coordinate system, rather than treating display numbers as detector values or converting only polygon vertices into a different nonlinear space. Boundaries follow the existing FlowKit conventions: rectangle/range lower limits inclusive, upper limits exclusive; quadrant equality belongs to the positive side. Counts need comparison with FACSDiva statistics from the same FCS/worksheet/settings, particularly for events near boundaries.

Choose exactly one compensation source:

- **XML compensation:** coefficient rows describe output channels, so compensated events equal source events multiplied by the coefficient matrix transpose. A corresponding spillover matrix is built for FlowKit. Explicit A/H/W blocks are supported only when named pulse groups and coefficient counts establish their order. Missing/non-finite/singular or ambiguous matrices stop analysis.
- **Embedded FCS spillover:** use the existing compatible embedded matrix instead; no XML matrix is applied.
- **Source values:** no additional matrix is applied.

XML compensation always starts from FlowKit source values, never an already FCS-compensated array. It does not overwrite the embedded matrix. No import can establish whether the instrument/exporter already compensated those source values; review that history before adding a matrix. Negative values and original event order remain intact.

Gates retain their individual transforms and compensation mode. XML matrices are bound per sample, so an analysis ZIP exports **per-sample GatingML** under `gates/`, with paths and FCS hashes in `manifest.json`; the original XML is `source-workspace.xml`. Replaying those GatingML documents in FlowKit preserves membership in tested reference cases. Imported-source provenance and reconstruction warnings also accompany experiment measurements.

## Analyze a larger experiment locally

The interactive workspace keeps its 24-sample/300-MB defaults. For an explicitly selected directory, the streaming batch command analyzes one hash-matched FCS file at a time:

```sh
python -m aureka_flow.diva_batch \
  --xml /path/to/experiment.xml \
  --fcs-dir /path/to/exported-fcs \
  --output /path/to/new-empty-results \
  --worksheet global:0 \
  --compensation xml \
  --acknowledge-reconstruction
```

The output contains an offline `report.html`, `population-statistics.csv`, `aureka-project.json`, original XML, full-event `membership-ranges.jsonl` and a hash receipt. Counts retain total/parent denominators; root means all parsed FCS events, not an inferred acquired-event or sort counter. Medians retain per-channel finite counts. Repeat acquisitions stay separate files, not biological replicates. File errors are listed and cause a nonzero exit; existing output files are not overwritten. This is an explicit local file workflow, not a watcher or instrument connection. Only read completed exports; incomplete writes are not monitored or retried.

## Evidence and references

Public tests use generated XML/FCS fixtures. They verify matrix direction/application once, independent sinh/threshold references, open quadrant coverage, full-event membership independent of display sampling, exact original XML, hash-bound project replay, valid GatingML replay, isolation and storage budgets. A permitted private FACSDiva 8.0.1/LSRFortessa export was also analyzed locally; its raw files, metadata and numeric results are not redistributed. Analytical consistency checks are separate from validation against vendor-reported counts. Matched nonzero vendor statistics remain needed for that comparison. Neither establishes FACSMelody compatibility.

[FlowJo's Diva integration documentation](https://docs.flowjo.com/flowjo/workspaces-and-samples/diva-integration/) describes choosing a global worksheet and reference scaling/compensation. It also documents height/width export issues in Diva 8 and possible differences in population statistics. Aureka therefore requires review and does not silently swap columns. [BD's FACSDiva product documentation](https://www.bdbiosciences.com/en-in/products/software/instrument-software/bd-facsdiva-software) identifies experiment/FCS/statistics export and linear/log/biexponential scaling as distinct capabilities. These vendor documents are linked as references, not copied or used as a claim of numerical equivalence. Accessed 23 November 2026.
