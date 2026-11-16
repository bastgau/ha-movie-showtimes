// Unit tests of the pure pieces added to the reference card. Run: node --test tests/card/card.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// The module registers custom elements on load: give it just enough of a browser.
globalThis.HTMLElement = class {
  constructor() {
    this.events = [];
  }
  appendChild() {}
  dispatchEvent(event) {
    this.events.push(event);
  }
};
const defined = {};
globalThis.customElements = {
  get: () => undefined,
  define: (name, constructor) => {
    defined[name] = constructor;
  },
};
globalThis.window = {};
globalThis.document = {};

const card = await import(
  "../../custom_components/movie_showtimes/frontend/movie-showtimes-card.js"
);
const films = JSON.parse(
  readFileSync(
    new URL("./fixtures/films_real_examples.json", import.meta.url),
    "utf8",
  ),
);

const entry = (
  entity_id,
  device_id,
  translation_key,
  platform = "movie_showtimes",
) => ({
  entity_id,
  device_id,
  platform,
  translation_key,
});
const hass = {
  entities: {
    "sensor.a_today": entry("sensor.a_today", "dev_a", "today"),
    "sensor.a_tomorrow": entry("sensor.a_tomorrow", "dev_a", "tomorrow"),
    "sensor.a_day_2": entry("sensor.a_day_2", "dev_a", "day_2"),
    "sensor.b_today": entry("sensor.b_today", "dev_b", "today"),
    "sensor.other_today": entry(
      "sensor.other_today",
      "dev_a",
      "today",
      "other",
    ),
  },
};

test("day sensors are found by device and translation_key", () => {
  assert.deepEqual(card.resolveDaySensors(hass, "dev_a"), {
    today: "sensor.a_today",
    tomorrow: "sensor.a_tomorrow",
    day_2: "sensor.a_day_2",
  });
  assert.equal(
    card.resolveDayEntity(hass, { device_id: "dev_b" }),
    "sensor.b_today",
  );
  assert.equal(
    card.resolveDayEntity(hass, { device_id: "dev_a" }, "tomorrow"),
    "sensor.a_tomorrow",
  );
  assert.equal(
    card.resolveDayEntity(hass, { entity: "sensor.a_tomorrow" }),
    "sensor.a_today",
  );
  assert.equal(card.resolveDayEntity(hass, { device_id: "nope" }), null);
  assert.equal(card.resolveDayEntity({}, { device_id: "dev_a" }), null);
});

test("a sensor with nothing to read says why", () => {
  assert.match(
    card.sensorProblem(null, undefined),
    /No Movie Showtimes sensor/,
  );
  assert.match(
    card.sensorProblem("sensor.x", { state: "unavailable", attributes: {} }),
    /unavailable/,
  );
  assert.equal(
    card.sensorProblem("sensor.x", { state: "0", attributes: { films: [] } }),
    null,
  );
});

test("films become the reference's items", () => {
  const data = card.filmsToItems({ date: "2026-11-14", films });
  assert.equal(data.length, films.length + 1);
  assert.equal(data[0].title_default, "$title");
  const [, item] = data;
  assert.equal(item.title, "Comment braquer une banque");
  assert.equal(item.airdate, "2026-11-14");
  assert.equal(item.runtime, 121);
  assert.deepEqual(item.genres, ["Action", "Thriller", "Policier"]);
  assert.equal(item.rating, "2.8");
  assert.equal(item.poster, films[0].poster);
  assert.equal(item.deep_link, films[0].url);
  assert.deepEqual(item.cast, [
    "Nicholas Hoult",
    "Pete Davidson",
    "Zoë Kravitz",
  ]);
  assert.equal(item.flag, false);
});

test("source text cannot inject markup, bad urls are dropped", () => {
  const [, item] = card.filmsToItems({
    date: "2026-11-14",
    films: [
      {
        title: "<img onerror=x>A &lt;b&gt; & B",
        poster: "javascript:alert(1)",
        url: "https://x.test/a'b",
      },
    ],
  });
  assert.equal(item.title, "img onerror=xA &amp;lt;b&amp;gt; & B");
  assert.match(item.poster, /^data:image\/svg\+xml/);
  assert.equal(item.deep_link, null);
});

test("an empty day gives only the template", () => {
  assert.equal(card.filmsToItems({ date: "2026-11-14", films: [] }).length, 1);
});

test("tokens: a part with an empty token is left out, hyphens in values survive", () => {
  const keys = {
    $title: "Spider-Man",
    $runtime: "2h01",
    $genres: null,
    $empty: "",
  };
  assert.equal(card.resolveText("$title", keys), "Spider-Man");
  assert.equal(card.resolveText("$runtime-$genres", keys), "2h01");
  assert.equal(card.resolveText("$title-$runtime", keys), "Spider-Man - 2h01");
});

// A line, resolved the way the card does: the reference's own tokens and the formatted ones
// first, then the film's attributes by name.
const line = (template, film, extra = {}) => {
  const [, item] = card.filmsToItems({ date: "2026-11-14", films: [film] });
  const keys = {
    $title: item.title || null,
    $genres: item.genres ? item.genres.join(", ") : null,
    ...card.filmKeys((key) => item[key]),
    $showtimes: card.umcShowtimesText(item._filmObj) || null,
    ...extra,
  };
  return card.resolveText(template.replace(" - ", "-"), keys, item._film, {
    raw: item._filmObj,
    clean: card.umcClean,
  });
};

test("every attribute of a film is a token with its own name", () => {
  const [braquer, corset, dune, ramayana] = films;
  assert.equal(line("$film_id", braquer), "1000020289");
  assert.equal(line("$film_type", braquer), "FEATURE_FILM");
  assert.equal(line("$visa_number", braquer), "168593");
  assert.equal(line("$user_review_count", braquer), "5");
  assert.equal(line("$user_rating_count", braquer), "7");
  assert.equal(line("$want_to_see_count", braquer), "416");
  assert.equal(line("$hits", braquer), "35758");
  assert.equal(line("$sessions", braquer), "24958");
  assert.equal(line("$languages", braquer), "ENGLISH");
  assert.equal(line("$countries", braquer), "U.S.A.");
  assert.equal(
    line("$press_rating_count", corset),
    String(corset.press_rating_count),
  );
  assert.equal(line("$flags", braquer), braquer.flags.join(", "));
  assert.equal(line("$premiere", braquer), "No");
  assert.equal(line("$weekly_outing", braquer), "Yes");
  assert.equal(line("$has_trailer", braquer), "Yes");
  assert.equal(line("$vf", dune), "17:30");
  assert.equal(line("$vost", dune), "17:45");
  assert.equal(
    line("$release_date", dune),
    dune.release_date,
    "unformatted without the card's `date`",
  );
  assert.equal(
    line("$related_tags", dune),
    dune.details.related_tags.join(", "),
  );
  assert.equal(
    line("$cast", ramayana),
    ramayana.details.cast.slice(0, 3).join(", "),
  );
  // `details` attributes by their own name too; the film's own keys win.
  assert.equal(line("$synopsis", dune), dune.details.synopsis);
  assert.equal(line("$synopsis", ramayana), "", "no short synopsis: nothing");
});

test("objects, lists of objects and unknown names are empty", () => {
  const [braquer] = films;
  for (const token of [
    "$accessibility",
    "$details",
    "$credits",
    "$nope",
    "$constructor",
  ]) {
    assert.equal(line(token, braquer), "", token);
  }
  // A part with an empty token is dropped, the others stay.
  assert.equal(
    line("$film_id-$credits-$visa_number", braquer),
    "1000020289 - 168593",
  );
  assert.equal(line("$title - $nope", braquer), "Comment braquer une banque");
});

test("tokens keep their old output", () => {
  const braquer = films[0];
  assert.equal(line("$title", braquer), "Comment braquer une banque");
  assert.equal(line("$original_title", braquer), "How To Rob A Bank");
  assert.equal(line("$year", braquer), "2026");
  assert.equal(line("$directors", braquer), "David Leitch");
  assert.equal(line("$genres", braquer), "Action, Thriller, Policier");
  assert.equal(
    line("$cast", braquer),
    "Nicholas Hoult, Pete Davidson, Zoë Kravitz",
  );
  assert.equal(line("$user_rating", braquer), "2.8");
  assert.equal(line("$certificate", braquer), "");
  assert.equal(line("$certificate", films[2]), "Tout public");
  assert.equal(line("$press_rating", films[2]), "4.0");
  assert.equal(line("$synopsis", braquer), braquer.details.synopsis);
  assert.equal(
    line("$original_title-$year", braquer),
    "How To Rob A Bank - 2026",
  );
  assert.equal(
    line("$title", { ...braquer, title: "Spider-Man" }),
    "Spider-Man",
  );
});

test("a token in a sentence, and formatted tokens win over the attribute", () => {
  const dune = films[2];
  assert.equal(
    line("$user_rating ($user_review_count)", dune),
    `4.2 (${dune.user_review_count})`,
  );
  assert.equal(
    line("Rated $user_rating by $user_rating_count", dune),
    `Rated 4.2 by ${dune.user_rating_count}`,
  );
  // `$release_date` is the formatted one when the card gives it, and is not `$release` + `_date`.
  const formatted = { $release_date: "11/11/26", $release: null };
  assert.equal(line("$release_date", dune, formatted), "11/11/26");
  assert.equal(line("$release", dune, formatted), "");
  assert.equal(line("$release - $release_date", dune, formatted), "11/11/26");
  assert.equal(line("$year", dune), "2021");
});

test("generic values are sanitised before they reach the card's innerHTML", () => {
  const nasty = {
    title: "T",
    film_type: "<script>alert(1)</script>",
    certificate: "&lt;img src=x&gt;",
    countries: ["<b>FR</b>", "U.S.A."],
    details: {
      synopsis_full:
        '<p class="bo-p">A &amp; B &lt;script&gt;x&lt;/script&gt;</p><p>C<br>D&#233;&nbsp;E</p>',
    },
  };
  assert.equal(line("$film_type", nasty), "scriptalert(1)/script");
  assert.equal(line("$certificate", nasty), "&amp;lt;img src=x&amp;gt;");
  assert.equal(line("$countries", nasty), "bFR/b, U.S.A.");
  const full = line("$synopsis_full", nasty);
  assert.equal(full, "A & B scriptx/script C D\u00e9 E");
  assert.doesNotMatch(full, /[<>]/);
  const values = card.umcFilmValues(nasty);
  for (const text of Object.values(values)) assert.doesNotMatch(text, /[<>]/);
});

test("the token names come from the film's attributes", () => {
  const names = card.filmTokenNames(films[2]);
  for (const name of [
    "title",
    "film_id",
    "visa_number",
    "languages",
    "premiere",
    "synopsis",
    "synopsis_full",
    "cast",
    "related_tags",
    "showtimes",
    "day",
    "date",
  ]) {
    assert.ok(names.includes(name), name);
  }
  for (const name of ["accessibility", "details", "credits"]) {
    assert.ok(!names.includes(name), name);
  }
  assert.equal(new Set(names).size, names.length);
  assert.deepEqual(card.filmTokenNames(null), []);
  assert.match(card.umcTokenHelp(names), /\$film_id, /);
  assert.match(
    card.umcTokenHelp([]),
    /\$visa_number/,
    "static text without data",
  );
});

test("local search: title, genres, directors, cast, ignoring case and accents", () => {
  const [, item] = card.filmsToItems({ date: "2026-11-14", films });
  for (const query of [
    "braquer",
    "THRILLER",
    "leitch",
    "kravitz",
    "zoe",
    "rob a",
  ]) {
    assert.ok(card.matchesSearch(item, query), query);
  }
  assert.ok(!card.matchesSearch(item, "western"));
});

test("the editor hides the flag options but keeps url and the rest", () => {
  const names = [];
  const walk = (schema) =>
    schema.forEach((field) => {
      if (field.name) names.push(field.name);
      if (field.schema) walk(field.schema);
    });
  walk(card.umcEditorSchema());
  for (const hidden of [
    "flag",
    "flag_color",
    "icon",
    "icon_color",
    "hide_flagged",
    "hide_unflagged",
  ]) {
    assert.ok(!names.includes(hidden), `${hidden} should be hidden`);
  }
  for (const kept of ["url", "enable_search", "line1_text"]) {
    assert.ok(names.includes(kept), `${kept} should stay`);
  }
});

// ── Day selector ──────────────────────────────────────────────────────────────
const KEYS = ["today", "tomorrow", "day_2", "day_3", "day_4", "day_5", "day_6"];
const NOW = new Date(2026, 10, 14, 12); // Saturday 14 November 2026, local time
const isoDay = (offset) => {
  const day = new Date(2026, 10, 14 + offset);
  const pad = (n) => String(n).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
};
// A cinema with the 7 day sensors, `shift` days after 2026-11-14; `down` lists unavailable keys.
const week = (shift = 0, down = []) => {
  const week = { entities: {}, states: {} };
  KEYS.forEach((key, offset) => {
    const id = `sensor.c_${key}`;
    week.entities[id] = entry(id, "dev_c", key);
    week.states[id] = down.includes(key)
      ? { state: "unavailable", attributes: {} }
      : { state: "4", attributes: { date: isoDay(shift + offset), films } };
  });
  return week;
};

test("a date is parsed as a local date", () => {
  const day = card.parseLocalDate("2026-11-14");
  assert.deepEqual(
    [day.getFullYear(), day.getMonth(), day.getDate(), day.getHours()],
    [2026, 10, 14, 0],
  );
  assert.equal(card.parseLocalDate("14/11/2026"), null);
  assert.equal(card.parseLocalDate(undefined), null);
});

test("day labels: relative words, then weekday and day number, in the user's language", () => {
  assert.equal(card.dayLabel(0, "2026-11-14", "en"), "Today");
  assert.equal(card.dayLabel(1, "2026-11-15", "en"), "Tomorrow");
  assert.equal(card.dayLabel(0, "2026-11-14", "fr"), "Aujourd’hui");
  assert.equal(card.dayLabel(1, "2026-11-15", "fr"), "Demain");
  assert.equal(card.dayLabel(2, "2026-11-16", "en"), "Mon 16");
  assert.match(card.dayLabel(2, "2026-11-16", "fr"), /^lun\.? 16$/);
  // No date (unavailable sensor): counted from `now`; a bad language falls back to English.
  assert.equal(card.dayLabel(3, null, "en", NOW), "Tue 17");
  assert.equal(card.dayLabel(0, null, "not a language!"), "Today");
});

test("one chip per day sensor, unavailable ones flagged", () => {
  const chips = card.dayChips(
    week(0, ["day_3"]),
    { device_id: "dev_c" },
    "en",
    NOW,
  );
  assert.deepEqual(
    chips.map((chip) => chip.key),
    KEYS,
  );
  assert.deepEqual(
    chips.map((chip) => chip.label),
    ["Today", "Tomorrow", "Mon 16", "Tue 17", "Wed 18", "Thu 19", "Fri 20"],
  );
  assert.equal(chips[3].available, false);
  assert.equal(chips[3].date, null);
  assert.equal(chips[2].date, "2026-11-16");
  assert.equal(chips[0].entity, "sensor.c_today");
  assert.deepEqual(card.dayChips(week(), { device_id: "nope" }, "en", NOW), []);
  assert.equal(
    card.dayChips(week(), { entity: "sensor.c_day_2" }, "en", NOW).length,
    7,
  );
});

test("the selection follows the date, not the offset", () => {
  const today = card.dayChips(week(0), { device_id: "dev_c" }, "en", NOW);
  assert.equal(
    card.resolveSelection(today, { date: "2026-11-16", key: "day_2" }).key,
    "day_2",
  );
  // After midnight the same day is one sensor earlier: the user stays on it.
  const after = card.dayChips(week(1), { device_id: "dev_c" }, "en", NOW);
  assert.equal(
    card.resolveSelection(after, { date: "2026-11-16", key: "day_2" }).key,
    "tomorrow",
  );
  // The chosen day is gone: back to today.
  assert.equal(
    card.resolveSelection(after, { date: "2026-11-14", key: "today" }).key,
    "today",
  );
  // Nothing chosen yet: today.
  assert.equal(card.resolveSelection(today, {}).key, "today");
  assert.equal(card.resolveSelection(today, null).key, "today");
  assert.equal(card.resolveSelection([], { date: "2026-11-16" }), null);
});

test("an unavailable chosen sensor stays selected (its problem is shown, the row stays)", () => {
  const chips = card.dayChips(
    week(0, ["day_2"]),
    { device_id: "dev_c" },
    "en",
    NOW,
  );
  assert.equal(
    card.resolveSelection(chips, { date: "2026-11-16", key: "day_2" }).key,
    "day_2",
  );
  // ... but the unavailable sensor of another key does not capture a date that exists elsewhere.
  assert.equal(
    card.resolveSelection(chips, { date: "2026-11-15", key: "day_2" }).key,
    "tomorrow",
  );
});

test("the editor has the Show Days option", () => {
  const names = JSON.stringify(card.umcEditorSchema());
  assert.match(names, /"name":"enable_days"/);
});

// Real-looking widths (Roboto, 14 px) of "Today", "Tomorrow", "Tue 17" ... "Sat 21".
const REAL = [113, 165, 128, 136, 136, 113, 122];

test("lines are split on the real widths of the chips", () => {
  assert.deepEqual(card.dayLineSplit(REAL, 660), [4, 3]);
  assert.deepEqual(card.dayLineSplit(REAL, 1000), [7]);
  assert.deepEqual(card.dayLineSplit(REAL, 380), [3, 2, 2]);
  // 4 + 3: the first 4 chips need 113+165+128+136+24 = 566 px, the last 3 need 387.
  assert.deepEqual(card.dayLineSplit(REAL, 566), [4, 3]);
  assert.deepEqual(card.dayLineSplit(REAL, 565), [3, 4]);
  assert.deepEqual(card.dayLineSplit([90, 90], 100), [2]); // too wide: still two on a line
  assert.deepEqual(card.dayLineSplit([90], 500), [1]);
  assert.deepEqual(card.dayLineSplit([], 500), [0]);
  // Uniform widths give the old results (n chips of 86 px, gap 8).
  assert.deepEqual(card.dayLineSplit(Array(7).fill(86), 368), [4, 3]);
  assert.deepEqual(card.dayLineSplit(Array(7).fill(86), 367), [3, 2, 2]);
  assert.deepEqual(card.dayLineSplit(Array(5).fill(86), 368), [3, 2]);
  assert.deepEqual(card.dayLineSplit(Array(6).fill(86), 1000), [6]);
});

test("line split: fits, two per line at least, fewer lines when wider", () => {
  const sets = [
    REAL,
    Array(7).fill(86),
    [60, 200, 60, 200, 60, 200, 60],
    [80, 80, 160, 80, 80, 160, 80],
  ];
  for (const base of sets) {
    for (let count = 2; count <= 7; count++) {
      const widths = base.slice(0, count);
      let previous = Infinity;
      for (let row = 100; row <= 1200; row++) {
        const sizes = card.dayLineSplit(widths, row);
        assert.equal(
          sizes.reduce((a, b) => a + b),
          count,
        );
        assert.ok(Math.min(...sizes) >= 2, `${widths} @${row}: ${sizes}`);
        assert.ok(sizes.length <= previous, `${widths} @${row}: ${sizes}`);
        previous = sizes.length;
        let from = 0;
        const widest = Math.max(
          ...sizes.map((size) => {
            const line = widths.slice(from, from + size);
            from += size;
            return line.reduce((a, b) => a + b) + 8 * (size - 1);
          }),
        );
        // It fits, unless even the best split of that many lines cannot.
        if (sizes.length < Math.floor(count / 2))
          assert.ok(widest <= row, `${widths} @${row}: ${sizes}`);
      }
    }
  }
});

test("lines 5 and 6: poster view only, only when configured", () => {
  for (let index = 0; index <= 4; index++) {
    assert.ok(
      card.umcLineShown(index, "poster", ""),
      `line ${index} is always drawn`,
    );
    assert.ok(
      card.umcLineShown(index, "fanart", ""),
      `line ${index} is always drawn`,
    );
  }
  for (const index of [5, 6]) {
    assert.ok(card.umcLineShown(index, "poster", "$title"));
    assert.ok(
      !card.umcLineShown(index, "poster", ""),
      "no default: nothing reserved",
    );
    assert.ok(!card.umcLineShown(index, "poster", undefined));
    assert.ok(
      !card.umcLineShown(index, "fanart", "$title"),
      "fanart ignores them",
    );
  }
  const schema = JSON.stringify(card.umcEditorSchema());
  for (const name of [
    "line5_text",
    "line6_text",
    "line5_color",
    "line6_color",
  ]) {
    assert.ok(schema.includes(`"name":"${name}"`), name);
  }
});

test("runtime: XhYY from an hour on, Ymin under it, empty when it is not a duration", () => {
  assert.equal(card.umcRuntimeText(121), "2h01");
  assert.equal(card.umcRuntimeText(140), "2h20");
  assert.equal(card.umcRuntimeText(120), "2h00");
  assert.equal(card.umcRuntimeText(60), "1h00");
  assert.equal(card.umcRuntimeText(65), "1h05");
  assert.equal(card.umcRuntimeText(59), "59min");
  assert.equal(card.umcRuntimeText(1), "1min");
  assert.equal(card.umcRuntimeText("95"), "1h35");
  assert.equal(card.umcRuntimeText(605), "10h05");
  for (const bad of [
    0,
    "0",
    null,
    undefined,
    "",
    -5,
    90.5,
    "abc",
    "1h30",
    NaN,
  ]) {
    assert.equal(card.umcRuntimeText(bad), "", `${String(bad)} gives nothing`);
  }
});

// ── Tooltip text ──────────────────────────────────────────────────────────────
const tooltip = (template, film, extra = {}) => {
  const [, item] = card.filmsToItems({ date: "2026-11-14", films: [film] });
  const keys = {
    $title: item.title || null,
    $genres: item.genres ? item.genres.join(", ") : null,
    ...card.filmKeys((key) => item[key]),
    $showtimes: card.umcShowtimesText(item._filmObj) || null,
    ...extra,
  };
  return card.umcTooltipText(template, keys, item._filmRaw, item._filmObj);
};

test("tooltip text: the default is the synopsis, as before", () => {
  const [braquer, , dune] = films;
  assert.equal(tooltip("$synopsis", braquer), braquer.details.synopsis);
  assert.equal(tooltip("$synopsis", dune), dune.details.synopsis);
  // The adapter no longer sets `summary`; the item's key set did not otherwise change.
  const [, item] = card.filmsToItems({ date: "2026-11-14", films });
  assert.ok(!("summary" in item));
  assert.ok(
    !Object.keys(item).includes("_filmRaw"),
    "not in the JSON cache key",
  );
});

test("tooltip text: any token, a mix, plain text from HTML, line breaks", () => {
  const [braquer, , dune, ramayana] = films;
  assert.equal(
    tooltip("$original_title - $year", braquer),
    "How To Rob A Bank - 2026",
  );
  assert.equal(
    tooltip("$directors\n$cast", braquer),
    "David Leitch\nNicholas Hoult, Pete Davidson, Zoë Kravitz",
  );
  assert.equal(
    tooltip("$film_type: $visa_number", braquer),
    "FEATURE_FILM: 168593",
  );
  const full = tooltip("$synopsis_full", dune);
  assert.doesNotMatch(full, /[<>]/);
  assert.match(full, /^L'histoire de Paul Atreides/);
  assert.equal(tooltip("Rated $user_rating", dune), "Rated 4.2");
  // A part with an empty token is dropped; all empty: no tooltip.
  assert.equal(
    tooltip("$synopsis - $certificate", braquer),
    braquer.details.synopsis,
  );
  assert.equal(tooltip("$synopsis", ramayana), "");
  assert.equal(tooltip("$nope", braquer), "");
  assert.equal(tooltip("", braquer), "");
});

test("tooltip text reads naturally: apostrophes, quotes, accents, entities, < and >", () => {
  const film = {
    title: "T",
    details: {
      synopsis:
        "L'été \"vrai\" d'Amélie & Tom: 1 < 2 > 0, &amp; &#39;ok&#39; &eacute; &quot;x&quot; &lt;b&gt;",
    },
  };
  assert.equal(
    tooltip("$synopsis", film),
    "L'été \"vrai\" d'Amélie & Tom: 1 < 2 > 0, & 'ok' &eacute; \"x\" <b>",
  );
  // The line version of the same value stays sanitised.
  const [, item] = card.filmsToItems({ date: "2026-11-14", films: [film] });
  assert.doesNotMatch(item._film.synopsis, /[<>]/);
});

test('a value with "null" in it is not mistaken for a missing token ("nulle part")', () => {
  const film = { title: "T", details: { synopsis: "Il ne va nulle part." } };
  assert.equal(tooltip("$synopsis", film), "Il ne va nulle part.");
  assert.equal(line("$synopsis", film), "Il ne va nulle part.");
});

test("the editor has the Tooltip Text field", () => {
  const schema = JSON.stringify(card.umcEditorSchema());
  assert.match(schema, /"name":"tooltip_text"/);
});

// ── Paths into a film: $vo[0], $accessibility.pmr[0] ──────────────────────────
const AFTER_LIFE = {
  title: "After Life",
  vf: [],
  vo: ["20:30"],
  vost: [],
  accessibility: { pmr: ["20:30"], sme: [], audio_description: [] },
  film_id: "1000",
  genres: ["Drame", "Comédie"],
  countries: ["France", "Belgique", "Italie"],
  hits: 12,
  premiere: false,
  details: {
    synopsis: "Un film.",
    cast: ["A B", "C D"],
    credits: [{ name: "X", role: "DIRECTOR" }],
    showtimes: [
      {
        time: "20:30",
        version: "vo",
        projection: ["DIGITAL"],
        ticket_url: "https://x.test/t",
      },
      { time: "22:00", version: "vf" },
    ],
  },
};

test("a token can reach into lists and objects", () => {
  const f = AFTER_LIFE;
  assert.equal(line("$vo[0]", f), "20:30");
  assert.equal(line("$genres[0]", f), "Drame");
  assert.equal(line("$genres[1]", f), "Comédie");
  assert.equal(line("$genres[-1]", f), "Comédie");
  assert.equal(line("$genres[-2]", f), "Drame");
  assert.equal(line("$countries[-1]", f), "Italie");
  assert.equal(line("$accessibility.pmr[0]", f), "20:30");
  assert.equal(line("$accessibility.pmr", f), "20:30", "a list leaf is joined");
  assert.equal(line("$details.synopsis", f), "Un film.");
  assert.equal(line("$details.cast[1]", f), "C D");
  assert.equal(line("$cast[0]", f), "A B", "raw list, not the formatted $cast");
  assert.equal(line("$details.showtimes[0].time", f), "20:30");
  assert.equal(line("$details.showtimes[1].version", f), "vf");
  assert.equal(line("$details.showtimes[0].projection[0]", f), "DIGITAL");
  assert.equal(line("$details.showtimes[0].projection", f), "DIGITAL");
  assert.equal(line("$hits", f), "12");
  assert.equal(line("$premiere", f), "No");
});

test("bare tokens behave as before next to paths", () => {
  const f = AFTER_LIFE;
  assert.equal(line("$genres", f), "Drame, Comédie");
  assert.equal(line("$vo", f), "20:30");
  assert.equal(line("$cast", f), "A B, C D");
  assert.equal(line("$genres[0] - $genres", f), "Drame - Drame, Comédie");
  assert.equal(line("$genres[0]-$vo[0]", f), "Drame - 20:30");
  assert.equal(line("$title $vo[0]", f), "After Life 20:30");
});

test("a missing path is empty and drops its part", () => {
  const f = AFTER_LIFE;
  for (const token of [
    "$vf[0]", // empty list
    "$vo[1]", // out of range
    "$vo[-2]",
    "$vo[99999999999999999999]",
    "$title[0]", // [n] on a string
    "$title.length", // .key on a string
    "$vo.length", // .key on a list
    "$genres.x",
    "$accessibility.nope",
    "$accessibility.pmr[3]",
    "$accessibility.pmr.x",
    "$nope[0]",
    "$nope.x",
    "$certificate[0]",
    "$accessibility", // object
    "$accessibility.sme", // empty list
    "$details.credits", // list of objects
    "$details.credits[0]", // object
    "$details.showtimes[0]",
    "$details.showtimes",
    "$details.credits[0].name.x",
  ]) {
    assert.equal(line(token, f), "", token);
  }
  assert.equal(line("$vf[0] - $title", f), "After Life");
  assert.equal(line("$genres[0]-$certificate-$vo[0]", f), "Drame - 20:30");
  assert.equal(line("$details.credits[0].name", f), "X");
});

test("prototype keys find nothing", () => {
  const f = AFTER_LIFE;
  for (const token of [
    "$constructor",
    "$constructor[0]",
    "$title.constructor",
    "$accessibility.toString",
    "$accessibility.hasOwnProperty",
    "$accessibility.constructor",
    "$details.valueOf",
    "$genres.map",
    "$details.cast.length",
  ]) {
    assert.equal(line(token, f), "", token);
  }
});

test("a period, brackets or a word after a token are not part of it", () => {
  const f = { ...films[2] };
  assert.equal(line("Rated $user_rating.", f), "Rated 4.2.");
  assert.equal(line("$title [x]", f), "Dune [x]");
  assert.equal(line("$title.", f), "Dune.");
  assert.equal(line("$title, $year.", f), "Dune, 2021.");
  assert.equal(line("($genres[0])", AFTER_LIFE), "(Drame)");
  assert.equal(line("$genres[0].", AFTER_LIFE), "Drame.");
  assert.equal(
    line("$genres[0] et $genres[1]", AFTER_LIFE),
    "Drame et Comédie",
  );
  assert.equal(line("$genres[0].$genres[1]", AFTER_LIFE), "Drame.Comédie");
  assert.equal(line("$genres[a]", AFTER_LIFE), "Drame, Comédie[a]");
  assert.equal(line("$genres[]", AFTER_LIFE), "Drame, Comédie[]");
  assert.equal(line("$genres[0", AFTER_LIFE), "Drame, Comédie[0");
  assert.equal(line("$year.5", f), "2021.5");
  assert.equal(line("$title.Next", f), "Dune.Next");
  assert.deepEqual("$vo[0] $accessibility.pmr[0]x".match(card.UMC_KEYWORDS), [
    "$vo[0]",
    "$accessibility.pmr[0]",
  ]);
});

test("a leaf is sanitised for the lines and decoded for the tooltip", () => {
  const f = {
    title: "T",
    genres: ["<script>x</script>", "A &amp; B &#39;"],
    accessibility: { pmr: ["&lt;img&gt;"] },
    details: { synopsis_full: "<p>Un <b>vrai</b> &amp; beau</p>" },
  };
  assert.equal(line("$genres[0]", f), "scriptx/script");
  assert.equal(line("$genres[1]", f), "A &amp;amp; B &amp;#39;");
  assert.equal(line("$accessibility.pmr[0]", f), "&amp;lt;img&amp;gt;");
  assert.equal(line("$details.synopsis_full", f), "Un vrai & beau");
  for (const token of ["$genres[0]", "$genres[1]", "$accessibility.pmr[0]"]) {
    assert.doesNotMatch(line(token, f), /[<>]/, token);
  }
  assert.equal(tooltip("$genres[0]", f), "<script>x</script>");
  assert.equal(tooltip("$genres[1]", f), "A & B '");
  assert.equal(tooltip("$accessibility.pmr[0]", f), "<img>");
  assert.equal(tooltip("$details.synopsis_full", f), "Un vrai & beau");
  assert.equal(tooltip("$genres[0] - $vo[0]", AFTER_LIFE), "Drame - 20:30");
});

test("the item's JSON signal changes when anything in the film changes", () => {
  const sig = (film) =>
    card.filmsToItems({ date: "2026-11-14", films: [film] })[1]._sig;
  const base = sig(AFTER_LIFE);
  assert.equal(base, sig(structuredClone(AFTER_LIFE)));
  assert.notEqual(base, sig({ ...AFTER_LIFE, vo: ["20:45"] }));
  assert.notEqual(
    base,
    sig({
      ...AFTER_LIFE,
      accessibility: { ...AFTER_LIFE.accessibility, pmr: [] },
    }),
  );
  assert.notEqual(base, sig({ ...AFTER_LIFE, hits: 13 }));
  const [, item] = card.filmsToItems({
    date: "2026-11-14",
    films: [AFTER_LIFE],
  });
  assert.ok(
    !Object.keys(item).includes("_filmObj"),
    "the raw film stays out of the JSON",
  );
});

test("the helper mentions the path syntax", () => {
  assert.match(
    card.umcTokenHelp([]),
    /\$genres\[0\].*\$accessibility\.pmr\[0\]/,
  );
  assert.match(card.umcTokenHelp(["title", "film_id"]), /\$vo\[0\]/);
});

// ── Entry point ───────────────────────────────────────────────────────────────
test("entry_point: the attribute the films are read from (default films)", () => {
  const attributes = {
    date: "2026-11-14",
    films,
    programme: [films[2]],
    broken: "x",
  };
  assert.equal(card.filmsToItems(attributes).length, films.length + 1);
  assert.equal(card.filmsToItems(attributes, "films").length, films.length + 1);
  const other = card.filmsToItems(attributes, "programme");
  assert.equal(other.length, 2);
  assert.equal(other[1].title, "Dune");
  // Missing or not a list: no film, no error.
  assert.equal(card.filmsToItems(attributes, "nope").length, 1);
  assert.equal(card.filmsToItems(attributes, "broken").length, 1);
  assert.equal(card.filmsToItems(attributes, "constructor").length, 1);
});

test("entry_point: a sensor without that list is a problem, with it is not", () => {
  const state = { state: "3", attributes: { films, programme: [] } };
  assert.equal(card.sensorProblem("sensor.x", state), null);
  assert.equal(card.sensorProblem("sensor.x", state, "programme"), null);
  assert.match(card.sensorProblem("sensor.x", state, "nope"), /unavailable/);
  assert.match(
    card.sensorProblem(
      "sensor.x",
      { state: "3", attributes: { programme: "x" } },
      "programme",
    ),
    /unavailable/,
  );
  // The day chips follow the entry point too.
  const hass = week(0);
  for (const id of Object.keys(hass.states))
    hass.states[id].attributes.programme = hass.states[id].attributes.films;
  assert.ok(
    card
      .dayChips(hass, { device_id: "dev_c" }, "en", NOW)
      .every((chip) => chip.available),
  );
  assert.ok(
    card
      .dayChips(
        hass,
        { device_id: "dev_c", entry_point: "programme" },
        "en",
        NOW,
      )
      .every((chip) => chip.available),
  );
  assert.ok(
    card
      .dayChips(hass, { device_id: "dev_c", entry_point: "nope" }, "en", NOW)
      .every((chip) => !chip.available),
  );
});

test("entry_point is in the editor", () => {
  assert.match(JSON.stringify(card.umcEditorSchema()), /"name":"entry_point"/);
});

// ── Showtime badges ───────────────────────────────────────────────────────────
test("the badge model: one badge per showtime, in time order", () => {
  const dune = films[2];
  const badges = card.umcShowtimeBadges(dune);
  assert.equal(badges.length, dune.details.showtimes.length);
  assert.deepEqual(
    badges.map((badge) => badge.time),
    [...badges.map((badge) => badge.time)].sort(),
  );
  assert.deepEqual(badges[0], {
    time: "17:30",
    version: "vf",
    label: "VF",
    url: dune.details.showtimes[0].ticket_url,
    subtitled: false,
    pmr: false,
    sme: false,
    audio_description: false,
  });
  assert.equal(badges[1].label, "VOST");
  assert.equal(badges[1].version, "vost");
  for (const film of films) {
    for (const badge of card.umcShowtimeBadges(film)) {
      assert.match(badge.time, /^\d\d:\d\d$/);
      assert.ok(["VF", "VO", "VOST", "?"].includes(badge.label));
      assert.ok(badge.url === null || /^https?:\/\//.test(badge.url));
    }
  }
});

test("the badge model: fallback to the version lists, ties, unsafe urls, nothing", () => {
  const afterLife = card.umcShowtimeBadges({
    vf: ["22:00", "9:05"],
    vo: ["20:30", "22:00"],
    vost: [],
    other: ["21:00"],
  });
  assert.deepEqual(
    afterLife.map((badge) => `${badge.label} ${badge.time}`),
    ["VF 09:05", "VO 20:30", "? 21:00", "VF 22:00", "VO 22:00"],
  );
  assert.ok(afterLife.every((badge) => badge.url === null));
  // `details.showtimes` wins over the lists; bad entries and urls are dropped.
  const mixed = card.umcShowtimeBadges({
    vf: ["10:00"],
    details: {
      showtimes: [
        { time: "20:30", version: "vo", ticket_url: "javascript:alert(1)" },
        { time: "bad", version: "vf" },
        { time: "18:00", version: "weird", ticket_url: "https://x.test/a'b" },
        { time: "19:00", version: "vf", ticket_url: "https://x.test/t" },
        null,
      ],
    },
  });
  assert.deepEqual(
    mixed.map((badge) => [badge.label, badge.time, badge.url]),
    [
      ["?", "18:00", null],
      ["VF", "19:00", "https://x.test/t"],
      ["VO", "20:30", null],
    ],
  );
  for (const film of [
    null,
    undefined,
    {},
    { details: {} },
    { vf: "x" },
    { details: { showtimes: [] } },
    5,
  ]) {
    assert.deepEqual(card.umcShowtimeBadges(film), []);
  }
});

test("$showtimes: badges for a line that is only the token, plain text elsewhere", () => {
  assert.ok(card.umcIsBadgeLine("$showtimes_badge"));
  assert.ok(card.umcIsBadgeLine("  $showtimes_badge "));
  assert.ok(!card.umcIsBadgeLine("$showtimes"), "the plain token is text");
  assert.ok(
    card.umcIsBadgeLine("Séances: $showtimes_badge"),
    "a mixed line is a badge line",
  );
  assert.ok(card.umcIsBadgeLine("$showtimes_badge - $title"));
  assert.ok(!card.umcIsBadgeLine("$showtimes[0]"));
  const film = { title: "T", vf: ["22:00"], vo: ["20:30"], vost: [] };
  assert.equal(card.umcShowtimesText(film), "VO 20:30, VF 22:00");
  assert.equal(card.umcShowtimesText({ title: "T" }), "");
  // As a token of a text (a tooltip, or a mixed line): the plain list; empty drops its part.
  const keys = { $showtimes: card.umcShowtimesText(film) || null };
  assert.equal(
    card.resolveText("Séances: $showtimes", keys),
    "Séances: VO 20:30, VF 22:00",
  );
  assert.equal(
    card.umcTooltipText("$showtimes", keys, {}, film),
    "VO 20:30, VF 22:00",
  );
  assert.equal(
    card.resolveText("$title-$showtimes", { ...keys, $showtimes: null }),
    "",
  );
  const real = card.umcShowtimesText(films[2]);
  assert.match(real, /^VF 17:30, VOST 17:45$/);
});

test("the colour options are in the editor", () => {
  const schema = JSON.stringify(card.umcEditorSchema());
  for (const name of ["vf_color", "vo_color", "vost_color", "other_color"]) {
    assert.ok(schema.includes(`"name":"${name}"`), name);
  }
  assert.match(card.umcTokenHelp([]), /\$showtimes/);
});

// ── $showtimes[n] and .key on a list ──────────────────────────────────────────
test("$showtimes[n] is the n-th showtime of the badges' model", () => {
  const braquer = films[0]; // six VOST showtimes
  assert.equal(
    line("$showtimes", braquer),
    "VOST 08:55, VOST 11:25, VOST 14:00, VOST 16:40, VOST 19:20, VOST 21:55",
  );
  assert.equal(line("$showtimes[0]", braquer), "VOST 08:55");
  assert.equal(line("$showtimes[1]", braquer), "VOST 11:25");
  assert.equal(line("$showtimes[-1]", braquer), "VOST 21:55");
  assert.equal(line("$showtimes[5]", braquer), "VOST 21:55");
  assert.equal(line("$showtimes[6]", braquer), "");
  assert.equal(line("$showtimes[-7]", braquer), "");
  assert.equal(
    line("$showtimes[0] - $showtimes[1]", braquer),
    "VOST 08:55 - VOST 11:25",
  );
  assert.equal(line("$showtimes[0]-$showtimes[9]", braquer), "VOST 08:55");
  assert.equal(line("$showtimes[0]", AFTER_LIFE), "VO 20:30");
  assert.equal(line("$showtimes[1]", AFTER_LIFE), "VF 22:00");
  // The fallback lists feed it too; no showtimes: empty, the part is dropped.
  assert.equal(
    line("$showtimes[0]", { title: "T", vf: ["22:00"], vo: ["20:30"] }),
    "VO 20:30",
  );
  assert.equal(line("$showtimes[0]", { title: "T" }), "");
  assert.equal(line("$title-$showtimes[0]", { title: "T" }), "T");
  assert.equal(line("$showtimes[0]-$showtimes[1]", { title: "T" }), "");
  // Steps into a showtime (a badge: time, version, label, url); a leaf that is a badge is its label.
  assert.equal(line("$showtimes[0].time", braquer), "08:55");
  assert.equal(line("$showtimes[0].version", braquer), "vost");
  assert.equal(line("$showtimes[0].label", braquer), "VOST");
  assert.equal(line("$showtimes[1].time", braquer), "11:25");
  assert.equal(line("$showtimes[-1].time", braquer), "21:55");
  assert.equal(
    line("$showtimes[0].url", {
      details: { showtimes: [{ time: "20:30", version: "vo" }] },
    }),
    "",
    "no ticket url: empty",
  );
  assert.equal(line("$showtimes[0].url", AFTER_LIFE), "https://x.test/t");
  assert.equal(
    line("$showtimes[0].url", films[2]),
    films[2].details.showtimes[0].ticket_url,
  );
  // The projection over the showtimes (the user's `$showtimes.time[0]`).
  assert.equal(
    line("$showtimes.time", braquer),
    "08:55, 11:25, 14:00, 16:40, 19:20, 21:55",
  );
  assert.equal(line("$showtimes.time[0]", braquer), "08:55");
  assert.equal(line("$showtimes.time[-1]", braquer), "21:55");
  assert.equal(line("$showtimes.version[0]", AFTER_LIFE), "vo");
  assert.equal(line("$showtimes.label", AFTER_LIFE), "VO, VF");
  assert.equal(line("$showtimes.label[-1]", AFTER_LIFE), "VF");
  assert.equal(line("$showtimes.time[0]", { title: "T" }), "");
  // Nothing else to reach, and nothing throws.
  for (const token of [
    "$showtimes[0][0]",
    "$showtimes.length",
    "$showtimes.constructor",
    "$showtimes[0].constructor",
    "$showtimes[0].toString",
    "$showtimes[6].time",
    "$showtimes.time.x",
    "$showtimes.nope",
    "$showtimes[0].nope",
  ]) {
    assert.equal(line(token, braquer), "", token);
  }
  // Only the exact token is a badge line.
  assert.ok(card.umcIsBadgeLine("$showtimes_badge"));
  assert.ok(!card.umcIsBadgeLine("$showtimes"));
  assert.ok(!card.umcIsBadgeLine("$showtimes[0]"));
  assert.ok(!card.umcIsBadgeLine("$showtimes[0] - $showtimes[1]"));
});

test(".key on a list gives that key of each object", () => {
  const braquer = films[0];
  const times = braquer.details.showtimes.map((showtime) => showtime.time);
  assert.equal(line("$details.showtimes.time", braquer), times.join(", "));
  assert.equal(line("$details.showtimes.time[0]", braquer), "08:55");
  assert.equal(line("$details.showtimes.time[-1]", braquer), "21:55");
  assert.equal(line("$details.showtimes.time[5]", braquer), "21:55");
  assert.equal(line("$details.showtimes.time[9]", braquer), "");
  assert.equal(line("$details.showtimes.version[0]", braquer), "vost");
  assert.equal(
    line("$details.showtimes.version", braquer),
    Array(6).fill("vost").join(", "),
  );
  assert.equal(
    line("$details.showtimes.ticket_url[0]", braquer),
    braquer.details.showtimes[0].ticket_url,
  );
  assert.equal(
    line("$details.showtimes.time[0] - $details.showtimes.version[0]", braquer),
    "08:55 - vost",
  );
  assert.equal(line("$details.showtimes.nope", braquer), "");
  assert.equal(line("$details.showtimes.nope[0]", braquer), "");
  // Another list of objects: the credits (a list of {name, role}); a list of strings is as before.
  assert.equal(line("$details.credits.name", braquer), "David Leitch");
  assert.equal(line("$details.credits.role[0]", braquer), "DIRECTOR");
  assert.equal(line("$details.cast.name", braquer), "");
  assert.equal(line("$details.cast[0]", braquer), "Nicholas Hoult");
  // Only own keys of objects, scalar values, one projection.
  for (const token of [
    "$details.showtimes.length",
    "$details.showtimes.constructor",
    "$details.showtimes.map",
    "$details.showtimes.toString",
    "$details.showtimes.projection", // a list of lists: not scalars
    "$details.showtimes.time.x", // a second .key on the projection
    "$genres.length",
    "$vo.constructor",
    "$details.showtimes[0].constructor",
  ]) {
    assert.equal(line(token, braquer), "", token);
  }
  assert.equal(
    line("$details.showtimes.time", {
      details: {
        showtimes: [
          { time: "10:00" },
          null,
          3,
          { x: 1 },
          { time: { a: 1 } },
          { time: "11:00" },
        ],
      },
    }),
    "10:00, 11:00",
  );
  assert.equal(line("$details.showtimes.time[1]", AFTER_LIFE), "22:00");
});

test("the same paths in the tooltip text", () => {
  const braquer = films[0];
  assert.equal(
    tooltip("$showtimes[0] - $showtimes[-1]", braquer),
    "VOST 08:55 - VOST 21:55",
  );
  assert.equal(tooltip("$details.showtimes.time[0]", braquer), "08:55");
  assert.equal(tooltip("$details.showtimes.time", AFTER_LIFE), "20:30, 22:00");
  assert.equal(tooltip("$showtimes[9]", braquer), "");
  assert.equal(tooltip("$showtimes.time[0]", AFTER_LIFE), "20:30");
  assert.match(
    card.umcTokenHelp([]),
    /\$details\.showtimes\.time\[0\].*\$showtimes\[0\]/,
  );
});

test("the build marker and the console banner", () => {
  assert.match(card.CARD_BUILD, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
  const banner = card.umcBanner(
    card.CARD_VERSION,
    card.CARD_BUILD,
    "/movie_showtimes/movie-showtimes-card.js?v=0de668d6",
  );
  assert.equal(
    banner,
    `MOVIE-SHOWTIMES-CARD ${card.CARD_VERSION} · build ${card.CARD_BUILD} · url v=0de668d6`,
  );
  assert.match(
    card.umcBanner("1", "b", "http://x/y.js?a=1&v=abc#z"),
    /url v=abc$/,
  );
  assert.match(card.umcBanner("1", "b", "file:///x/card.js"), /url v=none$/);
  assert.match(card.umcBanner("1", "b", undefined), /url v=none$/);
});

test("badge rows that cannot be measured are retried, within a limit", () => {
  assert.equal(card.umcShouldRetry(0, 0), false, "nothing pending");
  assert.equal(card.umcShouldRetry(3, 0), true);
  assert.equal(card.umcShouldRetry(1, 59), true);
  assert.equal(card.umcShouldRetry(1, 60), false, "default limit: 60 frames");
  assert.equal(card.umcShouldRetry(1, 5, 5), false);
  assert.equal(card.umcShouldRetry(1, 4, 5), true);
});

// ── Sorting ───────────────────────────────────────────────────────────────────
const sortedTitles = (list, path, ascending) =>
  card
    .umcSortItems(
      card.filmsToItems({ date: "2026-11-14", films: list }).slice(1),
      path,
      ascending,
    )
    .map((item) => item.title);
const F = (title, extra = {}) => ({ title, ...extra });

test("sorting: numbers, missing values last in both directions, stable ties", () => {
  const list = [
    F("a", { hits: 5 }),
    F("none"),
    F("b", { hits: 20 }),
    F("c", { hits: 5 }),
    F("zero", { hits: 0 }),
    F("nan", { hits: NaN }),
  ];
  assert.deepEqual(sortedTitles(list, "hits", true), [
    "zero",
    "a",
    "c",
    "b",
    "none",
    "nan",
  ]);
  assert.deepEqual(
    sortedTitles(list, "hits", false),
    ["b", "a", "c", "zero", "none", "nan"],
    "ties keep the order, missing last",
  );
  assert.deepEqual(
    sortedTitles(list, "hits"),
    ["zero", "a", "c", "b", "none", "nan"],
    "ascending by default",
  );
  // The real fixtures: the rating text is not what is compared.
  const real = films;
  const byRating = sortedTitles(real, "user_rating", false);
  assert.deepEqual(
    byRating,
    [...real].sort((x, y) => y.user_rating - x.user_rating).map((f) => f.title),
  );
  assert.deepEqual(
    sortedTitles(real, "user_review_count", true),
    [...real]
      .sort((x, y) => x.user_review_count - y.user_review_count)
      .map((f) => f.title),
  );
  // press_rating is missing for two real films: last in both directions.
  const press = sortedTitles(real, "press_rating", true);
  assert.deepEqual(
    press.slice(-2).sort(),
    real
      .filter((f) => f.press_rating === undefined)
      .map((f) => f.title)
      .sort(),
  );
  const pressDesc = sortedTitles(real, "press_rating", false);
  assert.deepEqual(pressDesc.slice(-2).sort(), press.slice(-2).sort());
});

test("sorting: dates, strings, booleans, lists, paths", () => {
  // A midnight-crossing film: HH:MM strings would sort "00:15" first; the date-times do not.
  const night = F("night", {
    details: {
      showtimes: [{ time: "00:15", starts_at: "2026-11-15T00:15:00+01:00" }],
    },
  });
  const evening = F("evening", {
    details: {
      showtimes: [{ time: "21:30", starts_at: "2026-11-14T21:30:00+01:00" }],
    },
  });
  const noon = F("noon", {
    details: {
      showtimes: [{ time: "12:00", starts_at: "2026-11-14T12:00:00+01:00" }],
    },
  });
  assert.deepEqual(
    sortedTitles(
      [night, evening, noon],
      "details.showtimes[0].starts_at",
      true,
    ),
    ["noon", "evening", "night"],
  );
  assert.deepEqual(
    sortedTitles(
      [night, evening, noon],
      "details.showtimes[0].starts_at",
      false,
    ),
    ["night", "evening", "noon"],
  );
  assert.deepEqual(
    sortedTitles([night, evening, noon], "details.showtimes.starts_at", true),
    ["noon", "evening", "night"],
    "a projection: its first element",
  );
  // ISO dates; a date and a plain string do not mix up.
  const d = [
    F("b", { release_date: "2026-11-11" }),
    F("a", { release_date: "2021-10-01" }),
    F("c", { release_date: "2026-10-14" }),
  ];
  assert.deepEqual(sortedTitles(d, "release_date", true), ["a", "c", "b"]);
  // Strings: accents, case, numbers inside.
  const s = [F("Film 10"), F("film 2"), F("Éclair"), F("zèbre"), F("Eden")];
  assert.deepEqual(sortedTitles(s, "title", true), [
    "Éclair",
    "Eden",
    "film 2",
    "Film 10",
    "zèbre",
  ]);
  assert.deepEqual(sortedTitles(s, "title", false), [
    "zèbre",
    "Film 10",
    "film 2",
    "Eden",
    "Éclair",
  ]);
  // Booleans: false before true.
  const bo = [F("t", { premiere: true }), F("f", { premiere: false }), F("n")];
  assert.deepEqual(sortedTitles(bo, "premiere", true), ["f", "t", "n"]);
  assert.deepEqual(sortedTitles(bo, "premiere", false), ["t", "f", "n"]);
  // A list is its first element; a negative index; a details key; mixed numbers and strings do not throw.
  const l = [
    F("x", { genres: ["Drame", "A"] }),
    F("y", { genres: ["Action"] }),
    F("z", { genres: [] }),
  ];
  assert.deepEqual(sortedTitles(l, "genres", true), ["y", "x", "z"]);
  assert.deepEqual(
    sortedTitles(l, "genres[-1]", true),
    ["x", "y", "z"]
      .sort((p, q) => (p === "x" ? -1 : q === "x" ? 1 : p === "y" ? -1 : 1))
      .filter(() => true),
    "last genre: A, Action, none",
  );
  const cast = [
    F("p", { details: { cast: ["Zed"] } }),
    F("q", { details: { cast: ["Abe"] } }),
  ];
  assert.deepEqual(sortedTitles(cast, "cast[0]", true), ["q", "p"]);
  const mixed = [
    F("s", { hits: "text" }),
    F("n", { hits: 3 }),
    F("b", { hits: true }),
  ];
  assert.deepEqual(sortedTitles(mixed, "hits", true), ["n", "b", "s"]);
});

test("sorting: legacy values, `$`, unknown names, prototype keys, objects", () => {
  const list = [
    F("b", { user_rating: 2.5 }),
    F("a", { user_rating: 4.1 }),
    F("c"),
  ];
  assert.deepEqual(
    sortedTitles(list, "rating", false),
    ["a", "b", "c"],
    "rating is user_rating, numeric",
  );
  assert.deepEqual(sortedTitles(list, "$user_rating", true), ["b", "a", "c"]);
  assert.deepEqual(sortedTitles(list, " user_rating ", true), ["b", "a", "c"]);
  for (const path of [
    "airdate",
    "nope",
    "constructor",
    "details.constructor",
    "title.length",
    "accessibility",
    "details",
    "genres.map",
    "",
    "$",
    "a b",
    "title[0]",
    "x[",
    "__proto__",
  ]) {
    assert.deepEqual(
      sortedTitles(list, path, true),
      ["b", "a", "c"],
      `${path}: source order`,
    );
    assert.deepEqual(
      sortedTitles(list, path, false),
      ["b", "a", "c"],
      `${path}: source order`,
    );
  }
  assert.deepEqual(sortedTitles(list, "title", true), ["a", "b", "c"]);
  assert.equal(card.umcSortValue(null, "title"), null);
  assert.deepEqual(card.umcSortValue({ title: "T" }, "title"), {
    kind: "string",
    value: "T",
  });
  assert.deepEqual(card.umcSortValue({ runtime: 5 }, "runtime"), {
    kind: "number",
    value: 5,
  });
  assert.equal(card.umcSortValue({ d: "2026-11-14" }, "d").kind, "date");
  assert.equal(
    card.umcSortValue({ d: "2026-13-45" }, "d").kind,
    "string",
    "not a date",
  );
  // An item without its film has no value; the source order stays.
  assert.deepEqual(card.umcSortItems([{ n: 1 }, { n: 2 }], "title"), [
    { n: 1 },
    { n: 2 },
  ]);
});

test("the editor: sort_ascending defaults to true, unticking is kept, ticking again removes it", () => {
  const Editor = defined["movie-showtimes-card-editor"];
  const form = {
    events: {},
    addEventListener(name, handler) {
      this.events[name] = handler;
    },
  };
  globalThis.document.createElement = () => form;
  const editor = new Editor();
  editor.setConfig({ device_id: "d", sort_by: "hits" });
  editor._buildForm();
  assert.equal(
    form.data.sort_ascending,
    true,
    "the checkbox is ticked by default",
  );
  const change = (value) => {
    form.events["value-changed"]({ stopPropagation() {}, detail: { value } });
    return editor.events.at(-1).detail.config;
  };
  const unticked = change({ ...form.data, sort_ascending: false });
  assert.equal(unticked.sort_ascending, false, "descending is written");
  assert.equal(unticked.sort_by, "hits");
  assert.equal(form.data.sort_ascending, false);
  editor.setConfig(unticked); // Home Assistant gives the new config back
  const ticked = change({ ...form.data, sort_ascending: true });
  assert.ok(!("sort_ascending" in ticked), "ticked again: the key is removed");
  editor.setConfig(ticked);
  assert.equal(form.data.sort_ascending, true);
  // A YAML that already has `sort_ascending: true` also loses it when the box is edited.
  editor.setConfig({ device_id: "d", sort_ascending: true });
  assert.ok(
    !("sort_ascending" in change({ ...form.data, sort_ascending: true })),
  );
});

test("the editor: sort presets and helpers", () => {
  const sort = JSON.stringify(card.umcEditorSchema());
  assert.match(sort, /"custom_value":true/);
  for (const value of [
    "title",
    "user_rating",
    "press_rating",
    "user_review_count",
    "want_to_see_count",
    "hits",
    "release_date",
    "runtime",
    "year",
    "details.showtimes[0].starts_at",
  ]) {
    assert.ok(sort.includes(`"value":"${value}"`), value);
  }
  // No "None": like image_style, the list always has a value (Title is the default), and the
  // presets are in alphabetical order of their labels.
  const findField = (schema, name) => {
    for (const field of schema) {
      if (field.name === name) return field;
      const inner = field.schema && findField(field.schema, name);
      if (inner) return inner;
    }
    return null;
  };
  const options = findField(card.umcEditorSchema(), "sort_by").selector.select
    .options;
  assert.ok(options.every((option) => option.value && option.value !== "none"));
  const labels = options.map((option) => option.label);
  assert.ok(!labels.some((label) => /none/i.test(label)));
  assert.deepEqual(
    labels,
    [...labels].sort((a, b) => a.localeCompare(b)),
  );
  assert.ok(!sort.includes('"value":"airdate"'));
  assert.ok(!sort.includes('"value":"rating"'));
  assert.ok(!sort.includes("Air Date"));
  const Editor = defined["movie-showtimes-card-editor"];
  const form = { addEventListener() {} };
  globalThis.document.createElement = () => form;
  const editor = new Editor();
  editor.setConfig({ device_id: "d" });
  editor._buildForm();
  assert.match(
    form.computeHelper({ name: "sort_by" }),
    /any film attribute or path.*Films without a value come last/,
  );
  assert.equal(
    form.computeHelper({ name: "sort_ascending" }),
    "Untick for descending.",
  );
});

test("the editor: Title is shown when sort_by is unset, and not written when picked", () => {
  const Editor = defined["movie-showtimes-card-editor"];
  const handlers = {};
  const form = {
    addEventListener(name, fn) {
      handlers[name] = fn;
    },
  };
  globalThis.document.createElement = () => form;
  const editor = new Editor();
  editor.setConfig({ device_id: "d" });
  editor._buildForm();
  assert.equal(form.data.sort_by, "title");
  editor.dispatchEvent = () => {};
  handlers["value-changed"]({
    stopPropagation() {},
    detail: { value: { ...form.data, sort_by: "hits" } },
  });
  assert.equal(editor._config.sort_by, "hits");
  assert.equal(form.data.sort_by, "hits");
  handlers["value-changed"]({
    stopPropagation() {},
    detail: { value: { ...form.data, sort_by: "title" } },
  });
  assert.ok(!("sort_by" in editor._config));
  assert.equal(form.data.sort_by, "title");
});

// ── Version groups and the popover ────────────────────────────────────────────
const entryTimes = (group) => group.entries.map((entry) => entry.time);

test("showtime groups: one group per version (VF, VO, VOST, other); only the non-empty ones", () => {
  const dune = card.umcShowtimeGroups(films[2], "en");
  assert.deepEqual(
    dune.map((g) => [g.key, g.label, g.count]),
    [
      ["vf", "VF", 1],
      ["vost", "VOST", 1],
    ],
  );
  assert.deepEqual(dune[1].entries[0], {
    time: "17:45",
    version: "vost",
    subtitled: true,
    url: films[2].details.showtimes[1].ticket_url,
    pmr: false,
    sme: false,
    audio_description: false,
  });
  assert.equal(dune[0].entries[0].version, "vf");
  // The six VOST showtimes of the first real film are one VOST group, not VO.
  const braquer = card.umcShowtimeGroups(films[0], "en");
  assert.deepEqual(
    braquer.map((g) => [g.key, g.count]),
    [["vost", 6]],
  );
  assert.deepEqual(entryTimes(braquer[0]), [
    "08:55",
    "11:25",
    "14:00",
    "16:40",
    "19:20",
    "21:55",
  ]);
  assert.ok(braquer[0].entries.every((entry) => entry.version === "vost"));
  // After Life: the order of the groups is fixed, whatever the order of the showtimes.
  assert.deepEqual(
    card.umcShowtimeGroups(AFTER_LIFE, "en").map((g) => g.key),
    ["vf", "vo"],
  );
  // Unknown versions are "other"; empty groups are omitted; nothing gives [].
  const odd = card.umcShowtimeGroups(
    {
      details: {
        showtimes: [
          { time: "10:00", version: "weird" },
          { time: "09:00", version: "other" },
          { time: "11:00", version: "vo" },
        ],
      },
    },
    "en",
  );
  assert.deepEqual(
    odd.map((g) => [g.key, g.label, g.count]),
    [
      ["vo", "VO", 1],
      ["other", "OTHER", 2],
    ],
  );
  assert.deepEqual(entryTimes(odd[1]), ["09:00", "10:00"]);
  assert.deepEqual(card.umcShowtimeGroups({ title: "T" }, "en"), []);
  assert.deepEqual(card.umcShowtimeGroups(null, "en"), []);
});

test("showtime groups: labels by language, sorted entries, fallback lists, urls", () => {
  const other = { vf: [], vo: [], vost: [], other: ["21:00"] };
  assert.equal(card.umcShowtimeGroups(other, "fr")[0].label, "AUTRES");
  assert.equal(card.umcShowtimeGroups(other, "fr-CA")[0].label, "AUTRES");
  assert.equal(card.umcShowtimeGroups(other, "en")[0].label, "OTHER");
  assert.equal(card.umcShowtimeGroups(other, "de")[0].label, "OTHER");
  assert.equal(
    card.umcShowtimeGroups(other, "not a language!")[0].label,
    "OTHER",
  );
  assert.equal(card.umcShowtimeGroups(other, undefined)[0].label, "OTHER");
  // Fallback to the lists: VO and VOST are separate groups, times sorted.
  const lists = card.umcShowtimeGroups(
    { vf: ["22:00", "9:05"], vo: ["20:30"], vost: ["19:00"] },
    "en",
  );
  assert.deepEqual(
    lists.map((g) => [g.key, entryTimes(g)]),
    [
      ["vf", ["09:05", "22:00"]],
      ["vo", ["20:30"]],
      ["vost", ["19:00"]],
    ],
  );
  assert.deepEqual(
    lists[2].entries.map((entry) => entry.version),
    ["vost"],
  );
  // A midnight-crossing film: the 00:15 showtime of the next night is the last one.
  const night = card.umcShowtimeGroups(
    {
      details: {
        showtimes: [
          {
            time: "00:15",
            starts_at: "2026-11-15T00:15:00+01:00",
            version: "vf",
          },
          {
            time: "21:30",
            starts_at: "2026-11-14T21:30:00+01:00",
            version: "vf",
          },
          {
            time: "12:00",
            starts_at: "2026-11-14T12:00:00+01:00",
            version: "vf",
          },
        ],
      },
    },
    "en",
  );
  assert.deepEqual(entryTimes(night[0]), ["12:00", "21:30", "00:15"]);
  assert.equal(
    card.umcShowtimesText({
      details: {
        showtimes: [
          {
            time: "00:15",
            starts_at: "2026-11-15T00:15:00+01:00",
            version: "vf",
          },
          {
            time: "21:30",
            starts_at: "2026-11-14T21:30:00+01:00",
            version: "vf",
          },
        ],
      },
    }),
    "VF 21:30, VF 00:15",
  );
  // Only http(s) links are kept.
  const links = card.umcShowtimeGroups(
    {
      details: {
        showtimes: [
          { time: "10:00", version: "vf", ticket_url: "https://x.test/t" },
          { time: "11:00", version: "vf", ticket_url: "javascript:alert(1)" },
          { time: "12:00", version: "vf", ticket_url: "https://x.test/a'b" },
        ],
      },
    },
    "en",
  )[0].entries;
  assert.deepEqual(
    links.map((entry) => entry.url),
    ["https://x.test/t", null, null],
  );
});

test("the popover header counts and pluralises by language", () => {
  const g = (count, label = "VF") => ({ label, count });
  assert.equal(card.umcGroupHeader(g(1), "en"), "VF · 1 Showtime");
  assert.equal(card.umcGroupHeader(g(4), "en"), "VF · 4 Showtimes");
  assert.equal(card.umcGroupHeader(g(1), "fr"), "VF · 1 Séance");
  assert.equal(card.umcGroupHeader(g(4, "AUTRES"), "fr"), "AUTRES · 4 Séances");
  assert.equal(card.umcGroupHeader(g(2), "xx!"), "VF · 2 Showtimes");
});

test("the popover position: above and centred, flipped below, clamped, tiny viewports", () => {
  const size = { width: 200, height: 100 };
  const view = { width: 800, height: 600 };
  const anchor = (left, top) => ({
    left,
    top,
    right: left + 50,
    bottom: top + 20,
  });
  // Above the pill, centred on it (centre 425 - half the width 100).
  assert.deepEqual(card.umcPopoverPosition(anchor(400, 300), size, view), {
    left: 325,
    top: 194,
  });
  // No room above: below, still centred.
  assert.deepEqual(card.umcPopoverPosition(anchor(400, 60), size, view), {
    left: 325,
    top: 86,
  });
  // Clamped to the right edge and to the left edge.
  assert.equal(
    card.umcPopoverPosition(anchor(780, 300), size, view).left,
    800 - 200 - 8,
  );
  assert.equal(card.umcPopoverPosition(anchor(-30, 300), size, view).left, 8);
  // Centred on another box (the card) instead of the anchor, still above the anchor.
  const cardBox = { left: 100, right: 700, top: 0, bottom: 800 };
  assert.deepEqual(
    card.umcPopoverPosition(anchor(130, 300), size, view, 6, 8, cardBox),
    { left: 300, top: 194 },
  );
  // ... and still kept inside the viewport when the card is wider than it.
  assert.equal(
    card.umcPopoverPosition(anchor(130, 300), size, view, 6, 8, {
      left: 700,
      right: 2000,
      top: 0,
      bottom: 800,
    }).left,
    800 - 200 - 8,
  );
  // Room neither above nor below: the side with more room, kept inside the viewport.
  const tiny = { width: 300, height: 130 };
  const p = card.umcPopoverPosition(anchor(10, 60), size, tiny);
  assert.ok(p.top >= 8);
  // Larger than the viewport: pinned to the margin.
  assert.deepEqual(
    card.umcPopoverPosition(
      anchor(50, 50),
      { width: 500, height: 400 },
      { width: 300, height: 200 },
    ),
    { left: 8, top: 8 },
  );
});

// ── Accessibility marks of the showtimes ──────────────────────────────────────
test("accessibility: from details.showtimes, per showtime", () => {
  // The first real film: all six showtimes are wheelchair accessible, none has the other marks.
  const groups = card.umcShowtimeGroups(films[0], "en");
  const entries = groups.flatMap((group) => group.entries);
  assert.equal(entries.length, 6);
  assert.ok(
    entries.every(
      (entry) =>
        entry.pmr === true &&
        entry.sme === false &&
        entry.audio_description === false,
    ),
  );
  // Ramayana: only some are (and two showtimes share 13:45, only one of them is accessible).
  const ramayana = card
    .umcShowtimeGroups(films[3], "en")
    .flatMap((group) => group.entries);
  assert.deepEqual(
    ramayana.map((entry) => [entry.time, entry.pmr]),
    [
      ["13:15", false],
      ["13:45", false],
      ["13:45", true],
      ["16:00", true],
      ["20:15", false],
      ["20:45", true],
    ],
  );
  // Dune: none.
  assert.ok(
    card
      .umcShowtimeGroups(films[2], "en")
      .flatMap((g) => g.entries)
      .every((e) => !e.pmr && !e.sme && !e.audio_description),
  );
  // The three marks together, from a synthetic showtime.
  const all = card.umcShowtimeGroups(
    {
      details: {
        showtimes: [
          {
            time: "10:00",
            version: "vf",
            pmr: true,
            sme: true,
            audio_description: true,
          },
          { time: "11:00", version: "vf", pmr: "yes", sme: 1 },
        ],
      },
    },
    "en",
  )[0].entries;
  assert.deepEqual(
    all.map((e) => [e.pmr, e.sme, e.audio_description]),
    [
      [true, true, true],
      [false, false, false],
    ],
  );
});

test("accessibility: fallback from the film's accessibility lists", () => {
  const film = {
    vf: ["9:05", "22:00", "22:00"],
    vo: ["20:30"],
    vost: ["19:00"],
    accessibility: {
      pmr: ["09:05", "22:00"],
      sme: ["20:30"],
      audio_description: ["22:00", "19:00"],
    },
  };
  const byTime = (list) =>
    Object.fromEntries(
      list
        .flatMap((g) => g.entries)
        .map((e, i) => [
          e.time + "#" + i,
          [e.pmr, e.sme, e.audio_description].map(Number).join(""),
        ]),
    );
  const entries = card.umcShowtimeGroups(film, "en").flatMap((g) => g.entries);
  assert.deepEqual(
    entries.map((e) => [e.version, e.time, e.pmr, e.sme, e.audio_description]),
    [
      ["vf", "09:05", true, false, false],
      ["vf", "22:00", true, false, true],
      ["vf", "22:00", true, false, true], // duplicate times: all are flagged
      ["vo", "20:30", false, true, false],
      ["vost", "19:00", false, false, true],
    ],
  );
  assert.ok(byTime);
  // A time that is in no list, and bad lists, flag nothing and do not throw.
  const bare = card.umcShowtimeGroups(
    { vf: ["10:00"], accessibility: { pmr: ["11:00", 5, null], sme: "x" } },
    "en",
  )[0].entries[0];
  assert.deepEqual(
    [bare.pmr, bare.sme, bare.audio_description],
    [false, false, false],
  );
  assert.equal(
    card.umcShowtimeGroups({ vf: ["10:00"], accessibility: null }, "en")[0]
      .entries[0].pmr,
    false,
  );
  // details.showtimes wins over the lists.
  const both = card.umcShowtimeGroups(
    {
      vf: ["10:00"],
      accessibility: { pmr: ["10:00"] },
      details: { showtimes: [{ time: "10:00", version: "vf", pmr: false }] },
    },
    "en",
  )[0].entries[0];
  assert.equal(both.pmr, false);
});

test("accessibility: the plain text tokens and the order are unchanged, the flags reach the paths", () => {
  const f = films[3];
  assert.equal(
    card.umcShowtimesText(f),
    "VOST 13:15, VOST 13:45, VOST 13:45, VOST 16:00, VOST 20:15, VOST 20:45",
  );
  assert.equal(line("$showtimes[3].pmr", f), "Yes");
  assert.equal(line("$showtimes[0].pmr", f), "No");
  assert.equal(line("$showtimes.pmr", f), "No, No, Yes, Yes, No, Yes");
  assert.equal(line("$showtimes[0].sme", f), "No");
  assert.equal(line("$showtimes[0].audio_description", f), "No");
  assert.equal(
    line("$showtimes[3]", f),
    "VOST 16:00",
    "the label text is unchanged",
  );
});

test("accessibility flags and legend: icons, order, languages", () => {
  const entry = { pmr: true, sme: false, audio_description: true };
  assert.deepEqual(card.umcAccessibilityFlags(entry, "en"), [
    {
      key: "pmr",
      icon: "mdi:wheelchair-accessibility",
      label: "Wheelchair accessible",
    },
    {
      key: "audio_description",
      icon: "mdi:account-voice",
      label: "Audio description",
    },
  ]);
  assert.deepEqual(
    card
      .umcAccessibilityFlags(
        { pmr: true, sme: true, audio_description: true },
        "fr",
      )
      .map((f) => [f.key, f.icon, f.label]),
    [
      ["pmr", "mdi:wheelchair-accessibility", "Accès PMR"],
      [
        "sme",
        "mdi:ear-hearing-off",
        "Sous-titres pour sourds et malentendants",
      ],
      ["audio_description", "mdi:account-voice", "Audiodescription"],
    ],
  );
  assert.equal(
    card.umcAccessibilityFlags({ sme: true }, "en")[0].label,
    "Subtitles for the deaf and hard of hearing",
  );
  assert.equal(
    card.umcAccessibilityFlags({ sme: true }, "xx!")[0].label,
    "Subtitles for the deaf and hard of hearing",
  );
  assert.equal(
    card.umcAccessibilityFlags({ pmr: true }, "fr-CA")[0].label,
    "Accès PMR",
  );
  // Nothing true (or not strictly true), nothing missing: no icons.
  assert.deepEqual(
    card.umcAccessibilityFlags(
      { pmr: false, sme: "yes", audio_description: 1 },
      "en",
    ),
    [],
  );
  assert.deepEqual(card.umcAccessibilityFlags({}, "en"), []);
  assert.deepEqual(card.umcAccessibilityFlags(null, "en"), []);
  // The legend: each present mark once, in the fixed order, in the language.
  const entries = [
    { audio_description: true },
    { pmr: true },
    { pmr: true, audio_description: true },
    {},
  ];
  assert.deepEqual(
    card.umcAccessibilityLegend(entries, "en").map((f) => f.key),
    ["pmr", "audio_description"],
  );
  assert.deepEqual(
    card.umcAccessibilityLegend(entries, "fr").map((f) => f.label),
    ["Accès PMR", "Audiodescription"],
  );
  assert.deepEqual(card.umcAccessibilityLegend([{}, { pmr: false }], "en"), []);
  assert.deepEqual(card.umcAccessibilityLegend([], "en"), []);
  const real = card.umcShowtimeGroups(films[0], "en").flatMap((g) => g.entries);
  assert.deepEqual(
    card.umcAccessibilityLegend(real, "en").map((f) => f.key),
    ["pmr"],
  );
});

// ── `_badge` tokens, the age badge, ignored lines ─────────────────────────────
test("the _badge convention: a line with a badge token draws badges, in text it is plain text", () => {
  assert.deepEqual(card.umcBadgeSegments("$showtimes_badge"), [
    { type: "badge", kind: "showtimes" },
  ]);
  assert.deepEqual(card.umcBadgeSegments(" $certificate_badge "), [
    { type: "badge", kind: "certificate" },
  ]);
  for (const template of [
    "$showtimes",
    "$certificate",
    "$user_rating",
    "$press_rating",
    "$showtimes_badge[0]",
    "$constructor",
    "",
    "$title",
    "$showtimes_badges",
  ]) {
    assert.equal(card.umcBadgeSegments(template), null, template);
  }
  const film = {
    vf: ["22:00"],
    vo: ["20:30"],
    certificate: "Interdit - 12 ans",
  };
  const keys = {
    $showtimes: card.umcShowtimesText(film),
    $showtimes_badge: card.umcShowtimesText(film),
    $certificate_badge: card.umcCertificateBadge(film, "fr").label,
  };
  assert.equal(
    card.resolveText("Séances: $showtimes_badge", keys),
    "Séances: VO 20:30, VF 22:00",
  );
  assert.equal(card.resolveText("$showtimes", keys), "VO 20:30, VF 22:00");
  assert.equal(card.resolveText("Âge $certificate_badge", keys), "Âge -12 ans");
  assert.equal(
    card.umcTooltipText(
      "$certificate_badge - $showtimes_badge",
      keys,
      {},
      film,
    ),
    "-12 ans - VO 20:30, VF 22:00",
  );
  // The paths of $showtimes_badge walk the showtimes like $showtimes.
  const walk = (template) =>
    card.resolveText(template, keys, {}, { raw: film, clean: card.umcClean });
  assert.equal(walk("$showtimes_badge[0]"), "VO 20:30");
  assert.equal(walk("$showtimes_badge.time"), "20:30, 22:00");
  assert.match(card.umcTokenHelp([]), /\$showtimes_badge.*\$certificate_badge/);
});

test("the age badge: parsing, label, title, colour key", () => {
  const age = (certificate, lang) =>
    card.umcCertificateBadge({ certificate }, lang);
  assert.deepEqual(age("Interdit - 12 ans", "fr"), {
    age: 12,
    key: "age_12",
    label: "-12 ans",
    title: "Interdit aux moins de 12 ans",
  });
  assert.deepEqual(age("Interdit - 12 ans", "en"), {
    age: 12,
    key: "age_12",
    label: "-12",
    title: "Not suitable for under 12",
  });
  assert.equal(age("Interdit aux moins de 16 ans", "fr-CA").label, "-16 ans");
  assert.equal(age("Interdit - 16 ans", "en").key, "age_16");
  assert.equal(age("Interdit - 18 ans", "en").key, "age_18");
  assert.equal(age("18 ans", "en").age, 18);
  assert.equal(
    age("Interdit - 10 ans", "en").key,
    "age_12",
    "10 shares the amber colour",
  );
  assert.equal(age("Interdit - 10 ans", "en").age, 10);
  assert.equal(age("-12", "en").age, 12, "written without 'ans'");
  assert.equal(age("- 16", "fr").label, "-16 ans");
  assert.equal(
    age("Interdit - 14 ans", "en").age,
    12,
    "the nearest lower bucket",
  );
  assert.equal(age("Interdit - 17 ans", "en").age, 16);
  assert.equal(age("Interdit - 21 ans", "en").age, 18);
  assert.equal(age("Interdit - 12 ans", "not a language!").label, "-12");
  assert.equal(age("Interdit - 12 ans", undefined).label, "-12");
  // Nothing to show: all audiences, a warning, an age under 10, junk, nothing.
  for (const value of [
    "Tout public",
    "Tout public avec avertissement",
    "Avertissement",
    "Interdit - 6 ans",
    "6 ans",
    "",
    "abc",
    null,
    undefined,
    12,
    {},
  ]) {
    assert.equal(age(value, "fr"), null, String(value));
  }
  assert.equal(card.umcCertificateBadge(null, "fr"), null);
  assert.equal(
    card.umcCertificateBadge(
      { details: { certificate: "Interdit - 16 ans" } },
      "en",
    ).age,
    16,
  );
  // The real fixtures: none of their certificates restricts the age.
  for (const film of films)
    assert.equal(card.umcCertificateBadge(film, "fr"), null);
});

test("lines that resolve to nothing are ignored, an explicit $empty is not", () => {
  assert.equal(
    card.umcLineIsIgnored(3, "$certificates", ""),
    true,
    "unknown token",
  );
  assert.equal(
    card.umcLineIsIgnored(3, "$certificate", ""),
    true,
    "no value for this film",
  );
  assert.equal(
    card.umcLineIsIgnored(3, "$nope-$nada", ""),
    true,
    "every part dropped",
  );
  assert.equal(
    card.umcLineIsIgnored(3, "$empty", ""),
    false,
    "explicit blank line",
  );
  assert.equal(card.umcLineIsIgnored(5, "$empty", ""), false);
  assert.equal(card.umcLineIsIgnored(3, "$title", "Dune"), false, "has text");
  assert.equal(
    card.umcLineIsIgnored(0, "$nope", ""),
    false,
    "the title keeps the reference's handling",
  );
  // The text of such a line really is empty, per film.
  const line = (template, film) =>
    card.resolveText(
      template,
      { $title: film.title },
      card.umcFilmValues(film),
      { raw: film, clean: card.umcClean },
    );
  assert.equal(line("$certificates", films[0]), "");
  assert.equal(
    line("$certificate", films[0]),
    "",
    "film A has no certificate...",
  );
  assert.equal(line("$certificate", films[2]), "Tout public", "...film B has");
  assert.equal(line("$nope - $nada", films[0]), "");
});

test("the age colours are in the editor", () => {
  const schema = JSON.stringify(card.umcEditorSchema());
  for (const name of ["age_12_color", "age_16_color", "age_18_color"])
    assert.ok(schema.includes(`"name":"${name}"`), name);
});

// ── Badge lines: several tokens, text around them, rating badges ──────────────
test("badge segments: tokens and text in order, blanks are spacing", () => {
  const seg = card.umcBadgeSegments;
  assert.deepEqual(seg("$certificate_badge $showtimes_badge"), [
    { type: "badge", kind: "certificate" },
    { type: "badge", kind: "showtimes" },
  ]);
  assert.deepEqual(
    seg("$certificate_badge$showtimes_badge"),
    [
      { type: "badge", kind: "certificate" },
      { type: "badge", kind: "showtimes" },
    ],
    "adjacent",
  );
  assert.deepEqual(seg("Séances: $showtimes_badge"), [
    { type: "text", template: "Séances:" },
    { type: "badge", kind: "showtimes" },
  ]);
  assert.deepEqual(seg("$title $certificate_badge"), [
    { type: "text", template: "$title" },
    { type: "badge", kind: "certificate" },
  ]);
  assert.deepEqual(seg("a $user_rating_badge b $press_rating_badge c"), [
    { type: "text", template: "a" },
    { type: "badge", kind: "user_rating" },
    { type: "text", template: "b" },
    { type: "badge", kind: "press_rating" },
    { type: "text", template: "c" },
  ]);
  assert.deepEqual(
    seg("   $user_rating_badge   "),
    [{ type: "badge", kind: "user_rating" }],
    "whitespace only is spacing",
  );
  // The whole name is the token: `$user_rating_badge` is not `$user_rating` + `_badge`.
  assert.deepEqual(seg("$user_rating $user_rating_badge"), [
    { type: "text", template: "$user_rating" },
    { type: "badge", kind: "user_rating" },
  ]);
  assert.equal(seg("$user_rating"), null);
  assert.equal(seg("$press_rating $user_rating"), null);
  // Inside a '-' separated template, and a token with steps is a path, not a badge.
  assert.deepEqual(seg("$title-$showtimes_badge"), [
    { type: "text", template: "$title-" },
    { type: "badge", kind: "showtimes" },
  ]);
  assert.equal(seg("$showtimes_badge[0] $title"), null);
  assert.ok(card.umcIsBadgeLine("x $press_rating_badge"));
});

test("the rating badge: label, title, which values count", () => {
  const r = (film, key, lang) => card.umcRatingBadge(film, key, lang);
  assert.deepEqual(r({ user_rating: 4.11 }, "user_rating", "en"), {
    key: "user_rating",
    value: 4.11,
    label: "★ 4.1",
    text: "4.1",
    title: "Spectators' rating: 4.1 out of 5",
  });
  assert.equal(
    r({ user_rating: 4.11 }, "user_rating", "fr").title,
    "Note des spectateurs : 4,1 sur 5",
  );
  assert.equal(
    r({ user_rating: 4.11 }, "user_rating", "fr").label,
    "★ 4.1",
    "the label keeps the dot",
  );
  assert.deepEqual(r({ press_rating: 3.03 }, "press_rating", "en"), {
    key: "press_rating",
    value: 3.03,
    label: "★ 3.0",
    text: "3.0",
    title: "Press rating: 3.0 out of 5",
  });
  assert.equal(
    r({ press_rating: 3.03 }, "press_rating", "fr-CA").title,
    "Note de la presse : 3,0 sur 5",
  );
  assert.equal(
    r({ press_rating: 3.03 }, "press_rating", "not a language!").title,
    "Press rating: 3.0 out of 5",
  );
  assert.equal(r({ user_rating: 5 }, "user_rating", "en").label, "★ 5.0");
  assert.equal(r({ user_rating: 0.04 }, "user_rating", "en").label, "★ 0.0");
  for (const value of [0, -1, NaN, Infinity, "4.1", null, undefined, {}, [4]])
    assert.equal(
      r({ user_rating: value }, "user_rating", "en"),
      null,
      String(value),
    );
  assert.equal(r({}, "user_rating", "en"), null);
  assert.equal(r(null, "user_rating", "en"), null);
  assert.equal(
    r({ user_rating: 4 }, "title", "en"),
    null,
    "only the two ratings",
  );
  assert.equal(r({ user_rating: 4 }, "constructor", "en"), null);
  // The real fixtures: the label is `★ ` plus the text of `$user_rating`.
  for (const film of films) {
    assert.equal(r(film, "user_rating", "en").text, line("$user_rating", film));
    if (film.press_rating !== undefined)
      assert.equal(
        r(film, "press_rating", "en").text,
        line("$press_rating", film),
      );
    else assert.equal(r(film, "press_rating", "en"), null);
  }
});

test("rating badge tokens in texts: the label, or nothing", () => {
  const dune = films[2];
  const keys = {
    $user_rating_badge: card.umcRatingBadge(dune, "user_rating", "en").text,
    $press_rating_badge: card.umcRatingBadge(dune, "press_rating", "en").text,
  };
  assert.equal(
    card.umcTooltipText(
      "$user_rating_badge / $press_rating_badge",
      keys,
      {},
      dune,
    ),
    "4.2 / 4.0",
  );
  assert.equal(card.resolveText("Note $user_rating_badge", keys), "Note 4.2");
  assert.equal(
    card.resolveText("$title-$press_rating_badge", {
      ...keys,
      $press_rating_badge: null,
    }),
    "",
  );
  const walk = (template) =>
    card.resolveText(template, keys, {}, { raw: dune, clean: card.umcClean });
  assert.equal(
    walk("$user_rating_badge[0]"),
    "",
    "steps give nothing, as for the scalar they mirror",
  );
  assert.match(
    card.umcTokenHelp([]),
    /\$user_rating_badge.*\$press_rating_badge/,
  );
});

test("the rating colour options are gone from the editor", () => {
  const schema = JSON.stringify(card.umcEditorSchema());
  for (const name of ["user_rating_color", "press_rating_color"])
    assert.ok(!schema.includes(name), name);
});

test("the fallback text of a badge row", () => {
  assert.equal(
    card.umcBadgeFallbackText([
      { type: "text", text: "Séances:" },
      { type: "badge", text: "VF 09:10, VO 11:00" },
      { type: "badge", text: "-12 ans" },
      { type: "badge", text: "★ 4.1" },
    ]),
    "Séances: VF 09:10, VO 11:00 -12 ans ★ 4.1",
  );
  assert.equal(card.umcBadgeFallbackText([]), "");
  assert.equal(
    card.umcBadgeFallbackText([
      { type: "badge", text: "" },
      { type: "badge", text: "-16 ans" },
    ]),
    "-16 ans",
  );
});

test("badge items: each token on its own, text kept or dropped, nothing at all", () => {
  const items = (template, film, text = (t) => t) =>
    card.umcBadgeItems(card.umcBadgeSegments(template), film, "fr", text);
  const full = {
    vf: ["10:00"],
    vo: ["20:30"],
    certificate: "Interdit - 12 ans",
    user_rating: 4.11,
    press_rating: 3.03,
  };
  const kinds = (list) =>
    list.map((item) =>
      item.type === "text" ? "text:" + item.text : item.kind,
    );
  assert.deepEqual(kinds(items("$certificate_badge $showtimes_badge", full)), [
    "certificate",
    "showtimes",
  ]);
  assert.equal(
    items("$certificate_badge $showtimes_badge", full)[0].text,
    "-12 ans",
  );
  // The certificate is empty: the showtimes still show, and the other way round.
  const noAge = { ...full, certificate: "Tout public" };
  assert.deepEqual(kinds(items("$certificate_badge $showtimes_badge", noAge)), [
    "showtimes",
  ]);
  assert.deepEqual(
    kinds(
      items("$certificate_badge $showtimes_badge", { ...full, vf: [], vo: [] }),
    ),
    ["certificate"],
  );
  assert.deepEqual(
    kinds(items("$user_rating_badge $press_rating_badge", full)),
    ["user_rating", "press_rating"],
  );
  assert.deepEqual(
    kinds(items("$user_rating_badge $press_rating_badge", { user_rating: 3 })),
    ["user_rating"],
  );
  assert.deepEqual(
    kinds(items("$user_rating_badge $press_rating_badge", { press_rating: 3 })),
    ["press_rating"],
  );
  // Text segments: resolved by the caller's function, dropped when empty.
  assert.deepEqual(kinds(items("Séances: $showtimes_badge", full)), [
    "text:Séances:",
    "showtimes",
  ]);
  assert.deepEqual(kinds(items("Séances: $showtimes_badge", full, () => "")), [
    "showtimes",
  ]);
  assert.deepEqual(
    kinds(
      items("$title $certificate_badge", full, (t) =>
        t === "$title" ? "Dune" : t,
      ),
    ),
    ["text:Dune", "certificate"],
  );
  // Everything empty: no items, so the line is ignored; a text without badge is not enough to keep the row.
  assert.deepEqual(
    items("$certificate_badge $showtimes_badge", {
      certificate: "Tout public",
    }),
    [],
  );
  assert.deepEqual(items("$certificate_badge $user_rating_badge", {}), []);
  assert.deepEqual(items("$certificate_badge", null), []);
  // Text around badges that all vanish: the line is empty.
  assert.deepEqual(
    items("x $certificate_badge", {}, () => "x"),
    [],
  );
  // The version pills: the same groups as before.
  assert.deepEqual(
    items("$showtimes_badge", full)[0].groups.map((g) => g.key),
    ["vf", "vo"],
  );
});

test("the synopsis tooltip zone: the poster and the title only", () => {
  const rect = (left, top, right, bottom) => ({
    left,
    top,
    right,
    bottom,
    width: right - left,
  });
  const make = (poster, title, box) => ({
    getBoundingClientRect: () => box,
    querySelector: (selector) =>
      selector.includes("_container_poster")
        ? poster && { getBoundingClientRect: () => poster }
        : title && { getBoundingClientRect: () => title },
  });
  const poster = make(
    rect(0, 0, 100, 150),
    rect(110, 5, 200, 20),
    rect(0, 0, 400, 150),
  );
  assert.equal(card.umcTooltipZone(poster, "poster", 50, 100), true);
  assert.equal(card.umcTooltipZone(poster, "poster", 150, 15), true);
  assert.equal(card.umcTooltipZone(poster, "poster", 390, 15), true, "row");
  assert.equal(card.umcTooltipZone(poster, "poster", 150, 80), false);
  const fanart = make(null, rect(10, 5, 120, 20), rect(0, 0, 400, 100));
  assert.equal(card.umcTooltipZone(fanart, "fanart", 300, 60), true);
  assert.equal(card.umcTooltipZone(fanart, "fanart", 50, 15), true);
  assert.equal(card.umcTooltipZone(fanart, "fanart", 50, 60), false);
});

test("the rating badge text: the star is drawn apart, the number is the plain text", () => {
  const french = card.umcRatingBadge(
    { user_rating: 4.11 },
    "user_rating",
    "fr",
  );
  assert.equal(french.label, "★ 4.1");
  assert.equal(
    french.text,
    "4.1",
    "the same as the $user_rating text, without the star",
  );
});

test("the room after a badge row: its extra height, and 4 more before another badge row", () => {
  assert.equal(card.umcBadgeRowExtra(18.4, 14, false), 5);
  assert.equal(card.umcBadgeRowExtra(14.4, 14, false), 1);
  assert.equal(card.umcBadgeRowExtra(14, 14, false), 0);
  assert.equal(card.umcBadgeRowExtra(12, 14, false), 0, "never negative");
  assert.equal(
    card.umcBadgeRowExtra(14.4, 14, true),
    5,
    "a badge row follows: 4 more",
  );
  assert.equal(card.umcBadgeRowExtra(12, 14, true), 4);
});

// ── The retry loop of the badge rows that cannot be measured yet ──────────────
test("the badge retry loop: one callback per frame, stops at the limit, then the text", () => {
  const proto = defined["movie-showtimes-card"].prototype;
  let queue = [];
  let handle = 0;
  const cancelled = [];
  globalThis.requestAnimationFrame = (callback) => {
    queue.push([++handle, callback]);
    return handle;
  };
  globalThis.cancelAnimationFrame = (id) => {
    cancelled.push(id);
    queue = queue.filter(([queued]) => queued !== id);
  };
  const tspan = {
    textContent: ".",
    style: { fill: "transparent", textShadow: "x" },
  };
  const svg = { querySelector: () => tspan };
  const container = {
    _umcBadgeSlots: [{ i: 1, text: "VO 20:30" }],
    querySelector: () => svg,
  };
  const host = {
    layouts: 0,
    // A layout that is never possible: it asks to be watched again, as _layoutBadges does.
    _layoutBadges(item) {
      this.layouts++;
      proto._pendBadges.call(this, item);
    },
    _badgesAsText: proto._badgesAsText,
    _unwatchBadges: proto._unwatchBadges,
  };
  proto._pendBadges.call(host, container);
  proto._pendBadges.call(host, container); // a second call while the loop is armed adds nothing
  assert.equal(queue.length, 1);
  let frames = 0;
  while (queue.length && frames < 500) {
    const running = queue;
    queue = [];
    assert.equal(running.length, 1, "at most one callback per frame");
    running.forEach(([, callback]) => callback());
    assert.ok(queue.length <= 1, "it arms at most one more");
    frames++;
  }
  assert.equal(frames, 60, "it stops at the 60-frame limit");
  assert.equal(host.layouts, 60, "one layout try per frame");
  assert.equal(host._badgeLoop, false);
  assert.equal(
    tspan.textContent,
    "VO 20:30",
    "the plain text instead of a blank line",
  );
  assert.equal(container._umcBadgesFallback, true);
  // After it ended, a new request starts a new loop.
  proto._pendBadges.call(host, container);
  assert.equal(queue.length, 1);
  // Stopping cancels the frame and clears the flag.
  proto._stopBadgeWatch.call(host);
  assert.equal(queue.length, 0);
  assert.equal(host._badgeLoop, false);
  assert.equal(host._badgeRaf, null);
  // A layout that becomes possible ends the loop early, without the text.
  const ready = {
    _umcBadgeSlots: [{ i: 1, text: "VF 10:00" }],
    querySelector: () => svg,
  };
  tspan.textContent = ".";
  const host2 = {
    ok: false,
    _layoutBadges(item) {
      if (this.ok) proto._unwatchBadges.call(this, item);
      else proto._pendBadges.call(this, item);
    },
    _badgesAsText: proto._badgesAsText,
    _unwatchBadges: proto._unwatchBadges,
  };
  proto._pendBadges.call(host2, ready);
  for (let i = 0; i < 3; i++)
    queue.splice(0).forEach(([, callback]) => callback());
  host2.ok = true;
  queue.splice(0).forEach(([, callback]) => callback());
  assert.equal(queue.length, 0, "the loop ended when nothing was pending");
  assert.equal(
    tspan.textContent,
    ".",
    "no text fallback: the badges were laid out",
  );
  delete globalThis.requestAnimationFrame;
  delete globalThis.cancelAnimationFrame;
});

test("the card keeps its own synopsis bubbles apart from the pills' tips", () => {
  const proto = defined["movie-showtimes-card"].prototype;
  const cleaned = [];
  const host = {
    tooltipListeners: new Map([
      ["a", { cleanup: () => cleaned.push("a") }],
      ["b", {}],
      ["c", { cleanup: () => cleaned.push("c") }],
    ]),
  };
  proto._hideSynopsisBubbles.call(host);
  assert.deepEqual(cleaned, ["a", "c"]);
});
