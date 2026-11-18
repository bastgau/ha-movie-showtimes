/**
 * movie-showtimes-card - Lovelace card of the Movie Showtimes integration.
 *
 * Copyright (c) 2026 Bastien Gautier
 *
 * This file is a near-verbatim fork of card/upcoming-media-card.js from
 * https://github.com/bastgau/ha-betaseries at commit
 * 46a6ef3c2cc88eaf339f84a4680ccba0bc973879 (itself a fork of
 * https://github.com/custom-cards/upcoming-media-card). Changes: BetaSeries
 * removed, a cinema selector and an adapter from the sensors' `films`
 * attribute to the reference's items, film `$tokens`, a local search over the
 * films. Everything else is the reference's.
 *
 * Upstream notices, verbatim:
 *
 * ---- bastgau/ha-betaseries (LICENSE) ----
 *
 * MIT License
 *
 * Copyright (c) 2026 Bastien Gautier
 *
 * ---- custom-cards/upcoming-media-card (LICENSE) ----
 *
 * MIT License
 *
 * Copyright (c) 2026 Custom cards for Home Assistant
 *
 * ---- Full MIT text (applies to the notices above and to this file) ----
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

// ── Movie Showtimes: the only code that is not the reference's ─────────────
// The reference reads the `data` attribute of one sensor: a list whose element 0 is
// a template ({title_default, line1_default..line4_default, icon}) and whose other
// elements are items ({airdate, title, poster, runtime, ...}). Our sensors expose
// `films`; filmsToItems() converts one to the other so the rendering code below is
// the reference's.
const UMC_PLATFORM = "movie_showtimes";

// Which code is running: shown in the console (see the banner at the end) and as
// `customElements.get("movie-showtimes-card").build`. CARD_BUILD is the UTC date and time of the
// last edit of this file: bump it with every change.
const CARD_VERSION = "1.0.0";
const CARD_BUILD = "2026-11-16 14:07";

// The console banner: version, build, and the `v` hash of the url the module was loaded with (the
// cache-busting query added by the integration at Home Assistant's start; "none" without).
function umcBanner(version, build, url) {
  const hash = /[?&]v=([^&#]*)/.exec(String(url || ""));
  return `MOVIE-SHOWTIMES-CARD ${version} · build ${build} · url v=${hash ? hash[1] : "none"}`;
}
// The attribute holding the list of films the card (and its tokens) reads; option `entry_point`.
const UMC_ENTRY_POINT = "films";
// translation_key of the day sensors, from today on. Only the first one is read for now.
const UMC_DAY_KEYS = [
  "today",
  "tomorrow",
  "day_2",
  "day_3",
  "day_4",
  "day_5",
  "day_6",
];

// Grey 2:3 placeholder for a film without poster (no request; keeps the card's height).
const UMC_NO_POSTER =
  "data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 2 3%27%3E" +
  "%3Crect width=%272%27 height=%273%27 fill=%27%23999%27 fill-opacity=%27.25%27/%3E%3C/svg%3E";

// A token: `$name`, then any number of steps: `[n]` (the n-th element of a list, 0-based, negative from
// the end) and `.key` (into an object). A `.` or `[` that does not start a valid step is not part of
// the token ("Rated $user_rating." keeps its period). Longest match wins, so `$release_date` is not
// `$release` + `_date`. What a token means: see umcTokenValue.
const UMC_KEYWORDS =
  /\$[a-z][a-z0-9_]*(?:\[-?\d+\])*(?:\.[a-z][a-z0-9_]*(?:\[-?\d+\])*)*/g;

// Shown under the text lines when the cinema has no film yet to take the names from.
const UMC_PATH_HELP =
  "Reach into lists and objects: $genres[0], $vo[0], $accessibility.pmr[0]; .key on a list gives that " +
  "key of each item ($details.showtimes.time[0], $showtimes.time[0]); $showtimes[0] is the first showtime. " +
  "A line with a $..._badge token is drawn as badges: $showtimes_badge (VF, VO, OTHER: click one for its times), " +
  "$certificate_badge (-12 ans), $user_rating_badge and $press_rating_badge (★ 4.1).";

const UMC_FILM_TOKENS_HELP =
  "Tokens: any attribute of a film by its name, e.g. $title, $original_title, $year, $runtime, " +
  "$genres, $directors, $cast, $certificate, $user_rating, $film_type, $visa_number, " +
  "$synopsis; and $day, $date. Separate parts with ' - ': a part whose token is empty is left out. " +
  UMC_PATH_HELP;

// Entities of one cinema's day sensors: { today: "sensor.x", tomorrow: ... }.
function resolveDaySensors(hass, deviceId) {
  const sensors = {};
  for (const entry of Object.values(hass.entities || {})) {
    if (
      entry.platform === UMC_PLATFORM &&
      entry.device_id === deviceId &&
      UMC_DAY_KEYS.includes(entry.translation_key)
    ) {
      sensors[entry.translation_key] = entry.entity_id;
    }
  }
  return sensors;
}

// The cinema: `device_id`, or the device of `entity` (any sensor of it).
function resolveDeviceId(hass, config) {
  let deviceId = config.device_id;
  if (!deviceId && config.entity) {
    const entry = (hass.entities || {})[config.entity];
    deviceId = entry && entry.device_id;
  }
  return deviceId || null;
}

// The sensor to read for one day of the cinema.
function resolveDayEntity(hass, config, dayKey = UMC_DAY_KEYS[0]) {
  const deviceId = resolveDeviceId(hass, config);
  if (!deviceId) return null;
  return resolveDaySensors(hass, deviceId)[dayKey] || null;
}

// Why there is nothing to draw, or null.
// `entryPoint`: the attribute holding the list of films (default `films`).
function sensorProblem(entity, state, entryPoint = UMC_ENTRY_POINT) {
  if (!entity) return "No Movie Showtimes sensor found for this cinema.";
  if (
    !state ||
    state.state === "unavailable" ||
    !state.attributes ||
    !Array.isArray(state.attributes[entryPoint])
  ) {
    return "Showtimes unavailable.";
  }
  return null;
}

// "YYYY-MM-DD" as a LOCAL date (new Date("YYYY-MM-DD") is UTC: a day early west of UTC).
function parseLocalDate(text) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text || "");
  return match ? new Date(+match[1], +match[2] - 1, +match[3]) : null;
}

// Label of a day chip, in the user's language: "today" / "tomorrow" for the first two
// days, then a short weekday and the day number ("sat. 14"). `date` may be null (unavailable
// sensor): the day is then `offset` days after `now`.
function dayLabel(offset, date, lang, now = new Date()) {
  const day =
    parseLocalDate(date) ||
    new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
  let locale = lang || "en";
  try {
    Intl.getCanonicalLocales(locale);
  } catch (_) {
    locale = "en";
  }
  if (offset < 2) {
    // "today" / "tomorrow" come lower-cased from Intl: capitalise the first letter.
    const relative = new Intl.RelativeTimeFormat(locale, {
      numeric: "auto",
    }).format(offset, "day");
    return relative.charAt(0).toLocaleUpperCase(locale) + relative.slice(1);
  }
  const weekday = new Intl.DateTimeFormat(locale, { weekday: "short" }).format(
    day,
  );
  return `${weekday} ${day.getDate()}`;
}

// One chip per day sensor of the cinema, from today on: { key, offset, entity, available,
// date, label }. `date` (the sensor's `date` attribute) is null when the sensor is unavailable.
function dayChips(hass, config, lang, now = new Date()) {
  const deviceId = resolveDeviceId(hass, config);
  if (!deviceId) return [];
  const sensors = resolveDaySensors(hass, deviceId);
  return UMC_DAY_KEYS.filter((key) => sensors[key]).map((key) => {
    const offset = UMC_DAY_KEYS.indexOf(key);
    const entity = sensors[key];
    const available = !sensorProblem(
      entity,
      hass.states[entity],
      config.entry_point || UMC_ENTRY_POINT,
    );
    const date =
      available && parseLocalDate(hass.states[entity].attributes.date)
        ? hass.states[entity].attributes.date
        : null;
    return {
      key,
      offset,
      entity,
      available,
      date,
      label: dayLabel(offset, date, lang, now),
    };
  });
}

// Splits the chips (their measured widths, in order) into consecutive lines of at least two.
// Fewest lines that fit in `rowWidth`; among those, the most balanced (the closest chip
// counts, the larger lines on top, then the narrowest widest line). If nothing fits (a chip wider than the row), the most lines
// allowed, balanced the same way: the widest chips are then ellipsised. Returns line sizes.
function dayLineSplit(widths, rowWidth, gap = 8) {
  const count = widths.length;
  if (count < 2) return [count];
  // The compositions of `count` into `rows` parts of at least 2, as arrays of part sizes.
  const parts = (left, rows) =>
    rows === 1
      ? left >= 2
        ? [[left]]
        : []
      : Array.from({ length: left - 2 * rows + 1 }, (_, k) => k + 2).flatMap(
          (first) =>
            parts(left - first, rows - 1).map((rest) => [first, ...rest]),
        );
  const measure = (sizes) => {
    let from = 0;
    const lines = sizes.map((size) => {
      const line = widths.slice(from, from + size);
      from += size;
      return line.reduce((sum, w) => sum + w, 0) + gap * (size - 1);
    });
    return [Math.max(...lines), Math.max(...sizes) - Math.min(...sizes)];
  };
  // Most even chip counts first, then the larger lines on top (4 + 3, not 3 + 4), then the
  // narrowest widest line.
  const best = (candidates) =>
    candidates
      .map((sizes) => ({ sizes, score: measure(sizes) }))
      .sort((a, b) => {
        if (a.score[1] !== b.score[1]) return a.score[1] - b.score[1];
        const at = a.sizes.findIndex((size, i) => size !== b.sizes[i]);
        if (at >= 0) return b.sizes[at] - a.sizes[at];
        return a.score[0] - b.score[0];
      })[0];
  const most = Math.floor(count / 2);
  for (let rows = 1; rows <= most; rows++) {
    const fitting = parts(count, rows).filter(
      (sizes) => measure(sizes)[0] <= rowWidth,
    );
    if (fitting.length) return best(fitting).sizes;
  }
  return best(parts(count, most)).sizes;
}

// The chip to show. The choice is remembered by date, so that after midnight the card stays
// on the day the user chose while a sensor still holds it: 1. the available chip with that
// date; 2. the chip of the same key if it is unavailable (the problem is shown, the row stays);
// 3. today (the first chip). `selected` is { date, key }; null when there is no chip.
function resolveSelection(chips, selected) {
  const sel = selected || {};
  return (
    chips.find((chip) => chip.available && chip.date === sel.date) ||
    chips.find((chip) => !chip.available && chip.key === sel.key) ||
    chips[0] ||
    null
  );
}

// Source text ends up in innerHTML in the reference: drop tags, keep entities literal.
const umcClean = (value) =>
  typeof value === "string" && value
    ? value.replace(/[<>]/g, "").replace(/&(?=#?\w+;)/g, "&amp;")
    : null;
const umcCleanList = (value) =>
  Array.isArray(value) ? value.map(umcClean).filter(Boolean) : null;
const umcUrl = (value) =>
  typeof value === "string" && /^https?:\/\/[^\s"'<>\\]+$/i.test(value)
    ? value
    : null;
// HTML from the source (`synopsis_full`) as one line of plain text; tags removed, entities decoded.
function umcHtmlText(html) {
  return umcDecodeEntities(
    String(html)
      .replace(/<\/p>|<br\s*\/?>/gi, " ")
      .replace(/<[^>]*>/g, ""),
  )
    .replace(/\s+/g, " ")
    .trim();
}

// `&amp;`, `&#39;`, `&#x27;`, `&eacute;`... as characters (the common named ones; others stay as
// they are). Only for text that is shown through textContent, or that is cleaned afterwards.
function umcDecodeEntities(text) {
  const named = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
  return String(text).replace(
    /&(#x[0-9a-f]+|#\d+|[a-z]+);/gi,
    (match, entity) => {
      if (entity[0] !== "#") return named[entity.toLowerCase()] ?? match;
      const code =
        entity[1] === "x" || entity[1] === "X"
          ? parseInt(entity.slice(2), 16)
          : parseInt(entity.slice(1), 10);
      return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : match;
    },
  );
}

// The text of one film attribute as a token value, already sanitised (the reference puts text in
// innerHTML): a string as is, a number as is, a list of scalars joined with ", ", true / false as
// "Yes" / "No"; objects and lists of objects (accessibility, showtimes, credits...) are not
// supported: null, like an empty value.
function umcTokenText(name, value, clean = umcClean) {
  if (typeof value === "string") {
    return clean(name === "synopsis_full" ? umcHtmlText(value) : value);
  }
  if (typeof value === "number")
    return Number.isFinite(value) ? String(value) : null;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (!Array.isArray(value)) return null;
  const items = value.filter((item) => item !== null && item !== undefined);
  if (items.some((item) => typeof item === "object")) return null;
  const texts = items
    .map((item) => umcTokenText(name, item, clean))
    .filter(Boolean);
  return texts.length ? texts.join(", ") : null;
}

const umcRaw = (value) => (typeof value === "string" && value ? value : null);

// Every supported attribute of a film (and of its `details`) as { name: text }; the film's own
// keys win over `details`.
// `clean` is umcClean for the values that reach innerHTML, and umcRaw for the tooltip (textContent).
function umcFilmValues(film, clean = umcClean) {
  const values = {};
  for (const source of [film, film.details]) {
    for (const [name, value] of Object.entries(source || {})) {
      if (!/^[a-z][a-z0-9_]*$/.test(name) || Object.hasOwn(values, name))
        continue;
      const text = umcTokenText(name, value, clean);
      if (text !== null) values[name] = text;
    }
  }
  return values;
}

// The names usable as `$name` for this film: its attributes, then the reference's `day` and `date`.
function filmTokenNames(film) {
  if (!film || typeof film !== "object") return [];
  return [
    ...new Set([
      ...Object.keys(umcFilmValues(film)),
      "showtimes",
      "showtimes_badge",
      "certificate_badge",
      "user_rating_badge",
      "press_rating_badge",
      "day",
      "date",
    ]),
  ];
}

// The text shown under the line fields of the editor.
function umcTokenHelp(names) {
  if (!names.length) return UMC_FILM_TOKENS_HELP;
  return (
    "Tokens: " +
    names.map((name) => "$" + name).join(", ") +
    " (any attribute of a film, by its name). Separate parts with ' - ': a part whose token is " +
    "empty is left out. " +
    UMC_PATH_HELP
  );
}

// The value of a `$token`. A bare `$name`: the reference's own (and the formatted ones, in `keys`)
// first, then the film's attribute of that name (`film`: the item's `_film`). A token with steps
// (`$vo[0]`, `$accessibility.pmr[0]`): resolved on the raw film (`deep`: { raw, clean }), see
// umcPathText. null when there is none.
function umcTokenValue(token, keys, film, deep) {
  if (!/^\$[a-z][a-z0-9_]*$/.test(token)) return umcPathText(token, deep);
  const own = keys[token];
  if (own !== undefined && own !== null) return own;
  const name = token.slice(1);
  return film && Object.hasOwn(film, name) ? film[name] : null;
}

// A token with steps on the raw film: the first name is a key of the film, or of its `details`;
// then `[n]` needs a list and an index in range, `.key` an object that owns the key (own
// properties only: `.constructor` or `.toString` find nothing). Anything else, and a result that is
// an object or a list of objects, is null (empty). The leaf is formatted like a flat token and
// passed through `deep.clean` (umcClean for the lines, which reach innerHTML).
// Follows the steps of a path (`[n]`, `.key`, see umcPathText) from a value: { value, last } (`last`
// is the last key followed, "" if none), or null when a step finds nothing.
function umcWalkSteps(start, steps) {
  let value = start;
  let last = "";
  for (const step of steps.matchAll(/\[(-?\d+)\]|\.([a-z][a-z0-9_]*)/g)) {
    if (step[1] !== undefined) {
      if (!Array.isArray(value)) return null;
      const index = Number(step[1]);
      const at = index < 0 ? value.length + index : index;
      if (at < 0 || at >= value.length) return null;
      value = value[at];
    } else if (Array.isArray(value)) {
      // `.key` on a list: the list of that key's scalar values of its objects (`$details.showtimes.time`).
      value = value
        .filter(
          (element) =>
            element &&
            typeof element === "object" &&
            !Array.isArray(element) &&
            Object.hasOwn(element, step[2]),
        )
        .map((element) => element[step[2]])
        .filter((leaf) =>
          ["string", "number", "boolean"].includes(typeof leaf),
        );
      last = step[2];
    } else {
      if (
        value === null ||
        typeof value !== "object" ||
        !Object.hasOwn(value, step[2])
      )
        return null;
      value = value[step[2]];
      last = step[2];
    }
  }
  return { value, last };
}

function umcPathText(token, deep) {
  const film = deep && deep.raw;
  if (!film || typeof film !== "object") return null;
  const head = /^\$([a-z][a-z0-9_]*)/.exec(token);
  const details =
    film.details && typeof film.details === "object" ? film.details : {};
  // `$showtimes[n]`: the n-th showtime of the badges' model ("VOST 08:55"), not the raw objects.
  let value =
    head[1] === "showtimes" || head[1] === "showtimes_badge"
      ? umcShowtimeBadges(film)
      : Object.hasOwn(film, head[1])
        ? film[head[1]]
        : Object.hasOwn(details, head[1])
          ? details[head[1]]
          : undefined;
  const walked = umcWalkSteps(value, token.slice(head[0].length));
  if (!walked) return null;
  value = walked.value;
  const last = walked.last || head[1];
  // A badge itself (`$showtimes[0]`) is its label and time ("VO 20:30").
  if (
    (head[1] === "showtimes" || head[1] === "showtimes_badge") &&
    umcIsBadge(value)
  ) {
    value = umcShowtimeLabel(value);
  }
  return value === undefined ? null : umcTokenText(last, value, deep.clean);
}

// A badge object of umcShowtimeBadges.
function umcIsBadge(value) {
  return (
    !!value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    typeof value.label === "string" &&
    typeof value.time === "string"
  );
}

// ── Sorting ─────────────────────────────────────────────────────────────────
// The value a film is sorted on, from `sort_by`: an attribute of the film or a path into it (as in a
// token: `user_rating`, `genres[0]`, `details.showtimes[0].starts_at`; a leading `$` is ignored). The
// first name is a key of the film or of its `details`. Returns { kind, value } with kind "number",
// "date" (an ISO date or date-time string, as milliseconds), "boolean" or "string", or null when the
// value is missing: no such attribute, an empty value, NaN, an object. A list is its first element.
// The old names of the reference: `rating` is `user_rating`; `airdate` is no film attribute (missing).
function umcSortValue(film, path) {
  if (!film || typeof film !== "object") return null;
  let name = String(path || "")
    .trim()
    .replace(/^\$/, "");
  if (name === "rating") name = "user_rating";
  const parsed = /^([a-z][a-z0-9_]*)((?:\[-?\d+\]|\.[a-z][a-z0-9_]*)*)$/.exec(
    name,
  );
  if (!parsed) return null;
  const details =
    film.details && typeof film.details === "object" ? film.details : {};
  const first = Object.hasOwn(film, parsed[1])
    ? film[parsed[1]]
    : Object.hasOwn(details, parsed[1])
      ? details[parsed[1]]
      : undefined;
  const walked = umcWalkSteps(first, parsed[2]);
  let value = walked ? walked.value : undefined;
  if (Array.isArray(value)) value = value[0];
  if (typeof value === "number")
    return Number.isNaN(value) ? null : { kind: "number", value };
  if (typeof value === "boolean") return { kind: "boolean", value: +value };
  if (typeof value !== "string" || value.trim() === "") return null;
  if (/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}.*)?$/.test(value)) {
    const time = Date.parse(value);
    if (!Number.isNaN(time)) return { kind: "date", value: time };
  }
  return { kind: "string", value };
}

// The items (the reference's, without the template) sorted on `path`, as a new list. Films without a
// value come last whatever the direction, ties keep the original order, numbers and dates come
// before booleans, and those before strings; strings compare without case and accents, numbers inside
// them as numbers ("Film 2" before "Film 10"). An item without `_filmObj` has no value.
function umcSortItems(items, path, ascending = true) {
  const rank = { number: 0, date: 0, boolean: 1, string: 2 };
  const entries = items.map((item, index) => ({
    item,
    index,
    sort: umcSortValue(item && item._filmObj, path),
  }));
  const compare = (a, b) => {
    if (a.sort === null || b.sort === null) {
      return a.sort === b.sort ? a.index - b.index : a.sort === null ? 1 : -1;
    }
    let order = rank[a.sort.kind] - rank[b.sort.kind];
    if (order === 0) {
      order =
        a.sort.kind === "string"
          ? a.sort.value.localeCompare(b.sort.value, undefined, {
              numeric: true,
              sensitivity: "base",
            })
          : a.sort.value - b.sort.value;
      if (order !== 0 && !ascending) order = -order;
    } else if (!ascending) {
      order = -order;
    }
    return order || a.index - b.index;
  };
  return entries.sort(compare).map((entry) => entry.item);
}

// ── Showtime badges (`$showtimes`) ─────────────────────────────────────────
// Whether to try again to lay out badge rows that could not be measured yet (the item is not in
// the page, or not shown): while some are pending and fewer than `limit` animation frames passed.
function umcShouldRetry(pending, frame, limit = 60) {
  return pending > 0 && frame < limit;
}

const UMC_NOT_READY = new Error("not measurable yet");
const UMC_VERSIONS = ["vf", "vo", "vost", "other"];
const UMC_VERSION_LABELS = { vf: "VF", vo: "VO", vost: "VOST", other: "?" };

// The showtimes of a film as badges: [{ time, version, label, url }], in time order (then VF, VO,
// VOST, other). They come from `details.showtimes`; without it, from the lists `vf` / `vo` / `vost` /
// `other` of "HH:MM" strings. An unknown version is "other"; a ticket url is kept only when it is
// http(s). The sensor already drops the showtimes that are past.
function umcShowtimeBadges(film) {
  if (!film || typeof film !== "object") return [];
  const details =
    film.details && typeof film.details === "object" ? film.details : {};
  let found = [];
  if (Array.isArray(details.showtimes) && details.showtimes.length) {
    found = details.showtimes
      .filter((showtime) => showtime && typeof showtime === "object")
      .map((showtime) => ({
        time: showtime.time,
        version: showtime.version,
        url: showtime.ticket_url,
        startsAt: showtime.starts_at,
        subtitled: showtime.subtitled === true,
        pmr: showtime.pmr === true,
        sme: showtime.sme === true,
        audio_description: showtime.audio_description === true,
      }));
  } else {
    // Without `details.showtimes`: flagged when the time is in the `accessibility` lists.
    const accessibility =
      film.accessibility && typeof film.accessibility === "object"
        ? film.accessibility
        : {};
    const listed = (key) =>
      new Set(
        Array.isArray(accessibility[key])
          ? accessibility[key]
              .filter((time) => typeof time === "string")
              .map((time) => time.padStart(5, "0"))
          : [],
      );
    const flagged = {
      pmr: listed("pmr"),
      sme: listed("sme"),
      audio_description: listed("audio_description"),
    };
    for (const version of UMC_VERSIONS) {
      if (!Array.isArray(film[version])) continue;
      for (const time of film[version]) {
        const padded = typeof time === "string" ? time.padStart(5, "0") : "";
        found.push({
          time,
          version,
          url: null,
          startsAt: null,
          subtitled: false,
          pmr: flagged.pmr.has(padded),
          sme: flagged.sme.has(padded),
          audio_description: flagged.audio_description.has(padded),
        });
      }
    }
  }
  return found
    .filter(
      (showtime) =>
        typeof showtime.time === "string" &&
        /^\d{1,2}:\d{2}$/.test(showtime.time),
    )
    .map((showtime) => {
      const version = UMC_VERSIONS.includes(showtime.version)
        ? showtime.version
        : "other";
      return {
        time: showtime.time.padStart(5, "0"),
        version,
        label: UMC_VERSION_LABELS[version],
        url: umcUrl(showtime.url),
        subtitled: showtime.subtitled === true,
        pmr: showtime.pmr === true,
        sme: showtime.sme === true,
        audio_description: showtime.audio_description === true,
        instant: Date.parse(showtime.startsAt),
      };
    })
    .sort(
      (a, b) =>
        // The real instant when both have one (a 00:15 showtime of the next night comes last).
        (Number.isNaN(a.instant) || Number.isNaN(b.instant)
          ? 0
          : a.instant - b.instant) ||
        a.time.localeCompare(b.time) ||
        UMC_VERSIONS.indexOf(a.version) - UMC_VERSIONS.indexOf(b.version),
    )
    .map(({ instant, ...badge }) => badge);
}

// The language to use for our own texts: a valid language tag of the user, else English.
function umcLocale(lang) {
  const locale = lang || "en";
  try {
    Intl.getCanonicalLocales(locale);
    return locale;
  } catch (_) {
    return "en";
  }
}

const UMC_BADGE_TEXT = {
  en: {
    other: "OTHER",
    one: "showtime",
    many: "showtimes",
    pmr: "Wheelchair accessible",
    sme: "Subtitles for the deaf and hard of hearing",
    audio_description: "Audio description",
  },
  fr: {
    other: "AUTRES",
    one: "séance",
    many: "séances",
    pmr: "Accès PMR",
    sme: "Sous-titres pour sourds et malentendants",
    audio_description: "Audiodescription",
  },
};
// The accessibility marks of a showtime, in the order they are shown, with their mdi icon
// (all three names exist in the installed frontend's mdi list).
const UMC_ACCESSIBILITY = [
  { key: "pmr", icon: "mdi:wheelchair-accessibility" },
  { key: "sme", icon: "mdi:ear-hearing-off" },
  { key: "audio_description", icon: "mdi:account-voice" },
];
const umcBadgeText = (lang) =>
  UMC_BADGE_TEXT[umcLocale(lang).toLowerCase().startsWith("fr") ? "fr" : "en"];

// The showtimes of a film by their own `version` (vf, vo, vost, other): [{ key, label, count, entries }]
// for the groups that are not empty, in the order VF, VO, VOST, other. Entries: { time, version,
// subtitled, url }, in time order (see umcShowtimeBadges). The label of the last group follows the
// language ("AUTRES" in French).
function umcShowtimeGroups(film, lang) {
  const text = umcBadgeText(lang);
  const groups = [
    { key: "vf", label: "VF", entries: [] },
    { key: "vo", label: "VO", entries: [] },
    { key: "vost", label: "VOST", entries: [] },
    { key: "other", label: text.other, entries: [] },
  ];
  for (const badge of umcShowtimeBadges(film)) {
    groups
      .find((group) => group.key === badge.version)
      .entries.push({
        time: badge.time,
        version: badge.version,
        subtitled: badge.subtitled,
        url: badge.url,
        pmr: badge.pmr,
        sme: badge.sme,
        audio_description: badge.audio_description,
      });
  }
  return groups
    .filter((group) => group.entries.length)
    .map((group) => ({ ...group, count: group.entries.length }));
}

// The accessibility marks of one showtime entry that are true: [{ key, icon, label }] in the fixed
// order (wheelchair, deaf and hard of hearing, audio description); label in the user's language.
function umcAccessibilityFlags(entry, lang) {
  const text = umcBadgeText(lang);
  return UMC_ACCESSIBILITY.filter(
    ({ key }) => entry && entry[key] === true,
  ).map(({ key, icon }) => ({ key, icon, label: text[key] }));
}

// The marks that appear among the entries of a popup, each once, in the fixed order: its legend.
function umcAccessibilityLegend(entries, lang) {
  const present = new Set(
    entries.flatMap((entry) =>
      umcAccessibilityFlags(entry, lang).map((flag) => flag.key),
    ),
  );
  const text = umcBadgeText(lang);
  return UMC_ACCESSIBILITY.filter(({ key }) => present.has(key)).map(
    ({ key, icon }) => ({ key, icon, label: text[key] }),
  );
}

// An `ha-icon` of the frontend (size through its CSS variable, colour inherited).
function umcAccessibilityIcon(flag, size, labelled) {
  const icon = document.createElement("ha-icon");
  icon.setAttribute("icon", flag.icon);
  icon.style.setProperty("--mdc-icon-size", size + "px");
  icon.style.display = "inline-flex";
  icon.style.flex = "none";
  icon.style.color = "inherit";
  icon.style.opacity = "0.85";
  if (labelled) {
    icon.setAttribute("role", "img");
    icon.setAttribute("title", flag.label);
    icon.setAttribute("aria-label", flag.label);
  } else {
    icon.setAttribute("aria-hidden", "true");
  }
  return icon;
}

// "VF · 4 showtimes", "VF · 4 séances" (the plural form follows the language).
function umcGroupHeader(group, lang) {
  const text = umcBadgeText(lang);
  const one =
    new Intl.PluralRules(umcLocale(lang)).select(group.count) === "one";
  const word = one ? text.one : text.many;
  // "VF · 4 Showtimes": the word starts with a capital letter (in the user's language).
  const capital =
    word.charAt(0).toLocaleUpperCase(umcLocale(lang)) + word.slice(1);
  return `${group.label} · ${group.count} ${capital}`;
}

// Where the popover goes: { left, top }, in the viewport. Above the anchor if it fits, else below if
// it fits, else the side with more room. Horizontally it is centred on `centerOn` (the card's box)
// when given, else on the anchor; kept `margin` px inside the viewport.
function umcPopoverPosition(
  rect,
  size,
  viewport,
  gap = 6,
  margin = 8,
  centerOn = rect,
) {
  const above = rect.top - gap - size.height;
  const below = rect.bottom + gap;
  let top;
  if (above >= margin) top = above;
  else if (below + size.height <= viewport.height - margin) top = below;
  else top = rect.top > viewport.height - rect.bottom ? above : below;
  top = Math.max(margin, Math.min(top, viewport.height - size.height - margin));
  const centre = (centerOn.left + centerOn.right) / 2;
  const left = Math.max(
    margin,
    Math.min(centre - size.width / 2, viewport.width - size.width - margin),
  );
  return { left, top };
}

// The colours of the version badges: the options when the browser accepts them, else the defaults.
function umcBadgeColors(options) {
  const accepted = (value, fallback) =>
    value && typeof CSS !== "undefined" && CSS.supports("color", value)
      ? value
      : fallback;
  return {
    vf: accepted(options.vf, "var(--primary-color)"),
    vo: accepted(options.vo, "var(--accent-color, #ff9800)"),
    vost: accepted(
      options.vost,
      "color-mix(in srgb, var(--primary-color) 50%, var(--accent-color, #ff9800))",
    ),
    other: accepted(options.other, "var(--secondary-text-color)"),
  };
}

// A soft fill in a colour (the colour at `percent`%, see-through), or a neutral one where the
// browser does not know color-mix.
function umcSoftFill(color, percent) {
  const mix = `color-mix(in srgb, ${color} ${percent}%, transparent)`;
  return typeof CSS !== "undefined" && CSS.supports("background-color", mix)
    ? mix
    : "rgba(128, 128, 128, 0.25)";
}

// The showtimes as plain text, "VF 20:30, VO 22:00": what `$showtimes` is in a text that is not
// drawn as badges (the tooltip, a line that mixes it with other text).
function umcShowtimesText(film) {
  return umcShowtimeBadges(film).map(umcShowtimeLabel).join(", ");
}

// One showtime as text: "VOST 08:55".
function umcShowtimeLabel(badge) {
  return badge.label + " " + badge.time;
}

// The `$<thing>_badge` tokens (name -> kind of badge). A badge token is only ever drawn as a badge,
// in the lines; in the tooltip and other texts it is plain text. The plain `$<thing>` tokens are
// always text.
const UMC_BADGE_TOKENS = {
  $showtimes_badge: "showtimes",
  $certificate_badge: "certificate",
  $user_rating_badge: "user_rating",
  $press_rating_badge: "press_rating",
};

// The segments of a badge line, in order: { type: "badge", kind } for each `_badge` token and
// { type: "text", template } for the text around them (blank text between tokens is only spacing and
// is dropped). null when the template has no `_badge` token: it is not a badge line. A token with
// steps (`$showtimes_badge[0]`) is not a badge token, it is a path.
function umcBadgeSegments(template) {
  const source = String(template);
  const segments = [];
  let from = 0;
  let found = false;
  const push = (end) => {
    const text = source.slice(from, end);
    if (text.trim() !== "")
      segments.push({ type: "text", template: text.trim() });
  };
  for (const match of source.matchAll(UMC_KEYWORDS)) {
    if (!Object.hasOwn(UMC_BADGE_TOKENS, match[0])) continue;
    found = true;
    push(match.index);
    segments.push({ type: "badge", kind: UMC_BADGE_TOKENS[match[0]] });
    from = match.index + match[0].length;
  }
  if (!found) return null;
  push(source.length);
  return segments;
}
function umcIsBadgeLine(template) {
  return umcBadgeSegments(template) !== null;
}

// The items of a badge row from the segments of its line, in order. Each badge token is resolved on
// its own: one that has nothing for this film (no certificate, "Tout public", no showtimes, no
// rating) adds nothing and does not affect the others. A text segment (`resolve(template)` gives its
// text) is kept when it is not empty, but only if at least one badge is drawn. [] when there is
// nothing to draw: the line is then ignored.
function umcBadgeItems(segments, film, lang, resolve) {
  const items = [];
  for (const segment of segments) {
    if (segment.type === "text") {
      const text = resolve(segment.template);
      if (text) items.push({ type: "text", text });
    } else if (segment.kind === "showtimes") {
      const groups = umcShowtimeGroups(film, lang);
      if (groups.length)
        items.push({
          type: "badge",
          kind: "showtimes",
          groups,
          text: umcShowtimesText(film),
        });
    } else if (segment.kind === "certificate") {
      const certificate = umcCertificateBadge(film, lang);
      if (certificate)
        items.push({
          type: "badge",
          kind: "certificate",
          certificate,
          text: certificate.label,
        });
    } else {
      const rating = umcRatingBadge(film, segment.kind, lang);
      if (rating)
        items.push({
          type: "badge",
          kind: segment.kind,
          rating,
          text: rating.label,
        });
    }
  }
  // No badge for this film (no certificate, "Tout public", no showtimes, no rating): the text
  // around them has nothing to introduce, the line is empty.
  return items.some((item) => item.type === "badge") ? items : [];
}

// The text shown instead of a badge row that cannot be placed: the texts of its items, by a space.
function umcBadgeFallbackText(items) {
  return items
    .map((item) => item.text)
    .filter(Boolean)
    .join(" ");
}

// Where the synopsis tooltip may show: the poster and the title. `container` is the item, `view`
// poster or fanart (there the picture is the right 53 % of the item); (x, y) is the pointer.
function umcTooltipZone(container, view, x, y) {
  const inside = (rect, pad = 0) =>
    x >= rect.left - pad &&
    x <= rect.right + pad &&
    y >= rect.top - pad &&
    y <= rect.bottom + pad;
  const box = container.getBoundingClientRect();
  if (view === "fanart") {
    if (x >= box.left + box.width * 0.47) return true;
  } else {
    const poster = container.querySelector('[class*="_container_poster"]');
    if (poster && inside(poster.getBoundingClientRect())) return true;
  }
  // The whole title row (the item's full width), not only the text.
  const title = container.querySelector('tspan[class*="_line0_"]');
  if (!title) return false;
  const row = title.getBoundingClientRect();
  return (
    y >= row.top - 4 && y <= row.bottom + 4 && x >= box.left && x <= box.right
  );
}

// ── Rating badges (`$user_rating_badge`, `$press_rating_badge`) ─────────────
// The rating of a film (`key`: user_rating or press_rating) as a badge { key, value, label, title }
// or null: only a finite number above 0 is a rating (the sensor leaves missing ones out). The label
// is "★ 4.1" (one decimal, a dot, like the `$user_rating` text); the title says it in the language.
function umcRatingBadge(film, key, lang) {
  if (!film || typeof film !== "object") return null;
  if (key !== "user_rating" && key !== "press_rating") return null;
  const value = film[key];
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0)
    return null;
  const french = umcBadgeText(lang) === UMC_BADGE_TEXT.fr;
  const number = new Intl.NumberFormat(umcLocale(lang), {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value);
  const user = key === "user_rating";
  return {
    key,
    value,
    label: "★ " + umcStars(value),
    // In texts (tooltip): the same as `$user_rating`, without the star.
    text: umcStars(value),
    title: french
      ? `${user ? "Note des spectateurs" : "Note de la presse"} : ${number} sur 5`
      : `${user ? "Spectators' rating" : "Press rating"}: ${number} out of 5`,
  };
}

// How far the line after a badge row is moved down (in svg units): what the row is taller than its
// slot, and 4 more when that line is a badge row too, so two pill rows in a row do not touch
// (a pill sticks 2px out of its row at the top and the bottom).
function umcBadgeRowExtra(rowHeight, slotHeight, nextIsBadgeRow) {
  return (
    Math.max(0, Math.ceil(rowHeight - slotHeight)) + (nextIsBadgeRow ? 4 : 0)
  );
}

// A line that resolved to nothing (an unknown token, a token without a value for this film, every
// part dropped) is ignored: no text, no room. Not an explicit `$empty` line (the reference keeps its
// blank line), and not the title (line 0 keeps the reference's own handling).
function umcLineIsIgnored(index, template, text) {
  return index > 0 && text === "" && !String(template).match("empty");
}

// ── Age restriction (`$certificate_badge`) ─────────────────────────────────
// The age of a film's certificate ("Interdit - 12 ans", "-16", "Interdit aux moins de 18 ans") as a
// badge: { age, key, label, title } or null. Supported ages 10, 12, 16, 18 (13 is 12, 17 is 16, an
// age under 10 or no age at all, "Tout public" and "Avertissement" included, is null: nothing to
// show). `key` is the colour option: age_12 (also for 10), age_16, age_18.
function umcCertificateBadge(film, lang) {
  if (!film || typeof film !== "object") return null;
  const details =
    film.details && typeof film.details === "object" ? film.details : {};
  const certificate =
    typeof film.certificate === "string"
      ? film.certificate
      : typeof details.certificate === "string"
        ? details.certificate
        : "";
  const found =
    /(\d{1,2})\s*ans/i.exec(certificate) ||
    /(?:^|\s)-\s*(\d{1,2})(?!\d)/.exec(certificate);
  if (!found) return null;
  const number = Number(found[1]);
  const age = [18, 16, 12, 10].find((supported) => number >= supported);
  if (!age) return null;
  const french = umcBadgeText(lang) === UMC_BADGE_TEXT.fr;
  return {
    age,
    key: age >= 18 ? "age_18" : age >= 16 ? "age_16" : "age_12",
    label: french ? `-${age} ans` : `-${age}`,
    title: french
      ? `Interdit aux moins de ${age} ans`
      : `Not suitable for under ${age}`,
  };
}

// The colours of the age badges: the options when the browser accepts them, else amber, orange, red.
function umcAgeColors(options) {
  const accepted = (value, fallback) =>
    value && typeof CSS !== "undefined" && CSS.supports("color", value)
      ? value
      : fallback;
  return {
    age_12: accepted(options.age_12, "#ffb300"),
    age_16: accepted(options.age_16, "#fb8c00"),
    age_18: accepted(options.age_18, "#e53935"),
  };
}

// A soft filled pill (`span`) for the age and rating badges: not clickable, with a title for
// screen readers.
function umcStaticPill(label, fill) {
  const pill = document.createElement("span");
  pill.setAttribute("role", "img");
  pill.style.padding = "2px 8px";
  // The padding must not make the line taller than a text line: the pill sticks out of its box.
  pill.style.margin = "-2px 0";
  pill.style.borderRadius = "999px";
  pill.style.whiteSpace = "nowrap";
  pill.style.fontVariantNumeric = "tabular-nums";
  pill.style.background = fill;
  if (label !== null) pill.textContent = label;
  return pill;
}

// What the age and rating items do: a small hover tip with their meaning (a native `title` does not
// show reliably in a foreignObject under the item's click area), their text for screen readers, and
// a click that goes on to the item's link (they sit above its click area to be hovered).
function umcExplain(element, text, options) {
  element.setAttribute("role", "img");
  element.setAttribute("aria-label", text);
  element.style.pointerEvents = "auto";
  element.style.cursor = options.cursor || "default";
  element.addEventListener("mouseenter", () => options.onTip(element, text));
  element.addEventListener("mouseleave", () => options.onTip(null));
  // Moving over them is not moving over the picture: no synopsis bubble.
  element.addEventListener("mousemove", (event) => event.stopPropagation());
  element.addEventListener("click", (event) => {
    event.stopPropagation();
    options.onTip(null);
    options.onForward();
  });
  return element;
}

// The badge row, an HTML element for a foreignObject of the card's svg (its size is in the svg's
// units, so it scales with the card). `items`, in the order of the line: { type: "text", text } (a
// span), or { type: "badge", kind, ... } with kind "showtimes" (one pill button per version group,
// "VF · 4", that opens the times through `options.onToggle(group, button)`), "certificate" (the
// age pill) or "user_rating" / "press_rating" (a gold star and the rating). Only the showtime pills
// take clicks. Strings go through textContent and setAttribute only; the colours (options) are
// assigned only when the browser accepts them.
function umcBuildBadgeRow(items, options) {
  const colors = umcBadgeColors(options.colors);
  const ageColors = umcAgeColors(options.colors);
  const text = umcBadgeText(options.lang);
  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.flexWrap = "wrap";
  row.style.alignItems = "center";
  // 6px between items; the pills stick out 2px above and below their box (negative margin), so
  // wrapped rows are 10px apart to leave 6px between the pills.
  row.style.gap = items.some(
    (item) =>
      item.type === "badge" &&
      (item.kind === "showtimes" || item.kind === "certificate"),
  )
    ? "10px 6px"
    : "6px";
  row.style.width = "100%";
  row.style.fontSize = options.size + "px";
  row.style.lineHeight = "1.2";
  row.style.color = options.color;
  row.style.pointerEvents = "none";
  if (options.shadow) row.style.textShadow = options.shadow;
  for (const item of items) {
    if (item.type === "text") {
      const span = document.createElement("span");
      span.textContent = item.text;
      row.appendChild(span);
    } else if (item.kind === "certificate") {
      const pill = umcStaticPill(
        item.certificate.label,
        umcSoftFill(ageColors[item.certificate.key], 28),
      );
      row.appendChild(umcExplain(pill, item.certificate.title, options));
    } else if (item.kind === "user_rating" || item.kind === "press_rating") {
      // Plain text, not a pill: like `$user_rating` in the reference's own look, the number in the
      // line's colour and only the star recoloured (`options.star`, the reference's adjustedStar).
      const rating = item.rating;
      const span = document.createElement("span");
      span.style.whiteSpace = "nowrap";
      span.style.fontVariantNumeric = "tabular-nums";
      const star = document.createElement("span");
      star.textContent = "★";
      star.style.color = options.star || "#f0b429";
      const number = document.createElement("span");
      number.textContent = " " + rating.text;
      span.append(star, number);
      row.appendChild(umcExplain(span, rating.title, options));
    } else {
      for (const group of item.groups) {
        const pill = document.createElement("button");
        pill.type = "button";
        pill.setAttribute("data-umc-group", group.key);
        pill.setAttribute("aria-expanded", "false");
        pill.setAttribute("aria-haspopup", "dialog");
        const name = `${group.label}, ${group.count} ${group.count === 1 ? text.one : text.many}`;
        pill.setAttribute("aria-label", name);
        // The tip reads like the panel's header: "VO : 3 showtimes".
        const tip = `${group.label} : ${group.count} ${group.count === 1 ? text.one : text.many}`;
        pill.addEventListener("mouseenter", () => options.onTip(pill, tip));
        pill.addEventListener("mouseleave", () => options.onTip(null));
        pill.addEventListener("mousemove", (event) => event.stopPropagation());
        const label = document.createElement("span");
        label.textContent = group.label;
        const count = document.createElement("span");
        count.textContent = " · " + group.count;
        count.style.opacity = "0.7";
        pill.append(label, count);
        pill.style.font = "inherit";
        pill.style.color = "inherit";
        pill.style.textShadow = "inherit";
        pill.style.border = "none";
        pill.style.borderRadius = "999px";
        pill.style.padding = "2px 8px";
        pill.style.margin = "-2px 0";
        pill.style.whiteSpace = "nowrap";
        pill.style.cursor = "pointer";
        pill.style.pointerEvents = "auto";
        pill.style.fontVariantNumeric = "tabular-nums";
        pill.style.background = umcSoftFill(colors[group.key], 22);
        pill.dataset.soft = pill.style.background;
        pill.dataset.strong = umcSoftFill(colors[group.key], 45);
        pill.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          options.onTip(null);
          options.onToggle(group, pill);
        });
        // Presses stay off the item underneath (its link and its hover bubble).
        for (const type of ["mousedown", "pointerdown", "touchstart"]) {
          pill.addEventListener(type, (event) => event.stopPropagation(), {
            passive: true,
          });
        }
        row.appendChild(pill);
      }
    }
  }
  return row;
}

// A small hash of a string (FNV-1a), to tell when a film changed.
function umcHash(text) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash = Math.imul(hash ^ text.charCodeAt(i), 0x01000193) >>> 0;
  }
  return hash;
}

// A runtime in minutes (a number or a string of digits) as `XhYY` (121 -> "2h01", 120 -> "2h00");
// under an hour `Ymin` ("45min"). Empty for anything that is not a positive whole number.
function umcRuntimeText(runtime) {
  if (!runtime || !/^\d+$/.test(runtime)) return "";
  const total = parseInt(runtime, 10);
  if (total <= 0) return "";
  const hours = Math.floor(total / 60);
  return hours > 0
    ? `${hours}h${String(total % 60).padStart(2, "0")}`
    : `${total}min`;
}

// A rating as plain text ("4.1", one decimal and a dot); the badge tokens add the star.
const umcStars = (score) =>
  typeof score === "number" ? score.toFixed(1) : null;

function filmToItem(film, day) {
  const details = film.details || {};
  const userRating = umcStars(film.user_rating);
  const item = {
    airdate: day,
    title: umcClean(film.title),
    original_title: umcClean(film.original_title),
    release_date: /^\d{4}-\d{2}-\d{2}$/.test(film.release_date || "")
      ? film.release_date
      : null,
    runtime: Number.isInteger(film.runtime) ? film.runtime : null,
    genres: umcCleanList(film.genres),
    directors: umcCleanList(film.directors),
    cast: umcCleanList(details.cast),
    user_rating: userRating,
    rating: userRating,
    press_rating: umcStars(film.press_rating),
    poster: umcUrl(film.poster) || UMC_NO_POSTER,
    // No fanart: the reference falls back to the poster (and lays it out for that).
    fanart: null,
    deep_link: umcUrl(film.url),
    flag: false,
    // Every other attribute, as sanitised text, for `$name` tokens (see umcTokenValue).
    _film: umcFilmValues(film),
    // Changes when anything in the film changes (also what only a `$path[0]` token reads, which
    // `_film` does not hold): the card redraws when the JSON of its items changes.
    _sig: umcHash(JSON.stringify(film)),
  };
  // The same values, unsanitised, for the tooltip only (it is shown through textContent). Not
  // enumerable: it stays out of the card's JSON cache key.
  Object.defineProperty(item, "_filmRaw", {
    value: umcFilmValues(film, umcRaw),
  });
  // The film itself, for the tokens with steps (resolved on it, only the leaf is sanitised).
  Object.defineProperty(item, "_filmObj", { value: film });
  return item;
}

// The sensor's attributes ({date, films}) -> the reference's `data` list.
function filmsToItems(attributes, entryPoint = UMC_ENTRY_POINT) {
  const films = Array.isArray(attributes[entryPoint])
    ? attributes[entryPoint]
    : [];
  const day = /^\d{4}-\d{2}-\d{2}$/.test(attributes.date || "")
    ? attributes.date
    : new Date().toISOString().slice(0, 10);
  const template = {
    title_default: "$title",
    line1_default: "$runtime - $genres",
    line2_default: "$directors",
    line3_default: "$user_rating",
    line4_default: "$certificate",
    icon: "mdi:movie-open",
  };
  return [template, ...films.map((film) => filmToItem(film, day))];
}

// Values of the formatted `$tokens` (the others are the film's attributes, by name);
// `item` is the reference's accessor (key => value).
function filmKeys(item) {
  const cast = item("cast");
  return {
    $cast: Array.isArray(cast) ? cast.slice(0, 3).join(", ") || null : null,
    $user_rating: item("user_rating") || null,
    $press_rating: item("press_rating") || null,
  };
}

// The parts of a template: split at each `-` that is not inside a token (`$genres[-1]`).
function umcSplitTemplate(template) {
  const parts = [];
  let from = 0;
  for (const match of template.matchAll(
    new RegExp(UMC_KEYWORDS.source + "|-", "g"),
  )) {
    if (match[0] !== "-") continue;
    parts.push(template.slice(from, match.index));
    from = match.index + 1;
  }
  parts.push(template.slice(from));
  return parts;
}

// One text line: the template is split at '-', and a part whose keyword is empty or unknown
// (its value is null, so the text "null") is ignored.
function resolveText(template, keys, film, deep) {
  // A missing value is a sentinel character, not the text "null": "nulle part" is French.
  const missing = "\u0000";
  const parts = umcSplitTemplate(template)
    .map((part) =>
      part.replace(UMC_KEYWORDS, (token) => {
        const value = umcTokenValue(token, keys, film, deep);
        return value === null ? missing : value;
      }),
    )
    .filter((part) => !part.includes(missing));
  // Replacing twice to get keywords in component generated strings (unknown ones stay as they are)
  return parts
    .join(" - ")
    .replace(UMC_KEYWORDS, (token) => {
      const value = umcTokenValue(token, keys, film, deep);
      return value === null ? token : value;
    })
    .trim();
}

// The tooltip's text: a template like the lines' (`$tokens`), from the unsanitised values, with
// entities decoded (`&amp;`, `&#39;`): it is shown through textContent. `keys` are the card's
// tokens (their values went through umcClean: its `&amp;` escaping is undone), `film` is the
// item's `_filmRaw`. "" when nothing is left: no tooltip.
function umcTooltipText(template, keys, film, raw) {
  return umcDecodeEntities(
    resolveText(template.replace(/ - /g, "-"), keys, film, {
      raw,
      clean: umcRaw,
    }).replace(/&amp;(?=#?\w+;)/g, "&"),
  ).trim();
}

// Local search: title, original title, genres, directors, cast; case and accent insensitive.
function matchesSearch(item, query) {
  const fold = (text) =>
    String(text).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const wanted = fold(query.trim());
  return ["title", "original_title", "genres", "directors", "cast"].some(
    (key) => fold([].concat(item[key] ?? "").join(" ")).includes(wanted),
  );
}

// ── Visual Editor ──────────────────────────────────────────────────
const UMC_EDITOR_SCHEMA = [
  {
    name: "title",
    selector: { text: {} },
  },
  {
    name: "image_style",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "poster", label: "Poster" },
          { value: "fanart", label: "Fanart" },
        ],
      },
    },
  },
  {
    type: "grid",
    name: "",
    schema: [
      {
        name: "max",
        selector: { number: { min: 1, max: 50, mode: "box" } },
      },
      {
        name: "clock",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "12", label: "12-hour" },
              { value: "24", label: "24-hour" },
            ],
          },
        },
      },
    ],
  },
  {
    type: "grid",
    name: "",
    schema: [
      {
        name: "overflow",
        selector: { boolean: {} },
      },
      {
        name: "max_columns",
        selector: { number: { min: 0, max: 6, mode: "box" } },
      },
    ],
  },
  {
    name: "collapse",
    selector: { number: { min: 1, max: 50, mode: "box" } },
  },
  {
    // The options this fork adds, kept together and folded away so the editor
    // still opens on the upstream settings.
    type: "expandable",
    title: "Fork enhancements",
    schema: [
      {
        name: "overflow_fit",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "viewport", label: "Fit viewport height" },
              { value: "content", label: "Grow with content" },
            ],
          },
        },
      },
      { name: "enable_search", selector: { boolean: {} } },
      { name: "enable_days", selector: { boolean: {} } },
    ],
  },
  {
    type: "expandable",
    title: "Appearance",
    schema: [
      {
        type: "grid",
        name: "",
        schema: [
          {
            name: "date",
            selector: { text: {} },
          },
          {
            name: "corner_radius",
            selector: { number: { min: 0, max: 20, mode: "slider" } },
          },
        ],
      },
      {
        type: "grid",
        name: "",
        schema: [
          {
            name: "title_size",
            selector: {
              select: {
                mode: "dropdown",
                options: [
                  { value: "large", label: "Large" },
                  { value: "medium", label: "Medium" },
                  { value: "small", label: "Small" },
                ],
              },
            },
          },
          {
            name: "line_size",
            selector: {
              select: {
                mode: "dropdown",
                options: [
                  { value: "large", label: "Large" },
                  { value: "medium", label: "Medium" },
                  { value: "small", label: "Small" },
                ],
              },
            },
          },
        ],
      },
      {
        type: "grid",
        name: "",
        schema: [
          { name: "title_color", selector: { text: {} } },
          { name: "line1_color", selector: { text: {} } },
          { name: "line2_color", selector: { text: {} } },
          { name: "line3_color", selector: { text: {} } },
          { name: "line4_color", selector: { text: {} } },
          { name: "line5_color", selector: { text: {} } },
          { name: "line6_color", selector: { text: {} } },
          { name: "vf_color", selector: { text: {} } },
          { name: "vo_color", selector: { text: {} } },
          { name: "vost_color", selector: { text: {} } },
          { name: "other_color", selector: { text: {} } },
          { name: "age_12_color", selector: { text: {} } },
          { name: "age_16_color", selector: { text: {} } },
          { name: "age_18_color", selector: { text: {} } },
          { name: "accent_color", selector: { text: {} } },
          { name: "border_color", selector: { text: {} } },
          { name: "flag_color", selector: { text: {} } },
          { name: "icon_color", selector: { text: {} } },
        ],
      },
    ],
  },
  {
    type: "expandable",
    title: "Text Lines",
    schema: [
      { name: "title_text", selector: { text: {} } },
      { name: "line1_text", selector: { text: {} } },
      { name: "line2_text", selector: { text: {} } },
      { name: "line3_text", selector: { text: {} } },
      { name: "line4_text", selector: { text: {} } },
      { name: "line5_text", selector: { text: {} } },
      { name: "line6_text", selector: { text: {} } },
    ],
  },
  {
    type: "expandable",
    title: "Features",
    schema: [
      {
        type: "grid",
        name: "",
        schema: [
          { name: "enable_tooltips", selector: { boolean: {} } },
          {
            name: "tooltip_delay",
            selector: { number: { min: 150, max: 3000, mode: "box" } },
          },
        ],
      },
      { name: "tooltip_text", selector: { text: {} } },
      {
        type: "grid",
        name: "",
        schema: [
          { name: "enable_trailers", selector: { boolean: {} } },
          { name: "disable_hyperlinks", selector: { boolean: {} } },
        ],
      },
      {
        type: "grid",
        name: "",
        schema: [
          { name: "enable_transparency", selector: { boolean: {} } },
          { name: "hide_empty", selector: { boolean: {} } },
        ],
      },
      {
        type: "grid",
        name: "",
        schema: [
          { name: "hide_flagged", selector: { boolean: {} } },
          { name: "hide_unflagged", selector: { boolean: {} } },
        ],
      },
    ],
  },
  {
    type: "expandable",
    title: "Sorting & Filtering",
    schema: [
      {
        name: "sort_by",
        selector: {
          select: {
            mode: "dropdown",
            custom_value: true,
            options: [
              {
                value: "details.showtimes[0].starts_at",
                label: "First showtime",
              },
              { value: "user_review_count", label: "Number of reviews" },
              { value: "hits", label: "Popularity" },
              { value: "press_rating", label: "Press rating" },
              { value: "release_date", label: "Release date" },
              { value: "runtime", label: "Runtime" },
              { value: "title", label: "Title" },
              { value: "want_to_see_count", label: "Want to see" },
              { value: "year", label: "Year" },
              { value: "user_rating", label: "Your rating" },
            ],
          },
        },
      },
      { name: "sort_ascending", selector: { boolean: {} } },
      { name: "filter", selector: { text: {} } },
    ],
  },
  {
    type: "expandable",
    title: "Advanced",
    schema: [
      { name: "entry_point", selector: { text: {} } },
      { name: "url", selector: { text: {} } },
      { name: "icon", selector: { icon: {} } },
      { name: "flag", selector: { boolean: {} } },
      { name: "all_shadows", selector: { boolean: {} } },
      { name: "box_shadows", selector: { boolean: {} } },
      { name: "text_shadows", selector: { boolean: {} } },
    ],
  },
];

// The corner flag has no meaning for films yet (the adapter sets `flag: false` on every
// item), so its options are kept in the code and in YAML but hidden from the visual
// editor. Set to `true` to show them again.
const UMC_FLAG_ENABLED = false;
const UMC_FLAG_FIELDS = [
  "flag",
  "flag_color",
  "icon",
  "icon_color",
  "hide_flagged",
  "hide_unflagged",
];

// The editor schema, without the flag fields (and the groups they leave empty) unless enabled.
function umcEditorSchema(schema = UMC_EDITOR_SCHEMA) {
  if (UMC_FLAG_ENABLED) return schema;
  return schema
    .filter((field) => !UMC_FLAG_FIELDS.includes(field.name))
    .map((field) =>
      field.schema
        ? { ...field, schema: umcEditorSchema(field.schema) }
        : field,
    )
    .filter((field) => !field.schema || field.schema.length > 0);
}

// Lines 5 and 6 exist in the poster view only, and have no default text.
const UMC_EXTRA_LINES = ["line5_text", "line6_text"];

// Whether line `index` (0 = title) is drawn: lines 0-4 always, 5 and 6 only in the poster view and
// when their text is configured (nothing is reserved for them otherwise).
function umcLineShown(index, view, text) {
  return index < 5 || (view === "poster" && !!text);
}

const UMC_EDITOR_LABELS = {
  device_id: "Cinema",
  title: "Card Title",
  image_style: "Image Style",
  max: "Maximum Items",
  clock: "Clock Format",
  overflow: "Overflow Columns",
  max_columns: "Maximum Columns",
  overflow_fit: "Overflow Height",
  collapse: "Collapse After",
  date: "Date Format",
  corner_radius: "Corner Radius",
  title_size: "Title Size",
  line_size: "Line Size",
  title_color: "Title Color",
  line1_color: "Line 1 Color",
  line2_color: "Line 2 Color",
  line3_color: "Line 3 Color",
  line4_color: "Line 4 Color",
  line5_color: "Line 5 Color",
  line6_color: "Line 6 Color",
  vf_color: "VF Color",
  vo_color: "VO Color",
  vost_color: "VOST Color",
  other_color: "Other Color",
  age_12_color: "Age -12 Color",
  age_16_color: "Age -16 Color",
  age_18_color: "Age -18 Color",
  accent_color: "Accent Color",
  border_color: "Border Color",
  flag_color: "Flag Color",
  icon_color: "Icon Color",
  title_text: "Title Line",
  line1_text: "Line 1",
  line2_text: "Line 2",
  line3_text: "Line 3",
  line4_text: "Line 4",
  line5_text: "Line 5",
  line6_text: "Line 6",
  enable_tooltips: "Enable Tooltips",
  tooltip_delay: "Tooltip Delay (ms)",
  tooltip_text: "Tooltip Text",
  enable_trailers: "Enable Trailers",
  disable_hyperlinks: "Disable Hyperlinks",
  enable_transparency: "Enable Transparency",
  hide_empty: "Hide When Empty",
  hide_flagged: "Hide Flagged",
  hide_unflagged: "Hide Unflagged",
  sort_by: "Sort By",
  sort_ascending: "Sort Ascending",
  filter: "Filter (attribute=value)",
  enable_search: "Enable Search",
  enable_days: "Show Days",
  entry_point: "Entry Point",
  url: "Custom URL",
  icon: "Icon",
  flag: "Show Flag",
  all_shadows: "All Shadows",
  box_shadows: "Box Shadows",
  text_shadows: "Text Shadows",
};

class MovieShowtimesCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = null;
    this._formReady = false;
  }

  setConfig(config) {
    this._config = { ...config };
    this._yamlKeys = new Set(Object.keys(config));
    this._updateForm();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) {
      if (this._tokenHelp() !== this._helpShown) this._setHelper();
      this._form.hass = hass;
    }
  }

  _rebuildSchema() {
    if (!this._form) return;
    // The cinema is a device of the integration; its day sensors are found from
    // it (see resolveDayEntity).
    const cinemaField = {
      name: "device_id",
      required: true,
      selector: { device: { integration: "movie_showtimes" } },
    };
    this._form.schema = [cinemaField, ...umcEditorSchema()];
  }

  async connectedCallback() {
    await this._ensureFormComponents();
    this._buildForm();
  }

  async _ensureFormComponents() {
    if (customElements.get("ha-form")) return;
    try {
      const helpers = await window.loadCardHelpers?.();
      if (helpers)
        await helpers.createCardElement({ type: "entity", entity: "sun.sun" });
    } catch (_) {}
    if (!customElements.get("ha-form"))
      await customElements.whenDefined("ha-form");
  }

  // The token help under the line fields: the names come from the first film of the cinema's
  // today sensor. A new function (not a changed result) is what makes the form render it again.
  _setHelper() {
    if (!this._form) return;
    const help = this._tokenHelp();
    this._helpShown = help;
    // The token list is shown once, under the first text field (the title); the other fields
    // only say what is specific to them.
    this._form.computeHelper = (schema) => {
      if (schema.name === "title_text") return help;
      if (schema.name === "tooltip_text")
        return "Default: $synopsis. Same tokens as the text lines.";
      if (schema.name === "entry_point")
        return "Attribute holding the list the $tokens read from. Default: films";
      if (schema.name === "sort_by")
        return "Pick one or type any film attribute or path, e.g. user_review_count or details.showtimes[0].starts_at. Films without a value come last.";
      if (schema.name === "sort_ascending") return "Untick for descending.";
      if (UMC_EXTRA_LINES.includes(schema.name))
        return "Poster view only. No default: empty shows nothing.";
      return undefined;
    };
  }

  _tokenHelp() {
    const hass = this._hass;
    const entity = hass && resolveDayEntity(hass, this._config || {});
    const state = entity ? hass.states[entity] : undefined;
    const films =
      state &&
      state.attributes &&
      state.attributes[
        (this._config && this._config.entry_point) || UMC_ENTRY_POINT
      ];
    return umcTokenHelp(Array.isArray(films) ? filmTokenNames(films[0]) : []);
  }

  _buildForm() {
    if (this._formReady) return;
    this._form = document.createElement("ha-form");
    this._form.computeLabel = (schema) =>
      UMC_EDITOR_LABELS[schema.name] || schema.name;
    this._setHelper();

    // ── Canonical YAML key order: groups related settings together ──
    const KEY_ORDER = [
      "type",
      "device_id",
      "entity",
      "title",
      "image_style",
      "max",
      "clock",
      "overflow",
      "max_columns",
      "overflow_fit",
      "collapse",
      "date",
      "corner_radius",
      "title_size",
      "line_size",
      "title_color",
      "line1_color",
      "line2_color",
      "line3_color",
      "line4_color",
      "line5_color",
      "line6_color",
      "vf_color",
      "vo_color",
      "vost_color",
      "other_color",
      "age_12_color",
      "age_16_color",
      "age_18_color",
      "accent_color",
      "border_color",
      "flag_color",
      "icon_color",
      "title_text",
      "line1_text",
      "line2_text",
      "line3_text",
      "line4_text",
      "line5_text",
      "line6_text",
      "enable_tooltips",
      "tooltip_delay",
      "tooltip_text",
      "enable_trailers",
      "disable_hyperlinks",
      "enable_transparency",
      "hide_empty",
      "hide_flagged",
      "hide_unflagged",
      "sort_by",
      "sort_ascending",
      "filter",
      "enable_search",
      "enable_days",
      "entry_point",
      "url",
      "icon",
      "flag",
      "box_shadows",
      "text_shadows",
    ];

    const CARD_DEFAULTS = {
      flag: true,
      enable_tooltips: false,
      tooltip_text: "$synopsis",
      entry_point: "films",
      enable_trailers: true,
      enable_transparency: false,
      disable_hyperlinks: false,
      hide_empty: false,
      hide_flagged: false,
      hide_unflagged: false,
      corner_radius: 12,
      overflow: false,
      overflow_fit: "viewport",
      sort_by: "title",
      sort_ascending: true,
      enable_search: false,
      enable_days: true,
      clock: 12,
      box_shadows: true,
      text_shadows: true,
    };

    const orderAndStrip = (config) => {
      const yamlKeys = this._yamlKeys || new Set();
      const ordered = {};
      const stripped = new Set();
      for (const key of KEY_ORDER) {
        if (!(key in config)) continue;
        const val = config[key];
        if (val === undefined || val === null || val === "") continue;
        if (
          key in CARD_DEFAULTS &&
          val === CARD_DEFAULTS[key] &&
          // (`sort_ascending: true` is never kept: ticking the box again removes the key)
          (!yamlKeys.has(key) || key === "sort_ascending")
        ) {
          stripped.add(key);
          continue;
        }
        ordered[key] = val;
      }
      for (const key of Object.keys(config)) {
        // (a default that was just stripped must not come back through this second pass)
        if (key in ordered || stripped.has(key)) continue;
        const val = config[key];
        if (val === undefined || val === null || val === "") continue;
        ordered[key] = val;
      }
      return ordered;
    };

    this._form.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const updated = { ...ev.detail.value };
      if (updated.clock !== undefined)
        updated.clock = parseInt(updated.clock, 10) || 12;
      if (!updated.sort_by) delete updated.sort_by;

      const prevOC = this._prevOverflowCollapse || {
        overflow: false,
        collapse: undefined,
      };
      const overflowJustEnabled = !!updated.overflow && !prevOC.overflow;
      const collapseJustSet =
        updated.collapse !== undefined &&
        updated.collapse !== null &&
        updated.collapse !== prevOC.collapse;
      if (overflowJustEnabled) {
        delete updated.collapse;
      } else if (collapseJustSet && updated.collapse >= 1) {
        updated.overflow = false;
      }

      // ── Shadow sync: all_shadows is a convenience master toggle ──
      const prev = this._prevShadowDisplay || {
        all: true,
        box: true,
        text: true,
      };
      if (updated.all_shadows !== prev.all) {
        updated.box_shadows = updated.all_shadows;
        updated.text_shadows = updated.all_shadows;
      }
      delete updated.all_shadows;

      // ── Order keys and strip defaults not explicitly in YAML ──
      this._config = orderAndStrip(updated);

      this._updateForm();
      this.dispatchEvent(
        new CustomEvent("config-changed", {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        }),
      );
    });
    this.appendChild(this._form);
    this._formReady = true;
    this._rebuildSchema();
    this._updateForm();
  }

  _updateForm() {
    if (!this._form) return;
    if (this._tokenHelp() !== this._helpShown) this._setHelper();
    const formData = { ...this._config };
    if (formData.clock !== undefined) formData.clock = String(formData.clock);

    // ── Display defaults: show the value the card actually renders ──
    if (formData.flag === undefined) formData.flag = true;
    if (formData.enable_days === undefined) formData.enable_days = true;
    if (formData.tooltip_text === undefined)
      formData.tooltip_text = "$synopsis";
    if (formData.entry_point === undefined) formData.entry_point = "films";
    if (formData.sort_ascending === undefined) formData.sort_ascending = true;
    if (!formData.sort_by) formData.sort_by = "title";
    if (formData.corner_radius === undefined) formData.corner_radius = 12;
    if (formData.enable_trailers === undefined) formData.enable_trailers = true;

    if (formData.overflow) {
      delete formData.collapse;
    }
    this._prevOverflowCollapse = {
      overflow: !!formData.overflow,
      collapse: formData.collapse,
    };

    // ── Shadow display logic ──
    let effectiveBox, effectiveText;
    if (formData.all_shadows !== undefined) {
      effectiveBox = !!formData.all_shadows;
      effectiveText = !!formData.all_shadows;
    } else {
      effectiveBox =
        formData.box_shadows !== undefined ? !!formData.box_shadows : true;
      effectiveText =
        formData.text_shadows !== undefined ? !!formData.text_shadows : true;
    }
    formData.box_shadows = effectiveBox;
    formData.text_shadows = effectiveText;
    formData.all_shadows = effectiveBox && effectiveText;

    this._prevShadowDisplay = {
      all: formData.all_shadows,
      box: formData.box_shadows,
      text: formData.text_shadows,
    };

    this._form.data = formData;
    if (this._hass) this._form.hass = this._hass;
  }
}
if (!customElements.get("movie-showtimes-card-editor")) {
  customElements.define(
    "movie-showtimes-card-editor",
    MovieShowtimesCardEditor,
  );
}

// ── Card ───────────────────────────────────────────────────────────
class MovieShowtimesCard extends HTMLElement {
  static get version() {
    return CARD_VERSION;
  }

  static get build() {
    return CARD_BUILD;
  }

  constructor() {
    super();
    this.uniqueId = "umc-" + Math.random().toString(36).substr(2, 9);
    this._boundClickListener;
    this.deepLinkListeners = new Map();
    this.tooltipListeners = new Map();
    this._searchQuery = "";
  }
  connectedCallback() {
    this.style.position = "relative";
    this.style.zIndex = "0";
    this.style.touchAction = "manipulation"; // Remove 300ms tap delay; allow pan + pinch zoom
    // Drawn while the card was not in the page: the badge rows can be placed now.
    this._layoutAllBadges();
  }
  disconnectedCallback() {
    this._hidePillTip();
    this.cleanupTooltipListeners();
    this._closeBadgePopover();
    this._stopBadgeWatch();
    if (this._daysObserver) {
      this._daysObserver.disconnect();
      this._daysObserver = null;
    }
    this._daysLayoutKey = null;
    clearTimeout(this._overflowResizeTimer);
    clearTimeout(this._overflowImageTimer);
    if (this._overflowInitRAF) {
      cancelAnimationFrame(this._overflowInitRAF);
      this._overflowInitRAF = null;
    }
    if (this._overflowObserver) {
      this._overflowObserver.disconnect();
      this._overflowObserver = null;
    }
    if (this._overflowResizeHandler) {
      window.removeEventListener("resize", this._overflowResizeHandler);
      this._overflowResizeHandler = null;
    }
    this._recalcInProgress = false;
    this._recalcPending = false;
    this._opacityLocked = false;
    this._overflowMinCols = 0;
    this._overflowReducedColWidth = null;
    if (this._overflowIntersectionObs) {
      this._overflowIntersectionObs.disconnect();
      this._overflowIntersectionObs = null;
    }
  }
  cleanupDeepLinkListeners() {
    this.deepLinkListeners.forEach((listeners, element) => {
      element.removeEventListener("click", listeners.click);
      element.removeEventListener("touchstart", listeners.touchstart);
      element.removeEventListener("touchmove", listeners.touchmove);
      element.removeEventListener("touchend", listeners.touchend);
    });
    this.deepLinkListeners.clear();
  }
  cleanupTooltipListeners() {
    this.tooltipListeners.forEach((listeners, element) => {
      element.removeEventListener("mouseenter", listeners.mouseenter);
      element.removeEventListener("mouseleave", listeners.mouseleave);
      element.removeEventListener("touchstart", listeners.touchstart);
      element.removeEventListener("touchmove", listeners.touchmove);
      element.removeEventListener("touchend", listeners.touchend);
      if (listeners.cleanup) listeners.cleanup();
    });
    this.tooltipListeners.clear();
  }
  addDeepLinkListener(element, url, trailer) {
    if (this.config.disable_hyperlinks) return;
    const createOverlay = (videoId) => {
      const overlay = document.createElement("div");
      overlay.style.position = "fixed";
      overlay.style.top = "0";
      overlay.style.left = "0";
      overlay.style.width = "100%";
      overlay.style.height = "100%";
      overlay.style.backgroundColor = "rgba(0, 0, 0, 0.9)";
      overlay.style.zIndex = "9999";
      overlay.style.display = "flex";
      overlay.style.justifyContent = "center";
      overlay.style.alignItems = "center";
      const iframeContainer = document.createElement("div");
      iframeContainer.style.width = "95%";
      iframeContainer.style.aspectRatio = "16 / 9";
      iframeContainer.style.maxWidth = "1600px";
      iframeContainer.style.maxHeight = "min(900px, calc(100vh - 92px))";
      iframeContainer.style.position = "relative";
      let checkVideoEndedInterval;
      const closeOverlayAndCleanup = () => {
        clearInterval(checkVideoEndedInterval);
        window.removeEventListener("message", handleMessage);
        window.removeEventListener("popstate", handlePopState);
        closeOverlay();
      };
      const handleMessage = (event) => {
        if (event.source === iframe.contentWindow) {
          try {
            const data = JSON.parse(event.data);
            if (
              data.event === "infoDelivery" &&
              data.info &&
              data.info.playerState === 0
            ) {
              closeOverlayAndCleanup();
            }
          } catch (e) {
            console.error("Error parsing message:", e);
          }
        }
      };
      const handlePopState = (event) => {
        closeOverlayAndCleanup();
      };
      window.addEventListener("message", handleMessage);
      window.addEventListener("popstate", handlePopState);
      const closeButton = document.createElement("button");
      const closeIcon = document.createElement("span");
      closeIcon.innerHTML = "&times;";
      closeIcon.style.background =
        "linear-gradient(180deg, #ffffff 0%, #b0b0b0 55%, #707070 100%)";
      closeIcon.style.webkitBackgroundClip = "text";
      closeIcon.style.backgroundClip = "text";
      closeIcon.style.color = "transparent";
      closeIcon.style.filter =
        "drop-shadow(0 2px 3px rgba(0, 0, 0, 0.9)) drop-shadow(0 0 6px rgba(0, 0, 0, 0.5))";
      closeIcon.style.lineHeight = "1";
      closeButton.appendChild(closeIcon);
      closeButton.style.position = "absolute";
      closeButton.style.top = "-40px";
      closeButton.style.right = "5px";
      closeButton.style.zIndex = "10000";
      closeButton.style.width = "36px";
      closeButton.style.height = "36px";
      closeButton.style.fontSize = "35px";
      closeButton.style.fontWeight = "bold";
      closeButton.style.cursor = "pointer";
      closeButton.style.backgroundColor = "transparent";
      closeButton.style.border = "none";
      closeButton.style.borderRadius = "50%";
      closeButton.style.display = "flex";
      closeButton.style.justifyContent = "center";
      closeButton.style.alignItems = "center";
      closeButton.style.padding = "0";
      closeButton.style.overflow = "visible";
      closeButton.style.transition = "none";
      closeButton.onmouseenter = () => {
        const glow = document.createElement("div");
        glow.className = "close-glow";
        glow.style.position = "absolute";
        glow.style.top = "calc(50% - 2px)";
        glow.style.left = "50%";
        glow.style.transform = "translate(-50%, -50%)";
        glow.style.width = "39px";
        glow.style.height = "39px";
        glow.style.borderRadius = "50%";
        glow.style.background =
          "radial-gradient(circle at center, rgba(255, 255, 255, 0.62) 0%, rgba(255, 255, 255, 0.27) 35%, transparent 70%)";
        glow.style.pointerEvents = "none";
        glow.style.zIndex = "-1";
        closeButton.appendChild(glow);
        const tooltip = document.createElement("div");
        tooltip.textContent = "Close";
        tooltip.className = "close-tooltip";
        tooltip.style.position = "absolute";
        tooltip.style.top = "-30px";
        tooltip.style.left = "50%";
        tooltip.style.transform = "translateX(-50%)";
        tooltip.style.backgroundColor = "rgba(0, 0, 0, 0.7)";
        tooltip.style.color = "white";
        tooltip.style.padding = "5px 10px";
        tooltip.style.borderRadius = "3px";
        tooltip.style.fontSize = "14px";
        tooltip.style.fontWeight = "normal";
        tooltip.style.whiteSpace = "nowrap";
        tooltip.style.filter = "none";
        tooltip.style.webkitBackgroundClip = "unset";
        tooltip.style.backgroundClip = "unset";
        tooltip.style.background = "rgba(0, 0, 0, 0.7)";
        closeButton.appendChild(tooltip);
      };
      closeButton.onmouseleave = () => {
        closeButton.style.background = "transparent";
        const glow = closeButton.querySelector(".close-glow");
        if (glow) closeButton.removeChild(glow);
        const tooltip = closeButton.querySelector(".close-tooltip");
        if (tooltip) closeButton.removeChild(tooltip);
      };

      // ── YouTube Integration Controls (Thumbs + Profile Avatar) ──────
      // Only displayed when the youtube_recently_added integration is
      // installed, configured, running, and has registered its service.
      const hasYTIntegration =
        this._hass &&
        this._hass.services &&
        this._hass.services["youtube_recently_added"] &&
        this._hass.services["youtube_recently_added"]["rate_video"];

      if (hasYTIntegration) {
        let avatarUrl = null;
        let channelUrl = null;
        try {
          const ytSensor = this._hass.states["sensor.youtube_recently_added"];
          if (ytSensor && ytSensor.attributes) {
            avatarUrl = ytSensor.attributes.profile_avatar_url || null;
            channelUrl = ytSensor.attributes.profile_channel_url || null;
          }
        } catch (e) {
          /* silently skip if entity unavailable */
        }

        const controlBar = document.createElement("div");
        controlBar.style.position = "absolute";
        controlBar.style.top = "-40px";
        controlBar.style.right = "57px"; // 5px (close right) + 36px (close) + 16px (gap)
        controlBar.style.zIndex = "10000";
        controlBar.style.display = "flex";
        controlBar.style.alignItems = "center";
        controlBar.style.flexDirection = "row-reverse"; // rightmost item first in DOM

        if (avatarUrl) {
          const avatarImg = document.createElement("img");
          avatarImg.src = avatarUrl;
          avatarImg.referrerPolicy = "no-referrer"; // Required for Google-hosted images
          avatarImg.style.width = "32px";
          avatarImg.style.height = "32px";
          avatarImg.style.borderRadius = "50%";
          avatarImg.style.objectFit = "cover";
          avatarImg.style.border = "2px solid rgba(255, 255, 255, 0.20)";
          avatarImg.style.flexShrink = "0";
          avatarImg.style.marginLeft = "13px";
          avatarImg.style.transition = "border-color 0.3s ease";
          avatarImg.onerror = () => {
            avatarImg.style.display = "none";
          }; // Hide on load failure
          if (channelUrl) {
            avatarImg.style.cursor = "pointer";
            avatarImg.title = "Open YouTube profile";
            avatarImg.onclick = (e) => {
              e.stopPropagation();
              window.open(channelUrl, "_blank", "noopener,noreferrer");
            };
            avatarImg.onmouseenter = () => {
              avatarImg.style.borderColor = "rgba(255, 255, 255, 0.35)";
            };
            avatarImg.onmouseleave = () => {
              avatarImg.style.borderColor = "rgba(255, 255, 255, 0.20)";
            };
          } else {
            avatarImg.style.pointerEvents = "none";
          }
          controlBar.appendChild(avatarImg);
        }

        const thumbsPair = document.createElement("div");
        thumbsPair.style.display = "flex";
        thumbsPair.style.gap = "0px";
        thumbsPair.style.flexShrink = "0";

        const createThumbButton = (type) => {
          const btn = document.createElement("button");
          const thumbUpSVG = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z"/></svg>`;
          const thumbDownSVG = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z"/></svg>`;
          btn.innerHTML = type === "like" ? thumbUpSVG : thumbDownSVG;
          btn.dataset.ratingType = type;
          btn.dataset.active = "false";
          btn.style.display = "inline-flex";
          btn.style.position = "relative";
          btn.style.justifyContent = "center";
          btn.style.alignItems = "center";
          btn.style.width = "36px";
          btn.style.height = "36px";
          btn.style.cursor = "pointer";
          btn.style.backgroundColor = "rgba(0, 0, 0, 0.5)";
          btn.style.color = "white";
          btn.style.border = "none";
          btn.style.borderRadius = "50%";
          btn.style.padding = "0";
          btn.style.lineHeight = "1";
          btn.style.transition = "background-color 0.3s ease, color 0.3s ease";
          btn.onmouseenter = () => {
            if (btn.dataset.active !== "true") {
              btn.style.backgroundColor = "rgba(255, 255, 255, 0.3)";
            }
            const tooltip = document.createElement("div");
            tooltip.textContent = type === "like" ? "Like" : "Dislike";
            tooltip.style.position = "absolute";
            tooltip.style.top = "-30px";
            tooltip.style.left = "50%";
            tooltip.style.transform = "translateX(-50%)";
            tooltip.style.backgroundColor = "rgba(0, 0, 0, 0.7)";
            tooltip.style.color = "white";
            tooltip.style.padding = "5px 10px";
            tooltip.style.borderRadius = "3px";
            tooltip.style.fontSize = "14px";
            tooltip.style.whiteSpace = "nowrap";
            tooltip.className = "thumb-tooltip";
            btn.appendChild(tooltip);
          };
          btn.onmouseleave = () => {
            if (btn.dataset.active !== "true") {
              btn.style.backgroundColor = "rgba(0, 0, 0, 0.5)";
            }
            const tooltip = btn.querySelector(".thumb-tooltip");
            if (tooltip) btn.removeChild(tooltip);
          };
          return btn;
        };

        const thumbUpBtn = createThumbButton("like");
        const thumbDownBtn = createThumbButton("dislike");

        const setActiveState = (btn, active) => {
          btn.dataset.active = active ? "true" : "false";
          if (active) {
            btn.style.backgroundColor = "rgba(255, 255, 255, 0.35)";
            btn.style.color = "#3ea6ff";
            btn.querySelector("svg").setAttribute("fill", "currentColor");
          } else {
            btn.style.backgroundColor = "rgba(0, 0, 0, 0.5)";
            btn.style.color = "white";
            btn.querySelector("svg").setAttribute("fill", "none");
          }
        };

        const handleThumbClick = (rating, activeBtn, otherBtn) => {
          const isAlreadyActive = activeBtn.dataset.active === "true";
          const effectiveRating = isAlreadyActive ? "none" : rating;

          this._hass.callService("youtube_recently_added", "rate_video", {
            video_id: videoId,
            rating: effectiveRating,
          });

          if (isAlreadyActive) {
            setActiveState(activeBtn, false);
          } else {
            setActiveState(activeBtn, true);
            setActiveState(otherBtn, false);
          }
        };

        thumbUpBtn.onclick = (e) => {
          e.stopPropagation();
          handleThumbClick("like", thumbUpBtn, thumbDownBtn);
        };
        thumbDownBtn.onclick = (e) => {
          e.stopPropagation();
          handleThumbClick("dislike", thumbDownBtn, thumbUpBtn);
        };

        // Pre-set thumb state from sensor my_rating
        const findMyRating = (entityId) => {
          try {
            const st = this._hass.states[entityId];
            if (!st || !st.attributes || !st.attributes.data) return null;
            const items = st.attributes.data;
            for (let i = 1; i < items.length; i++) {
              if (items[i] && items[i].id === videoId && items[i].my_rating) {
                return items[i].my_rating;
              }
            }
          } catch (e) {
            /* entity unavailable */
          }
          return null;
        };
        const existingRating =
          findMyRating(this.config.entity) ||
          findMyRating("sensor.youtube_recently_added") ||
          findMyRating("sensor.youtube_recently_added_shorts") ||
          findMyRating("sensor.youtube_recently_added_favorite_channels");
        if (existingRating === "like") {
          setActiveState(thumbUpBtn, true);
        } else if (existingRating === "dislike") {
          setActiveState(thumbDownBtn, true);
        }

        thumbsPair.appendChild(thumbUpBtn);
        thumbsPair.appendChild(thumbDownBtn);
        controlBar.appendChild(thumbsPair);
        iframeContainer.appendChild(controlBar);
      }
      // ── End YouTube Integration Controls ─────────────────────────────

      const iframe = document.createElement("iframe");
      iframe.style.width = "100%";
      iframe.style.height = "100%";
      iframe.src = `https://www.youtube.com/embed/${videoId}?autoplay=1&controls=1&rel=0&fs=1&modestbranding=1&enablejsapi=1&origin=${encodeURIComponent(window.location.origin)}&playsinline=1`;
      iframe.referrerPolicy = "strict-origin-when-cross-origin";
      iframe.frameBorder = "0";
      iframe.allow =
        "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
      iframe.allowFullscreen = true;
      checkVideoEndedInterval = setInterval(() => {
        iframe.contentWindow.postMessage('{"event":"listening"}', "*");
      }, 1000);
      iframeContainer.appendChild(iframe);
      iframeContainer.appendChild(closeButton);
      overlay.appendChild(iframeContainer);
      const closeOverlay = () => {
        clearInterval(checkVideoEndedInterval);
        window.removeEventListener("message", handleMessage);
        window.removeEventListener("popstate", handlePopState);
        document.body.removeChild(overlay);
        document.body.style.overflow = "";
        if (history.state && history.state.overlayOpen) {
          history.back();
        }
      };
      closeButton.onclick = closeOverlay;
      const handleKeyPress = (event) => {
        if (event.key === "Escape") {
          closeOverlay();
        }
      };
      document.addEventListener("keydown", handleKeyPress);
      overlay.addEventListener("remove", () => {
        document.removeEventListener("keydown", handleKeyPress);
      });
      history.pushState({ overlayOpen: true }, "");
      return overlay;
    };
    let touchStartX, touchStartY, touchStartTime;
    const touchThreshold = 500; // ms — long-press cancels tap
    const moveThresholdPx = 10; // px — per Android touch slop / Mobiscroll standard
    let touchTimer;
    let preventClick = false;
    let isMoving = false;
    const handleTouchStart = (event) => {
      touchStartX = event.touches[0].pageX;
      touchStartY = event.touches[0].pageY;
      touchStartTime = Date.now();
      preventClick = false;
      isMoving = false;
      touchTimer = setTimeout(() => {
        preventClick = true;
      }, touchThreshold);
    };
    const handleTouchMove = (event) => {
      if (isMoving) return;
      const dx = event.touches[0].pageX - touchStartX;
      const dy = event.touches[0].pageY - touchStartY;
      if (Math.abs(dx) > moveThresholdPx || Math.abs(dy) > moveThresholdPx) {
        isMoving = true;
        preventClick = true;
        clearTimeout(touchTimer);
      }
    };
    const handleTouchEnd = (event) => {
      clearTimeout(touchTimer);
      if (
        !isMoving &&
        !preventClick &&
        Date.now() - touchStartTime < touchThreshold
      ) {
        event.preventDefault();
        handleClick(event);
      }
    };
    const handleClick = (event) => {
      if (preventClick) return;
      event.preventDefault();
      const videoUrl = this.config.enable_trailers && trailer ? trailer : url;
      const videoId = this.getYouTubeVideoId(videoUrl);
      if (videoId) {
        const overlay = createOverlay(videoId);
        document.body.appendChild(overlay);
        document.body.style.overflow = "hidden";
      } else {
        window.open(videoUrl, "_blank");
      }
    };
    element.addEventListener("click", handleClick);
    element.addEventListener("touchstart", handleTouchStart, { passive: true });
    element.addEventListener("touchmove", handleTouchMove, { passive: true });
    element.addEventListener("touchend", handleTouchEnd);
    this.deepLinkListeners.set(element, {
      click: handleClick,
      touchstart: handleTouchStart,
      touchmove: handleTouchMove,
      touchend: handleTouchEnd,
    });
  }
  getYouTubeVideoId(url) {
    const regExp =
      /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|\&v=)([^#\&\?]*).*/;
    const match = url.match(regExp);
    return match && match[2].length === 11 ? match[2] : null;
  }
  removeDeepLinkListener(element) {
    const listeners = this.deepLinkListeners.get(element);
    if (listeners) {
      element.removeEventListener("click", listeners.click);
      element.removeEventListener("touchstart", listeners.touchstart);
      element.removeEventListener("touchmove", listeners.touchmove);
      element.removeEventListener("touchend", listeners.touchend);
      this.deepLinkListeners.delete(element);
    }
  }
  _onSearchInput(ev) {
    this._searchQuery = ev.target.value || "";
    this._redraw();
  }

  // Forces a full redraw: `prev_json` is the card's "nothing changed" guard,
  // and search results are not part of the entity state it compares.
  _redraw() {
    this.prev_json = null;
    if (this._hass) this.hass = this._hass;
  }

  // The day chips: shown when there are two or more day sensors (`enable_days`), rebuilt only
  // when what they show changes (not on every hass update).
  _updateDays(chips, selected) {
    const view = this.config.image_style || "poster";
    this._daysShown = !!this.config.enable_days && chips.length >= 2;
    this._daysRow.style.display = this._daysShown ? "flex" : "none";
    if (this._searchInput) {
      this._searchInput.style.marginBottom =
        view == "poster" || this._daysShown ? "0" : "15px";
    }
    if (!this._daysShown) return;
    // Same horizontal margins as the search row; close under it, or, when the search bar is
    // hidden, where the search row would be (no gap above, and none below the title).
    const top = this.config.enable_search
      ? "8px"
      : this.config.title
        ? "0"
        : "15px";
    this._daysRow.style.margin = `${top} 15px ${view == "poster" ? "0" : "15px"}`;
    // 4px of breathing room above the first line of dates.
    this._daysRow.style.paddingTop = "4px";

    const signature = chips
      .map((c) => [c.key, c.date, c.available, c.label].join("|"))
      .concat(selected && selected.key, this.config.accent_color || "")
      .join(",");
    if (this._daysSignature !== signature) {
      this._daysSignature = signature;
      this._buildDayChips(chips, selected);
    }
    this._layoutDays();
    // The lines depend on the row's width: measured now, and again when it changes. Created
    // once, disconnected in disconnectedCallback (like the overflow observer).
    if (!this._daysObserver && typeof ResizeObserver !== "undefined") {
      this._daysObserverWidth = null;
      this._daysObserver = new ResizeObserver((entries) => {
        const w = entries[0].contentRect.width;
        if (w === this._daysObserverWidth) return;
        this._daysObserverWidth = w;
        this._layoutDays();
      });
      this._daysObserver.observe(this._daysRow);
    }
  }

  _buildDayChips(chips, selected) {
    this._dayButtons = [];
    this._daysLayoutKey = null;
    for (const chip of chips) {
      const on = !!selected && chip.key === selected.key;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = chip.label;
      button.disabled = !chip.available;
      button.setAttribute("aria-pressed", String(on));
      button.style.padding = "4px 10px";
      button.style.borderRadius = "8px";
      button.style.border = "1px solid var(--divider-color, #ccc)";
      button.style.fontSize = "14px";
      button.style.fontFamily = "inherit";
      button.style.cursor = chip.available ? "pointer" : "default";
      button.style.opacity = chip.available ? "" : "0.5";
      // The selected day takes the card's accent colour (as the poster's title line does).
      button.style.background = on
        ? this.config.accent_color || "var(--primary-color)"
        : "var(--card-background-color, #fff)";
      button.style.color = on ? "#fff" : "var(--primary-text-color)";
      button.addEventListener("click", () => {
        this._selectedDate = chip.date;
        this._selectedKey = chip.key;
        this._redraw();
      });
      // A long label is cut with an ellipsis rather than overflowing a narrow card.
      button.style.flex = "0 1 auto";
      button.style.minWidth = "0";
      button.style.overflow = "hidden";
      button.style.textOverflow = "ellipsis";
      button.style.whiteSpace = "nowrap";
      this._dayButtons.push(button);
    }
    this._groupDays([chips.length]);
    this._layoutDays();
    // A web font that arrives later changes the chips' widths.
    if (typeof document !== "undefined" && document.fonts) {
      document.fonts.ready.then(() => this._layoutDays());
    }
  }

  // Puts the chips on lines of the given sizes, each line centred. The chips are moved, not
  // recreated.
  _groupDays(sizes) {
    this._daysRow.innerHTML = "";
    let from = 0;
    for (const size of sizes) {
      const line = document.createElement("div");
      line.style.display = "flex";
      line.style.justifyContent = "center";
      line.style.gap = "8px";
      for (const button of this._dayButtons.slice(from, from + size)) {
        line.appendChild(button);
      }
      from += size;
      this._daysRow.appendChild(line);
    }
  }

  // Splits the chips into lines from their real widths (see dayLineSplit). Everything is
  // measured afresh each time (each chip's natural width with shrinking switched off, the row's
  // width): a cached measure goes stale when the font or the label changes. Nothing is measured
  // while the row has no width (hidden, not attached): the observer calls this again when it does.
  _layoutDays() {
    const buttons = this._dayButtons;
    if (!buttons || buttons.length < 2 || !this._daysShown) return;
    const width = Math.floor(this._daysRow.getBoundingClientRect().width);
    if (!width) return;
    buttons.forEach((b) => (b.style.flexShrink = "0"));
    const widths = buttons.map((b) =>
      Math.ceil(b.getBoundingClientRect().width),
    );
    buttons.forEach((b) => (b.style.flexShrink = "1"));
    const sizes = dayLineSplit(widths, width);
    const key = sizes.join();
    if (key === this._daysLayoutKey) return;
    this._daysLayoutKey = key;
    this._groupDays(sizes);
  }

  // Renders a one-line message in place of the grid (loading, error, no match).
  _showSearchMessage(text) {
    const message = document.createElement("div");
    message.style.padding = "16px";
    message.style.textAlign = "center";
    message.style.color = "var(--secondary-text-color)";
    message.textContent = text;
    this.content.innerHTML = "";
    this.content.appendChild(message);
  }

  set hass(hass) {
    this._hass = hass;
    this.classList.add(this.uniqueId);
    if (!this.content) {
      const card = document.createElement("ha-card");
      card.header = this.config.title;

      this._searchBar = document.createElement("div");
      this._searchBar.style.padding = "0 10px";

      this._searchRow = document.createElement("div");
      this._searchRow.style.display = "flex";
      this._searchRow.style.alignItems = "center";
      this._searchRow.style.gap = "8px";
      const initialView = this.config.image_style || "poster";
      this._searchRow.style.margin =
        initialView == "poster" ? "15px 15px 0" : "15px";
      // The title (ha-card header) has a 24px bottom padding, which is ha-card's own
      // `--ha-space-6`. Reducing that token on the card (24px - 5px, measured by eye) closes the
      // gap without a negative margin, so the search row never overlaps the title's padding.
      if (this.config.title) {
        card.style.setProperty("--ha-space-6", "19px");
        this._searchRow.style.marginTop = "0";
      }

      this._searchInput = document.createElement("input");
      this._searchInput.type = "search";
      this._searchInput.autocomplete = "off";
      this._searchInput.spellcheck = false;
      this._searchInput.placeholder =
        this.config.search_placeholder || "Search title, genre, director";
      this._searchInput.style.flex = "1 1 auto";
      this._searchInput.style.minWidth = "0";
      this._searchInput.style.boxSizing = "border-box";
      this._searchInput.style.padding = "8px 12px";
      this._searchInput.style.borderRadius = "8px";
      this._searchInput.style.border = "1px solid var(--divider-color, #ccc)";
      this._searchInput.style.background = "var(--card-background-color, #fff)";
      this._searchInput.style.color = "var(--primary-text-color)";
      this._searchInput.style.fontSize = "14px";
      this._searchInput.addEventListener(
        "input",
        this._onSearchInput.bind(this),
      );
      this._searchRow.appendChild(this._searchInput);

      this._searchBar.appendChild(this._searchRow);

      card.appendChild(this._searchBar);

      // Day chips, just below the search zone (built like it: inline styles).
      this._daysRow = document.createElement("div");
      this._daysRow.style.display = "none";
      this._daysRow.style.flexDirection = "column";
      this._daysRow.style.gap = "8px";
      card.appendChild(this._daysRow);

      this.content = document.createElement("div");
      this.content.style.padding = "5px 10px";
      this.content.style.position = "relative";
      card.appendChild(this.content);
      this.appendChild(card);
    }
    this._searchBar.style.display = this.config.enable_search ? "" : "none";

    const lang = (hass.locale && hass.locale.language) || hass.language || "en";
    const chips = dayChips(hass, this.config, lang);
    const chip = resolveSelection(chips, {
      date: this._selectedDate,
      key: this._selectedKey,
    });
    if (chip) {
      this._selectedKey = chip.key;
      if (chip.date) this._selectedDate = chip.date;
    }
    this._updateDays(chips, chip);

    const entity = resolveDayEntity(
      hass,
      this.config,
      chip ? chip.key : undefined,
    );
    const state = entity ? hass.states[entity] : undefined;
    const problem = sensorProblem(entity, state, this.config.entry_point);
    if (problem) {
      // Nothing to draw: say why, once (the marker keeps an unrelated state
      // update from redrawing the same message on every hass tick).
      const marker = "message:" + problem;
      if (this.prev_json !== marker) {
        this._clearOverflow();
        this.content.style.visibility = "";
        this._showSearchMessage(problem);
        this.prev_json = marker;
      }
      return;
    }
    let service = entity.slice(7, 11);
    // The adapter builds a lot of text: once per state object, not on every hass update.
    if (state !== this._itemsState) {
      this._itemsState = state;
      this._items = filmsToItems(state.attributes, this.config.entry_point);
    }
    let data = this._items;
    let json;

    // START: 'sort_by' and 'sort_ascending' features
    try {
      json = typeof data === "object" ? data : JSON.parse(data);
      if (this.config && this.config.sort_by !== "none") {
        // The films sorted on `sort_by` (see umcSortItems); the template item stays first.
        const { sort_ascending = true } = this.config;
        const sort_by = this.config.sort_by || "title";
        json = [
          json[0],
          ...umcSortItems(json.slice(1), sort_by, sort_ascending !== false),
        ];
      }
    } catch (e) {
      console.error("Error sorting data:", e);
    }
    // END: 'sort_by' and 'sort_ascending' features

    //Collapse filter (takes precedence over general filter)
    let collapseProcessed = false;
    let conditionalCollapse =
      typeof this.config.collapse === "string"
        ? this.config.collapse.match(/(\w+)=(.*)/)
        : null;
    if (this.config.overflow) {
      this.collapse = Infinity;
    } else if (conditionalCollapse) {
      collapseProcessed = true;
      const attr = conditionalCollapse[1];
      const value = conditionalCollapse[2].toLowerCase();
      let filteredItems = json
        .slice(1)
        .filter((item) => String(item[attr]).toLowerCase().includes(value));
      let unmatchedItems = json
        .slice(1)
        .filter((item) => !String(item[attr]).toLowerCase().includes(value));
      json = [json[0], ...filteredItems, ...unmatchedItems];
      this.collapse = filteredItems.length;
    } else if (typeof this.config.collapse === "number") {
      collapseProcessed = true;
      this.collapse = this.config.collapse;
    } else {
      this.collapse = Infinity;
    }

    // General filter
    if (this.config.filter && !collapseProcessed) {
      const filterParts = this.config.filter.split("=");
      if (filterParts.length === 2) {
        const filterKey = filterParts[0].trim();
        const filterValue = filterParts[1].trim().toLowerCase();
        const templateItem = json[0];
        const filteredItems = json.slice(1).filter((item) => {
          const itemValue = item[filterKey];
          if (filterValue === "") {
            return (
              itemValue === null || itemValue === undefined || itemValue === ""
            );
          }
          if (typeof itemValue === "string") {
            return itemValue.toLowerCase().includes(filterValue);
          } else if (itemValue !== null && itemValue !== undefined) {
            return itemValue.toString().toLowerCase() === filterValue;
          }
          return false;
        });
        json = [templateItem, ...filteredItems];
      }
    }

    // Live search filter (title, genres, directors, cast), applied on top of config.filter above
    if (this._searchQuery && this._searchQuery.trim() !== "") {
      const q = this._searchQuery.trim();
      const templateItem = json[0];
      const searched = json.slice(1).filter((item) => matchesSearch(item, q));
      json = [templateItem, ...searched];
    }

    if (!json[1] && this.config.hide_empty && !this._searchQuery) {
      this.style.display = "none";
    } else if (this.style.display === "none") {
      this.style.display = "";
    }
    if (!json || !json[1]) {
      // The reference only drew a message for a search; a day without films (a
      // closed cinema) needs one too, or the previous content would stay.
      this._clearOverflow();
      this.content.style.visibility = "";
      this._showSearchMessage(
        this._searchQuery
          ? `No results for “${this._searchQuery}”`
          : "No showtimes for this day.",
      );
      this.prev_json =
        JSON.stringify(json) + "|" + (this.config.image_style || "poster");
      return;
    }
    const view = this.config.image_style || "poster";
    const cacheKey = JSON.stringify(json) + "|" + view;
    if (this.prev_json == cacheKey) return;
    this.prev_json = cacheKey;
    this.content.style.marginTop = view == "poster" ? "9px" : "";
    if (this._searchInput) {
      this._searchInput.style.marginBottom =
        view == "poster" || this._daysShown ? "0" : "15px";
    }
    const dateform = this.config.date || "mmdd";
    const icon = this.config.icon || json[0]["icon"];
    const icon_hide = this.config.icon == "none" ? "display:none;" : "";
    const icon_color = this.config.icon_color || "white";
    const flag_color = this.config.flag_color || "var(--primary-color)";
    const flag = this.config.flag == undefined ? true : this.config.flag;
    const timeform = {
      hour12: this.config.clock != 24,
      hour: "2-digit",
      minute: "2-digit",
    };
    const title_text = this.config.title_text || json[0]["title_default"];
    const line1_text = this.config.line1_text || json[0]["line1_default"];
    const line2_text = this.config.line2_text || json[0]["line2_default"];
    const line3_text = this.config.line3_text || json[0]["line3_default"];
    const line4_text = this.config.line4_text || json[0]["line4_default"];
    // Lines 5 and 6: poster view only, no default (see umcLineShown).
    const line5_text = this.config.line5_text || "";
    const line6_text = this.config.line6_text || "";
    const title_size = this.config.title_size || "large";
    const line1_size =
      this.config.line1_size || this.config.line_size || "medium";
    const line2_size =
      this.config.line2_size || this.config.line_size || "small";
    const line3_size =
      this.config.line3_size || this.config.line_size || "small";
    const line4_size =
      this.config.line4_size || this.config.line_size || "small";
    const line5_size =
      this.config.line5_size || this.config.line_size || "small";
    const line6_size =
      this.config.line6_size || this.config.line_size || "small";
    const tSize = (size) =>
      size == "large" ? "18" : size == "medium" ? "14" : "12";
    const size = [
      tSize(title_size),
      tSize(line1_size),
      tSize(line2_size),
      tSize(line3_size),
      tSize(line4_size),
      tSize(line5_size),
      tSize(line6_size),
    ];
    const defaultClr = (poster, fanart) => (view == "poster" ? poster : fanart);
    const title_color =
      this.config.title_color ||
      defaultClr("var(--primary-text-color)", "#fff");
    const line1_color =
      this.config.line1_color ||
      this.config.line_color ||
      defaultClr("var(--primary-text-color)", "#fff");
    const line2_color =
      this.config.line2_color ||
      this.config.line_color ||
      defaultClr("var(--primary-text-color)", "#fff");
    const line3_color =
      this.config.line3_color ||
      this.config.line_color ||
      defaultClr("var(--primary-text-color)", "#fff");
    const line4_color =
      this.config.line4_color ||
      this.config.line_color ||
      defaultClr("var(--primary-text-color)", "#fff");
    const line5_color =
      this.config.line5_color ||
      this.config.line_color ||
      defaultClr("var(--primary-text-color)", "#fff");
    const line6_color =
      this.config.line6_color ||
      this.config.line_color ||
      defaultClr("var(--primary-text-color)", "#fff");
    const accent =
      this.config.accent_color || defaultClr("var(--primary-color)", "#000");
    const border = this.config.border_color || defaultClr("#fff", "#000");
    const corner_radius = this.config.corner_radius;
    const shadows = (conf) =>
      this.config.all_shadows == undefined
        ? conf == undefined
          ? true
          : conf
        : this.config.all_shadows;
    const boxshdw = shadows(this.config.box_shadows)
      ? view == "poster"
        ? "5px 5px 10px"
        : "3px 2px 25px"
      : "";
    const svgshdw = shadows(this.config.box_shadows) ? "url(#grad1)" : accent;
    const txtshdw = shadows(this.config.text_shadows) ? "1px 1px 3px" : "";
    const overflowActive = this.config.overflow;
    const max = this.config.max
      ? Math.min(json.length - 1, this.config.max)
      : json.length - 1;
    this.cardSize = max;

    const createStyleElement = () => {
      let style = document.createElement("style");
      style.setAttribute("id", this.uniqueId + "_style");
      return style;
    };
    let style = createStyleElement();
    let existingStyle = this.querySelector(`[id="${this.uniqueId}_style"]`);
    if (!existingStyle) {
      if (view == "poster") {
        style.textContent = `
          .${this.uniqueId} .${service}_${view} {
            width:100%;
            margin-left: auto;
            margin-right: auto;
            margin-bottom: 10px;
            position: relative;
            display: inline-block;
            overflow: hidden;
            break-inside: avoid;
            ${corner_radius ? "border-radius:" + corner_radius + "px;" : ""}
          }
          .${this.uniqueId} .${service}_${view} ha-icon {
            top: -1%;
            right: 2%;
            z-index: 2;
            width: 17%;
            height: 17%;
            --mdc-icon-size: 100%;
            transform: scale(0.9);
            position:absolute;
            color:${icon_color};
            filter: drop-shadow( 0px 0px 1px rgba(0,0,0,1));
            ${icon_hide};
          }
          .${this.uniqueId} .${service}_${view} img {
            width:100%;
            visibility:hidden;
          }
          .${this.uniqueId} .${service}_svg_${view} {
            width:55%;
            margin-top:5%;
            margin-left:0;
            vertical-align:top;
            overflow:visible;
            z-index:1;
          }
          .${this.uniqueId} .${service}_container_${view} {
            position:relative;
            ${corner_radius ? "" : "outline: 5px solid #fff;"}
            width:30%;
            ${corner_radius ? "border:5px solid " + border + "; box-sizing:border-box;" : "outline:5px solid " + border + ";"}
            box-shadow:${boxshdw} rgba(0,0,0,.8);
            float:left;
            background-position: center;
            background-repeat: no-repeat;
            background-size: cover;
            margin:5px 0 0 5px;
            ${corner_radius ? "border-radius:" + corner_radius + "px; overflow:hidden;" : ""}
          }
          .${this.uniqueId} .${service}_flag_${view} {
            z-index: 1;
            height: 100%;
            width: 100%;
            position: absolute;
            bottom: 0;
            right: 0;
            fill:${flag_color};
          }
          .${this.uniqueId} .${service}_flag_${view} svg{
            float:right;
            width: 100%;
            height: 100%;
            margin:0;
            filter: drop-shadow( -1px 1px 1px rgba(0,0,0,.5));
          }
          .${this.uniqueId} .${service}_line0_${view} {
            font-weight:600;
            font-size:${size[0]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${title_color};
          }
          .${this.uniqueId} .${service}_line1_${view} {
            font-size:${size[1]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line1_color};
          }
          .${this.uniqueId} .${service}_line2_${view} {
            font-size:${size[2]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line2_color};
          }
          .${this.uniqueId} .${service}_line3_${view} {
            font-size:${size[3]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line3_color};
          }
          .${this.uniqueId} .${service}_line4_${view} {
            font-size:${size[4]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line4_color};
          }
          .${this.uniqueId} .${service}_line5_${view} {
            font-size:${size[5]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line5_color};
          }
          .${this.uniqueId} .${service}_line6_${view} {
            font-size:${size[6]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line6_color};
          }
        `;
      } else {
        style.textContent = `
          .${this.uniqueId} .${service}_${view} {
            width:100%;
            overflow:hidden;
            margin-left: auto;
            margin-right: auto;
            margin-bottom: 10px;
            background-repeat:no-repeat;
            background-size: var(--background-size);
            box-shadow:${boxshdw} rgba(0,0,0,.8);
            position:relative;
            break-inside: avoid;
            ${corner_radius ? "border-radius:" + corner_radius + "px;" : ""}
          }
          .${this.uniqueId} .${service}_gap_wrapper_${view} {
            break-inside: avoid;
          }
          .${this.uniqueId} .${service}_${view} ha-icon {
            top: 4%;
            margin-right: -4%;
            right:0;
            z-index: 2;
            width: 15%;
            height: 15%;
            --mdc-icon-size: 100%;
            transform: scale(0.9);
            position:absolute;
            color:${icon_color};
            filter: drop-shadow( 0px 0px 1px rgba(0,0,0,1));
            ${icon_hide};
          }
          .${this.uniqueId} .${service}_svg_${view} {
            overflow:visible;
            width:55%;
            margin-top:1%;
            margin-left:2.5%;
            alignment-baseline:text-after-edge;
          }
          .${this.uniqueId} .${service}_fan_${view} {
            width:100%;
            background: ${this.config.enable_transparency ? `linear-gradient(to right, transparent 0%, ${accent} 47%, transparent 70%, ${accent} 100%)` : `linear-gradient(to right, ${accent} 47%, transparent 70%, ${accent} 100%)`};
            margin:auto;
            box-shadow:inset 0 0 0 3px ${border};
            ${corner_radius ? "border-radius:" + corner_radius + "px;" : ""}
          }
          ${
            this.config.enable_transparency
              ? `
          .${this.uniqueId} .${service}_fan_${view}::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: 50%;
            height: 100%;
            background: ${accent};
            backdrop-filter: blur(1px);
            -webkit-backdrop-filter: blur(1px);
            opacity: 0.1;
            z-index: 1;
          }
          .${this.uniqueId} .${service}_${view}.non-standard-aspect-ratio::before,
          .${this.uniqueId} .${service}_${view}.non-standard-aspect-ratio::after {
            content: '';
            position: absolute;
            left: 0;
            right: 0;
            z-index: 2;
          }
          .${this.uniqueId} .${service}_${view}.non-standard-aspect-ratio::before {
            top: 0;
            height: var(--gap-height);
            background: linear-gradient(to right, transparent 0%, transparent 47%, ${border} 55%, ${border} 100%);
            z-index: 2;
          }
          .${this.uniqueId} .${service}_${view}.non-standard-aspect-ratio::after {
            bottom: 0;
            height: var(--gap-height);
            background: linear-gradient(to right, transparent 0%, transparent 47%, ${border} 55%, ${border} 100%);
            z-index: 2;
          }
          .${this.uniqueId} .${service}_fan_${view} .text-content {
            position: relative;
            z-index: 3;
          }`
              : ""
          }
          .${this.uniqueId} .${service}_flag_${view} {
            z-index: 1;
            height: 100%;
            width: 100%;
            position: absolute;
            margin-top:3px;
            margin-right:3px;
            right: 0;
            fill:${flag_color};
            ${corner_radius ? "border-radius:" + Math.max(0, corner_radius - 3) + "px; overflow:hidden;" : ""}
          }
          .${this.uniqueId} .${service}_flag_${view} svg{
            float:right;
            width: 100%;
            height: 100%;
            margin:0;
            filter: drop-shadow( -1px 1px 1px rgba(0,0,0,.5));
          }
          .${this.uniqueId} .${service}_line0_${view} {
            font-weight:600;
            font-size:${size[0]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${title_color};
          }
          .${this.uniqueId} .${service}_line1_${view} {
            font-size:${size[1]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line1_color};
          }
          .${this.uniqueId} .${service}_line2_${view} {
            font-size:${size[2]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line2_color};
          }
          .${this.uniqueId} .${service}_line3_${view} {
            font-size:${size[3]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line3_color};
          }
          .${this.uniqueId} .${service}_line4_${view} {
            font-size:${size[4]}px;
            text-shadow:${txtshdw} rgba(0,0,0,0.9);
            fill:${line4_color};
          }
          :host {
            cursor: pointer;
          }
        `;
      }
      style.textContent += `
        .${this.uniqueId} * {
          -webkit-tap-highlight-color: transparent;
          -webkit-touch-callout: none;
        }
        .${this.uniqueId} *:active {
          -webkit-tap-highlight-color: transparent;
        }
      `;
      this.appendChild(style);
    }
    this.cleanupDeepLinkListeners();
    this.cleanupTooltipListeners();
    this._hidePillTip();
    this._closeBadgePopover();
    this._stopBadgeWatch();
    this._badgeItems = new Set();
    this.content.innerHTML = "";

    // Truncate text...
    function truncate(text, chars, isTitle) {
      function decodeEntities(input) {
        var textarea = document.createElement("textarea");
        textarea.innerHTML = input;
        return textarea.value;
      }
      // When to truncate depending on size
      chars = chars == "large" ? 23 : chars == "medium" ? 25 : 32;
      text = decodeEntities(text);
      // Truncate only at whole word w/ no punctuation or space before ellipsis.
      if (text.length > chars) {
        for (let i = chars; i > 0; i--) {
          if (
            text.charAt(i).match(/( |\s|:|-|;|"|'|,)/) &&
            text.charAt(i - 1).match(/[^\s:;-;"',]/)
          ) {
            if (isTitle) return text.substring(0, i);
            return text.charAt(i) === "," || text.charAt(i) === " "
              ? text.substring(0, i).replace(/\s+[-&]$/, "")
              : `${text.substring(0, i)}...`;
          }
        }
        // The cycle above had a really big single word, so we return it anyway
        return isTitle
          ? text.substring(0, chars)
          : `${text.substring(0, chars)}...`;
      } else {
        return text;
      }
    }

    function format_date(input_date, format = "mm/dd/yy") {
      let fd_day, fd_month, fd_year, fd_year4;
      format = String(format || "mm/dd/yy");
      const s = String(input_date);

      if ((format === "yyyy" || format === "(yyyy)") && s.match(/^\d{4}$/)) {
        return format === "(yyyy)" ? "(" + s + ")" : s;
      }

      if (s.match(/[T]\d+[:]\d+[:]\d+[Z]/)) {
        const dt = new Date(input_date);
        fd_day = dt.toLocaleDateString([], { day: "2-digit" });
        fd_month = dt.toLocaleDateString([], { month: "2-digit" });
        fd_year = dt.toLocaleDateString([], { year: "2-digit" });
        const y = dt.getFullYear();
        fd_year4 = isNaN(y) ? "" : String(y);
      } else if (s.match(/\d+[-]\d+[-]\d+/)) {
        input_date = s.split("-");
        fd_month = input_date[1];
        fd_day = input_date[2];
        fd_year = input_date[0].slice(-2);
        fd_year4 = input_date[0];
      } else {
        return "";
      }

      const dayInt = parseInt(fd_day, 10);
      const monthInt = parseInt(fd_month, 10);
      const fd_day1 = isNaN(dayInt) ? fd_day : String(dayInt);
      const fd_month1 = isNaN(monthInt) ? fd_month : String(monthInt);

      const formatMap = {
        dd: fd_day,
        d: fd_day1,
        mm: fd_month,
        m: fd_month1,
        yyyy: fd_year4,
        yy: fd_year,
      };
      const mark = "\u0000";

      return format
        .replace(
          /yyyy|yy|mm|m|dd|d/g,
          (matched) => (formatMap[matched] ?? matched) + mark,
        )
        .replace(new RegExp(mark + "(?=\\d)", "g"), "/")
        .replace(new RegExp(mark, "g"), "");
    }

    this.content.style.visibility = "hidden";
    this.content.style.position = "absolute";
    this.content.style.left = "-9999px";

    // Star brightness and saturation matching
    const resolveRGB = (colorStr) => {
      const t = document.createElement("div");
      t.style.color = colorStr;
      t.style.display = "none";
      document.body.appendChild(t);
      const c = getComputedStyle(t).color;
      document.body.removeChild(t);
      const m = c.match(/(\d+),\s*(\d+),\s*(\d+)/);
      return m ? [+m[1], +m[2], +m[3]] : [255, 255, 255];
    };
    const perceivedBrightness = (rgb) =>
      (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
    const rgbToSat = (rgb) => {
      const r = rgb[0] / 255,
        g = rgb[1] / 255,
        b = rgb[2] / 255;
      const max = Math.max(r, g, b),
        min = Math.min(r, g, b);
      if (max === min) return 0;
      const l = (max + min) / 2;
      return ((max - min) / (l > 0.5 ? 2 - max - min : max + min)) * 100;
    };
    const defaultLine3 = defaultClr("var(--primary-text-color)", "#fff");
    const defRGB = resolveRGB(defaultLine3);
    const curRGB = resolveRGB(line3_color);
    const defBright = perceivedBrightness(defRGB);
    const curBright = perceivedBrightness(curRGB);
    const brightRatio = defBright > 0 ? curBright / defBright : 1;
    const defSat = rgbToSat(defRGB);
    const curSat = rgbToSat(curRGB);
    const satRatio =
      defSat > 5 ? curSat / defSat : curSat > 5 ? curSat / 55 : 1;
    const adjustedStar = (() => {
      const h = 41;
      const brightnessAdjustment = 5;
      const saturationAdjustment = 29;
      const satCurveSteepness = 3.0; // TUNE THIS: higher = saturation ramps up faster with brightness (1.0 = linear, 2.0 = steep, 3.0 = very steep, 4.0+ = extreme)
      const brightBoost =
        Math.pow(brightRatio, 1.4) *
        (1 + Math.log1p(Math.pow(brightRatio, 2.5)) / Math.log(3));
      const satBoost = Math.pow(brightRatio, satCurveSteepness);
      let s = Math.min(
        100,
        Math.round(57 * satRatio * 1.07 * brightBoost * satBoost) +
          saturationAdjustment,
      );
      let l = Math.min(
        100,
        Math.round(65 * brightRatio * 1.09) + brightnessAdjustment,
      );
      const hsl2rgb = (h, s, l) => {
        s /= 100;
        l /= 100;
        const k = (n) => (n + h / 30) % 12;
        const a = s * Math.min(l, 1 - l);
        const f = (n) =>
          l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
        return (
          "#" +
          [f(0), f(8), f(4)]
            .map((v) =>
              Math.round(v * 255)
                .toString(16)
                .padStart(2, "0"),
            )
            .join("")
        );
      };
      return hsl2rgb(h, s, l);
    })();

    const dividerBaseLightness = 44; // ← tune default divider brightness (0–100)
    const adjustedDividerL = Math.min(
      100,
      Math.round(dividerBaseLightness * brightRatio * 1.09),
    );
    const adjustedDivider = `hsl(0, 0%, ${adjustedDividerL}%)`;

    // ── MDI thumb icon SVG paths (24×24 viewBox) ─────────────────────
    const MDI_THUMB_UP =
      "M23,10C23,8.89 22.1,8 21,8H14.68L15.64,3.43C15.66,3.33 15.67,3.22 15.67,3.11C15.67,2.7 15.5,2.32 15.23,2.05L14.17,1L7.59,7.59C7.22,7.95 7,8.45 7,9V19A2,2 0 0,0 9,21H18C18.83,21 19.54,20.5 19.84,19.78L22.86,12.73C22.95,12.5 23,12.26 23,12V10M1,21H5V9H1V21Z";
    const MDI_THUMB_UP_OUTLINE =
      "M5,9V21H1V9H5M9,21A2,2 0 0,1 7,19V9C7,8.45 7.22,7.95 7.59,7.59L14.17,1L15.23,2.05C15.5,2.32 15.67,2.7 15.67,3.11L15.64,3.43L14.69,8H21C22.11,8 23,8.9 23,10V12C23,12.26 22.95,12.5 22.86,12.73L19.84,19.78C19.54,20.5 18.83,21 18,21H9M9,19H18.03L21,12V10H12.21L13.34,4.68L9,9.03V19Z";
    const MDI_THUMB_DOWN =
      "M19,15H23V3H19M15,3A2,2 0 0,1 17,5V15C17,15.55 16.78,16.05 16.41,16.41L9.83,23L8.77,21.95C8.5,21.68 8.33,21.3 8.33,20.89L8.36,20.57L9.31,16H3C1.89,16 1,15.1 1,14V12C1,11.74 1.05,11.5 1.14,11.27L4.16,4.22C4.46,3.5 5.17,3 6,3H15Z";
    const MDI_THUMB_DOWN_OUTLINE =
      "M19,15V3H23V15H19M15,3A2,2 0 0,1 17,5V15C17,15.55 16.78,16.05 16.41,16.41L9.83,23L8.77,21.95C8.5,21.68 8.33,21.3 8.33,20.89L8.36,20.57L9.31,16H3C1.89,16 1,15.1 1,14V12C1,11.74 1.05,11.5 1.14,11.27L4.16,4.22C4.46,3.5 5.17,3 6,3H15M15,5H5.97L3,12V14H11.79L10.66,19.32L15,14.97V5Z";

    //Begin of loop iterating through each item in for json data
    for (let count = 1; count <= max; count++) {
      const item = (key) => json[count][key];
      if (!item("airdate")) continue;
      if (this.config.hide_flagged && item("flag")) continue;
      else if (this.config.hide_unflagged && !item("flag")) continue;
      let airdate = new Date(item("airdate"));
      let dflag = item("flag") && flag ? "" : "display:none;";
      let image =
        view == "poster" ? item("poster") : item("fanart") || item("poster");
      if (typeof image === "string" && !/^(https?:|data:)/i.test(image)) {
        image = hass.hassUrl().substring(0, hass.hassUrl().length - 1) + image;
      }
      let daysBetween = Math.round(
        Math.abs(
          (new Date().getTime() - airdate.getTime()) / (24 * 60 * 60 * 1000),
        ),
      );
      let day =
        daysBetween <= 7
          ? airdate.toLocaleDateString([], { weekday: "long" })
          : airdate.toLocaleDateString([], { weekday: "short" });

      let runtime = umcRuntimeText(item("runtime"));

      // Shifting images for fanart view since we use poster as fallback image.
      let shiftimg = item("fanart")
        ? "background-position:100% 0;"
        : "background-size: 54% auto;background-position:100% 35%;";

      // First item in card needs no top margin.
      let top;
      if (count == 1) top = "margin-top: 0px;";
      else top = view == "poster" ? "margin-top: 20px;" : "margin-top: 10px;";

      let line = [
        title_text,
        line1_text,
        line2_text,
        line3_text,
        line4_text,
        line5_text,
        line6_text,
      ];
      let char = [
        title_size,
        line1_size,
        line2_size,
        line3_size,
        line4_size,
        line5_size,
        line6_size,
      ];

      // Keyword map for replacement, return null if empty so we can hide empty sections.
      let keywords = UMC_KEYWORDS;
      const format = this.config.date || "mm/dd/yy";
      const releaseFormat = this.config.date || "mm/dd/yy";
      let keys = {
        $title: item("title") || null,
        $episode: item("episode") || null,
        $genres:
          (Array.isArray(item("genres"))
            ? item("genres").join(", ")
            : item("genres")) || null,
        $number: item("number") || null,
        $rating: item("rating")
          ? String(item("rating")).replace(/\d+\.\d+/, (m) =>
              parseFloat(m).toFixed(1),
            )
          : null,
        $release:
          (item("release") || "")
            .replace("$date", format_date(item("airdate"), releaseFormat))
            .replace("$year", format_date(item("airdate"), "yy"))
            .replace(" $time", "&nbsp;&nbsp;$time") || null,
        $runtime: runtime || null,
        $studio: item("studio") || null,
        $price: item("price") || null,
        $day: day || null,
        $date: format_date(item("airdate"), format) || null,
        $time: airdate.toLocaleTimeString([], timeform) || null,
        $aired: format_date(item("aired"), format) || null,
        $album: item("album") || null,
        $artist: item("artist") || null,
        $channel: item("channel") || null,
        $views: item("views") || null,
        $likes: item("likes") || null,
        $dislikes: item("dislikes") || null,
        $live_status: item("live_status") || null,
        $tmdb_id: item("tmdb_id") || null,
        ...filmKeys(item),
        $release_date: format_date(item("release_date"), format) || null,
        $showtimes: umcShowtimesText(item("_filmObj")) || null,
        $showtimes_badge: umcShowtimesText(item("_filmObj")) || null,
        $certificate_badge:
          (umcCertificateBadge(item("_filmObj"), lang) || {}).label || null,
        $user_rating_badge:
          (umcRatingBadge(item("_filmObj"), "user_rating", lang) || {}).text ||
          null,
        $press_rating_badge:
          (umcRatingBadge(item("_filmObj"), "press_rating", lang) || {}).text ||
          null,
        $empty: "",
      };

      // Poster view with lines 5-6: the height the text needs, in the svg's viewBox units (the
      // item is as tall as the poster, which is not always enough for six lines).
      const extraLines =
        view === "poster" && (line5_text !== "" || line6_text !== "");
      let neededUnits = 0;
      let lastSize = 0;

      // The tooltip's text (see umcTooltipText); "" means no tooltip for this item.
      const tooltipText = this.config.enable_tooltips
        ? umcTooltipText(
            this.config.tooltip_text,
            keys,
            item("_filmRaw"),
            item("_filmObj"),
          )
        : "";

      // Lines that are only `$showtimes` are drawn as badges (see _layoutBadges); the others
      // resolve it as plain text.
      const lineColors = [
        title_color,
        line1_color,
        line2_color,
        line3_color,
        line4_color,
        line5_color,
        line6_color,
      ];
      const badgeSlots = [];

      // Replace keywords in lines
      for (let i = 0; i < line.length; i++) {
        if (!umcLineShown(i, view, line[i])) {
          line[i] = "";
          continue;
        }
        line[i] = line[i].replace(" - ", "-");
        // Split the template at '-' (not the values: a title may contain one) so that a part
        // whose keyword is empty is ignored
        let text = resolveText(line[i], keys, item("_film"), {
          raw: item("_filmObj"),
          clean: umcClean,
        });
        // A line that contains a `_badge` token is drawn as a row of badges and texts (see
        // _layoutBadges), never as text: each badge token stands for itself (an empty one adds
        // nothing and does not affect the others), the text around them is a text span.
        const segments = umcBadgeSegments(line[i]);
        const film = item("_filmObj");
        let slot = null;
        if (segments) {
          text = "";
          const items = umcBadgeItems(segments, film, lang, (template) =>
            resolveText(template.replace(" - ", "-"), keys, item("_film"), {
              raw: film,
              clean: umcClean,
            }),
          );
          if (items.length)
            slot = {
              i,
              items,
              lang,
              text: umcBadgeFallbackText(items),
              size: Number(size[i]),
              color: lineColors[i],
              star: adjustedStar,
              shadow: txtshdw ? `${txtshdw} rgba(0,0,0,0.9)` : "",
              x: view == "fanart" ? 0 : 12,
              colors: {
                vf: this.config.vf_color,
                vo: this.config.vo_color,
                vost: this.config.vost_color,
                other: this.config.other_color,
                age_12: this.config.age_12_color,
                age_16: this.config.age_16_color,
                age_18: this.config.age_18_color,
              },
            };
        }
        if (slot) badgeSlots.push(slot);
        // Nothing to show: the line is ignored (no tspan, no room).
        if (!slot && umcLineIsIgnored(i, line[i], text)) {
          line[i] = "";
          continue;
        }
        if (
          extraLines &&
          (i == 0 || line[i].match("empty") || slot || text !== "")
        ) {
          lastSize = Number(size[i]);
          neededUnits +=
            i == 0
              ? (lastSize == 18 ? -5 : lastSize == 14 ? -2 : 0) +
                1.3 * lastSize +
                3.9
              : 1.3 * lastSize + (i == 1 ? 3 : 2);
        }

        // Shifting header text around depending on view & size
        let svgshift, y;
        if (i == 0)
          size[i].match(/18/)
            ? (y = "-5")
            : size[i].match(/14/)
              ? (y = "-2")
              : (y = "0");
        const extraPx = i == 1 ? 3 : i >= 2 ? 2 : 0;
        const lineDy = (1.3 + extraPx / size[i]).toFixed(3) + "em";
        if (view == "fanart")
          svgshift = i == 0 ? `x="0" dy="1.15em" ` : `x="0" dy="${lineDy}" `;
        else
          svgshift =
            i == 0 ? `x="12" y="${y}" dy="1.3em" ` : `x="12" dy="${lineDy}" `;

        // Build lines HTML or empty line
        line[i] =
          line[i].match("empty") || slot
            ? `<tspan class="${service}_line${i}_${view}"${slot ? ` data-umc-badges="${i}"` : ""} style="fill:transparent;text-shadow:0 0 transparent;" ${svgshift}>.</tspan>`
            : `<tspan class="${service}_line${i}_${view}" ${svgshift}>${truncate(
                text,
                char[i],
                i === 0,
              )
                .replace(/,\s[^,]*\.\.\.$/g, "")
                .replace(
                  /★(?=\s*\d)/g,
                  `<tspan fill="${adjustedStar}">★</tspan>`,
                )}</tspan>`;
      }

      let l4FOData = null;
      if (
        !this.config.line4_text ||
        this.config.line4_text.includes("$likes")
      ) {
        const l4Views = item("views");
        const l4Likes = item("likes");
        const l4Dislikes = item("dislikes");
        const l4Rating = item("my_rating") || "none";
        const thumbSpan =
          "display:inline-flex;align-items:center;vertical-align:-0.15em;gap:0.25em;";
        const thumbIcon = (path, fill) =>
          `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="1.15em" height="1.15em" style="fill:${fill};flex-shrink:0;"><path d="${path}"/></svg>`;
        const l4Parts = [];
        if (l4Views) l4Parts.push(l4Views + " views");
        let thumbsHtml = "";
        if (l4Likes != null) {
          const upPath =
            l4Rating === "like" ? MDI_THUMB_UP : MDI_THUMB_UP_OUTLINE;
          const upFill = l4Rating === "like" ? adjustedStar : line4_color;
          thumbsHtml += `<span style="${thumbSpan}">${thumbIcon(upPath, upFill)}${l4Likes}</span>`;
        }
        if (l4Likes != null && l4Dislikes != null) {
          thumbsHtml += `<span style="display:inline-block;width:1.5px;height:1.15em;vertical-align:-0.15em;margin:0 calc(0.55em + 1px);background:${adjustedDivider};"></span>`;
        }
        if (l4Dislikes != null) {
          const dnPath =
            l4Rating === "dislike" ? MDI_THUMB_DOWN : MDI_THUMB_DOWN_OUTLINE;
          const dnFill = l4Rating === "dislike" ? adjustedStar : line4_color;
          thumbsHtml += `<span style="${thumbSpan}">${thumbIcon(dnPath, dnFill)}${l4Dislikes}</span>`;
        }
        if (thumbsHtml) l4Parts.push(thumbsHtml);
        const l4Html = l4Parts.join(" \u2009\u2013\u2009 ");
        if (l4Html) {
          const foX = view === "poster" ? 12 : 0;
          const l4Shadow = txtshdw
            ? `text-shadow:${txtshdw} rgba(0,0,0,0.9);`
            : "";
          line[4] = line[4].replace("<tspan ", "<tspan data-umc-l4 ");
          l4FOData = {
            l4Html,
            foX,
            l4Shadow,
            fontSize: size[4],
            color: line4_color,
          };
        }
      }

      const applyLine4FO = (container) => {
        if (!l4FOData) return;
        requestAnimationFrame(() => {
          const wasHidden = container.style.display === "none";
          if (wasHidden) {
            container.style.visibility = "hidden";
            container.style.display = "";
          }
          try {
            const svg = container.querySelector('svg[class*="_svg_"]');
            const tspan = svg && svg.querySelector("[data-umc-l4]");
            if (!tspan || !svg) return;
            const bbox = tspan.getBBox();
            if (bbox.height < 1) return;
            const ns = "http://www.w3.org/2000/svg";
            const fo = document.createElementNS(ns, "foreignObject");
            fo.setAttribute("x", l4FOData.foX);
            fo.setAttribute("y", bbox.y);
            fo.setAttribute("width", 200 - l4FOData.foX);
            fo.setAttribute("height", bbox.height * 1.5);
            fo.innerHTML = `<body xmlns="http://www.w3.org/1999/xhtml" style="margin:0;padding:0;background:transparent;"><div style="font-size:${l4FOData.fontSize}px;color:${l4FOData.color};${l4FOData.l4Shadow}white-space:nowrap;line-height:1;">${l4FOData.l4Html}</div></body>`;
            svg.appendChild(fo);
            tspan.style.fill = "transparent";
            tspan.style.textShadow = "0 0 transparent";
          } catch (e) {
          } finally {
            if (wasHidden) {
              container.style.display = "none";
              container.style.visibility = "";
            }
          }
        });
      };

      // The badge rows are placed once the item is in the page (see _layoutBadges).
      const applyBadges = (container) => {
        if (!badgeSlots.length) return;
        container._umcBadgeSlots = badgeSlots;
        this._badgeItems.add(container);
        this._layoutBadges(container);
      };

      let deepLink = item("deep_link");
      // Replace keywords in custom url if configured
      if (this.url) {
        deepLink = this.url.replace(keywords, (val) =>
          umcTokenValue(val, keys, item("_film"), {
            raw: item("_filmObj"),
            clean: umcClean,
          }),
        );
      }

      // Mouse & touch event listeners
      function addDeepLinkListener(element, link) {
        let startX = 0,
          startY = 0,
          moveThresholdPx = 10,
          longPressThresholdMs = 500;
        let isMoving = false,
          timer,
          startTime;
        element.addEventListener(
          "touchstart",
          function (event) {
            startX = event.touches[0].pageX;
            startY = event.touches[0].pageY;
            isMoving = false;
            startTime = Date.now();
            timer = setTimeout(() => {
              isMoving = true;
            }, longPressThresholdMs);
          },
          { passive: true },
        );
        element.addEventListener(
          "touchmove",
          function (event) {
            if (isMoving) return;
            const moveX = event.touches[0].pageX,
              moveY = event.touches[0].pageY;
            if (
              Math.abs(moveX - startX) > moveThresholdPx ||
              Math.abs(moveY - startY) > moveThresholdPx
            ) {
              isMoving = true;
              clearTimeout(timer);
            }
          },
          { passive: true },
        );
        element.addEventListener(
          "touchend",
          function () {
            clearTimeout(timer);
            if (!isMoving && Date.now() - startTime < longPressThresholdMs) {
              window.open(link, "_blank");
            }
            isMoving = false;
          },
          { passive: true },
        );
        element.style.cursor = "pointer";
        element.addEventListener("click", function () {
          window.open(link, "_blank");
        });
      }

      if (view == "poster") {
        let containerDiv = document.createElement("div");
        if (this.config.enable_tooltips) {
          this.addTooltipHandlers(containerDiv, tooltipText, (x, y) =>
            umcTooltipZone(containerDiv, view, x, y),
          );
        }
        containerDiv.id = "main";
        containerDiv.className = `${service}_${view}`;
        containerDiv.style.cssText = top;
        let containerDivInnerHTML = `
          <div class="${service}_container_${view}" style="background-image:url('${image}');">
            <img src="${image}"/>
            <ha-icon icon="${icon}" style="${dflag}"></ha-icon>
            <div class="${service}_flag_${view}" style="${dflag}">
              <svg style="${dflag}" preserveAspectRatio="none" viewBox="0 0 100 100">
                <polygon points="100 25,65 0,100 0"></polygon>
              </svg>
            </div>
          </div>
          <svg class='${service}_svg_${view}' viewBox="0 0 200 ${extraLines ? Math.max(100, Math.ceil(neededUnits + 0.3 * lastSize)) : 100}">
            <defs>
              <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color:rgb(20,20,20,1);stop-opacity:1" />
                <stop offset="2%" style="stop-color:${accent};stop-opacity:1" />
              </linearGradient>
            </defs>
            <rect width="500px" height="23px" fill="${svgshdw}"/>
            <text>
              ${line[0]}
              <tspan dy="1.3em" style="font-size:3px;fill:transparent;text-shadow:0 0 transparent;">.</tspan>
              ${line[1]}${line[2]}${line[3]}${line[4]}${line[5]}${line[6]}
            </text>
          </svg>
        `;
        containerDiv.innerHTML = containerDivInnerHTML;
        let clickableAreaDiv = document.createElement("div");
        clickableAreaDiv.style.position = "absolute";
        clickableAreaDiv.style.top = "3px";
        clickableAreaDiv.style.right = "3px";
        clickableAreaDiv.style.bottom = "3px";
        clickableAreaDiv.style.left = "3px";
        clickableAreaDiv.style.borderRadius = "3px";
        clickableAreaDiv.style.pointerEvents = "auto";
        clickableAreaDiv.style.zIndex = "5";
        clickableAreaDiv.setAttribute("data-umc-click", "");
        containerDiv.style.overflow = "hidden";
        containerDiv.appendChild(clickableAreaDiv);
        if (
          !this.config.disable_hyperlinks &&
          (deepLink || (this.config.enable_trailers && item("trailer")))
        ) {
          if (this.config.enable_trailers && item("trailer") && !this.url) {
            this.addDeepLinkListener(
              clickableAreaDiv,
              deepLink,
              item("trailer"),
            );
          } else if (deepLink) {
            this.addDeepLinkListener(clickableAreaDiv, deepLink);
          }
          clickableAreaDiv.style.cursor = "pointer";
        } else {
          clickableAreaDiv.style.cursor = "default";
        }
        if (count <= this.collapse) {
          this.content.appendChild(containerDiv);
        } else {
          containerDiv.style.display = "none";
          containerDiv.classList.add("collapsed");
          this.content.appendChild(containerDiv);
        }
        applyLine4FO(containerDiv);
        applyBadges(containerDiv);
      } else {
        let fanartContainerDiv = document.createElement("div");
        if (this.config.enable_tooltips) {
          this.addTooltipHandlers(fanartContainerDiv, tooltipText, (x, y) =>
            umcTooltipZone(fanartContainerDiv, view, x, y),
          );
        }
        fanartContainerDiv.className = `${service}_${view}`;
        fanartContainerDiv.style.cssText = `${top} ${shiftimg}background-image:url('${image}');background-position:100% center;`;
        fanartContainerDiv.style.setProperty("--background-size", "53% auto");
        let img = new Image();
        img.onload = function () {
          let aspectRatio = img.width / img.height;
          if (aspectRatio > 1.78) {
            fanartContainerDiv.classList.add("non-standard-aspect-ratio");
            let heightAdjustmentFactor = (aspectRatio - 1.78) / 2;
            let heightPercentage = 100 - (heightAdjustmentFactor * 100) / 1.78;
            let backgroundSize = `54% ${Math.round(Math.max(heightPercentage, 50))}%`;
            fanartContainerDiv.style.setProperty(
              "--background-size",
              backgroundSize,
            );
            let gapHeightCalcExpression = `calc((100% - ${Math.round(Math.max(heightPercentage, 50))}%) / 2)`;
            fanartContainerDiv.style.setProperty(
              "--gap-height",
              gapHeightCalcExpression,
            );
          }
        };
        img.src = image;

        let fanartContainerInnerHTML = `
          <div class="${service}_fan_${view}">
            <ha-icon icon="${icon}" style="${dflag}"></ha-icon>
            <div class="${service}_flag_${view}" style="${dflag}">
              <svg style="${dflag}" preserveAspectRatio="none" viewBox="0 0 100 100">
                <polygon points="100 30,90 0,100 0"></polygon>
              </svg>
                </div>
                <svg class="${service}_svg_${view}"viewBox="0 0 200 100">
                   <text>${line[0]}${line[1]}${line[2]}${line[3]}${line[4]}</text>
                </svg>
            </div>
        `;
        fanartContainerDiv.innerHTML = fanartContainerInnerHTML;
        let clickableAreaDivFanart = document.createElement("div");
        clickableAreaDivFanart.style.position = "absolute";
        clickableAreaDivFanart.style.top = "3px";
        clickableAreaDivFanart.style.right = "3px";
        clickableAreaDivFanart.style.bottom = "3px";
        clickableAreaDivFanart.style.left = "3px";
        clickableAreaDivFanart.style.pointerEvents = "auto";
        clickableAreaDivFanart.style.zIndex = "5";
        clickableAreaDivFanart.setAttribute("data-umc-click", "");
        fanartContainerDiv.style.overflow = "hidden";
        fanartContainerDiv.appendChild(clickableAreaDivFanart);
        if (
          !this.config.disable_hyperlinks &&
          (deepLink || (this.config.enable_trailers && item("trailer")))
        ) {
          if (this.config.enable_trailers && item("trailer") && !this.url) {
            this.addDeepLinkListener(
              clickableAreaDivFanart,
              deepLink,
              item("trailer"),
            );
          } else if (deepLink) {
            this.addDeepLinkListener(clickableAreaDivFanart, deepLink);
          }
          clickableAreaDivFanart.style.cursor = "pointer";
        } else {
          clickableAreaDivFanart.style.cursor = "default";
        }
        let gapWrapperDiv = document.createElement("div");
        gapWrapperDiv.className = `${service}_gap_wrapper_${view}`;
        this.content.appendChild(gapWrapperDiv);
        gapWrapperDiv.appendChild(fanartContainerDiv);

        if (count <= this.collapse) {
          gapWrapperDiv.appendChild(fanartContainerDiv);
        } else {
          fanartContainerDiv.style.display = "none";
          fanartContainerDiv.classList.add("collapsed");
          gapWrapperDiv.appendChild(fanartContainerDiv);
        }
        this.content.appendChild(gapWrapperDiv);
        applyLine4FO(fanartContainerDiv);
        applyBadges(fanartContainerDiv);
      }
      if (!this.querySelector(`[id="${this.uniqueId}_style"]`))
        this.appendChild(style);
      this.style.cursor =
        this.url && this.url.trim() !== "" ? "pointer" : "default";
      this.removeEventListener("click", this._boundClickListener);
      const hasDeepLinks = json.some((item) => item.deep_link);
      if (!hasDeepLinks && this.url && this.url.trim() !== "") {
        this.style.cursor = "pointer";
        this._boundClickListener = () => window.open(this.url, "_blank");
        this.addEventListener("click", this._boundClickListener);
      } else {
        this.style.cursor = "default";
      }
    }
    this.content.style.position = "relative";
    this.content.style.left = "";

    // START: Overflow columns feature
    if (overflowActive) {
      if (this.config.overflow_fit === "content") {
        // No provisional viewport clamp: the layout is column-driven, not height-driven.
        this.content.style.height = "";
        this.content.style.overflowY = "";
      } else {
        this.content.style.height =
          Math.max(200, window.innerHeight - 120) + "px";
        this.content.style.overflowY = "hidden";
      }
      this._applyOverflow();
    } else {
      this._clearOverflow();
      this.content.style.visibility = "";
    }
    // END: Overflow columns feature
    // Every badge row that is not placed yet (see _layoutBadges), now that the layout is done.
    this._layoutAllBadges();

    // START: Expand/Collapse feature
    let hasUnmatchedItems = json.length > this.collapse + 1;
    if (hasUnmatchedItems && !this.querySelector(".expand-control")) {
      const controlContainer = document.createElement("div");
      controlContainer.classList.add("control-container");
      controlContainer.style.display = "flex";
      controlContainer.style.flexDirection = "column";
      controlContainer.style.alignItems = "flex-end";
      const firstCollapsedEl = this.content.querySelector(".collapsed");
      if (firstCollapsedEl) {
        let insertRef = firstCollapsedEl;
        while (insertRef.parentNode !== this.content)
          insertRef = insertRef.parentNode;
        this.content.insertBefore(controlContainer, insertRef);
      } else {
        this.content.appendChild(controlContainer);
      }

      if (
        typeof this.config.collapse === "string" &&
        this.config.collapse.includes("=")
      ) {
        const [attribute, expectedValue] = this.config.collapse
          .split("=")
          .map((part) => part.trim());
        if (
          !json
            .slice(1)
            .some(
              (item) =>
                item[attribute] &&
                item[attribute]
                  .toString()
                  .toLowerCase()
                  .includes(expectedValue.toLowerCase()),
            )
        ) {
          if (!controlContainer.querySelector(".placeholder")) {
            let placeholderContainer = document.createElement("div");
            placeholderContainer.classList.add("placeholder-container");
            placeholderContainer.style.position = "relative";
            placeholderContainer.style.width = "100%";
            placeholderContainer.style.boxSizing = "border-box";
            placeholderContainer.style.padding = "0 18px 0 0";
            placeholderContainer.style.lineHeight = "20px";
            placeholderContainer.style.textAlign = "right";
            placeholderContainer.style.marginTop = "21px";
            let placeholder = document.createElement("div");
            placeholder.classList.add("placeholder");
            placeholder.textContent = "No uncollapsed items";
            placeholder.style.color = "#929292";
            placeholder.style.whiteSpace = "nowrap";
            placeholder.style.overflow = "hidden";
            placeholder.style.textOverflow = "ellipsis";
            placeholder.style.display = "inline-block";
            placeholder.style.maxWidth = "100%";
            placeholderContainer.appendChild(placeholder);
            controlContainer.style.marginTop = "10px";
            controlContainer.insertBefore(
              placeholderContainer,
              controlContainer.firstChild,
            );
          }
        }
      }

      const expandControl = document.createElement("div");
      expandControl.classList.add("expand-control");
      expandControl.style = `
        position: relative;
        width: 50px;
        height: 6px;
        z-index: 6;
        display: flex;
        justify-content: center;
        align-items: center;
        overflow: visible;
      `;

      const touchShield = document.createElement("div");
      touchShield.classList.add("expand-touch-shield");
      touchShield.style = `
        position: absolute;
        width: 44px;
        height: 44px;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        clip-path: circle(50%);
        -webkit-clip-path: circle(50%);
        z-index: 7;
        cursor: pointer;
        background: transparent;
      `;

      const chevronWrapper = document.createElement("div");
      chevronWrapper.style = `
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        height: 100%;
        pointer-events: none;
      `;
      chevronWrapper.innerHTML =
        '<div class="rotate-icon" style="opacity: 1; transform: rotate(90deg) scaleX(0.65) scaleY(1.27); transition: transform 0.2s ease-in-out; margin-top: -2px; margin-left: -2px; line-height: 0; display: flex; align-items: center; justify-content: center;"><svg viewBox="0 0 7 14" width="6" height="11" style="display:block;"><polyline points="1,1 6,7 1,13" fill="none" stroke="#fff" stroke-width="2.0" stroke-linecap="round" stroke-linejoin="round"/></svg></div>';

      expandControl.appendChild(touchShield);
      expandControl.appendChild(chevronWrapper);
      controlContainer.appendChild(expandControl);

      const toggleExpand = () => {
        this.isExpanded = !this.isExpanded;
        const rotateIcon = expandControl.querySelector(".rotate-icon");
        rotateIcon.style.transition = "transform 0.2s ease-in-out";
        rotateIcon.style.transform = this.isExpanded
          ? "rotate(270deg) scaleX(0.65) scaleY(1.27)"
          : "rotate(90deg) scaleX(0.65) scaleY(1.27)";
        setTimeout(() => {
          const collapsedItems = this.querySelectorAll(".collapsed");
          collapsedItems.forEach((item) => {
            item.style.display = this.isExpanded ? "block" : "none";
          });
          // Items that were hidden when drawn could not be measured: do it now.
          if (this.isExpanded)
            collapsedItems.forEach((item) => this._layoutBadges(item));
        }, 60);
      };

      touchShield.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleExpand();
      });
      touchShield.addEventListener("touchstart", (e) => {
        e.stopPropagation();
      });
      touchShield.addEventListener("touchend", (e) => {
        e.stopPropagation();
      });
    }
    // END: Expand/Collapse feature
  }

  // Draws the badge rows of an item (`container._umcBadgeSlots`, see the render loop). Each is a
  // foreignObject in the item's svg, at the slot of its line: a transparent "." tspan, as for an empty
  // line. The row's size is in the svg's units, so it wraps the same at any card width: measured
  // once, here, and its height is made room for by moving the following lines down (the `dy` of the
  // next tspan that has text) and, if the text now reaches below the svg's viewBox, by growing it.
  // An item that cannot be measured yet (not in the page, hidden, collapsed, no size) is watched
  // (_pendBadges) and laid out as soon as it can be. A row that fails or ends up empty or outside
  // its item is replaced by the plain text, never a blank line.
  _layoutBadges(container) {
    const slots = container._umcBadgeSlots;
    const svg = container.querySelector('svg[class*="_svg_"]');
    if (!slots || !svg || container._umcBadgesDone) return;
    if (
      !container.isConnected ||
      container.getClientRects().length === 0 ||
      svg.getBoundingClientRect().width < 1
    ) {
      this._pendBadges(container);
      return;
    }
    if (container._umcBadgesFallback) this._restoreBadgeSlots(svg, slots);
    const text = svg.querySelector("text");
    const ns = "http://www.w3.org/2000/svg";
    const rows = [];
    try {
      for (const slot of slots) {
        const tspan = svg.querySelector(`[data-umc-badges="${slot.i}"]`);
        const box = tspan && tspan.getBBox();
        if (!box || box.height < 1) throw UMC_NOT_READY;
        const fo = document.createElementNS(ns, "foreignObject");
        fo.setAttribute("x", slot.x);
        fo.setAttribute("y", box.y);
        fo.setAttribute("width", 200 - slot.x);
        fo.setAttribute("height", 400);
        fo.style.overflow = "visible";
        fo.setAttribute("data-umc-badge-row", "");
        const area = container.querySelector("[data-umc-click]");
        const row = umcBuildBadgeRow(slot.items, {
          ...slot,
          cursor: area ? area.style.cursor : "default",
          onToggle: (group, pill) =>
            this._toggleBadgePopover(group, pill, slot),
          onTip: (anchor, text) => this._showPillTip(anchor, text),
          // The item's own link, as if the click had been on its click area.
          onForward: () => {
            const link = container.querySelector("[data-umc-click]");
            if (link) link.click();
          },
        });
        fo.appendChild(row);
        svg.appendChild(fo);
        rows.push(row);
        // (An engine that reports no height: about one line of the slot's size.)
        const height = row.offsetHeight || Math.ceil(slot.size * 1.5);
        fo.setAttribute("height", height);
        // Only the version pills take clicks (they say so themselves); the rest of the row, the
        // foreignObject and the svg around it do not, so the item's film link works under them.
        fo.style.pointerEvents = "none";
        let next = tspan.nextElementSibling;
        while (next && next.textContent === "") next = next.nextElementSibling;
        const extra = umcBadgeRowExtra(
          height,
          box.height,
          !!next && next.hasAttribute("data-umc-badges"),
        );
        if (extra > 0 && next) {
          const dy =
            parseFloat(next.getAttribute("dy")) *
            parseFloat(getComputedStyle(next).fontSize);
          next.setAttribute("dy", String(dy + extra));
        }
        const bottom = Math.max(
          text.getBBox().y + text.getBBox().height,
          box.y + height,
        );
        if (bottom + 2 > svg.viewBox.baseVal.height) {
          svg.setAttribute("viewBox", `0 0 200 ${Math.ceil(bottom + 2)}`);
        }
      }
      // Rendered rows must have a size and lie inside the item.
      const item = container.getBoundingClientRect();
      for (const row of rows) {
        const r = row.getBoundingClientRect();
        if (
          r.width < 1 ||
          r.height < 1 ||
          r.top < item.top - 2 ||
          r.bottom > item.bottom + 2 ||
          r.left < item.left - 2 ||
          r.right > item.right + 2
        )
          throw new Error("badge row empty or outside its item");
      }
    } catch (err) {
      svg
        .querySelectorAll("foreignObject[data-umc-badge-row]")
        .forEach((fo) => fo.remove());
      if (err === UMC_NOT_READY) {
        this._pendBadges(container);
        return;
      }
      this._badgesAsText(container, svg, slots);
      container._umcBadgesDone = true;
      this._unwatchBadges(container);
      return;
    }
    container._umcBadgesDone = true;
    this._unwatchBadges(container);
    // The svg is under the item's click area (the link to the film): above it, but letting clicks
    // through except on the badges.
    svg.style.position = "relative";
    svg.style.zIndex = "6";
    svg.style.pointerEvents = "none";
  }

  // Opens, switches or closes the popover of a badge: the times of its version group. One at a time,
  // as a dark panel like the card's hover bubble, on <body> (fixed), next to the pill inside the
  // viewport. It closes on a click outside, Escape, a scroll or resize of the page, a size change of
  // the card, another click on the pill, a new render and disconnection (see _closeBadgePopover).
  _toggleBadgePopover(group, pill, slot) {
    const same = this._popover && this._popover.pill === pill;
    this._hidePillTip();
    this._closeBadgePopover();
    if (same) return;
    // The hover bubble gives way (and does not come back while this is open).
    this._hideSynopsisBubbles();
    const colors = umcBadgeColors(slot.colors);
    const panel = document.createElement("div");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", umcGroupHeader(group, slot.lang));
    const s = panel.style;
    s.position = "fixed";
    s.visibility = "hidden";
    s.left = "-9999px";
    s.top = "-9999px";
    s.zIndex = "1001";
    s.padding = "12px 14px";
    s.borderRadius = "8px";
    s.background = "rgba(0, 0, 0, 0.92)";
    s.backdropFilter = "blur(4px)";
    s.boxShadow = "0 12px 24px rgba(0, 0, 0, 0.90)";
    s.color = "white";
    s.fontFamily = "var(--paper-font-body1_-_font-family, inherit)";
    s.fontSize = "12px";
    s.lineHeight = "1.45";
    s.fontWeight = "normal";
    s.letterSpacing = "normal";
    s.textShadow = "none";
    s.maxWidth = "min(340px, calc(100vw - 32px))";
    // At least the width of about 4 times on a row (a time is ~5 digits + its 8px side paddings,
    // 6px between them, then the panel's own 14px side paddings); the content is centred.
    s.minWidth =
      "min(calc(4 * (5ch + 16px) + 3 * 6px + 28px), calc(100vw - 32px))";
    s.boxSizing = "border-box";
    s.textAlign = "center";
    const header = document.createElement("div");
    header.textContent = umcGroupHeader(group, slot.lang);
    header.style.fontWeight = "600";
    panel.appendChild(header);
    const grid = document.createElement("div");
    grid.style.display = "flex";
    grid.style.flexWrap = "wrap";
    grid.style.justifyContent = "center";
    grid.style.gap = "6px";
    grid.style.marginTop = "8px";
    for (const entry of group.entries) {
      const chip = document.createElement(entry.url ? "a" : "span");
      const flags = umcAccessibilityFlags(entry, slot.lang);
      if (flags.length) {
        // The time and the icons apart, so that a link's underline stays under the time.
        const time = document.createElement("span");
        time.textContent = entry.time;
        chip.appendChild(time);
        for (const flag of flags)
          chip.appendChild(umcAccessibilityIcon(flag, 14, true));
        chip.style.display = "inline-flex";
        chip.style.alignItems = "center";
        chip.style.gap = "4px";
        chip.style.textDecoration = "none";
      } else {
        chip.textContent = entry.time;
        chip.style.textDecoration = "none";
      }
      if (entry.url) {
        chip.setAttribute("href", entry.url);
        chip.setAttribute("target", "_blank");
        chip.setAttribute("rel", "noopener noreferrer");
        chip.style.cursor = "pointer";
      }
      chip.style.color = "white";
      chip.style.padding = "2px 8px";
      chip.style.borderRadius = "6px";
      chip.style.fontVariantNumeric = "tabular-nums";
      chip.style.whiteSpace = "nowrap";
      chip.style.background = umcSoftFill(colors[group.key], 40);
      grid.appendChild(chip);
    }
    panel.appendChild(grid);
    // The legend: only the marks that appear in this popup (touch screens have no tooltips).
    const legend = umcAccessibilityLegend(group.entries, slot.lang);
    if (legend.length) {
      const list = document.createElement("div");
      list.style.display = "flex";
      list.style.flexWrap = "wrap";
      list.style.justifyContent = "center";
      list.style.gap = "2px 10px";
      list.style.marginTop = "8px";
      list.style.fontSize = "10px";
      list.style.opacity = "0.75";
      for (const flag of legend) {
        const item = document.createElement("span");
        item.style.display = "inline-flex";
        item.style.alignItems = "center";
        item.style.gap = "3px";
        item.appendChild(umcAccessibilityIcon(flag, 12, false));
        const label = document.createElement("span");
        label.textContent = flag.label;
        item.appendChild(label);
        list.appendChild(item);
      }
      panel.appendChild(list);
    }
    document.body.appendChild(panel);
    const place = () => {
      const box = panel.getBoundingClientRect();
      const at = umcPopoverPosition(
        pill.getBoundingClientRect(),
        { width: box.width, height: box.height },
        { width: window.innerWidth, height: window.innerHeight },
        6,
        8,
        (pill.closest("ha-card") || this).getBoundingClientRect(),
      );
      s.left = at.left + "px";
      s.top = at.top + "px";
      s.visibility = "visible";
    };
    place();
    pill.setAttribute("aria-expanded", "true");
    pill.style.background = pill.dataset.strong;
    const close = () => this._closeBadgePopover();
    const onClick = (event) => {
      if (panel.contains(event.target)) return;
      if (event.target.closest && event.target.closest("[data-umc-group]"))
        return;
      close();
    };
    const onKey = (event) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    let observer = null;
    if (typeof ResizeObserver !== "undefined") {
      let first = true;
      observer = new ResizeObserver(() => {
        if (first) first = false;
        else close();
      });
      observer.observe(this);
    }
    this._popoverOpen = true;
    this._popover = {
      pill,
      panel,
      cleanup: () => {
        document.removeEventListener("click", onClick, true);
        document.removeEventListener("keydown", onKey);
        window.removeEventListener("scroll", close, true);
        window.removeEventListener("resize", close);
        if (observer) observer.disconnect();
      },
    };
  }

  // The small tip of a badge, rating or age (`anchor` null hides it): the same dark look as the
  // card's bubbles, shown after `tooltip_delay`, above the anchor. It does not depend on
  // `enable_tooltips` (these are labels), and the synopsis bubble stays away meanwhile.
  // This card's own synopsis bubbles (and the timers about to show one), not another card's.
  _hideSynopsisBubbles() {
    this.tooltipListeners.forEach((listeners) => {
      if (listeners.cleanup) listeners.cleanup();
    });
  }

  _showPillTip(anchor, text) {
    this._hidePillTip();
    this._pillHover = !!anchor;
    if (!anchor) return;
    this._hideSynopsisBubbles();
    const hide = () => this._hidePillTip();
    const timer = setTimeout(() => {
      if (!anchor.isConnected || this._popoverOpen) return;
      const tip = document.createElement("div");
      tip.setAttribute("data-umc-tip", "");
      tip.setAttribute("role", "tooltip");
      tip.textContent = text;
      const s = tip.style;
      s.position = "fixed";
      s.visibility = "hidden";
      s.left = "-9999px";
      s.top = "-9999px";
      s.zIndex = "1001";
      s.padding = "6px 10px";
      s.borderRadius = "8px";
      s.background = "rgba(0, 0, 0, 0.92)";
      s.backdropFilter = "blur(4px)";
      s.boxShadow = "0 12px 24px rgba(0, 0, 0, 0.90)";
      s.color = "white";
      s.fontFamily = "var(--paper-font-body1_-_font-family, inherit)";
      s.fontSize = "12px";
      s.lineHeight = "1.45";
      s.fontWeight = "normal";
      s.letterSpacing = "normal";
      s.textShadow = "none";
      s.pointerEvents = "none";
      s.maxWidth = "min(340px, calc(100vw - 32px))";
      document.body.appendChild(tip);
      const box = tip.getBoundingClientRect();
      const at = umcPopoverPosition(
        anchor.getBoundingClientRect(),
        { width: box.width, height: box.height },
        { width: window.innerWidth, height: window.innerHeight },
      );
      s.left = at.left + "px";
      s.top = at.top + "px";
      s.visibility = "visible";
      this._pillTip.node = tip;
    }, this.config.tooltip_delay);
    window.addEventListener("scroll", hide, true);
    this._pillTip = {
      node: null,
      timer,
      cleanup: () => window.removeEventListener("scroll", hide, true),
    };
  }

  _hidePillTip() {
    const tip = this._pillTip;
    this._pillTip = null;
    this._pillHover = false;
    if (!tip) return;
    clearTimeout(tip.timer);
    tip.cleanup();
    if (tip.node) tip.node.remove();
  }

  _closeBadgePopover() {
    const popover = this._popover;
    this._popover = null;
    this._popoverOpen = false;
    if (!popover) return;
    popover.cleanup();
    popover.panel.remove();
    if (popover.pill.isConnected) {
      popover.pill.setAttribute("aria-expanded", "false");
      popover.pill.style.background = popover.pill.dataset.soft;
    }
  }

  // The showtimes as plain text in the slots of the item (never a blank line).
  _badgesAsText(container, svg, slots) {
    for (const slot of slots) {
      const tspan = svg.querySelector(`[data-umc-badges="${slot.i}"]`);
      if (!tspan) continue;
      tspan.textContent = slot.text;
      tspan.style.fill = "";
      tspan.style.textShadow = "";
    }
  }

  // Back to the transparent "." slots (an item that was given the text while it could not be
  // measured and now can).
  _restoreBadgeSlots(svg, slots) {
    for (const slot of slots) {
      const tspan = svg.querySelector(`[data-umc-badges="${slot.i}"]`);
      if (!tspan) continue;
      tspan.textContent = ".";
      tspan.style.fill = "transparent";
      tspan.style.textShadow = "0 0 transparent";
    }
  }

  // An item that cannot be measured yet: one shared ResizeObserver (created lazily) reports when it
  // gets a size, and a few animation frames are tried too (for when the observer does not fire,
  // e.g. an item moved by the overflow engine). After the limit the plain text is shown meanwhile;
  // the observer still lays the badges out when the item becomes measurable.
  _pendBadges(container) {
    if (!this._badgePending) this._badgePending = new Set();
    this._badgePending.add(container);
    if (!this._badgeObserver && typeof ResizeObserver !== "undefined") {
      this._badgeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          if (entry.contentRect.width > 0 && entry.contentRect.height > 0)
            this._layoutBadges(entry.target);
        }
      });
    }
    if (this._badgeObserver) this._badgeObserver.observe(container);
    // One loop at a time: while it runs, a re-entrant call (a layout that is still not possible)
    // only adds to the pending set, it neither resets the frame count nor arms another frame.
    if (this._badgeLoop) return;
    this._badgeLoop = true;
    this._badgeFrames = 0;
    const tick = () => {
      this._badgeRaf = null;
      if (!this._badgeLoop) return;
      this._badgeFrames++;
      for (const pending of [...this._badgePending])
        this._layoutBadges(pending);
      if (umcShouldRetry(this._badgePending.size, this._badgeFrames)) {
        this._badgeRaf = requestAnimationFrame(tick);
        return;
      }
      this._badgeLoop = false;
      for (const pending of this._badgePending) {
        const svg = pending.querySelector('svg[class*="_svg_"]');
        if (svg && pending._umcBadgeSlots && !pending._umcBadgesFallback) {
          this._badgesAsText(pending, svg, pending._umcBadgeSlots);
          pending._umcBadgesFallback = true;
        }
      }
    };
    if (this._badgeRaf) cancelAnimationFrame(this._badgeRaf);
    this._badgeRaf = requestAnimationFrame(tick);
  }

  _unwatchBadges(container) {
    if (this._badgePending) this._badgePending.delete(container);
    if (this._badgeObserver) this._badgeObserver.unobserve(container);
  }

  _stopBadgeWatch() {
    if (this._badgeRaf) cancelAnimationFrame(this._badgeRaf);
    this._badgeRaf = null;
    this._badgeLoop = false;
    if (this._badgeObserver) this._badgeObserver.disconnect();
    this._badgeObserver = null;
    if (this._badgePending) this._badgePending.clear();
  }

  // Every item of the current render whose badge rows are not placed yet (idempotent).
  _layoutAllBadges() {
    if (!this._badgeItems) return;
    for (const container of this._badgeItems) {
      if (!container.isConnected && container._umcBadgesDone) continue;
      this._layoutBadges(container);
    }
  }

  // Tooltip feature
  // `inZone(x, y)` (optional) tells whether the pointer is where the tooltip may show (the poster
  // and the title); elsewhere, the other tooltips of the item (badges) stay visible.
  addTooltipHandlers(element, summary, inZone = () => true) {
    if (!summary) return;
    element.style.webkitTapHighlightColor = "transparent";
    element.style.webkitUserSelect = "none";
    element.style.userSelect = "none";
    let tooltipTimeoutId;
    let tooltip;
    let removalTimeoutId;
    const removeTooltip = () => {
      if (tooltip) {
        const el = tooltip;
        tooltip = null;
        el.style.opacity = "0";
        const fallbackTimer = setTimeout(() => {
          if (el.parentNode) el.parentNode.removeChild(el);
        }, 600);
        el.addEventListener(
          "transitionend",
          function () {
            clearTimeout(fallbackTimer);
            if (el.parentNode) el.parentNode.removeChild(el);
          },
          { once: true },
        );
      }
    };
    const desiredDistance = 20; // Base distance from the cursor to tooltip
    const calculatePosition = (
      x,
      y,
      rect,
      windowWidth,
      windowHeight,
      isTouch = false,
      scaleFactor = 1,
    ) => {
      const touchMultiplier = 2.5; // 250% increase for touch
      const baseDistance = desiredDistance * scaleFactor;
      const scaledDistance = baseDistance * (isTouch ? touchMultiplier : 1);
      let finalX = x + scaledDistance;
      if (finalX + rect.width > windowWidth) {
        finalX = x - rect.width - scaledDistance;
      }
      let finalY = y - rect.height - scaledDistance;
      if (finalY < 0) {
        finalY = y + scaledDistance;
      }
      if (finalY + rect.height > windowHeight) {
        finalY = windowHeight - rect.height - scaledDistance;
        if (finalY < 0) {
          finalY = 0;
        }
      }
      return { finalX, finalY };
    };
    const showTooltip = (x, y, isTouch = false) => {
      clearTimeout(removalTimeoutId);
      if (tooltipTimeoutId) clearTimeout(tooltipTimeoutId);
      tooltipTimeoutId = setTimeout(
        () => {
          if (tooltip) removeTooltip();
          // Not while a badge popover is open.
          if (this._popoverOpen || this._pillHover) return;
          tooltip = document.createElement("div");
          tooltip.setAttribute("data-umc-tooltip", "");
          tooltip.style.position = "fixed";
          tooltip.style.opacity = "0";
          tooltip.style.transition = "opacity 0.5s";
          tooltip.style.visibility = "hidden";
          let elementWidth = element.offsetWidth;
          let elementHeight = element.offsetHeight;
          const isPoster = element.className.includes("_poster");
          const heightRatio = isPoster ? 102 / 178 : 1;
          let adjustedHeight = elementHeight * heightRatio;
          const scaleFactor = Math.sqrt(elementWidth * adjustedHeight) / 200;
          // Positioning still scales with the item (see calculatePosition), but
          // the text does not: a summary is prose, and prose has one readable
          // size. Upstream derived the font size from the poster's dimensions,
          // which rendered it at ~7px on a 100px-wide poster.
          tooltip.style.padding = "12px 14px";
          tooltip.style.zIndex = "1000";
          tooltip.style.whiteSpace = "pre-wrap";
          // The overlay is appended to document.body, but the card's own text
          // rules (title_size/line_size, weights, letter-spacing) still reach it
          // through inheritance from :root in some themes. Reset them here so a
          // card configured with, say, a bold condensed line style does not
          // silently restyle its summaries - the other tooltips above already
          // pin fontWeight for the same reason.
          tooltip.style.fontFamily =
            "var(--paper-font-body1_-_font-family, inherit)";
          tooltip.style.fontWeight = "normal";
          tooltip.style.letterSpacing = "normal";
          tooltip.style.textShadow = "none";
          tooltip.style.background = "rgba(0, 0, 0, 0.50)";
          tooltip.style.boxShadow = "0 12px 24px rgba(0, 0, 0, 0.90)";
          tooltip.style.color = "white";
          tooltip.style.backdropFilter = "blur(4px)";
          const tooltipText = document.createElement("div");
          tooltipText.textContent = summary;
          tooltip.appendChild(tooltipText);
          tooltip.style.left = `-9999px`;
          tooltip.style.top = `-9999px`;
          document.body.appendChild(tooltip);
          requestAnimationFrame(() => {
            // Fixed rather than derived from the thumbnail: an overlay is read at
            // reading distance whatever the item it came from. Upstream computed
            // `14 * scaleFactor`, which rendered at ~7px on a 100px-wide poster.
            // Not a theme variable either - a summary is secondary text, and this
            // stays 12px whatever body size the dashboard is set to. Width is
            // clamped so a narrow phone still fits the bubble on screen.
            tooltip.style.fontSize = "12px";
            tooltip.style.lineHeight = "1.45";
            tooltip.style.maxWidth = "min(340px, calc(100vw - 32px))";
            tooltip.style.minWidth = "min(240px, calc(100vw - 32px))";
            tooltip.style.borderRadius = "8px";
            requestAnimationFrame(() => {
              const rect = tooltip.getBoundingClientRect();
              const windowWidth = window.innerWidth;
              const windowHeight = window.innerHeight;
              let { finalX, finalY } = calculatePosition(
                x,
                y,
                rect,
                windowWidth,
                windowHeight,
                isTouch,
                scaleFactor,
              );
              tooltip.style.left = `${Math.max(0, Math.min(finalX, windowWidth - rect.width))}px`;
              tooltip.style.top = `${Math.max(0, Math.min(finalY, windowHeight - rect.height))}px`;
              setTimeout(() => {
                tooltip.style.visibility = "visible";
                tooltip.style.opacity = "1";
              }, 50);
            });
          });
        },
        isTouch
          ? this.config.tooltip_delay
          : Math.round(this.config.tooltip_delay * 1.5),
      );
    };
    const hideTooltip = () => {
      if (tooltipTimeoutId) clearTimeout(tooltipTimeoutId);
      if (tooltip) removalTimeoutId = setTimeout(removeTooltip, 300);
    };
    const handleMouseMove = (e) =>
      inZone(e.clientX, e.clientY)
        ? showTooltip(e.clientX, e.clientY)
        : hideTooltip();
    const listeners = {
      mouseenter: (e) => {
        if (listeners._touchActive) return;
        handleMouseMove(e);
        element.addEventListener("mousemove", handleMouseMove);
      },
      mouseleave: () => {
        if (listeners._touchActive) return;
        if (tooltipTimeoutId) clearTimeout(tooltipTimeoutId);
        removalTimeoutId = setTimeout(removeTooltip, 300);
        element.removeEventListener("mousemove", handleMouseMove);
      },
      touchstart: (e) => {
        listeners._touchActive = true;
        listeners._touchX = e.touches[0].pageX;
        listeners._touchY = e.touches[0].pageY;
        listeners._touchCancelled = false;
        if (inZone(e.touches[0].clientX, e.touches[0].clientY))
          showTooltip(e.touches[0].clientX, e.touches[0].clientY, true);
      },
      touchmove: (e) => {
        if (listeners._touchCancelled) return;
        const dx = e.touches[0].pageX - listeners._touchX;
        const dy = e.touches[0].pageY - listeners._touchY;
        if (Math.abs(dx) > 10 || Math.abs(dy) > 10) {
          listeners._touchCancelled = true;
          if (tooltipTimeoutId) clearTimeout(tooltipTimeoutId);
          removeTooltip();
        }
      },
      touchend: () => {
        setTimeout(() => {
          listeners._touchActive = false;
        }, 400);
        if (tooltipTimeoutId) clearTimeout(tooltipTimeoutId);
        removalTimeoutId = setTimeout(removeTooltip, 300);
      },
    };
    const cleanup = () => {
      clearTimeout(tooltipTimeoutId);
      clearTimeout(removalTimeoutId);
      if (tooltip) {
        if (tooltip.parentNode) tooltip.parentNode.removeChild(tooltip);
        tooltip = null;
      }
    };
    element.addEventListener("mouseenter", listeners.mouseenter);
    element.addEventListener("mouseleave", listeners.mouseleave);
    element.addEventListener("touchstart", listeners.touchstart, {
      passive: true,
    });
    element.addEventListener("touchmove", listeners.touchmove, {
      passive: true,
    });
    element.addEventListener("touchend", listeners.touchend);
    this.tooltipListeners.set(element, { ...listeners, cleanup });
  }

  _applyOverflow() {
    clearTimeout(this._overflowResizeTimer);
    clearTimeout(this._overflowImageTimer);
    if (this._overflowInitRAF) {
      cancelAnimationFrame(this._overflowInitRAF);
      this._overflowInitRAF = null;
    }
    if (this._deferredTrimRAF2) {
      cancelAnimationFrame(this._deferredTrimRAF2);
      this._deferredTrimRAF2 = null;
    }
    if (this._deferredTrimRAF1) {
      cancelAnimationFrame(this._deferredTrimRAF1);
      this._deferredTrimRAF1 = null;
    }

    const gap = 16;
    const haCard = this.querySelector("ha-card");
    if (haCard) haCard.style.overflow = "visible";

    const recalculate = (fromRecovery) => {
      if (!fromRecovery) {
        this._overflowRecoveryCount = 0;
      }

      this._recalcInProgress = true;

      if (!this._opacityLocked) {
        this._opacityLocked = true;
        this.style.transition = "none";
        this.style.opacity = "0";
      }

      const unlockAndReveal = () => {
        this._recalcInProgress = false;
        this._opacityLocked = false;
        this.style.opacity = "";
        this.style.transition = "";
        this.content.style.visibility = "";
        if (this._recalcPending) {
          this._recalcPending = false;
          clearTimeout(this._overflowResizeTimer);
          this._overflowResizeTimer = setTimeout(recalculate, 60);
        }
      };

      if (this._deferredTrimRAF2) {
        cancelAnimationFrame(this._deferredTrimRAF2);
        this._deferredTrimRAF2 = null;
      }
      if (this._deferredTrimRAF1) {
        cancelAnimationFrame(this._deferredTrimRAF1);
        this._deferredTrimRAF1 = null;
      }

      this.content.querySelectorAll(".umc-overflow-col").forEach((col) => {
        Array.from(col.children).forEach((child) => {
          if (child._umcOverflowHidden) {
            child.style.display = "";
            delete child._umcOverflowHidden;
          }
          if (child._umcOriginalMarginTop !== undefined) {
            child.style.marginTop = child._umcOriginalMarginTop;
            delete child._umcOriginalMarginTop;
          }
          const inner = child.firstElementChild;
          if (inner && inner._umcOriginalMarginTop !== undefined) {
            inner.style.marginTop = inner._umcOriginalMarginTop;
            delete inner._umcOriginalMarginTop;
          }
          this.content.insertBefore(child, col);
        });
        col.remove();
      });
      this.content.style.display = "";
      this.content.style.gap = "";
      this.content.style.height = "";
      this.content.style.overflowY = "";
      this.content.style.alignItems = "";
      this.content.style.justifyContent = "";
      if (haCard) {
        haCard.style.maxWidth = "";
        haCard.style.marginLeft = "";
        haCard.style.marginRight = "";
      }

      const items = Array.from(this.content.children);
      if (items.length === 0) {
        unlockAndReveal();
        return "empty";
      }
      const growWithContent = this.config.overflow_fit === "content";
      const firstH = items[0].offsetHeight;
      if (firstH < 10 || this.offsetWidth < 50) {
        if (!growWithContent) {
          this.content.style.height =
            Math.max(200, window.innerHeight - 120) + "px";
          this.content.style.overflowY = "hidden";
        }
        return "no-dimensions";
      }

      let visibleBottom = window.innerHeight;
      const _ancestorLog = [];
      let ancestor = this;
      while (ancestor) {
        if (ancestor !== this) {
          try {
            const cs = getComputedStyle(ancestor);
            const oy = cs.overflowY || cs.overflow;
            const aRect = ancestor.getBoundingClientRect();
            const hasOverflowClip = oy === "hidden";
            const hasExplicitHeight =
              cs.height && cs.height !== "auto" && cs.height !== "";
            const hasMaxHeight =
              cs.maxHeight && cs.maxHeight !== "none" && cs.maxHeight !== "";
            const gridRows = cs.gridTemplateRows || cs.gridAutoRows;
            const isGridConstrained =
              gridRows && gridRows !== "none" && gridRows !== "auto";
            const isBounded =
              hasOverflowClip ||
              hasExplicitHeight ||
              hasMaxHeight ||
              isGridConstrained;
            if (isBounded && aRect.bottom < visibleBottom - 1) {
              _ancestorLog.push({
                tag: ancestor.tagName,
                id: ancestor.id,
                cls: (ancestor.className || "").toString().slice(0, 40),
                overflow: oy,
                height: cs.height,
                maxH: cs.maxHeight,
                gridRows: gridRows || "",
                bottom: Math.round(aRect.bottom),
              });
              visibleBottom = Math.min(visibleBottom, aRect.bottom);
            }
          } catch (e) {
            /* skip inaccessible elements */
          }
        }
        if (ancestor.parentElement) {
          ancestor = ancestor.parentElement;
        } else if (ancestor.getRootNode() instanceof ShadowRoot) {
          ancestor = ancestor.getRootNode().host;
        } else {
          break;
        }
      }

      const contentRect = this.content.getBoundingClientRect();
      const contentCS = getComputedStyle(this.content);
      const contentPadTop = parseFloat(contentCS.paddingTop) || 0;
      const contentPadBottom = parseFloat(contentCS.paddingBottom) || 0;
      const bottomSafetyMargin = 8;
      const availableHeight =
        visibleBottom -
        contentRect.top -
        contentPadTop -
        contentPadBottom -
        bottomSafetyMargin;

      if (availableHeight < 100 && !growWithContent) {
        this.content.style.height =
          Math.max(200, window.innerHeight - 120) + "px";
        this.content.style.overflowY = "hidden";
        return "no-height";
      }

      const containerWidth = this.content.offsetWidth;
      const baseMaxColWidth = this._overflowReducedColWidth
        ? this._overflowReducedColWidth
        : fromRecovery && this._overflowProvenColWidth
          ? this._overflowProvenColWidth
          : 500;
      // Content mode shares the available width between the columns instead of
      // capping each one at 500px, so the card keeps filling its container.
      let maxColWidth = growWithContent
        ? containerWidth
        : Math.min(containerWidth, baseMaxColWidth);
      const originalMaxColWidth = maxColWidth;
      const isWidthUnconstrained = containerWidth > maxColWidth;

      if (!fromRecovery) {
        const dimsChanged =
          this._overflowProvenAvailH == null ||
          Math.abs(availableHeight - this._overflowProvenAvailH) > 10 ||
          Math.abs(containerWidth - (this._overflowProvenWidth || 0)) > 10 ||
          Math.abs(
            maxColWidth - (this._overflowProvenColWidth || maxColWidth),
          ) > 10;
        if (dimsChanged) {
          this._overflowMinCols = 0;
          this._overflowReducedColWidth = null;
          this._overflowProvenCapacity = null;
          this._overflowProvenAvailH = null;
          this._overflowProvenWidth = null;
          this._overflowProvenColWidth = null;
        } else {
        }
      }

      let itemGap = 0;
      if (items.length > 1) {
        itemGap =
          items[1].offsetTop - (items[0].offsetTop + items[0].offsetHeight);
      }
      if (itemGap < 0) itemGap = 0;
      if (!isWidthUnconstrained && !growWithContent) {
        let totalFlatHeight = 0;
        items.forEach((item, i) => {
          totalFlatHeight += item.offsetHeight + (i > 0 ? itemGap : 0);
        });
        if (totalFlatHeight <= availableHeight) {
          unlockAndReveal();
          return "fits";
        }
      }

      const applyPartition = (partition) => {
        this.content.querySelectorAll(".umc-overflow-col").forEach((col) => {
          Array.from(col.children).forEach((child) => {
            if (child._umcOverflowHidden) {
              child.style.display = "";
              delete child._umcOverflowHidden;
            }
            if (child._umcOriginalMarginTop !== undefined) {
              child.style.marginTop = child._umcOriginalMarginTop;
              delete child._umcOriginalMarginTop;
            }
            const inner = child.firstElementChild;
            if (inner && inner._umcOriginalMarginTop !== undefined) {
              inner.style.marginTop = inner._umcOriginalMarginTop;
              delete inner._umcOriginalMarginTop;
            }
            this.content.insertBefore(child, col);
          });
          col.remove();
        });

        this.content.style.display = "flex";
        this.content.style.alignItems = "flex-start";
        this.content.style.justifyContent = "center";
        this.content.style.gap = partition.length > 1 ? gap + "px" : "0px";
        if (growWithContent) {
          // Height follows the tallest column instead of the viewport, so no item
          // ever falls below a clip line and gets trimmed away.
          this.content.style.height = "";
          this.content.style.overflowY = "";
        } else {
          this.content.style.height = availableHeight + "px";
          this.content.style.overflowY = "hidden";
        }

        partition.forEach((colIndices, colIndex) => {
          const colDiv = document.createElement("div");
          colDiv.className = "umc-overflow-col";
          colDiv.style.cssText =
            "flex:1 1 0;min-width:0;max-width:" +
            maxColWidth +
            "px;overflow:visible";
          colIndices.forEach((idx, posInCol) => {
            const item = items[idx];
            if (posInCol === 0) {
              item._umcOriginalMarginTop = item.style.marginTop;
              item.style.marginTop = "0px";
              const inner = item.firstElementChild;
              if (inner) {
                inner._umcOriginalMarginTop = inner.style.marginTop;
                inner.style.marginTop = "0px";
              }
            }
            colDiv.appendChild(item);
          });
          this.content.appendChild(colDiv);
        });

        const numCols = partition.length;
        const contentPadX = 20;
        const totalGaps = numCols > 1 ? (numCols - 1) * gap : 0;
        const cardMaxWidth = numCols * maxColWidth + totalGaps + contentPadX;
        if (haCard) {
          // In content mode the card is meant to fill whatever space it is
          // given, so cap it in percentage terms instead of pinning a pixel
          // width that would leave a gap on wider screens.
          haCard.style.maxWidth = growWithContent
            ? "100%"
            : cardMaxWidth + "px";
          haCard.style.marginLeft = "auto";
          haCard.style.marginRight = "auto";
        }
      };

      const buildPackedPartition = (total, cols, perCol) => {
        const partition = [];
        let idx = 0;
        for (let c = 0; c < cols; c++) {
          const size =
            c < cols - 1 ? Math.min(perCol, total - idx) : total - idx;
          const indices = [];
          for (let i = 0; i < size; i++) indices.push(idx++);
          if (indices.length > 0) partition.push(indices);
        }
        return partition;
      };

      const measureCapacity = (targetCols) => {
        if (targetCols <= 1) {
          applyPartition([items.map((_, i) => i)]);
        } else {
          const measurePartition = [];
          const firstColCount = items.length - (targetCols - 1);
          let idx = 0;
          measurePartition.push(
            Array.from({ length: firstColCount }, () => idx++),
          );
          for (let c = 1; c < targetCols; c++) {
            measurePartition.push([idx++]);
          }
          applyPartition(measurePartition);
        }
        void this.content.offsetHeight;

        const cBCR = this.content.getBoundingClientRect();
        const cPadBot =
          parseFloat(getComputedStyle(this.content).paddingBottom) || 0;
        const clipBottom = Math.min(cBCR.bottom - cPadBot, window.innerHeight);

        const firstCol = this.content.querySelector(".umc-overflow-col");
        if (!firstCol) return 1;
        const children = Array.from(firstCol.children);
        const safeClip = clipBottom - 2;
        let capacity = 0;
        for (let i = 0; i < children.length; i++) {
          if (children[i].getBoundingClientRect().bottom <= safeClip) {
            capacity++;
          } else break;
        }
        const provenCap = this._overflowProvenCapacity;
        const provenStale =
          !provenCap ||
          Math.abs(availableHeight - (this._overflowProvenAvailH || 0)) > 10 ||
          Math.abs(containerWidth - (this._overflowProvenWidth || 0)) > 10 ||
          Math.abs(
            maxColWidth - (this._overflowProvenColWidth || maxColWidth),
          ) > 10;
        if (!provenStale && capacity > provenCap) {
          capacity = provenCap;
        }
        return Math.max(capacity, 1);
      };

      const trimOverflow = (label) => {
        const cBCR = this.content.getBoundingClientRect();
        const cPadBot =
          parseFloat(getComputedStyle(this.content).paddingBottom) || 0;
        const clipBottom = Math.min(cBCR.bottom - cPadBot, window.innerHeight);
        const tolerantClip = clipBottom + 2;
        const trimLog = [];
        this.content
          .querySelectorAll(".umc-overflow-col")
          .forEach((col, ci) => {
            const children = Array.from(col.children);
            let hiding = false;
            for (let i = 0; i < children.length; i++) {
              if (children[i]._umcOverflowHidden) continue;
              const itemBot = children[i].getBoundingClientRect().bottom;
              if (hiding || itemBot > tolerantClip) {
                hiding = true;
                trimLog.push({
                  col: ci,
                  item: i,
                  bottom: Math.round(itemBot),
                  clip: Math.round(clipBottom),
                  tolerantClip: Math.round(tolerantClip),
                });
                children[i].style.display = "none";
                children[i]._umcOverflowHidden = true;
              }
            }
          });
        if (trimLog.length > 0) {
        } else {
        }
        return trimLog.length;
      };

      const tightenHeight = () => {
        const tCols = this.content.querySelectorAll(".umc-overflow-col");
        if (tCols.length === 0) return;
        let tallestH = 0;
        tCols.forEach((c) => {
          const kids = Array.from(c.children).filter(
            (k) => !k._umcOverflowHidden,
          );
          if (kids.length === 0) return;
          const last = kids[kids.length - 1];
          const colTop = c.getBoundingClientRect().top;
          const lastBot = last.getBoundingClientRect().bottom;
          tallestH = Math.max(tallestH, lastBot - colTop);
        });
        if (tallestH <= 0) return;
        const physicalMax =
          visibleBottom - contentRect.top - contentPadTop - contentPadBottom;
        const maxHeight = Math.min(availableHeight + 8, physicalMax);
        const newHeight = Math.min(tallestH, maxHeight);
        if (Math.abs(newHeight - availableHeight) > 0.5) {
          this.content.style.height = newHeight + "px";
        }
      };

      const maxPossibleCols = Math.min(
        items.length,
        6,
        this.config.max_columns || 6,
      );
      const effectiveMinCols = this._overflowMinCols || 0;
      const startCols = Math.max(1, effectiveMinCols);

      // START: content-fit layout (overflow_fit: content)
      // The column count is driven by max_columns and the available width only.
      // Every item is laid out; the card grows vertically instead of trimming.
      if (growWithContent) {
        const minColWidth = 250;
        const widthCap = Math.max(
          1,
          Math.floor((containerWidth + gap) / (minColWidth + gap)),
        );
        const cols = Math.min(maxPossibleCols, widthCap);
        const perCol = Math.ceil(items.length / cols);
        applyPartition(buildPackedPartition(items.length, cols, perCol));
        void this.content.offsetHeight;
        unlockAndReveal();
        this._overflowPending = false;
        return "applied";
      }
      // END: content-fit layout

      const scheduleDeferredTrim = () => {
        let prevColHeight = -1;
        let stableCount = 0;
        let attempts = 0;
        const maxAttempts = 20; // ~320ms at 60fps
        const neededStable = 2; // require 2 consecutive stable reads
        const pollUntilStable = () => {
          this._deferredTrimRAF1 = requestAnimationFrame(() => {
            this._deferredTrimRAF1 = null;
            this._deferredTrimRAF2 = requestAnimationFrame(() => {
              this._deferredTrimRAF2 = null;
              attempts++;
              const firstCol = this.content.querySelector(".umc-overflow-col");
              const curHeight = firstCol ? firstCol.scrollHeight : 0;
              if (curHeight === prevColHeight) {
                stableCount++;
              } else {
                stableCount = 0;
                prevColHeight = curHeight;
              }
              trimOverflow("deferred-rAF-" + attempts);
              if (stableCount < neededStable && attempts < maxAttempts) {
                pollUntilStable();
                return;
              }
              const cols = this.content.querySelectorAll(".umc-overflow-col");
              let maxVisible = 0;
              let totalHiddenDeferred = 0;
              const colInfo = Array.from(cols).map((c, i) => {
                const kids = Array.from(c.children);
                const visible = kids.filter((k) => !k._umcOverflowHidden);
                const lastVis =
                  visible.length > 0 ? visible[visible.length - 1] : null;
                if (visible.length > maxVisible) maxVisible = visible.length;
                totalHiddenDeferred += kids.filter(
                  (k) => k._umcOverflowHidden,
                ).length;
                return {
                  col: i,
                  total: kids.length,
                  visible: visible.length,
                  lastVisBot: lastVis
                    ? Math.round(lastVis.getBoundingClientRect().bottom)
                    : "none",
                };
              });
              if (maxVisible > 0) {
                this._overflowProvenCapacity = maxVisible;
                this._overflowProvenAvailH = availableHeight;
                this._overflowProvenWidth = containerWidth;
                this._overflowProvenColWidth = maxColWidth;
              }

              if (
                totalHiddenDeferred > 0 &&
                this._overflowRecoveryCount < maxPossibleCols + 5
              ) {
                this._overflowRecoveryCount++;

                const currentColCount = cols.length;
                const neededPerCol = Math.ceil(items.length / currentColCount);

                const minNarrowWidth = 250;
                if (
                  maxVisible > 0 &&
                  maxVisible < neededPerCol &&
                  totalHiddenDeferred <= 3
                ) {
                  const firstCol =
                    this.content.querySelector(".umc-overflow-col");
                  const actualColWidth = firstCol
                    ? firstCol.offsetWidth
                    : maxColWidth;
                  const heightRatio = maxVisible / neededPerCol;
                  const targetColWidth = Math.round(
                    actualColWidth * heightRatio * 0.95,
                  );

                  if (
                    targetColWidth >= minNarrowWidth &&
                    targetColWidth < actualColWidth - 10
                  ) {
                    this._overflowReducedColWidth = targetColWidth;
                    this._overflowProvenCapacity = null;
                    recalculate(true);
                    return;
                  }
                }

                this._overflowReducedColWidth = null;
                if (
                  !this._overflowMinCols ||
                  currentColCount >= this._overflowMinCols
                ) {
                  this._overflowMinCols = currentColCount + 1;
                }
                this._overflowProvenCapacity = null;
                recalculate(true);
                return;
              }

              tightenHeight();
              unlockAndReveal();
            });
          });
        };
        pollUntilStable();
      };

      for (
        let targetCols = startCols;
        targetCols <= maxPossibleCols;
        targetCols++
      ) {
        const perCol = Math.ceil(items.length / targetCols);

        const capacity = measureCapacity(targetCols);
        if (capacity < perCol) {
          continue;
        }

        const packed = buildPackedPartition(items.length, targetCols, perCol);
        applyPartition(packed);
        void this.content.offsetHeight;

        const syncTrimmed = trimOverflow("sync");

        if (syncTrimmed > 0) {
          continue;
        }

        const cols = this.content.querySelectorAll(".umc-overflow-col");
        const colInfo = Array.from(cols).map((c, i) => {
          const kids = Array.from(c.children);
          const visible = kids.filter((k) => !k._umcOverflowHidden);
          const lastVis =
            visible.length > 0 ? visible[visible.length - 1] : null;
          return {
            col: i,
            total: kids.length,
            visible: visible.length,
            lastVisBot: lastVis
              ? Math.round(lastVis.getBoundingClientRect().bottom)
              : "none",
          };
        });

        scheduleDeferredTrim();
        this._overflowPending = false;
        return "applied";
      }

      const minColWidth = 300;
      if (isWidthUnconstrained && originalMaxColWidth > minColWidth) {
        for (
          let targetCols = startCols;
          targetCols <= maxPossibleCols;
          targetCols++
        ) {
          const perCol = Math.ceil(items.length / targetCols);
          for (
            let tryWidth = originalMaxColWidth - 50;
            tryWidth >= minColWidth;
            tryWidth -= 50
          ) {
            maxColWidth = tryWidth;
            const capacity = measureCapacity(targetCols);
            if (capacity < perCol) {
              continue;
            }
            const packed = buildPackedPartition(
              items.length,
              targetCols,
              perCol,
            );
            applyPartition(packed);
            void this.content.offsetHeight;
            const syncTrimmed = trimOverflow("sync-narrowed");

            if (syncTrimmed > 0) {
              continue;
            }

            const cols = this.content.querySelectorAll(".umc-overflow-col");
            const colInfo = Array.from(cols).map((c, i) => {
              const kids = Array.from(c.children);
              const visible = kids.filter((k) => !k._umcOverflowHidden);
              const lastVis =
                visible.length > 0 ? visible[visible.length - 1] : null;
              return {
                col: i,
                total: kids.length,
                visible: visible.length,
                lastVisBot: lastVis
                  ? Math.round(lastVis.getBoundingClientRect().bottom)
                  : "none",
              };
            });
            scheduleDeferredTrim();
            this._overflowPending = false;
            return "applied";
          }
        }
        maxColWidth = originalMaxColWidth;
      }

      const finalPerCol = Math.ceil(items.length / maxPossibleCols);
      const finalPacked = buildPackedPartition(
        items.length,
        maxPossibleCols,
        finalPerCol,
      );
      applyPartition(finalPacked);
      void this.content.offsetHeight;
      trimOverflow("sync-fallback");
      const fallbackCols = this.content.querySelectorAll(".umc-overflow-col");
      let fallbackVisible = 0;
      fallbackCols.forEach((c) => {
        fallbackVisible += Array.from(c.children).filter(
          (k) => !k._umcOverflowHidden,
        ).length;
      });
      scheduleDeferredTrim();
      this._overflowPending = false;
      return "applied";
    };

    let attempts = 0;
    const tryRecalculate = () => {
      this._overflowInitRAF = null;
      attempts++;
      const result = recalculate();
      if (
        (result === "no-dimensions" || result === "no-height") &&
        attempts < 300
      ) {
        this._overflowInitRAF = requestAnimationFrame(tryRecalculate);
      } else if (result === "no-dimensions" || result === "no-height") {
        this._overflowPending = true;
        this._recalcInProgress = false;
        this._opacityLocked = false;
        this.style.opacity = "";
        this.style.transition = "";
        this.content.style.visibility = "";
      }
    };
    this._overflowInitRAF = requestAnimationFrame(() => {
      this._overflowInitRAF = requestAnimationFrame(tryRecalculate);
    });

    const unloaded = Array.from(this.content.querySelectorAll("img")).filter(
      (img) => !img.complete,
    );
    if (unloaded.length > 0) {
      let pending = unloaded.length;
      let done = false;
      const onReady = () => {
        if (done) return;
        if (--pending <= 0) {
          done = true;
          if (this._recalcInProgress) {
            this._recalcPending = true;
            return;
          }
          recalculate();
        }
      };
      unloaded.forEach((img) => {
        img.addEventListener("load", onReady, { once: true });
        img.addEventListener("error", onReady, { once: true });
      });
      this._overflowImageTimer = setTimeout(() => {
        if (!done) {
          done = true;
          if (this._recalcInProgress) {
            this._recalcPending = true;
            return;
          }
          recalculate();
        }
      }, 3000);
    }

    if (this._overflowResizeHandler)
      window.removeEventListener("resize", this._overflowResizeHandler);
    this._overflowResizeHandler = () => {
      if (this._recalcInProgress) {
        this._recalcPending = true;
        return;
      }
      clearTimeout(this._overflowResizeTimer);
      this._overflowResizeTimer = setTimeout(recalculate, 60);
    };
    window.addEventListener("resize", this._overflowResizeHandler);

    if (this._overflowObserver) this._overflowObserver.disconnect();
    this._overflowLastWidth = null;
    this._overflowLastObsHeight = null;
    this._overflowObserver = new ResizeObserver((entries) => {
      const w = entries[0].contentRect.width;
      const h = entries[0].contentRect.height;
      const widthChanged =
        this._overflowLastWidth !== null && this._overflowLastWidth !== w;
      const heightChanged =
        this._overflowLastObsHeight !== null &&
        Math.abs(this._overflowLastObsHeight - h) > 10;
      this._overflowLastWidth = w;
      this._overflowLastObsHeight = h;
      if (!widthChanged && !heightChanged) return;
      if (this._recalcInProgress) {
        this._recalcPending = true;
        return;
      }
      clearTimeout(this._overflowResizeTimer);
      this._overflowResizeTimer = setTimeout(recalculate, 60);
    });
    // Observe the parent, not the card: applyPartition pins a pixel max-width
    // on ha-card, so once it is set the card itself stops widening and its
    // contentRect freezes - the observer would never fire again and the layout
    // would stay stuck at whatever width it was first measured at.
    this._overflowObserver.observe(this.parentElement || this);

    // Detect card becoming visible after section visibility toggle (GitHub #117)
    if (this._overflowIntersectionObs)
      this._overflowIntersectionObs.disconnect();
    this._overflowIntersectionObs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && this._overflowPending) {
          if (this._recalcInProgress) {
            this._recalcPending = true;
            return;
          }
          clearTimeout(this._overflowResizeTimer);
          this._overflowResizeTimer = setTimeout(recalculate, 100);
        }
      },
      { threshold: 0.01 },
    );
    this._overflowIntersectionObs.observe(this);
  }

  _clearOverflow() {
    clearTimeout(this._overflowResizeTimer);
    clearTimeout(this._overflowImageTimer);
    if (this._overflowInitRAF) {
      cancelAnimationFrame(this._overflowInitRAF);
      this._overflowInitRAF = null;
    }
    if (this._deferredTrimRAF2) {
      cancelAnimationFrame(this._deferredTrimRAF2);
      this._deferredTrimRAF2 = null;
    }
    if (this._deferredTrimRAF1) {
      cancelAnimationFrame(this._deferredTrimRAF1);
      this._deferredTrimRAF1 = null;
    }
    this._overflowProvenCapacity = null;
    this._overflowProvenAvailH = null;
    this._overflowProvenWidth = null;
    this._overflowProvenColWidth = null;
    this._overflowRecoveryCount = 0;
    this._overflowMinCols = 0;
    this._overflowReducedColWidth = null;
    this._recalcInProgress = false;
    this._recalcPending = false;
    this._opacityLocked = false;
    this._overflowPending = false;
    this.style.opacity = "";
    this.style.transition = "";
    const haCard = this.querySelector("ha-card");
    if (haCard) haCard.style.overflow = "";
    if (haCard) {
      haCard.style.maxWidth = "";
      haCard.style.marginLeft = "";
      haCard.style.marginRight = "";
    }
    this.content.style.display = "";
    this.content.style.gap = "";
    this.content.style.height = "";
    this.content.style.overflowY = "";
    this.content.style.alignItems = "";
    this.content.style.justifyContent = "";
    if (this._overflowObserver) {
      this._overflowObserver.disconnect();
      this._overflowObserver = null;
    }
    if (this._overflowResizeHandler) {
      window.removeEventListener("resize", this._overflowResizeHandler);
      this._overflowResizeHandler = null;
    }
    if (this._overflowIntersectionObs) {
      this._overflowIntersectionObs.disconnect();
      this._overflowIntersectionObs = null;
    }
  }

  setConfig(config) {
    if (!config.device_id && !config.entity) {
      throw new Error(
        "Define a cinema (device_id), or one of its sensors (entity).",
      );
    }
    this.config = { ...config };
    this.url = config.url;
    this.collapse = config.collapse || Infinity;
    this.config.enable_tooltips =
      config.enable_tooltips !== undefined ? config.enable_tooltips : false;
    this.config.tooltip_text =
      typeof config.tooltip_text === "string" && config.tooltip_text.trim()
        ? config.tooltip_text
        : "$synopsis";
    this.config.entry_point =
      typeof config.entry_point === "string" && config.entry_point.trim()
        ? config.entry_point.trim()
        : UMC_ENTRY_POINT;
    this._itemsState = null;
    this.config.tooltip_delay =
      config.tooltip_delay !== undefined && config.tooltip_delay !== null
        ? Math.max(150, config.tooltip_delay)
        : 500;
    this.config.enable_trailers =
      config.enable_trailers !== undefined ? config.enable_trailers : true;
    this.config.disable_hyperlinks =
      config.disable_hyperlinks !== undefined
        ? config.disable_hyperlinks
        : false;
    this.config.corner_radius =
      config.corner_radius !== undefined ? config.corner_radius : 12;
    this.config.overflow =
      config.overflow !== undefined ? config.overflow : false;
    const _mc =
      config.max_columns !== undefined ? parseInt(config.max_columns, 10) : NaN;
    this.config.max_columns = !isNaN(_mc)
      ? Math.max(0, Math.min(6, _mc))
      : undefined;
    // 'content' lays items out in up to max_columns columns and lets the card
    // grow as tall as it needs; 'viewport' (default) keeps the original
    // behaviour of fitting - and trimming to - the visible viewport height.
    this.config.overflow_fit =
      config.overflow_fit === "content" ? "content" : "viewport";
    this.config.enable_search =
      config.enable_search !== undefined ? config.enable_search : false;
    this.config.enable_days =
      config.enable_days !== undefined ? config.enable_days : true;
  }

  getCardSize() {
    let view = this.config.image_style || "poster";
    return view == "poster" ? this.cardSize * 5 : this.cardSize * 3;
  }

  getGridOptions() {
    const overflowActive = this.config && this.config.overflow;
    if (overflowActive) {
      return {
        columns: "full",
        rows: "auto",
        min_columns: 6,
        min_rows: 3,
      };
    }
    const view = this.config.image_style || "poster";
    const itemCount = this.cardSize || 5;
    const itemHeight = view === "poster" ? 180 : 100;
    const estimatedHeight = itemCount * itemHeight;
    const rowUnit = 64;
    const estimatedRows = Math.max(2, Math.ceil(estimatedHeight / rowUnit));
    return {
      columns: 12,
      min_columns: 6,
      rows: estimatedRows,
      min_rows: 2,
    };
  }

  static getStubConfig(hass) {
    const sensor = Object.values(hass.entities || {}).find(
      (entry) => entry.platform === UMC_PLATFORM,
    );
    return sensor ? { device_id: sensor.device_id } : {};
  }

  static getConfigElement() {
    return document.createElement("movie-showtimes-card-editor");
  }
}
if (customElements.get("movie-showtimes-card"))
  console.warn(
    "movie-showtimes-card already defined; skipping duplicate registration",
  );
else customElements.define("movie-showtimes-card", MovieShowtimesCard);
console.info(
  "%c " + umcBanner(CARD_VERSION, CARD_BUILD, import.meta.url) + " ",
  "color: white; background: #03a9f4; font-weight: 700;",
);

// Configure the preview in the Lovelace card picker
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "movie-showtimes-card")) {
  window.customCards.push({
    type: "movie-showtimes-card",
    name: "Movie Showtimes Card",
    preview: true,
    description:
      "The films showing today at one of your cinemas (Movie Showtimes integration).",
    documentationURL: "https://github.com/bastgau/ha-movie-showtimes",
  });
}

export {
  UMC_DAY_KEYS,
  dayChips,
  dayLabel,
  dayLineSplit,
  parseLocalDate,
  resolveSelection,
  filmKeys,
  filmTokenNames,
  filmsToItems,
  matchesSearch,
  resolveDayEntity,
  resolveDaySensors,
  resolveText,
  umcTooltipText,
  umcShowtimeBadges,
  umcShowtimesText,
  umcBadgeSegments,
  umcBadgeFallbackText,
  umcBadgeItems,
  umcRatingBadge,
  umcTooltipZone,
  umcLineIsIgnored,
  umcBadgeRowExtra,
  umcCertificateBadge,
  umcShowtimeGroups,
  umcAccessibilityFlags,
  umcAccessibilityLegend,
  umcGroupHeader,
  umcPopoverPosition,
  umcIsBadgeLine,
  UMC_KEYWORDS,
  umcClean,
  sensorProblem,
  umcEditorSchema,
  umcLineShown,
  umcShouldRetry,
  umcSortValue,
  umcSortItems,
  umcFilmValues,
  umcRuntimeText,
  umcTokenHelp,
  umcBanner,
  CARD_BUILD,
  CARD_VERSION,
};
