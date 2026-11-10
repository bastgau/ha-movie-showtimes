# Brand assets

Sources and tooling for the integration's brand images. The images Home Assistant
serves live in `custom_components/movie_showtimes/brand/` (PNG only); the SVG sources
of the chosen design live in `docs/brand/source/`.

- `render.cjs` — SVG → PNG set (`NODE_PATH=$(npm root -g) node render.cjs <dir>`).
- `preview.py` — light/dark comparison sheet of several proposals.
- `proposals/` — design proposals awaiting a choice (delete once one is installed).

Produced by the `ha-webdesigner` agent (`.claude/agents/ha-webdesigner.md`).
