# Adjust X and Y axes

Choose X/Y channels and Linear, Logicle or GatingML Asinh scales as before. The **X display range** and **Y display range** cards now control the visible window independently.

1. Enter Min and Max for either axis and click **Apply ranges**, or press Enter in a range field. Both values must be finite and Min must be smaller than Max. Negative values and scientific notation are supported. Leave both fields blank for automatic range.
2. Use **Auto X** or **Auto Y** to reset one axis, or **Auto both axes** to fit the displayed plot again.
3. Select **Zoom** beside the drawing tools and drag a box to inspect a region. Select **Pan** to move the window. The range fields update after navigation; wheel zoom is enabled while Plotly receives pointer input in Zoom/Pan modes. Return to Rectangle/Ellipse/Polygon/Freehand to draw a gate.

Range numbers use the displayed coordinate system **after the selected transform**. For example, on the synthetic expression/binding Logicle plot, X `0.3–0.8` and Y `0.2–0.9` are transformed coordinates, not raw detector intensities. Expand **Transform parameters** to change T/M/W/A and apply them separately. The range cards name the coordinates of the actual rendered plot, including while unsubmitted transform edits are present.

Manual windows remain consistent when selecting compatible samples, populations, backgating or redrawing the same coordinates. Different detector/scale/active transform parameters/compensation have separate windows. X and Y are independent even when they show the same channel. Histogram event-count, population/ancestor percentage and overlay normalization labels identify their Y units; single-sample and overlay heights have separate histories, as do count/area/modal normalizations.

These controls only change the display. Gate definitions, source event indices, full-event counts, histograms/bin normalization and statistical denominators remain unchanged. A gate drawn after zooming uses the current transformed coordinates. Cropping the plot can hide events while the displayed population count remains the full count.

The browser keeps up to 64 coordinate windows in memory for the current page. Reloading the page resets them; gate-project JSON does not store display windows. Plot/overlay PNG exports use the current displayed axes. Keep original FCS files and the gate project for analytical replay.
