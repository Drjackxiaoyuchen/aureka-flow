# Contributing to Aureka Flow

Bug reports, clearer tutorials, reproducible examples and focused code changes are welcome. Aureka Flow is a local browser workspace on top of FlowKit, with an initial focus on yeast-display expression and binding.

## Report an issue

Use the [issue tracker](https://github.com/Drjackxiaoyuchen/aureka-flow/issues/new/choose). Include the OS, Python/Aureka Flow/FlowKit versions, steps to reproduce, expected behavior and observed behavior. For a gating discrepancy, include the full parent path, axes, transform parameters and compensation mode.

Prefer the synthetic demo or a small generated fixture. Experimental FCS files, exported events and workspace metadata can contain private information. Do not publish them or local credentials in an issue. Redact local paths in logs and screenshots when needed.

## Run the checks

From a Python 3.11 or 3.12 source checkout:

```sh
python -m pip install -e '.[dev]'
python -m pytest tests -q
node tests/test_intake.mjs
node tests/test_gating.mjs
node --check aureka_flow/static/app.js
node --check aureka_flow/static/report-intake.js
python examples/analyze_synthetic.py
```

Node.js 22 is used for front-end checks. Gate checks include the click-to-finish workflow and coordinate mapping without point hits. API checks cover browser-session isolation and the actual ZIP/CSV contents. The example writes to the ignored `exports/` folder and verifies its results against the published synthetic reference. CI runs on Linux, macOS and Windows, and builds/smoke-tests the Docker server.

## Preserve analysis behavior

For numerical changes, use small fixtures with independently known event memberships. Check counts and parent denominators, transformed coordinates, compensation behavior and missing-data errors where relevant. Plot sampling must not determine counts, gates, medians or histograms. Preserve source hashes and original event indices in exports.

Shared gate definitions retain their own axes, transformations and compensation. Document any intentional change in interpretation or saved-project compatibility. A successful calculation does not by itself validate a biological gate or cross-software equivalence.

Changes to the FlowKit version require checking its release notes and API changes, then rerunning numerical, export and representative workspace comparisons. Do not update reference numbers solely to make a failing check pass; explain why the result changed.

## Update documentation

The learning-path index is [docs/README.md](docs/README.md). The complete guide's source is [docs/TUTORIAL.md](docs/TUTORIAL.md). To rebuild its local HTML, PNG/SVG figures and reference artifacts:

```sh
python -m pip install '.[docs]'
python scripts/build_tutorial.py
```

Keep simulated, experimental and source-reported results clearly identified. New public examples should use synthetic or explicitly redistributable data with provenance. Aureka names and logos remain brand assets; see [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
