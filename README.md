# CurbWatch LA

Street parking, block by block, from Echo Park to West Hollywood. Search an address or a place (a shop, park, school or venue), or click any block, to see its street-sweeping days, whether it's a permit street and when that's enforced, Dodger game-day restrictions, meters, nearby lots, plate-reader cameras, and where tickets actually get written.

## Coverage

Doheny east to the Arts District, Franklin down to roughly Pico. Labeled on the map:

| | |
|---|---|
| **Eastside** | Elysian Park, Angelino Heights, Echo Park, Westlake, Silver Lake, Virgil Village |
| **Central** | Los Feliz, East Hollywood, Koreatown, Hollywood, Larchmont, Hancock Park |
| **West** | Mid-Wilshire, Fairfax, Beverly Grove, West Hollywood |
| **Downtown** | Downtown, Chinatown, Little Tokyo, Arts District |

Also inside the covered area, unlabeled: Thai Town, Little Armenia, Historic Filipinotown,
Rampart Village, Melrose, Carthay, Bunker Hill and the Civic Center. West Hollywood is a separate city with its own rules;
it's drawn with a dashed boundary and uses the city's own permit and sweeping schedules.

Beverly Hills falls inside the map's frame but outside its coverage — it publishes none of
this data, so it's grayed out and a click there says so rather than implying the curb is free.

## Sources

- **LA City:** StreetsLA posted sweeping routes, street centerlines, LADOT meter inventory and live occupancy, LADOT city lots, and LA parking citations (last 6 months for ticket history, last 18 months for permit streets)
- **West Hollywood:** city GIS permit blocks with posted hours, permit districts, sweeping lines, and public lots
- **LA County:** address points, city boundaries
- **OpenStreetMap:** streets, parks, parking lots, named places for search, and plate-reader (ALPR) cameras, which is the same data DeFlock shows. © OpenStreetMap contributors
- **Dodger Stadium home dates:** hand-maintained in `tools/dodgers-home.json`
- **LADOT speed cameras:** the city's Speed Safety System corridors, hand-maintained in `tools/speed-cameras.json` and traced onto OpenStreetMap streets

Terms differ by layer — see [DATA-LICENSE.md](DATA-LICENSE.md). The OSM-derived parts of
`curb-data.js` are a derivative database under ODbL 1.0.

Code is MIT (see `LICENSE`). Type is the system Helvetica stack and deck.gl is vendored, so the site loads no webfonts and makes no third-party requests.

City data isn't the curb. Red curbs, hydrants, driveways and temporary signs aren't mapped, and the posted sign always wins.
