# UI refresh

## 1. Fixed three accuracy problems on the Evaluation page

The evaluation view is a static snapshot rendered from `static/js/knowledge.js`. Three
text-level defects were fixed; **no numeric value was altered**.

| # | Problem | Before | After |
| --- | --- | --- | --- |
| 1 | The cited data source did not exist in the repository, so the page pointed readers at an empty path. | `results/v16/wp-d/full144-hardened-c4-20261101/` | `analysis/wp_d/reports/hardened144-20261101/final-success-comparison.scored.json` (144 per-slot records) |
| 2 | A footnote claimed that `27/27` and `6/6` "cannot be added into 33/33". The arithmetic is in fact 27 + 6 = 33, so the sentence contradicted itself and invited a question it could not answer. | "…the two denominators differ, so 27/27 and 6/6 cannot be added into 33/33." | "…the two denominators differ and cannot be added directly; the combined measure is quality success, over all 36 cases, with technical failures counted as unsuccessful." |
| 3 | The headline figure `0 wrong root causes` sat directly above per-architecture accuracy of 25/28 and 15/27 without explaining the difference. | Small note under the stat: "19 missed judgments were INCONCLUSIVE" | Note rewritten to "all 19 lost judgments were abstentions; not one was a wrong root cause", plus a new explanatory paragraph under the stat band. |

Why it matters: the project's claim is that the system **abstains instead of guessing**.
The old wording made that claim look like a contradiction; the new wording states it as
the argument it is.

The matching English catalog entries in `i18n/catalog.knowledge.js` were updated in the
same commit so the EN/中文 toggle stays complete.

## 2. Added a presentation skin

A single additive stylesheet, `css/skin.css`, is loaded last from `index.html`. It
overrides the design tokens (`--bg-*`, `--text-*`, `--border-*`, `--accent*`, `--shadow-*`)
plus a small number of surface rules. Because `app.css` and `core.css` contain **zero
hard-coded colours**, the entire dashboard — every page, table, chart and badge — follows
automatically.

**Dark theme** — deep navy base with a fixed ambient bloom and a swept arc in the top-right
corner (three concentric ring gradients whose centre sits outside the viewport), frosted
panel chrome, translucent cards with a lit top edge, and accent glow on primary actions,
the active navigation item and comparison bars.

**Light theme** — the same structure on a white base: soft blue/violet tints, white glass
cards with a coloured shadow, and the same accent treatment at lower intensity.

Both themes keep the original layout, spacing, typography and information density. Text
colours were chosen to hold contrast on the new surfaces, and a
`prefers-reduced-transparency` fallback drops the blur and the translucency.

## 3. Controls on glass

Two usability fixes in the trace-archive toolbar, both requested after reviewing the skin:

- Filter chips (`All / Mock / Real`) were transparent with a faint outline and nearly
  invisible on the new background. They now have a raised surface, a visible border and a
  filled, glowing pressed state.
- The status `<select>` and the chips were 2 px apart in height and the select carried
  vertical padding, so the chosen label looked off-centre. Both are now 34 px tall with the
  select's block padding removed, which centres the native label.

- In-table buttons (`Demo replay`) were 28 px tall and clipped the descenders of their
  label. They are now 34 px with 7/14 px padding and `line-height: 1.35`. The rule is
  scoped to `table.data` so no other button changes size.

---

## Files

| File | Change |
| --- | --- |
| `static/css/skin.css` | **New.** Presentation skin for both themes and the control refinements. |
| `static/index.html` | **One line added.** `<link rel="stylesheet" href="css/skin.css">` after `astryx-bridge.css`. |
| `static/js/knowledge.js` | Three copy fixes and one explanatory paragraph on the evaluation view. |
| `static/js/i18n/catalog.knowledge.js` | English strings for the changed copy. |
| `docs/handoff/submission-package/UI_REFRESH.md` | This note. |

Nothing under `src/incident_lens/` outside `web/static/` was modified: no Python, no
configs, no data, no prompts, no traces, no evaluation numbers.

## Verification

- `node --check` passes on the two edited ES modules.
- `GET /css/skin.css` returns 200 and the file the browser receives matches the one on
  disk.
- All six routes (`#/`, `#/investigate`, `#/library`, `#/run`, `#/system`, `#/evaluation`)
  render in both themes, in 中文 and English.
- `/api/health`, `/api/meta`, `/api/cases`, `/api/traces` still respond unchanged.

## Reverting

Delete `static/css/skin.css` and remove its `<link>` line from `static/index.html`;
the dashboard returns to the original appearance. The copy fixes in `knowledge.js` are
independent of the skin and can be kept or reverted on their own.
