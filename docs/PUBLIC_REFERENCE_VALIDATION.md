# Frozen public FCS and FlowJo comparison

This is a reproducible qualification check of one upstream public example, separate from synthetic unit tests and direct BD instrument/export validation. Inputs are the FlowKit 1.2.3 `8_color_data_set` at commit [`f1c3726c85cf312b9fdc12670a2783b2ef33ab25`](https://github.com/whitews/FlowKit/tree/f1c3726c85cf312b9fdc12670a2783b2ef33ab25/data/8_color_data_set): one 17.4 MB FCS and its 436 KB workspace. The repository's BSD-3-Clause license and attribution are retained in [third-party notices](../THIRD_PARTY_NOTICES.md). FCS/WSP binaries are not redistributed here.

The file reports `CYT=LSRII`, FCS 3.1, 290,172 events and 15 channels. `CREATOR` is absent; the filename ends `_clean.fcs`. Its acquisition-software version, pre-export processing and compensation history are unverified. The workspace reports FlowJo **10.6.2**. Two other samples in that workspace are intentionally outside this selected-file scope. This is not FACSMelody/FACSChorus or direct FACSDiva export validation.

## Observed result

The source-import checks passed. All 4,352,580 values, in original event order, matched an independent float32 decoding of this frozen artifact, with its declared 0.01 Time scaling. Applying the file's matrix matched an independent NumPy solution of the mixing equations. The native batch adapter retained all events and matched the fluorescence medians. Applying a supplied matrix for this arithmetic test does not establish that additional compensation is biologically appropriate for the original sample.

Exact stored-count agreement **failed**: only **5 of 14** gate counts matched. The largest absolute difference was **690 events**; the largest difference in percent of parent was **0.23609 percentage points**. A rare population differed by **9.09% relative count**, despite a small absolute change.

| Saved gate path suffix | Stored FlowJo count | Fresh FlowKit count | Difference |
| --- | ---: | ---: | ---: |
| Time/Singlets | 239,691 | 239,001 | −690 |
| aAmine-/CD3+ | 133,860 | 133,670 | −190 |
| CD4+/CD107a+ | 71 | 68 | −3 |
| CD8+/IL2+ | 11 | 10 | −1 |

These are observed differences between saved counts and a replay of the supplied files. Their cause has not been established. No gate coordinates or reference counts were adjusted. No independent FlowJo event-membership masks were supplied; even matching counts would not prove matching events. See the complete [observed report](references/flowkit-1.2.3-observed.json) and [input manifest](references/flowkit-1.2.3.json).

## Boundary investigation, 24 November 2026

The added full-event diagnostic reproduces the literal inequalities for all **nine rectangle gates**, using a separate matrix solve and the imported FlowKit transforms and parent memberships. Every diagnosed rectangle selects exactly the same events as FlowKit. This checks the interval arithmetic; it does not independently validate the transforms, polygon geometry, inherited parent memberships or FlowJo's internal binning.

The first count disagreement is **Time**: 290,172 stored versus 290,166 replayed. Source event indices **0–5** are below its lower Time bound. In source-value coordinates after FCS Time preprocessing, the bound is approximately **1.28**, while those six events range from **1.251 to 1.277**. No events equal either Time boundary; all events pass the accompanying FSC-A interval. Switching strictness at an exact boundary cannot explain this first discrepancy. The reason the stored count includes more events remains unverified, including source lineage and whether stored statistics reflect these exact files/settings.

Upstream [FlowKit issue #280](https://github.com/whitews/FlowKit/issues/280) reports chart-edge/binning differences for another workspace; [issue #113](https://github.com/whitews/FlowKit/issues/113) discusses polygon binning. They motivate inspection, not an attribution of this fixture's discrepancies. No clipping, binning or count-based gate adjustment was introduced.

## Reproduce

Install the source checkout with `python -m pip install -e '.[dev,validation]'`. Use a new local input directory and retain the original downloaded files. From the repository root:

```sh
mkdir -p local-data/flowkit-reference/fcs_files
curl --fail --location --max-time 60 -o local-data/flowkit-reference/fcs_files/101_DEN084Y5_15_E01_008_clean.fcs https://raw.githubusercontent.com/whitews/FlowKit/f1c3726c85cf312b9fdc12670a2783b2ef33ab25/data/8_color_data_set/fcs_files/101_DEN084Y5_15_E01_008_clean.fcs
curl --fail --location --max-time 60 -o local-data/flowkit-reference/8_color_ICS.wsp https://raw.githubusercontent.com/whitews/FlowKit/f1c3726c85cf312b9fdc12670a2783b2ef33ab25/data/8_color_data_set/8_color_ICS.wsp
python scripts/qualify_public_reference.py --reference-dir local-data/flowkit-reference --output validation/public-reference
```

The qualification command makes no network requests. It requires the pinned sizes/SHA-256 hashes, rejects extra/missing FCS files, preserves existing reports and rechecks inputs after analysis. It records numerical checks, software versions and source-code hashes, plus every gate-count difference. The binary decoder is specific to this frozen float32 file, not a general FCS parser. Default CI uses offline generated acceptance-contract tests; the public-data run is an explicit separate check.

Qualification now also requires all nine expected rectangles to be diagnosed with zero event-membership differences. `gate-diagnostics.json` records source/workspace hashes, gate paths, parent denominators, transforms, matrix identities, boundary occupancy and full-event membership fingerprints. Index previews show at most 20 excluded source events, zero-based; counts and fingerprints use the complete arrays. The qualification report includes the first count discrepancy and the diagnostic file's hash.

For your own local workspace, enable the optional diagnostic without the frozen-fixture restrictions:

```sh
python scripts/validate_workspace.py --workspace /path/reference.wsp --fcs-dir /path/fcs_files --output validation/local-review --diagnostics
```

This diagnostic supports literal rectangle gates with exact source detector labels and source values or one named workspace matrix. Derived dimensions, inferred aliases, embedded `FCS` references and other gate geometries are explicitly marked **not diagnosed**. Membership fingerprints use one byte (0/1) per source event in original order. They identify replay results; they are not independent FlowJo masks. Keep private inputs and generated reports local.

Exit **0** means every selected check passed; **1** means analysis completed but qualification failed; **2** means invalid/missing/changed inputs or a report-directory error. With the observed FlowKit 1.2.3 results, **exit 1 is expected**. The report must retain `qualification_passed: false`; successful import checks or passing software tests cannot override failed count equivalence.
