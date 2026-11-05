# Aureka Flow

A local flow-cytometry workspace for **FCS visualization, manual gating and sample comparison**, built on [FlowKit](https://github.com/whitews/flowkit). The interface uses Aureka's purple and mint palette.

Upload your FCS files, choose channels, draw rectangle or freehand polygon gates, and export populations and statistics. Analysis runs on your own computer.

## Quick start

Requires **Python 3.11 or 3.12**. Works with a local browser on macOS, Linux or Windows.

```sh
git clone https://github.com/Drjackxiaoyuchen/aureka-flow.git
cd aureka-flow
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
python -m aureka_flow
```

On Windows, use `py -3.11 -m venv .venv` and `.venv\Scripts\Activate.ps1` for the virtual environment. After installation, `aureka-flow` also starts the app.

The browser opens at **http://127.0.0.1:8765**. Keep the terminal open while using the app. Press Control-C to stop it. To choose another port:

```sh
python -m aureka_flow --port 8766 --no-browser
```

On macOS, you can instead double-click **Setup Aureka Flow.command**, followed by **Start Aureka Flow.command**. The setup script installs the tested dependency lock file.

## Use the workspace

1. Click **Upload FCS** or drop `.fcs` files anywhere in the window. You can upload from the analyzer or the validation page.
2. Choose the X/Y channels and display scales. For yeast-display work, gate the relevant cells and singlets first, then assign expression and binding channels according to your staining panel.
3. Choose **Rectangle** and drag across the plot, or choose **Polygon** and drag to trace a freehand closed shape. Release to finish.
4. Enter a gate name or keep the suggested name, then click **Save gate**. Select a saved population to draw a child gate. **Clear drawing** cancels an unfinished selection.
5. Use **Compare samples** to inspect distributions and population statistics across compatible samples.

The **Try synthetic demo data** button generates three deterministic samples in memory. They contain simulated scatter and fluorescence signals and are clearly labeled as synthetic. They are useful for trying the workflow and are not experimental measurements. No raw experiments or user data are bundled in the repository.

## Analysis behavior

- Linear, Logicle and GatingML Asinh scales are available independently for X and Y. Default transform parameters are T=262144, M=4.5, W=0.5, A=0; Asinh uses T/M/A. These are display defaults, not instrument calibration.
- Each saved gate retains its compensation and transform settings. Changing the displayed channels or scales does not reinterpret existing gates.
- Rectangle lower boundaries are inclusive and upper boundaries are exclusive, following FlowKit/GatingML.
- The expression/binding tool creates four quadrants within the current parent plus an overlapping **Expression+** range population. Thresholds are entered in the current axis coordinates and should come from appropriate experimental controls. Do not sum all five populations.
- Scatter displays at most 25,000 finite coordinate pairs, sampled deterministically. Gate counts, percentages, medians and histograms use the full event data. Rare populations may be visually absent from the display sample while still being counted.
- Population medians use finite values in the selected display scale. Histogram comparisons use common bin edges and normalize each nonempty sample to 100% of finite values in the selected channel.
- Uncompensated data use FlowKit's `source='raw'`, which already includes standard FCS gain/log/time preprocessing. Original event order is preserved.
- Compensation can use an embedded FCS spillover matrix. Missing or incompatible matrices and detector names raise explicit errors. Custom matrix import is not implemented.

No automatic cell, singlet, viability or positive gates are inferred. Fluorescence, positive fractions and display/capture readouts are assay-specific; the app does not infer solution affinity, off-rate or cellular potency.

## Save and export

| Action | Result |
| --- | --- |
| Save project | JSON with gates, their transforms and compensation settings, software versions, source metadata and SHA-256 hashes. |
| Open project | Restore a strategy after reloading the source FCS files, or apply it as a template to compatible samples. |
| Export statistics | CSV with counts, percentages of total/parent, X/Y medians, transform settings, compensation, hashes and compatibility errors. |
| Export population events | Every gated event in all channels as uncompensated or compensated values. Includes source filename/hash and zero-based source-event index. Display transforms are not applied to these CSV values. |
| Export gates | GatingML 2.0 with XML-safe gate IDs and a comment mapping human names to those IDs. |
| Download plot | PNG of the displayed scatter, including sample, population, compensation and display count. |

**Save project does not embed the FCS events.** Keep the source files and reload them when restoring a project. Save the project JSON alongside event/statistics exports to preserve the gate definitions.

One running process has one shared in-memory workspace. Browser tabs connect to that same workspace. Restarting the process clears loaded samples and gates. Current limits are 24 samples, 100 MB per file, 300 MB of FCS input and 100 gates. RAM usage is higher than file size.

The server binds to loopback, with no remote plotting CDN or external analysis service required. It is a single-user local research tool; no multi-user authentication or public application hosting is included.

## Compare with a human FlowJo workspace

An optional command replays an existing FlowJo workspace on its matching FCS files. It independently reads the stored FlowJo counts from XML and compares them with fresh FlowKit results, retaining full gate paths.

```sh
python -m pip install '.[validation]'
python scripts/validate_workspace.py \
  --workspace /path/to/reference.wsp \
  --fcs-dir /path/to/fcs_files
```

Outputs are written to the ignored `validation/workspace-report/` directory and are available at `/validation/` in the app after restarting it. They include a local HTML report, comparison CSV, plot and source hashes. The report exposes differences rather than tuning the gates to match saved counts.

For a public example, obtain the `data/8_color_data_set` directory from the [upstream FlowKit repository](https://github.com/whitews/flowkit), then point the command at `8_color_ICS.wsp` and its `fcs_files/` directory. Upstream example data are not included in this repository.

Saved-gate replay is distinct from automatically choosing new gates. Count agreement alone does not establish event-level agreement; that requires an independent human event-membership reference. Cross-software equivalence should be checked for the intended assay and gate types.

## Development

```sh
python -m pip install -e '.[dev]'
python -m pytest tests -q
node tests/test_intake.mjs
node --check aureka_flow/static/app.js
```

Node.js 22 is used for the JavaScript checks; Node is not required to run the application. The numerical tests cover gate boundaries, nested percentages, transforms, compensation, full-event counting despite display sampling, polygon gates, expression/binding partitions and export round trips. Intake checks cover the file picker, whole-page drop handler, file validation and busy-state handling.

| Location | Purpose |
| --- | --- |
| `aureka_flow/engine.py` | Typed gate/project models, full-event analysis and source provenance. |
| `aureka_flow/server.py` | Local FastAPI endpoints. |
| `aureka_flow/demo.py` | Deterministic synthetic FCS data. |
| `aureka_flow/static/` | Buildless HTML/CSS/JavaScript interface and Aureka brand assets. |
| `scripts/validate_workspace.py` | Optional saved human-gate comparison. |
| `tests/` | Numerical/API and upload-handler checks. |

Uploaded events, experimental workspaces, local reports, credentials and environments are excluded by `.gitignore`. Generated outputs are local files and are not sent to GitHub by the app.

## License and attribution

Aureka Flow code is distributed under the [BSD 3-Clause license](LICENSE). Aureka names and logos remain brand assets and are not covered by that software license.

FlowKit is Copyright © 2018 Scott White and is distributed under BSD 3-Clause. Its attribution and license are retained in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). See the [FlowKit paper](https://doi.org/10.3389/fimmu.2021.768541). Upstream authors do not endorse this customization.
