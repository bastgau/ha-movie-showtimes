# Lovelace card (phase 1)

The previous design (a rewrite with its own shadow root, CSS and day chips) was rejected and is superseded. The card
is now **a near-verbatim copy of the reference card plus an adapter**.

## Approach

- `custom_components/movie_showtimes/frontend/movie-showtimes-card.js` is
  `bastgau/ha-betaseries` `card/upcoming-media-card.js` at commit `46a6ef3c2cc88eaf339f84a4680ccba0bc973879`
  (MIT, itself from `custom-cards/upcoming-media-card`, MIT; both notices and the MIT text are in the file's header).
  Its SVG, DOM building, CSS, overflow / columns engine, light DOM, `umc-*` classes and per-instance random class are
  untouched.
- Only these differ from the reference: BetaSeries removed; element names `movie-showtimes-card` and
  `movie-showtimes-card-editor`; `window.customCards` entry; the three steps below. The new code is one block at the top
  of the file (`filmsToItems`, `resolveDayEntity`, `filmKeys`, `resolveText`, `matchesSearch`, `sensorProblem`).
- The reference reads one sensor's `data` attribute: a list whose element 0 is a template (`title_default`,
  `line1_default` ... `line4_default`, `icon`) and whose other elements are items. Our sensors expose `films`;
  **`filmsToItems(attributes)`** builds that list, so the rendering code receives what it expects. It also strips `<`
  and `>` from source text and keeps only `http(s)` URLs, because the reference puts text in `innerHTML`.
- Delivery (D32) and binding by device (D33) are unchanged: `card.py` serves and registers the file.

## The three phase-1 steps

1. **Replace BetaSeries by this integration.** Removed: the watched button and `watched_button_style`,
   `device_betaseries`, the catalogue search / add / remove, the season-premieres toggle, the BetaSeries editor section
   and strings. Kept although unrelated to BetaSeries: trailers and the YouTube controls (inert: our items have no
   `trailer`). The editor has a **Cinema** field: a device selector filtered on integration `movie_showtimes`
   (`device_id`; in YAML `entity`, any sensor of the cinema, also works). The card finds the sensor in the browser from
   `hass.entities` (platform `movie_showtimes`, same `device_id`, `translation_key`). The day is chosen with the day selector (phase 2, below);
   `resolveDayEntity(hass, config, dayKey)` takes the key (`today`, `tomorrow`, `day_2` ... `day_6`). No cinema
   chosen: the reference's configuration error. Unavailable sensor, no sensor found, day without films: a one-line
   message in place of the grid.
2. **Choose the lines** with the reference's `title_text`, `line1_text` ... `line4_text` and its `$tokens`.
3. **Local search** with the reference's `enable_search` bar, over title, original title, genres, directors and cast
   (case and accent insensitive). The catalogue options and the tabs are gone.

## `$tokens` (dynamic)

A token is `$name` (`/\$[a-z][a-z0-9_]*/`, the longest name wins, so `$release_date` is not `$release` + `_date`).
Resolution (`umcTokenValue`): first the reference's own tokens and the few formatted ones (`$runtime` `2h01`,
`$user_rating` / `$press_rating` `4.1` (plain text), `$release_date` formatted by `date`, `$cast` first three, `$day`, `$date`,
`$empty`), then **any attribute of the film by its own name** (the film's keys, then its `details`). Nothing is coded
per attribute. The adapter builds, once per film, `item._film = {name: text}`: a string as is, a number as is, a list
of scalars joined with `, `, a boolean as `Yes` / `No`, `synopsis_full` (HTML) as plain text; objects and lists of
objects are left out. Every text is sanitised (`<` `>` stripped, entity-like `&...;` escaped) before it reaches the
reference's `innerHTML`. `_film` is one namespaced key, so no attribute collides with the keys the reference reads.
A missing, empty or unknown token is `null` and its part (split at `-`) is dropped, as in the reference. The template
is split before the values are substituted (the reference split the result, which turned `Spider-Man` into
`Spider - Man`). The editor lists the names of the first film of the cinema (`filmTokenNames`), with a static text as
fallback. Defaults: `$title` / `$runtime - $genres` / `$directors` / `$user_rating` / `$certificate`. The adapter's
result is memoised per sensor state object.

## Paths in tokens

A token is `$name` followed by steps: `[n]` (n-th element of a list, 0-based, negative from the end) and `.key` (into an
object): `/\$[a-z][a-z0-9_]*(?:\[-?\d+\])*(?:\.[a-z][a-z0-9_]*(?:\[-?\d+\])*)*/g`. A `.` or `[` that does not
continue a valid step is not part of the token. A bare `$name` resolves as before (`umcTokenValue`: the reference's and
the formatted tokens, then the film's flat attributes). With steps, `umcPathText` walks the **raw film** (kept
non-enumerable on the item as `_filmObj`; the first name is a film key, or a `details` key): own properties only
(`hasOwn`, so `.constructor` finds nothing), a missing key, an index out of range, a wrong step type or an object result
are empty. Only the leaf is sanitised (`umcClean` for the lines, which reach innerHTML; unsanitised then decoded for the
tooltip), so no sanitised deep copy is kept. The reference redraws when the JSON of its items changes, and `_filmObj`
is not in it: the item has an enumerable `_sig`, a hash of the film's JSON, computed once per sensor state. The template
is split at `-` outside the tokens (`$genres[-1]`).

## Sorting

`sort_by` is any film attribute or path (`umcSortValue(film, path)`, the first name is a key of the film or of its
`details`, steps shared with the tokens through `umcWalkSteps`, a leading `$` ignored, `rating` read as `user_rating`),
resolved on the raw film (`item._filmObj`, typed values). The leaf is a number, a date (ISO date or date-time, compared as
time), a boolean (false first) or a string (`localeCompare` with `numeric` and `sensitivity: base`); a list leaf is its
first element; anything else is missing. `umcSortItems(items, path, ascending)` returns a new list: missing values last
in both directions, numbers and dates before booleans before strings (no throw on mixed values), the original index as
the last tie-break. The render replaces the reference's sort block (same try/catch, the template item stays first, runs
before max and collapse, no debug logging). `sort_ascending` defaults to `true` in the code and in the editor
(`CARD_DEFAULTS`): true is not written to the YAML, unticking writes `false`, ticking again removes the key. The editor's
`orderAndStrip` also no longer puts back, in its second pass, the defaults it just stripped. `sort_by` is a select with
`custom_value` (the installed frontend renders it as a picker that accepts typed values) with presets for the common
attributes.

## Projection and `$showtimes[n]`

`.key` on a list maps the key over its elements (own property of objects only; other elements are skipped; only scalar
values are kept) and yields a list of scalars, so `$details.showtimes.time` is a list leaf (joined with `, `) and
`[n]` can follow; another `.key` on it finds nothing. A list of strings (`cast`) still gives nothing for `.key`.
`$showtimes[n]` does not read the raw film: for the first name `showtimes` the walk starts from the badges' model
(`umcShowtimeBadges` + `umcShowtimeLabel`, `"VOST 08:55"`), so it is the n-th element of the `$showtimes` text, and
the line is not a badge line (`umcIsBadgeLine` stays exact). `$details.showtimes` still reaches the raw objects. The elements are the badge objects
(`{time, version, label, url}`): a step goes into them (`$showtimes[0].time`, projection `$showtimes.time[0]`,
`$showtimes.label[-1]`), and a leaf that is a badge itself is its label and time (`umcIsBadge`). If the badge row cannot
be measured or built (`_layoutBadges` throws, the slot has no size in a displayed item), the line shows the plain text
`VO 20:30, ...` instead of nothing; an item that is not displayed (collapsed) is measured when it is shown.

## Badge rows: several `_badge` tokens, text around them, rating badges

A badge line is any line whose template **contains** a `_badge` token (`UMC_BADGE_TOKENS`: `$showtimes_badge`,
`$certificate_badge`, `$user_rating_badge`, `$press_rating_badge`; the token is matched with the same regex as
`UMC_KEYWORDS`, so a name is never cut: `$user_rating_badge` is not `$user_rating` + `_badge`, and a token with steps is a
path, not a badge). `umcBadgeSegments(template)` gives the ordered segments (`{type: "badge", kind}` and
`{type: "text", template}`; blank text between tokens is only spacing) or null; `umcIsBadgeLine` is `segments !== null`.
`umcBadgeItems(segments, film, lang, resolve)` (pure) resolves each badge on its own (an empty one adds nothing and does
not affect the others) and each text segment with the normal `resolveText` (dropped when empty): the slot's `items`. No
item: the line is ignored. A badge line is never text: the line's own text is not used, a title badge line with nothing
keeps the reference's empty title tspan.

The slot holds the `items`, the colours of all kinds, the plain `text` (`umcBadgeFallbackText`: the items' texts joined
by a space, the fallback when the row cannot be placed) and the geometry. `umcBuildBadgeRow(items, options)` appends, in
order, the version pills (buttons, popover), the age pill, the rating pills and text spans, 6 px apart, wrapping. All the
mechanics (slot tspan, measure, retry, observer, viewBox growth, overflow engine, `_layoutAllBadges`) are unchanged.
Pointer events: the foreignObject and the row take none; only the version pills have `pointer-events: auto`, so a row of
age and rating pills lets clicks through to the item's film link.

**Rating badges.** `umcRatingBadge(film, key, lang)`: a finite number above 0 in `user_rating` / `press_rating` gives
`{key, value, label: "★ 4.1", text: "4.1", title}` (the text is that of `$user_rating`, one decimal and a dot; the title uses
`Intl.NumberFormat`: "Note des spectateurs : 4,1 sur 5"). In the row it is **plain text, not a pill**, in the look of the reference's own rating: the number in the line's colour and
only the star recoloured with the reference's `adjustedStar` (passed to the slot as `star`; there are no colour options for
the ratings). In texts the
badge tokens are the text (`$user_rating_badge` = `$user_rating`), or nothing.

**Hover tips and forwarded clicks.** A native `title` does not show reliably in a foreignObject under the item's click
area, so the age pill, the rating items and the version pills have `pointer-events: auto` (the row and foreignObject stay
`none`) and `umcExplain` / the pill listeners call `_showPillTip(anchor, text)`: a div on `<body>` (`data-umc-tip`, the
popover's dark look, placed by `umcPopoverPosition`) after `tooltip_delay`, independent of `enable_tooltips`, hidden on
leave, click, scroll, a popover opening, a render and disconnection. `mousemove` on these items does not bubble to the
item (no synopsis timer) and `_pillHover` stops a pending synopsis bubble. Age and rating items forward their click to the
item's `[data-umc-click]` area (`.click()`, the user activation is still valid), so the film link works; version pills still
open the popover. The `aria-label` stays.

**No extra line height.** The age and version pills have a 2px vertical padding; their `margin: -2px 0` keeps the row as
tall as a text line (the pill sticks out of its box), so the lines after a pill are where they would be after a text line
(they used to move 4 to 5 units down); wrapped rows are 10px apart so the pills stay 6px apart.

## `_badge` tokens, the age badge, ignored lines

**Convention.** `umcBadgeKind(template)` returns the kind (`showtimes`, `certificate`) when the trimmed template is
exactly `$showtimes_badge` or `$certificate_badge`; `umcIsBadgeLine` is that check. The plain `$showtimes` is text only
(a **breaking** change from the first version, where the exact `$showtimes` drew the badges); `$showtimes_badge` is
the same text in a tooltip or a mixed line and walks like `$showtimes` (`$showtimes_badge[0]`...); `$certificate_badge`
is the label (`-12 ans`) or nothing.

**Slots.** The render loop builds one slot per badge line with a `kind` (`showtimes`: `groups`; `certificate`:
`certificate`) and the common fields (size, colour, shadow, x, lang, plain `text`). Everything after it is shared:
the transparent "." tspan, `_layoutBadges` (measure, retry, ResizeObserver, viewBox growth, text fallback, overflow
engine, `_layoutAllBadges`). Only the row differs: `umcBuildBadgeRow` (buttons, popover) or `umcBuildCertificateRow` (one
`span` pill, `role="img"`, `title`, no pointer events; the foreignObject is `pointer-events: none` for it).

**Age.** `umcCertificateBadge(film, lang)`: the age of `certificate` (`/(\d{1,2})\s*ans/i`, or a leading `-12`),
bucketed to 18, 16, 12 or 10 (nearest lower; under 10, no age, "Tout public", "Avertissement": null, so the line is
ignored). The key is the colour option: `age_12` (also 10), `age_16`, `age_18`
(`age_12_color` ... defaults amber, orange, red, same `CSS.supports` guard and soft fill as the version pills).

**Ignored lines.** `umcLineIsIgnored(index, template, text)`: lines 1..6 whose resolved text is empty and that are not
an explicit `$empty` (the reference's `match("empty")` rule) emit no tspan at all, so no space is reserved in any engine,
and `neededUnits` / the viewBox growth count only the drawn lines. A badge line with nothing to show is ignored the
same way. Line 0 (the title) keeps the reference's handling.

## Accessibility marks in the popover (done)

Every showtime of the badge model has `pmr`, `sme` and `audio_description` (true only when `=== true`): from
`details.showtimes[i]`, or, when the film has no `details.showtimes`, true when its time is in `film.accessibility.pmr /
sme / audio_description` (duplicate times are all flagged). The group entries carry them (snake case, so the token
paths reach them: `$showtimes[0].pmr` is `Yes` / `No`; the `$showtimes` text, `$showtimes[n]` and the ordering are
unchanged). `umcAccessibilityFlags(entry, lang)` gives the true marks in the fixed order PMR, SME, audio description with
their mdi icon and label (`UMC_BADGE_TEXT`, en and fr); `umcAccessibilityLegend(entries, lang)` the marks present among a
popup's entries, once each. In `_toggleBadgePopover` a chip with marks is an inline-flex of a `time` span (a link has no underline) and one `ha-icon` per mark (`--mdc-icon-size: 14px`, `role="img"`, `title` and `aria-label`);
a chip without marks is built as before. The legend (10px, dimmed, centred, icons `aria-hidden`) closes the panel when at
least one mark appears. Icons: `mdi:wheelchair-accessibility`, `mdi:ear-hearing-off` (clearer for "deaf" than
`ear-hearing`, and `closed-caption` would be confused with the VOST subtitles), `mdi:account-voice`, all checked in the
installed frontend's `static/mdi/iconList.json`. The panel's minimum width and centring are unchanged: wider chips wrap.

## Version badges and their popover (replaces the per-showtime chips)

The badge row of a `$showtimes` line now has one pill per **version group** (`umcShowtimeGroups(film, lang)`: one group
per `version` of the showtimes, as is: VF, VO, VOST, other; non-empty groups only; entries in time order, on the real `starts_at` instant when there is
one; the third label is `AUTRES` for a French user, `OTHER` otherwise). A pill is a `<button>` (`aria-expanded`,
`aria-label`) with a soft fill (`color-mix(colour 22%, transparent)` with a `CSS.supports` guard and a neutral fallback)
and the count. All the line mechanics are unchanged (slot tspan, foreignObject, measurement, retries, text fallback,
viewBox growth); the foreignObject always takes clicks now and the svg is always lifted above the item's click area with
`pointer-events: none`.

A click toggles `_toggleBadgePopover`: one panel at a time on `<body>` (`position: fixed`, the card's bubble look:
dark blurred panel, 12x14 padding, same radius and shadow, z-index 1001), a header from `umcGroupHeader` (plural by
`Intl.PluralRules`, en and fr), the times as chips (in the colour of the group; http(s) ticket links are links with a pointer cursor, no underline), placed
by the pure `umcPopoverPosition(rect, size, viewport)` (above the pill, centred horizontally on the card, else below, clamped to the viewport; the panel is at least about 4 times wide, its content centred). It closes on a click outside,
Escape, scroll or resize of the page, a size change of the card (a ResizeObserver created per open), another click on its
pill, a new render and `disconnectedCallback`; its listeners are removed on close. The hover bubble of the item is
removed when it opens and is not created while it is open (`data-umc-tooltip` marks the bubbles). The pills stop
`mousedown` / `pointerdown` / `touchstart` and the click, so the item's film link and long-press handling are not
triggered. Texts only by `textContent` / `setAttribute`.

The earlier description of the per-showtime chips below is superseded by this section, except for the row mechanics.

## Showtime badges (`$showtimes`)

`umcShowtimeBadges(film)` (pure) gives `[{time, version, label, url}]`, sorted by time then VF, VO, VOST, other, from
`details.showtimes` or, without it, from the `vf` / `vo` / `vost` / `other` lists; the ticket url is kept only when
http(s). `$showtimes` is a token of the static `keys` map: the plain text `VF 20:30, VO 22:00` (tooltip, mixed lines).
A line whose template is exactly `$showtimes` (`umcIsBadgeLine`) is drawn as badges instead.

Changes to the reference's svg and lines code, all only for such a line:

1. In the line loop, the line gets the transparent `.` tspan of an empty line (`fill: transparent`), with
   `data-umc-badges="i"`, so it keeps its place in the svg text; `neededUnits` (lines 5-6) counts it.
2. `applyBadges(container)`, next to the reference's `applyLine4FO`, hands the slots to the new `_layoutBadges`, which
   follows the `$likes` precedent: a `foreignObject` in the item's svg at the tspan's `getBBox().y`, `x` 12 (poster) or 0
   (fanart), `width` 200 - x, holding an HTML row (`umcBuildBadgeRow`: `textContent` and `setAttribute` only,
   `flex-wrap`, gap 4, font size = the line's, colours assigned only when `CSS.supports`).
3. The row is in the svg's units, so it wraps the same at every card width: it is measured once (`offsetHeight`), no
   ResizeObserver is needed. The room is made by adding the extra height to the `dy` of the next tspan that has text,
   and by growing the svg `viewBox` height only when the text now reaches below it (an item is as tall as its poster,
   or, in fanart, as its svg). Items without `$showtimes` are untouched (same heights).
4. A hidden (collapsed) item cannot be measured: the expand handler calls `_layoutBadges` for the items it shows.
   4b. An item that cannot be measured yet is not given up on: it can be drawn while the card is not in the page (a
   dashboard view that is not shown yet, a card built before it is attached), and the overflow engine moves items between
   columns. `_layoutBadges` then watches the item (`_pendBadges`: one shared ResizeObserver, created lazily, plus up to 60
   animation frames, rule in `umcShouldRetry`) and lays it out as soon as it has a size; `_layoutAllBadges` (idempotent,
   `_umcBadgesDone`) also runs after the overflow section of the render and on `connectedCallback`. Past the frame limit
   the slot shows the plain text meanwhile; the observer still replaces it with the badges later. After layout a row with no
   size or outside its item is replaced by the plain text. Observer and frames are stopped in `disconnectedCallback` and
   at each render.
5. When a badge is a link the svg is lifted above the item's click area (`position: relative; z-index: 6`) with
   `pointer-events: none`, and the foreignObject `pointer-events: auto`: only the badges take clicks, the rest of the item
   still opens the film page.

Options `vf_color`, `vo_color`, `vost_color`, `other_color` (text fields next to the other colours; theme defaults).
Accessibility marks: see the next section.

## Entry point

`entry_point` (default `films`) is the name of the sensor attribute holding the list of films: `filmsToItems`,
`sensorProblem` (so the day chips) and the editor's token names read it. A missing or non-list attribute is "no film":
the usual unavailable message, no error.

## Tooltip text

`tooltip_text` (default `$synopsis`, stripped from the editor's output when equal to it) is a template resolved per
item with the lines' machinery (`resolveText`, same `keys`), by the pure `umcTooltipText`. The bubble is shown through
`textContent`, so it uses `item._filmRaw`: the film's values without the sanitising of `_film` (`<` `>` kept, no
`&amp;` escaping), and the entities are decoded at the end (`&amp;`, `&#39;`, `&eacute;` ... as characters).
`_filmRaw` is not enumerable, so it stays out of the card's JSON cache key. An empty result is no tooltip. The adapter's
`summary` key is gone. The reference's bubble (`white-space: pre-wrap`, 240-340 px wide, no truncation) is unchanged, so
a newline in the template is a line break. `resolveText` marks a missing token with a sentinel character instead of the
text "null", which made any value containing "null" (French "nulle part") vanish with its whole part.

## Lines 5 and 6 (poster view only)

`line5_text` / `line6_text` reuse the mechanics of lines 1-4 (`line5_size`, `line5_color`, the `_line5_` / `_line6_`
classes, truncation, `line_size` and `line_color` fallbacks) in the **poster** style block and its svg `<text>`; the
fanart layout has no room and ignores them (`umcLineShown`). No default: an unset line is not drawn and reserves
nothing, so existing cards do not change. The item is as tall as the poster, which is too short for six lines on some
posters: when a line 5 or 6 is configured, the poster svg's viewBox height grows from 100 to the height the drawn
lines need (the scale does not change), and only then. The `$likes` handling of line 4 is not extended. The editor has
Line 5 / Line 6 text and colour fields; the helper says "Poster view only".

## Phase 2, step 1: day selector (done)

A row of chips just below the search zone, built like it (inline styles, the search row's 15 px margins), shown
whether or not `enable_search` is on, with `enable_days` (default `true`) and hidden below two day sensors.
`dayChips` builds one chip per day sensor (`today`, `tomorrow`, `day_2` ... `day_6`) with a label from
`Intl.RelativeTimeFormat` (first two days) or a short weekday and day number (`Intl.DateTimeFormat`), in
`hass.locale.language`; the sensor's `date` is parsed as a local date. An unavailable sensor is a disabled chip. The
choice is remembered **by date** (`resolveSelection`): after midnight the card stays on the chosen day while a sensor
holds it, falls back to today when it is gone, and keeps an unavailable chosen sensor selected (its message is shown,
the row stays). The chips are centred and laid out in balanced lines of at least two (`dayLineSizes`: widest chip measured once, a
ResizeObserver on the row, created once and disconnected in `disconnectedCallback`; a long label is ellipsised). A click redraws like the search does (`_redraw`, the search filter stays); the chips are rebuilt only
when their keys, dates, availability or selection change.

## Deliberately postponed

Time chips, tooltips with a styled synopsis (the reference's tooltip works with `enable_tooltips`), French translation of the
editor and messages.

## Tests

`tests/card/card.test.mjs` (Node's test runner) covers the pure pieces; `contract.mjs` checks, on a real snapshot of
the sensors, that the adapter fills every field the attributes have. `tests/card/test_card_js.py` runs both and
`node --check`. ESLint is relaxed for the card file only (`eqeqeq`, `prefer-const`, `no-var`, `no-unused-vars`).
