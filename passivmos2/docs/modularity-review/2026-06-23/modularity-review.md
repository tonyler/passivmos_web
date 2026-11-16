# Modularity Review

**Scope**: Entire codebase — PassivMOS2
**Date**: 2026-06-23

## Executive Summary

PassivMOS2 is a SvelteKit single-page crypto portfolio tracker that displays wallet balances, staking rewards, APR rates, and portfolio history across 20+ EVM and Cosmos chains. It is a solo project with a Windows XP aesthetic. The overall modularity is **healthy for its current scale**, with one critical issue and one significant issue that will become increasingly painful as the chain list and feature set grow. The most important finding is that post-build JavaScript overlays injected into `index.html` are [intrusively coupled](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) to the SvelteKit component's internal DOM structure and API response format, creating a silent failure mode every time the chart or history API evolves.

## Coupling Overview Table

| Integration | [Strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | [Distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) | [Volatility](https://coupling.dev/posts/dimensions-of-coupling/volatility/) | [Balanced?](https://coupling.dev/posts/core-concepts/balance/) |
| --- | --- | --- | --- | --- |
| `index.html` tooltip → SvelteKit chart component | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | Module | High | ❌ No |
| `index.html` Clippy → SvelteKit scan button | [Intrusive](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | Module | Moderate | ❌ No |
| SvelteKit App → Backend `/api/` routes | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | Module | Moderate | ✅ Yes |
| SvelteKit App → External blockchain RPCs/LCDs | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | System | Low–Moderate | ✅ Yes |
| SvelteKit App → `networks.json` | [Model](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | Module | Moderate | ✅ Yes |
| SvelteKit App → Logging API (`/api/log`) | [Functional](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) | Module | Low | ✅ Yes |

---

<div class="issue">

## Issue: Post-Build Chart Tooltip Coupled to SVG Internals and API Shape

**Integration**: `index.html` tooltip script → SvelteKit chart component
**Severity**: Critical

### Knowledge Leakage

The tooltip script injected into `index.html` knows four things it should not need to know about the chart component:

1. **CSS class name** — it queries `svg.chart-svg` to find the rendered SVG element.
2. **SVG internals** — it reads the `points` attribute of the `<polyline>` element inside the SVG to extract pixel coordinates.
3. **API response format** — it monkey-patches `window.fetch` to intercept calls to `/api/coinfolio/history` and stores the raw JSON payload (`{ ts, total_usd, yearly_income_usd }`) in a closure variable.
4. **Coordinate mapping heuristic** — it correlates API data points to SVG pixel points by matching the *count* of polyline vertices to the count of filtered API entries. This is a fragile re-implementation of logic that lives inside the Svelte component.

All of this is [implementation detail](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) — none of it is an explicit integration contract. The SvelteKit component never agreed to expose these facts.

### Complexity Impact

A developer working on the chart component holds a mental model of the Svelte chart code. They do not hold a mental model of the `index.html` overlay, because it lives outside the component tree, outside the build system, and is not visible in the Svelte source. When the chart is refactored, the overlay is an invisible dependent — the classic [complexity](https://coupling.dev/posts/core-concepts/complexity/) trap of unpredictable change outcomes.

Concretely, the coordinate-matching heuristic (`filteredForChart`) breaks whenever the filtered data count does not exactly match the polyline point count. Any change to how the Svelte component filters or sub-samples chart data will silently corrupt the tooltip — showing wrong timestamps or wrong values without throwing an error.

### Cascading Changes

- **Rename `chart-svg` class** → tooltip silently stops attaching to the SVG; no tooltip appears.
- **Change SVG from `<polyline>` to `<path>` or `<circle>` elements** → `parsePolyPoints` returns an empty array; tooltip renders empty.
- **Change history API response shape** (rename `ts`, add pagination, change field names) → tooltip renders stale or undefined values.
- **Add a second chart type** → the tooltip attaches to index `svgs[0]` and `svgs[1]` by positional assumption; any DOM reordering breaks the binding.
- **Add chart animations or deferred rendering** → the `MutationObserver` may attach before the polyline is fully rendered, returning zero points.

### Recommended Improvement

Move the tooltip logic inside the Svelte chart component, where it has direct reactive access to the data and the SVG coordinates. The component already has the filtered data in its own reactive state — there is no need to re-fetch or re-correlate it. The overlay exists only because it was added post-build to a compiled artifact.

The concrete fix: add a `<div class="tooltip">` inside the Svelte chart component, wire `mousemove` to a Svelte event handler that reads the reactive data directly, and remove the `index.html` tooltip block entirely. This eliminates the `window.fetch` monkey-patch and the fragile point-count heuristic in one step.

**Trade-off**: This requires touching the source, which means the next build will replace the current `index.html`. Given that the overlay was added precisely to avoid touching the source, the fix requires a short-term source edit in exchange for long-term safety.

</div>

<div class="issue">

## Issue: Clippy Triggers a Scan via Raw DOM Class-Name Lookup

**Integration**: `index.html` Clippy script → SvelteKit scan button
**Severity**: Significant

### Knowledge Leakage

Clippy's "Scan Now!" button click handler does:

```js
var s = document.querySelector('.scan-btn:not([disabled])');
if (s) s.click();
```

This couples the Clippy overlay to the internal CSS class name of the scan button component (`scan-btn`) and to the Svelte component's convention of using the `disabled` HTML attribute to represent scan state. These are [implementation details](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) of the Svelte component — not published integration points.

### Complexity Impact

Clippy lives in `index.html` as a self-contained IIFE. It has no awareness of the Svelte component lifecycle. The scan button may not exist in the DOM when Clippy tries to find it (e.g., if it renders conditionally), and the `.disabled` attribute convention may change if the button is replaced by a different control. The failure is silent — Clippy simply does nothing, with no feedback to the developer.

The [distance](https://coupling.dev/posts/dimensions-of-coupling/distance/) between the Clippy script and the Svelte component is module-level (different code units, different lifecycle), yet the [coupling strength](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) is intrusive. That imbalance is tolerable only if the scan button never changes — which is unlikely as the app evolves.

### Cascading Changes

- **Rename `.scan-btn`** → Clippy's "Scan Now!" button silently does nothing.
- **Replace button with a keyboard shortcut or toolbar action** → Clippy cannot trigger scans at all.
- **Move scan initiation to a Svelte store action** → the DOM element may no longer exist, or may no longer be the right trigger point.

### Recommended Improvement

Expose a lightweight global trigger that Clippy can call without knowing about DOM internals. The simplest option: dispatch a custom DOM event from Clippy (`document.dispatchEvent(new Event('passivmos:scan'))`) and listen for it inside the Svelte component. This is a [contract coupling](https://coupling.dev/posts/dimensions-of-coupling/integration-strength/) at the event name level — an explicit published interface that survives any internal refactor of the scan button.

**Trade-off**: This requires a one-line listener inside the Svelte source and a one-line dispatch change in `index.html`. Small cost, eliminates the class-name dependency entirely.

</div>

---

_This analysis was performed using the [Balanced Coupling](https://coupling.dev) model by [Vlad Khononov](https://vladikk.com)._
