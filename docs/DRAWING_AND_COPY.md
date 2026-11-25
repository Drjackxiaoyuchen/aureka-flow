# Draw and copy gates

The plot toolbar offers **Rectangle**, **Ellipse**, **Polygon**, **Freehand** and **Pan**. A histogram changes Rectangle to a one-dimensional **Range** tool.

- **Ellipse:** drag opposite corners, release, name the population and save. All four bounds are required. The ellipse is aligned with the selected transformed axes; edit its saved bounds through **Edit**.
- **Polygon:** click corners, then **Finish polygon** or Enter. **Undo corner** removes the last vertex; Escape cancels.
- **Freehand:** drag an outline and release to close it. This saves a polygon in the current coordinate system, with the sampled outline vertices retained in the project. A straight line is not a valid gate.
- **Range:** choose Histogram and drag horizontally. Histogram Y counts/binning never define gate membership.

All tools save geometric definitions. Display sampling does not determine membership, counts or exports. Each gate retains its own channel identities, transforms and compensation mode.

## Copy a gate and its children

Click **Copy** beside a saved population. Enter a new name, choose **Copy under parent**, and save. **Include all child populations** is checked by default. Uncheck it to copy only the selected gate.

The operation copies the entire selected hierarchical branch in one step, gives children unique names and preserves their hierarchy. Internal Boolean references are redirected to the copied inputs. Referenced populations outside the copied branch remain shared; copy their common ancestor when their definitions should also become independent. A Boolean gate's external inputs must share its destination parent, or the operation is rejected before changes are made.

The original definitions stay intact. Copied boundaries can be edited independently. A different destination parent changes the eligible events, so its counts may differ. The existing strategy already applies across compatible loaded samples; copying creates another strategy branch, rather than a per-sample override. Missing channels or compensation are reported explicitly.

**Undo gate** reverses the whole copy operation, and **Redo gate** restores it, within the existing bounded session history. A stale strategy revision, invalid parent, duplicate root name or copy exceeding 100 total gates fails atomically. Child names are kept within the 80-character limit.

## Save and reproduce

Ellipse projects use **schema 5**; earlier supported schemas remain readable. Freehand outlines retain polygon vertices, while ellipses retain bounds in their saved transformed coordinates. GatingML exports use FlowKit's EllipsoidGate with center, diagonal covariance and squared distance 1. In two dimensions, membership is `((x-cx)/rx)^2 + ((y-cy)/ry)^2 <= 1`, intersected with the parent. These are user-drawn shapes, not a fitted distribution or a statistical confidence interval.

Project and GatingML round trips preserve the tested full-event membership, including transformed ellipses, copied Boolean references and reviewed XML compensation. The original instrument XML stays preserved separately from the copied analytical definitions. Keep source FCS files: projects do not embed events. These checks do not establish FlowJo or instrument equivalence.
