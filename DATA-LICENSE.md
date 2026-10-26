# Data in `curb-data.js`

The snapshot ships two kinds of data in one file. They carry different terms.

## OpenStreetMap — ODbL 1.0

© OpenStreetMap contributors, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).

These fields are **derived from OSM**, and shipping them is distributing a derivative
database, not just a rendering — so they stay under ODbL and anyone redistributing them
inherits the same obligation:

- `roads`, `labels` — street geometry and names
- `green` — parks, water, cemeteries
- `alpr` — plate-reader camera locations, direction, maker, operator (the data DeFlock renders)
- `speed` — speed-camera corridor lines, traced on OSM streets (the corridor list, names and
  activation dates are LADOT's)
- `lots` entries with `"src": "OSM"` — off-street parking

The attribution is in the page footer and must stay in any public deployment.

## City and county open data

Everything else comes from government sources under their own terms, which permit reuse
including commercial reuse:

- **City of Los Angeles** — StreetsLA posted sweeping routes; Bureau of Engineering street
  centerlines; LADOT metered parking inventory, meter occupancy and city-owned lots;
  parking citations (via data.lacity.org / LA GeoHub APIs)
- **County of Los Angeles** — address points, city boundaries
- **City of West Hollywood** — permit blocks and hours, permit districts, sweeping routes,
  public parking (gis.weho.org and data.weho.org)

## Dodger Stadium home dates

`tools/dodgers-home.json` is a hand-maintained list of dates, times and opponents —
schedule facts, kept deliberately outside the MLB Stats API, whose terms limit use to
individual, non-commercial, non-bulk access.

## Derived analysis

Permit streets, enforcement hours and the District D game-day zone are computed here from
citation records. They are this project's own inferences, not official designations, and
the app says so wherever it shows them.
