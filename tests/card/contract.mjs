// Contract between the backend's sensor attributes and the card (phase 1).
// Usage: node tests/card/contract.mjs <snapshot.json>
// The snapshot is written by a Python test: { states, entities, devices, locale } taken from a running Home Assistant.
// Exits non-zero when the "today" sensor is not found, or when a film field that has data renders nothing.
import { readFileSync } from "node:fs";

globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define: () => undefined };
globalThis.window = {};
globalThis.document = {};

const { UMC_DAY_KEYS, filmKeys, filmsToItems, resolveDaySensors } =
  await import(
    "../../custom_components/movie_showtimes/frontend/movie-showtimes-card.js"
  );

const [, , path] = process.argv;
if (!path) {
  console.error("usage: node contract.mjs <snapshot.json>");
  process.exit(2);
}
const hass = JSON.parse(readFileSync(path, "utf8"));
const failures = [];

const deviceIds = [
  ...new Set(
    Object.values(hass.entities)
      .filter((entry) => entry.platform === "movie_showtimes")
      .map((entry) => entry.device_id),
  ),
];
if (deviceIds.length === 0) {
  failures.push("no movie_showtimes device in the snapshot");
}
// The explicit item keys the reference's rendering reads, by attribute.
const MAPPED = {
  title: "title",
  poster: "poster",
  url: "deep_link",
  runtime: "runtime",
  genres: "genres",
  directors: "directors",
  original_title: "original_title",
  release_date: "release_date",
  user_rating: "user_rating",
  press_rating: "press_rating",
};
const isScalar = (value) =>
  ["string", "number", "boolean"].includes(typeof value);
// An attribute a token can show: a scalar, or a non-empty list of scalars.
const supported = (value) =>
  isScalar(value) ||
  (Array.isArray(value) && value.length > 0 && value.every(isScalar));
for (const deviceId of deviceIds) {
  const sensors = resolveDaySensors(hass, deviceId);
  if (Object.keys(sensors).join() !== UMC_DAY_KEYS.join()) {
    failures.push(
      `device ${deviceId}: expected ${UMC_DAY_KEYS}, got [${Object.keys(sensors)}]`,
    );
  }
  const attributes = hass.states[sensors.today].attributes;
  const [, ...items] = filmsToItems(attributes);
  attributes.films.forEach((film, index) => {
    const item = items[index];
    for (const [attribute, key] of Object.entries(MAPPED)) {
      const filled = Array.isArray(film[attribute])
        ? film[attribute].length > 0
        : film[attribute] !== null && film[attribute] !== undefined;
      if (
        filled &&
        (item[key] === null ||
          item[key] === undefined ||
          (Array.isArray(item[key]) && item[key].length === 0))
      ) {
        failures.push(
          `"${film.title}" has "${attribute}" but the card item has no "${key}"`,
        );
      }
    }
    // Every supported attribute of the film is a token by its own name.
    for (const [name, value] of Object.entries({ ...film.details, ...film })) {
      if (supported(value) && value !== "" && !(name in item._film)) {
        failures.push(
          `"${film.title}": "${name}" is not available as $${name}`,
        );
      }
    }
    if (
      film.details?.cast?.length &&
      filmKeys((key) => item[key]).$cast === null
    ) {
      failures.push(`"${film.title}" has a cast but $cast is empty`);
    }
  });
}

if (failures.length > 0) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log(`contract ok (${deviceIds.length} device(s))`);
