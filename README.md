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

## License

MIT, see [LICENSE](LICENSE).
