"""Deterministic, explicitly synthetic FCS examples with no experimental data."""
import io

import flowio
import numpy as np


def demo_files():
    """Return three small simulated samples; every call yields the same bytes."""
    samples = []
    for seed, name, positive_fraction in [(710, "synthetic_control.fcs", .02),
                                           (711, "synthetic_expression.fcs", .30),
                                           (712, "synthetic_binding.fcs", .65)]:
        rng = np.random.default_rng(seed)
        n = 30000
        fsc = np.maximum(rng.normal(85000, 18000, n), 100)
        ssc = np.maximum(fsc * .45 + rng.normal(0, 10000, n), 100)
        expression = rng.lognormal(7.8, .85, n) + rng.normal(0, 70, n)
        positive = rng.random(n) < positive_fraction
        binding = rng.normal(80, 70, n) + positive * (expression * rng.lognormal(.3, .45, n))
        events = np.column_stack([fsc, ssc, fsc * rng.normal(.9, .04, n), expression, binding,
                                  np.arange(n)])
        buffer = io.BytesIO()
        flowio.create_fcs(buffer, events.ravel().tolist(),
                         ["FSC-A", "SSC-A", "FSC-H", "Expression-A", "Binding-A", "Time"],
                         opt_channel_names=["", "", "", "Simulated expression", "Simulated binding", ""],
                         metadata_dict={"date": "01-JAN-2000", "timestep": "0.01",
                                        "com": "SYNTHETIC DEMO. Generated from seeded distributions; not experimental measurements."})
        samples.append((name, buffer.getvalue()))
    return samples
