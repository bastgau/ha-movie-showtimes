# Movie Showtimes

[![Maintainer: bastgau](https://img.shields.io/badge/maintainer-bastgau-orange?logo=github&logoColor=%23959da5&labelColor=%232d333a)](https://github.com/bastgau)
[![Made with Python](https://img.shields.io/badge/Made_with-Python-blue?style=flat&logo=python&logoColor=%23959da5&labelColor=%232d333a)](https://www.python.org/)
[![Made for Home Assistant](https://img.shields.io/badge/Made_for-Homeassistant-blue?style=flat&logo=homeassistant&logoColor=%23959da5&labelColor=%232d333a)](https://www.home-assistant.io/)
[![GitHub Release](https://img.shields.io/github/v/release/bastgau/ha-movie-showtimes?logo=github&logoColor=%23959da5&labelColor=%232d333a&color=%230e80c0)](https://github.com/bastgau/ha-movie-showtimes/releases)
[![HACS validation](https://github.com/bastgau/ha-movie-showtimes/actions/workflows/validate-for-hacs.yml/badge.svg)](https://github.com/bastgau/ha-movie-showtimes/actions/workflows/validate-for-hacs.yml)
[![HASSFEST validation](https://github.com/bastgau/ha-movie-showtimes/actions/workflows/validate-with-hassfest.yml/badge.svg)](https://github.com/bastgau/ha-movie-showtimes/actions/workflows/validate-with-hassfest.yml)

A Home Assistant integration that shows the showtimes of your favourite French cinemas, as sensors you can use in dashboards, automations and templates.

## Features

- One config entry per cinema, with one device and **7 sensors**: today, tomorrow and the five following days.
- Per film: the VF, VO and VOST showtimes, accessibility (wheelchair, deaf and hard of hearing, audio description), and the film details (runtime, genres, directors, ratings, poster, synopsis, booking links…).
- Showtimes already started (more than 15 minutes ago) disappear by themselves, with no new request.
- The data is kept across restarts, and a failed refresh keeps showing the last good data (for 48 hours at most).
- Gentle with the source: the cinema is refreshed twice a day, never per entity.

> [!NOTE]
> The only source is [AlloCiné](https://www.allocine.fr) (France), read through the [`allocine-seances`](https://pypi.org/project/allocine-seances/) library. It scrapes the site, it is **not an official API** and it can break when the site changes. This project is not affiliated with AlloCiné.

## Installation

### Installation via HACS

1. Add this repository as a custom repository to HACS:

[![Add Repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bastgau&repository=ha-movie-showtimes&category=Integration)

2. Use HACS to install the integration.
3. Restart Home Assistant.
4. Set up the integration using the UI:

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=movie_showtimes)

### Manual Installation

1. Download the integration files from the GitHub repository.
2. Place the `movie_showtimes` folder in the `custom_components` directory of Home Assistant.
3. Restart Home Assistant.
4. Set up the integration using the UI:

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=movie_showtimes)

## Configuration

Add the integration from **Settings → Devices & services → Add integration → Movie Showtimes**, then:

1. Choose the source (AlloCiné is the only one for now).
2. Enter the **cinema reference** or the address of its page, and optionally a name.

The reference is the code at the end of the cinema page on allocine.fr: for
`https://www.allocine.fr/seance/salle_gen_csalle=W0124.html` it is `W0124`. Pasting the whole address works too.

Add the integration again for each cinema you want to follow. A cinema can only be added once.

## Entities

Each cinema is a device named after the cinema, with seven sensors:

| Sensor        | Day           | Example entity                        |
| ------------- | ------------- | ------------------------------------- |
| Today         | today         | `sensor.cinema_l_etincelle_today`     |
| Tomorrow      | today + 1     | `sensor.cinema_l_etincelle_tomorrow`  |
| In 2 days … 6 | today + 2 … 6 | `sensor.cinema_l_etincelle_in_2_days` |

- The **state** is the number of films still to come that day. It is `0` when the cinema is closed, or when the last showtime of the day has started.
- A sensor is **unavailable** when its data is more than 48 hours old, or when the day is not covered yet. It never shows `0` for a day it knows nothing about.
- Dates and times follow the time zone of your Home Assistant (the source gives French local time).

### Attributes

| Attribute    | Description                                     |
| ------------ | ----------------------------------------------- |
| `date`       | The day of the sensor, `YYYY-MM-DD`.            |
| `fetched_at` | When this day was last fetched from the source. |
| `films`      | The films still to come, sorted by title.       |

Each item of `films` always has:

| Key             | Description                                                                                  |
| --------------- | -------------------------------------------------------------------------------------------- |
| `title`         | The film title.                                                                              |
| `vf`            | Showtimes (`HH:MM`) dubbed in French, or of a French film.                                   |
| `vo`            | Showtimes in the original language, without subtitles.                                       |
| `vost`          | Showtimes in the original language with subtitles.                                           |
| `accessibility` | `pmr` (wheelchair), `sme` (deaf and hard of hearing), `audio_description`: lists of `HH:MM`. |
| `details`       | `details.showtimes`: every showtime with its `version`, `ticket_url`, projection, sound…     |

An `other` list is added when the source gives a showtime whose version is unknown, so that no showtime is lost.

The following keys are present **only when the source knows them**: `film_id`, `url`, `poster`, `original_title`, `year`,
`release_date`, `runtime` (minutes), `genres`, `countries`, `languages`, `directors`, `cast`, `certificate`, `synopsis`,
`user_rating`, `press_rating` and their counts, `premiere`, `has_trailer`… The complete list, with real examples, is in
[the design notes](docs/design/film-enrichment.md#6-attributes-showtimesfilm_attributes-constpy).

Values that come from the source (titles, genres, synopses) stay in French.

> [!NOTE]
> `films` is excluded from the recorder (it can weigh over 100 KB for a large cinema): the history keeps the count, `date` and `fetched_at`.

### Template examples

```jinja
{# Films showing today #}
{{ state_attr('sensor.my_cinema_today', 'films') | map(attribute='title') | list }}

{# Films with a VOST showtime #}
{{ state_attr('sensor.my_cinema_today', 'films') | selectattr('vost') | map(attribute='title') | list }}

{# Films with a wheelchair-accessible showtime #}
{{ state_attr('sensor.my_cinema_today', 'films') | selectattr('accessibility.pmr') | map(attribute='title') | list }}

{# Showtimes of the first film in VF #}
{{ (state_attr('sensor.my_cinema_today', 'films') | first).vf | join(', ') }}
```

## Card

The integration ships a Lovelace card, `custom:movie-showtimes-card`: the films showing at one cinema on the day you pick, as
posters (or fanart-style banners) with a title and up to four lines of text that you choose (six in the poster view). It is a copy of the
[upcoming-media-card](https://github.com/custom-cards/upcoming-media-card) family (see [Credits](#credits)), so it
shares its look and its layout options. There is nothing to install: the integration serves the card and loads it on
every dashboard (storage or YAML mode). Do **not** add it as a dashboard resource. After the first install or an
update, refresh your browser (a hard refresh if the card is not found).

The card makes no request of its own: it reads the cinema's day sensors. Your browser loads the posters from the
source's image server (`acsta.net`). A row of **day chips** under the search field (today, tomorrow, then a weekday and
a number, in your language) chooses the day (centred, balanced over the lines, never one chip alone on a line); the chip stays on the same date after midnight while it is still covered. The selected day is
highlighted with `accent_color` (default: the theme's primary colour), the colour that also paints the title line of a
poster.
The showtimes are in the `$showtimes_badge` badges (see below).

Add it from the card picker, choosing the **Cinema**, or in YAML:

```yaml
type: custom:movie-showtimes-card
device_id: 4f1c0e... # or entity: any sensor of the cinema
image_style: poster
enable_search: true
line1_text: $runtime - $genres
line2_text: $directors
date: dd/mm/yyyy
```

Main options (the others are those of the upcoming-media-card): `device_id`, `title`, `image_style` (`poster` or
`fanart`), `max`, `collapse`, `overflow` / `overflow_fit` / `max_columns`, `enable_search` (a local search over
title, original title, genres, directors and cast), `enable_days` (the day chips, default `true`; hidden when the
cinema has fewer than two day sensors), `sort_by`, `date` (default `mm/dd/yy`), `corner_radius`, colours
and sizes, `title_text`, `line1_text` ... `line4_text`.

**Sorting.** `sort_by` sorts the films of the day on any attribute of the film, or a path into it (the same names and
paths as the `$tokens`, without the `$`, which is accepted). `sort_ascending` is `true` by default (smallest, oldest or
A first); set it to `false` (untick "Sort Ascending" in the editor) for the reverse. Films that have no value for the
attribute always come last, in both directions; films with the same value keep the order of the sensor.

| `sort_by`                        | Sorts on                                  |
| -------------------------------- | ----------------------------------------- |
| `title` (the default)            | the title (case, accents and numbers)     |
| `user_rating`, `press_rating`    | the spectators' or the press rating       |
| `user_review_count`              | the number of reviews                     |
| `want_to_see_count`              | the number of people who want to see it   |
| `hits`                           | the popularity (entries)                  |
| `release_date`, `year`           | the release date, the year                |
| `runtime`                        | the runtime                               |
| `details.showtimes[0].starts_at` | the first showtime (a real date and time) |

Pick one in the editor or type any other, for example `genres[0]`, `film_id` or `details.cast[0]`. Numbers sort as
numbers, an ISO date or date-time as a date, a yes/no value as no before yes, a list on its first element, text without
case and accents. An object, an empty value or an unknown name counts as no value (an unknown name leaves the sensor's
order). `sort_by: none` keeps the raw order of the sensor. The old values of the original card still work: `rating` is `user_rating`, `airdate` changes nothing here (all
films have the day's date).

```yaml
sort_by: hits
sort_ascending: false # the most popular first
```

```yaml
sort_by: details.showtimes[0].starts_at # the film that starts first, first
```

**Lines.** `title_text` and `line1_text` ... `line4_text` are templates made of text and `$tokens`. Separate parts
with `-`: a part whose token is empty (or unknown) is left out. Defaults: `$title`, `$runtime - $genres`,
`$directors`, `$user_rating`, `$certificate`.

In the **poster view only**, two more lines are available, `line5_text` and `line6_text`. They have no default: when
they are not set nothing is drawn and the cards look exactly as before; in the `fanart` view they are ignored. The
sizes and colours work like the other lines (`line5_size`, `line6_size` in YAML, `line5_color`, `line6_color`, and the
global `line_size` and `line_color`). A film whose text for such a line needs more room than its poster gets a taller
item, only then.

**Any attribute of a film is a token, by its own name**: `$film_id`, `$film_type`, `$visa_number`, `$year`,
`$original_title`, `$directors`, `$languages`, `$countries`, `$user_rating_count`, `$user_review_count`,
`$press_rating_count`, `$want_to_see_count`, `$hits`, `$sessions`, `$premiere`, `$weekly_outing`, `$has_trailer`,
`$flags`, `$certificate`, `$synopsis`, `$synopsis_full` (as plain text), `$cast`, `$related_tags`... The editor lists
the names of the first film of the cinema under the line fields. A string is shown as is, a number as is, a list of
values joined with `, `, `true` / `false` as `Yes` / `No`. Objects and lists of objects (`accessibility`, `credits`,
the showtimes) cannot be used, and neither can a name the film does not have: they show nothing.

**Reaching into lists and objects.** After the name, a token can have steps: `[n]` takes the n-th element of a list
(counting from 0; `[-1]` is the last one) and `.key` goes into an object. They can be mixed and repeated:

| Token                        | Value for a film with `vo: ["20:30"]`, `genres: ["Drame", "Comédie"]` |
| ---------------------------- | --------------------------------------------------------------------- |
| `$vo[0]`                     | `20:30`                                                               |
| `$genres[0]`, `$genres[-1]`  | `Drame`, `Comédie`                                                    |
| `$accessibility.pmr[0]`      | the first showtime accessible to wheelchairs                          |
| `$accessibility.pmr`         | all of them, joined with `, `                                         |
| `$details.showtimes[0].time` | the time of the first showtime                                        |
| `$details.cast[0]`           | the first actor (`$cast` is the formatted first three)                |

`.key` on a **list of objects** gives the list of that key's values, one per item (items without it are skipped), so
`$details.showtimes.time` is `08:55, 11:25, ...`, `$details.showtimes.time[0]` is `08:55`, `$details.showtimes.time[-1]`
the last one, and `$details.credits.name` the names of the credits. After such a `.key` only an index can follow.
`$showtimes[0]` is the first showtime as text (`VOST 08:55`, like the badges: `[-1]` is the last); the line is still
drawn as text; badges need the exact `$showtimes_badge` (below).
The showtimes can be reached into like any list of objects, with the fields of a badge (`time`, `version`, `label`,
`url`): `$showtimes[0].time` is `20:30`, `$showtimes[0].version` is `vo`, `$showtimes.time` is `20:30, 22:00`,
`$showtimes.time[0]` the first time, `$showtimes.label[-1]` the last label. `$showtimes[0]` alone is the label and time
(`VO 20:30`).

A missing key, an index out of range, `[n]` on something that is not a list, `.key` on something that is not an
object, or a result that is itself an object (or a list of objects) shows nothing, so its part of the line is left out
like any empty token. A `.` or `[` that does not start a valid step is plain text: `Rated $user_rating.` keeps its
period. Bare names (`$genres`, `$vo`) work as before.

```yaml
line2_text: $genres[0] - $vo[0]
line3_text: $accessibility.pmr[0]
tooltip_text: $details.synopsis
```

A few tokens are formatted, or come from the original card, and win over the attribute of the same name:

| Token           | Value                                                  |
| --------------- | ------------------------------------------------------ |
| `$runtime`      | Runtime, like `2h01` (`45min` under an hour)           |
| `$user_rating`  | Spectators' rating, like `4.2`                         |
| `$press_rating` | Press rating, like `3.9`                               |
| `$release_date` | Release date, formatted with the `date` option         |
| `$cast`         | The first three actors                                 |
| `$day`, `$date` | The selected day (weekday, date formatted with `date`) |
| `$empty`        | An empty line (to keep the spacing)                    |

**Badge tokens (`_badge`).** A line (`title_text`, `line1_text` ... `line6_text`) that **contains** a `$<thing>_badge` token
is drawn as one row of **badges**, never as text. There are four, and each has a plain-text mirror that is always text:

| Badge token           | Draws                                           | Plain `$` token or text in a tooltip |
| --------------------- | ----------------------------------------------- | ------------------------------------ |
| `$showtimes_badge`    | one pill per version, `VF · 4`, click for times | `$showtimes`: `VF 20:30, VO 22:00`   |
| `$certificate_badge`  | the age restriction, `-12 ans`                  | `-12 ans`, or nothing                |
| `$user_rating_badge`  | the spectators' rating, `★ 4.1`                 | `$user_rating`: `4.1`                |
| `$press_rating_badge` | the press rating, `★ 3.0` (blue tones)          | `$press_rating`: `3.0`               |

Several tokens can sit side by side (`line4_text: $certificate_badge $showtimes_badge`) and come in the order of the
template, 6 px apart, wrapping when the column is narrow. Each badge stands for itself: one that has nothing for this film
(no age restriction, "Tout public", no showtimes, no rating) simply vanishes and the others still show. Text around the
tokens (`Séances: $showtimes_badge`, `$title $certificate_badge`) is shown as text in the same row, with the line's colour
and size, but only when at least one badge of the line is drawn: if every badge vanishes ("Tout public", no showtimes...), the line is empty and ignored (see below). In a tooltip
(`tooltip_text`) or any other text a badge token is only text. The synopsis tooltip shows only over the poster or the title, so the badges' own tooltips stay visible. Rating and age badges do not react to a click themselves: it goes on to the film link.

**Showtimes as badges: `$showtimes_badge`.** One badge per version, taken as is from the `version` of each showtime:
`VF · 4`, `VO · 2`, `VOST · 3`, `OTHER · 1` (`AUTRES` when Home Assistant is in French), a soft filled pill in the colour
of the version, with the number of showtimes. Click (or tap) a badge to open a small panel with the times of that version
and a link on those that have a booking link (opens in a new tab). Click the badge again, click elsewhere, press Escape, or
scroll to close it; only one panel is open at a time, and the film's own synopsis bubble stays away while it is open. A
film without showtimes shows no pill. In `fanart` view, lines 5 and 6 still do not exist. A line that is exactly
`$showtimes` is plain text (`VF 20:30, VO 22:00`); `$showtimes[0]`, `$showtimes.time` and so on work as described above.
The sensor already drops the showtimes that are past.

```yaml
line4_text: $showtimes_badge
vf_color: "#4caf50"
vost_color: orange
```

**Age restriction: `$certificate_badge`.** One small pill with the age restriction of the film: `-12 ans` (`-12` when
Home Assistant is not in French), `-16 ans`, `-18 ans`, found in the film's `certificate` ("Interdit - 12 ans",
"Interdit aux moins de 16 ans", `-18`...). Ages 10, 12, 16 and 18 are supported (13 counts as 12, 17 as 16). For all
audiences ("Tout public"), a warning only ("Avertissement"), no certificate or an age under 10, **nothing** is shown. Its
tooltip says "Interdit aux moins de 12 ans" ("Not suitable for under 12"). Colours: `age_12_color` (default amber, also for
-10), `age_16_color` (orange) and `age_18_color` (red).

```yaml
line3_text: $certificate_badge
age_18_color: "#b71c1c"
```

**Ratings: `$user_rating_badge` and `$press_rating_badge`.** Plain text in the row, not a pill, in the look of the card's
original rating: `★ 4.1`, the number in the colour of its line and only the star in the gold the card computes from that
line's colour. The film's `user_rating` (spectators) and `press_rating` give the two, both looking the same; only a number
above 0 shows. Hovering one shows "Note des spectateurs : 4,1 sur 5" or "Spectators' rating: 4.1 out of 5", in the language
of Home Assistant. In a text, `$user_rating` and `$press_rating` are the plain number (`4.1`), without the star.

```yaml
line3_text: $user_rating_badge $press_rating_badge
```

**Hover tips.** The age pill, the ratings and the version pills have a small tip on hover (after `tooltip_delay`, even when
`enable_tooltips` is off: they are labels, also read by screen readers). The film's synopsis bubble does not show while the
pointer is over them. A click on an age or rating item goes on to the film link like a click anywhere else on the item; a
click on a version pill opens its times.

```yaml
line3_text: $user_rating_badge $press_rating_badge
```

**Empty lines are left out.** A line whose text is empty (an unknown token such as `$certificates`, a token with no value
for this film, or every part of the line dropped) is ignored: nothing is drawn and the next lines move up, film by film. The
title line keeps its own handling. To keep a blank line on purpose, use `$empty`.

The version colours are `vf_color` (default: the theme's primary colour), `vo_color` (the theme's accent colour),
`other_color` (the secondary text colour) and `vost_color` (a mix of the two); in every badge row the text is the colour of
its line (`line_color` / `lineN_color`) and its size follows the line's size.

**Accessibility in the panel.** Next to the time of a showtime, a small icon for each mark it has: wheelchair access
(`mdi:wheelchair-accessibility`, "Accès PMR"), subtitles for the deaf and hard of hearing (`mdi:ear-hearing-off`,
"Sous-titres pour sourds et malentendants") and audio description (`mdi:account-voice`, "Audiodescription"), in that
order, with the name of the mark as a tooltip. At the bottom of the panel a one-line legend lists the icons that appear in
it (touch screens have no tooltips). A showtime without any mark looks as before. The marks come from the showtime
itself (`details.showtimes`), or, if the sensor has none, from the `accessibility` lists (a time is marked when it is in
the list). They are also available as `$showtimes[0].pmr`, `.sme` and `.audio_description` (`Yes` / `No`).

**Entry point.** The tokens read the list of films in the sensor's `films` attribute. The option `entry_point` (in the
Advanced section of the editor) names another attribute holding the list; the default is `films`, so you only need it
for a custom sensor. If the attribute is missing or is not a list the card shows no film.

**Tooltip.** With `enable_tooltips: true` a bubble appears when the pointer rests on a film (long press on a touch
screen, after `tooltip_delay` ms). `tooltip_text` is what it shows: a template with the same `$tokens` as the lines
(default `$synopsis`, so nothing changes if you do not set it). A line break in the template is a line break in the
bubble. Text such as `&amp;` or `&#39;` in the source is shown as the character. When the template gives nothing for a
film (for example a film without a synopsis), that film has no bubble. The bubble is at most 340 px wide and is not
truncated.

```yaml
enable_tooltips: true
tooltip_text: |
  $original_title ($year)
  $directors
  $synopsis
```

Examples:

```yaml
line1_text: $runtime - $genres
line2_text: $film_type - $visa_number
line3_text: $user_rating ($user_review_count)
```

The other tokens of the original card (`$episode`, `$studio` ...) show nothing. The editor and the messages are in
English only for now.

Troubleshooting: "Custom element doesn't exist" means the browser has an old page, so do a hard refresh or clear the
cache. "Showtimes unavailable": check that the cinema's sensors are available. The console shows the card's build (`MOVIE-SHOWTIMES-CARD 1.0.0 · build … · url v=…`): if it is older than your change, restart Home Assistant (the cache-busting hash is computed once per start) or disable the browser cache.

## How it works

- The cinema is refreshed **every 12 hours** (30 minutes after a connection error). The 8 following days are fetched at once; the showtimes are filtered locally, so they stay correct between two refreshes.
- Each refresh costs a few requests to allocine.fr, with no request per entity or per film.
- The data is saved to disk and restored at startup, so a restart does not hit the site again.

## Troubleshooting

| Message                                      | Meaning                                                                                           |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| _Invalid or unknown cinema_                  | The reference is wrong. Check the end of the cinema page address.                                 |
| _The site refused the request_               | allocine.fr answered 403. Try again later; the last good data is kept meanwhile.                  |
| _returned showtimes in an unexpected format_ | The site probably changed. [Open an issue](https://github.com/bastgau/ha-movie-showtimes/issues). |
| Sensors are _unavailable_                    | No successful refresh for 48 hours. Check the logs and the diagnostics.                           |

When you open an issue, please attach the **diagnostics** of the config entry (Settings → Devices & services → Movie Showtimes → ⋮ → Download diagnostics).

## Limitations

- France only, AlloCiné only.
- Seven days at most (today + 6).
- Scraping: a change on allocine.fr can interrupt the updates until the integration is fixed.

## Development

The repository comes with a devcontainer: open it in VS Code and choose "Reopen in Container". Then:

```bash
scripts/lint     # ruff, pylint, pyright, docstring-linter, Prettier
scripts/test     # pytest with the coverage gate
scripts/develop  # Home Assistant on http://localhost:8123, configuration in ./config
```

The scripts are described in [scripts/README.md](scripts/README.md). The development environment is managed by [ha-dev-environment](https://github.com/bastgau/ha-dev-environment): `uvx --from copier copier update` brings in its changes.

## Credits

The card is a copy of the card of [ha-betaseries](https://github.com/bastgau/ha-betaseries), itself a fork of
[upcoming-media-card](https://github.com/custom-cards/upcoming-media-card) by Custom cards for Home Assistant and its
contributors, with BetaSeries removed and an adapter for this integration's sensors. Both are MIT licensed; their
notices are kept in the header of `custom_components/movie_showtimes/frontend/movie-showtimes-card.js`.

## License

MIT, see [LICENSE](LICENSE).
