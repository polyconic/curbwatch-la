"""Neighborhood pages: /echo-park/, /silver-lake/, ... plus sitemap.xml.

Reads the finished curb-data.js (run build.py first) and writes one static page per
neighborhood, so search engines and AI tools get real text instead of a canvas. Every
number comes from the same data the map draws; nothing here is hand-written per page.

    python3 tools/neighborhoods.py

Neighborhood outlines: tools/neighborhoods.geojson, the LA Times "Mapping L.A."
boundaries (informal, not official city limits). A block belongs to the neighborhood that
contains its first point. West Hollywood is its own city with its own data and is not
generated here yet.
"""
import collections, html, json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = 'https://curbwatch.la'
O = (-118.40, 34.04)
DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
DOW3 = [d[:3] for d in DOW]
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

# slug -> display name, in the order they link to each other
HOODS = {
    'echo-park': 'Echo Park', 'silver-lake': 'Silver Lake', 'hollywood': 'Hollywood',
    'koreatown': 'Koreatown', 'east-hollywood': 'East Hollywood', 'westlake': 'Westlake',
    'mid-wilshire': 'Mid-Wilshire', 'beverly-grove': 'Beverly Grove',
}

esc = lambda s: html.escape(str(s), quote=True)

s = (ROOT / 'curb-data.js').read_text()
C = json.loads(s[s.index('window.CURB=') + 12:].rstrip().rstrip(';'))
GEO = json.loads((ROOT / 'tools' / 'neighborhoods.geojson').read_text())

built = C['meta']['built'][:10]
cite_to = C['citeRange'][1]


def date_txt(iso):
    y, m, d = map(int, iso.split('-'))
    return f'{MON[m - 1]} {d}, {y}'


def title(t):
    t = t.lower()
    t = re.sub(r'\b([a-z])', lambda m: m.group(1).upper(), t)
    t = re.sub(r'\b(\d+)(St|Nd|Rd|Th)\b', lambda m: m.group(1) + m.group(2).lower(), t)
    t = re.sub(r'\bWy\b', 'Way', t)
    t = re.sub(r'\bMc([a-z])', lambda m: 'Mc' + m.group(1).upper(), t)
    return t


def fmt_min(m):
    m = ((m % 1440) + 1440) % 1440
    h, mm = divmod(m, 60)
    if m == 0: return 'midnight'
    if m == 720: return 'noon'
    return f'{h % 12 or 12}' + (f':{mm:02d}' if mm else '') + (' AM' if h < 12 else ' PM')


def ordn(n):
    return f'{n}' + ('th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th'))


def pip(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][:2]
        xj, yj = ring[j][:2]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


polys = {}
for f in GEO['features']:
    g = f['geometry']
    polys[f['properties']['slug']] = [p[0] for p in ([g['coordinates']] if g['type'] == 'Polygon' else g['coordinates'])]


def hood_of(x, y):
    for slug, rings in polys.items():
        if any(pip(x, y, r) for r in rings): return slug
    return None


# ---------- sort blocks and meters into neighborhoods
HB = collections.defaultdict(list)
for b in C['blocks']:
    x, y = O[0] + b[9][0] / 1e5, O[1] + b[9][1] / 1e5
    h = hood_of(x, y)
    if h: HB[h].append((b, x, y))
HM = collections.Counter(), collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
for m in C['meters']:
    h = hood_of(O[0] + m[0] / 1e5, O[1] + m[1] / 1e5)
    if not h: continue
    HM[0][h] += 1
    HM[1][h][C['rates'][m[2]]] += 1
    HM[2][h][C['limits'][m[3]]] += 1


# ticket types as people say them; the city's codes repeat themselves
VIOL = {'NO PARK/STREET CLEAN': 'Street cleaning', '8069B NO PARK ST CLN': 'Street cleaning', 'PREFERENTIAL PARKING': 'Permit parking',
        'RED ZONE': 'Red zone', 'METER EXP.': 'Expired meter', 'DISPLAY OF PLATES': 'Plates not displayed', 'NO PARKING': 'No parking'}
vname = lambda v: VIOL.get(v) or title(v)


def block_range(lo, hi):
    if not lo: return 'whole street'
    a, b = lo // 100 * 100, hi // 100 * 100 + 99
    return f'{a}–{b}' if b != a + 99 else f'{a} block'


def nice_limit(l):
    return {'15MIN': '15 min', '30MIN': '30 min', '1HR': '1 hour', '2HR': '2 hours', '4HR': '4 hours', '6HR': '6 hours',
            '10HR': '10 hours', '2HR-30MIN': '2 hours / 30 min'}.get(l, l)


def sweep_groups(b):
    """A block's sweeping as [(t0, t1, wk, days-bitmask)], one entry per distinct schedule."""
    g = collections.OrderedDict()
    for ri in b[4]:
        _, mask, t0, t1, wk, _ = C['routes'][ri]
        k = (t0, t1, wk)
        g[k] = g.get(k, 0) | mask
    return sorted((k[0], k[1], k[2], v) for k, v in g.items())


def days_txt(mask):
    d = [DOW[i] for i in range(7) if mask & (1 << i)]
    if len(d) == 7: return 'Every day'
    if d == DOW[1:6]: return 'Monday–Friday'
    return ' & '.join(x[:3] for x in d) if len(d) <= 2 else ', '.join(x[:3] for x in d)


def weeks_txt(wk):
    w = [n for n in (1, 2, 3, 4) if wk & (1 << (n - 1))]
    return 'Every week' if not w else ' & '.join(ordn(n) for n in w) + ' of the month'


def street_key(name):
    return re.sub(r'^(N|S|E|W) ', '', name)


CSS = """:root{--ground:#EEEAE1;--panel:#FBFAF6;--ink:#2A2926;--ink-2:#6B675F;--ink-3:#9A958B;--line:#E2DDD1;--moss:#4E7A52;--red:#C8433B}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ground:#1C1B18;--panel:#26241F;--ink:#EDE9DF;--ink-2:#A9A497;--ink-3:#7D786C;--line:#3B3831;--moss:#7FB08A;--red:#E0625A}}
:root[data-theme="dark"]{--ground:#1C1B18;--panel:#26241F;--ink:#EDE9DF;--ink-2:#A9A497;--ink-3:#7D786C;--line:#3B3831;--moss:#7FB08A;--red:#E0625A}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font:16px/1.6 "Helvetica Neue",Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:46rem;margin:0 auto;padding:56px 24px 96px}
a{color:var(--moss)}
.top{margin:0 0 32px;font-size:14px}
.top a{text-decoration:none;font-weight:600}
.top a:hover{text-decoration:underline}
h1{font:600 38px/1.1 "Helvetica Neue",Helvetica,Arial,sans-serif;letter-spacing:-.02em;margin:0 0 6px}
.sub{color:var(--ink-2);margin:0 0 28px}
h2{font:600 21px/1.25 "Helvetica Neue",Helvetica,Arial,sans-serif;letter-spacing:-.02em;margin:38px 0 10px}
p,li{color:var(--ink-2)}
p{margin:0 0 14px}
ul{margin:0 0 14px;padding-left:20px}
li{margin-bottom:6px}
strong{color:var(--ink);font-weight:600}
.callout{background:var(--panel);border-left:4px solid var(--red);border-radius:12px;padding:16px 18px;margin:0 0 14px}
.callout p:last-child{margin:0}
.btn{display:inline-block;background:var(--moss);color:var(--panel);font-weight:600;text-decoration:none;border-radius:10px;padding:10px 16px;margin:4px 0 8px}
.btn:hover{opacity:.9}
.wrap{overflow-x:auto;margin:0 0 14px}
table{border-collapse:collapse;width:100%;font-size:15px}
th,td{text-align:left;padding:7px 12px 7px 0;border-bottom:1px solid var(--line);vertical-align:top;color:var(--ink-2)}
th{color:var(--ink);font-weight:600;font-size:13px;letter-spacing:.02em;text-transform:uppercase}
td:first-child{color:var(--ink);font-weight:500}
.n{font-variant-numeric:tabular-nums;white-space:nowrap}
.near{display:flex;flex-wrap:wrap;gap:6px 14px;list-style:none;padding:0}
.near li{margin:0}
footer{border-top:1px solid var(--line);margin-top:48px;padding-top:18px;font-size:13.5px;color:var(--ink-3)}
footer p{color:var(--ink-3)}"""


def render(slug, name):
    blocks = HB[slug]
    n = len(blocks)
    swept = [t for t in blocks if t[0][4]]
    permit = [t for t in blocks if t[0][11] and not t[0][10][0]]
    zone = [t for t in blocks if t[0][10][0]]
    nmeter = HM[0][slug]
    tix_total = sum(sum(t[0][7][1::2]) for t in blocks)
    ruled = sum(1 for t in blocks if t[0][4] or t[0][6] or t[0][11] or t[0][10][0])
    tix_only = sum(1 for t in blocks if not (t[0][4] or t[0][6] or t[0][11] or t[0][10][0]) and t[0][7])
    none = n - ruled - tix_only
    cx = sum(t[1] for t in blocks) / n
    cy = sum(t[2] for t in blocks) / n
    map_url = f'/?at={cx:.4f},{cy:.4f},14.5'
    here = f'{SITE}/{slug}/'

    # --- sweeping
    by_day = collections.Counter()
    for t in swept:
        seen = set()
        for g in sweep_groups(t[0]):
            for i in range(7):
                if g[3] & (1 << i): seen.add(i)
        for i in seen: by_day[i] += 1
    streets = collections.defaultdict(lambda: collections.defaultdict(list))
    for t, _, _ in blocks:
        if not t[4]: continue
        sig = tuple(sweep_groups(t))
        streets[t[0]][sig].append((t[1], t[2]))
    sweep_rows = []
    for st in sorted(streets, key=lambda s: (street_key(s), s)):
        for sig, rng in sorted(streets[st].items(), key=lambda kv: min(r[0] for r in kv[1])):
            lo, hi = min(r[0] for r in rng), max(r[1] for r in rng)
            sched = ' · '.join(f'{days_txt(g[3])}, {fmt_min(g[0])}–{fmt_min(g[1])} ({weeks_txt(g[2])})' for g in sig)
            sweep_rows.append((title(st), block_range(lo, hi), sched))
    day_line = ', '.join(f'{DOW[i]} {round(100 * c / len(swept))}%' for i, c in by_day.most_common() if len(swept) and c / len(swept) >= .05)

    # --- permit
    ps = collections.defaultdict(lambda: [10 ** 9, 0, 0])
    for t, _, _ in permit:
        p = ps[t[0]]
        p[0] = min(p[0], t[1]); p[1] = max(p[1], t[2]); p[2] += t[11][0] + t[11][1]
    permit_rows = sorted(((title(k), block_range(v[0], v[1]), v[2]) for k, v in ps.items()), key=lambda r: (street_key(r[0].upper()), r[0]))

    # --- Dodger zone
    zs = collections.defaultdict(lambda: [10 ** 9, 0, 0])
    for t, _, _ in zone:
        z = zs[t[0]]
        z[0] = min(z[0], t[1]); z[1] = max(z[1], t[2]); z[2] = max(z[2], t[10][0])
    zone_rows = sorted(((title(k), block_range(v[0], v[1]), 'inferred from ticket patterns' if v[2] == 2 else 'on our street list') for k, v in zs.items()), key=lambda r: r[0])

    # --- tickets
    top_blocks = sorted(blocks, key=lambda t: -sum(t[0][7][1::2]))[:8]
    viol, vfine = collections.Counter(), {}
    for t, _, _ in blocks:
        for v, c in t[8]:
            viol[vname(v)] += c
            if v in C['fines']: vfine.setdefault(vname(v), C['fines'][v])
    top_viol = viol.most_common(6)

    # --- meters
    prices = [float(x) for r in HM[1][slug] for x in re.findall(r'\$(\d+(?:\.\d+)?)', r or '')]
    limits = [(k, v) for k, v in HM[2][slug].most_common(4) if k]

    h = []
    P = h.append
    P(f'<h1>{esc(name)} parking rules &amp; street sweeping</h1>')
    P(f'<p class="sub">Data snapshot: {date_txt(built)} · ticket records through {date_txt(cite_to)}</p>')
    P('<div class="callout"><p><strong>The posted sign is the authority. This page is not.</strong> '
      'It is built from public records and can be out of date or wrong. Read the curb before you leave your car.</p></div>')
    P(f'<p><a class="btn" href="{map_url}">See {esc(name)} on the map</a></p>')

    P('<h2>At a glance</h2><ul>')
    P(f'<li><strong>{n:,}</strong> street blocks mapped in {esc(name)}; <strong>{ruled:,}</strong> ({round(100 * ruled / n)}%) have a mapped rule: sweeping, meters, permit enforcement or a game-day zone.</li>')
    if swept: P(f'<li>Street sweeping is posted on <strong>{len(streets)}</strong> streets.' + (f' By block, the days are {esc(day_line)}.' if day_line else '') + '</li>')
    if nmeter: P(f'<li><strong>{nmeter:,}</strong> parking meters.</li>')
    if permit_rows: P(f'<li><strong>{len(permit_rows)}</strong> streets where permit-parking tickets are written routinely.</li>')
    if zone_rows: P(f'<li><strong>{len(zone_rows)}</strong> streets in the Dodger Stadium game-day zone.</li>')
    P(f'<li><strong>{tix_total:,}</strong> parking tickets written here in the six months to {date_txt(cite_to)}.</li></ul>')

    if swept:
        P(f'<h2>Street sweeping in {esc(name)}, by street</h2>')
        P('<p>Posted no-parking hours for street cleaning, from the City of Los Angeles’ sweeping routes. '
          'Where two days are listed, the city usually sweeps one side of the street each day; the data doesn’t say which side. '
          '“1st &amp; 3rd” means the first and third week of the month.</p>')
        P('<div class="wrap"><table><thead><tr><th>Street</th><th>Block</th><th>Day, hours</th></tr></thead><tbody>')
        for st, rg, sc in sweep_rows:
            P(f'<tr><td>{esc(st)}</td><td class="n">{esc(rg)}</td><td>{esc(sc)}</td></tr>')
        P('</tbody></table></div>')
    else:
        P(f'<h2>Street sweeping</h2><p>No posted sweeping routes are mapped in {esc(name)}.</p>')

    if permit_rows:
        P('<h2>Permit parking streets</h2>')
        P('<p>Los Angeles hasn’t published a permit-district map since 2015, and that map no longer matches the street. '
          'These streets are <strong>inferred from ticket history</strong>: permit-parking tickets written here routinely, '
          'on many days over many months. A permit street nobody has ticketed yet won’t appear, so this list is a floor, not a full list.</p>')
        P('<div class="wrap"><table><thead><tr><th>Street</th><th>Block</th><th>Permit tickets</th></tr></thead><tbody>')
        for st, rg, c in permit_rows:
            P(f'<tr><td>{esc(st)}</td><td class="n">{esc(rg)}</td><td class="n">{c}</td></tr>')
        P('</tbody></table></div>')

    if zone_rows:
        P('<h2>Dodger Stadium game-day zone</h2>')
        P('<p>No parking from four hours before and during events at Dodger Stadium, except with District D permits. '
          'This zone is in no city dataset; it is built from a hand-kept street list plus blocks where almost all no-parking tickets land on game days. '
          'Concerts and other stadium events count too.</p>')
        P('<div class="wrap"><table><thead><tr><th>Street</th><th>Block</th><th>Source</th></tr></thead><tbody>')
        for st, rg, src in zone_rows:
            P(f'<tr><td>{esc(st)}</td><td class="n">{esc(rg)}</td><td>{esc(src)}</td></tr>')
        P('</tbody></table></div>')

    if nmeter:
        P('<h2>Meters</h2>')
        bits = [f'{nmeter:,} metered spaces']
        if prices: bits.append(f'hourly rates run from ${min(prices):.2f} to ${max(prices):.2f}')
        if limits: bits.append('time limits ' + ', '.join(esc(nice_limit(k)) for k, _ in limits))
        P('<p>' + '; '.join(bits) + '. Meter rates vary by time of day. Live space-by-space availability is on the map.</p>')

    P('<h2>Where tickets get written</h2>')
    if top_viol:
        P('<p>Most common tickets here: ' + ', '.join(f'{esc(v)} ({c:,}' + (f', typically ${vfine[v]}' if v in vfine else '') + ')' for v, c in top_viol) + '.</p>')
    P('<div class="wrap"><table><thead><tr><th>Block</th><th>Tickets, 6 months</th><th>Most common</th></tr></thead><tbody>')
    for t, _, _ in top_blocks:
        tot = sum(t[7][1::2])
        P(f'<tr><td>{esc(title(t[0]))}' + (f' · {esc(block_range(t[1], t[2]))}' if t[1] else '') + f'</td><td class="n">{tot}</td><td>{esc(vname(t[8][0][0])) if t[8] else ""}</td></tr>')
    P('</tbody></table></div>')

    P('<h2>What this page can’t tell you</h2>')
    P(f'<p>Of {n:,} blocks, {tix_only:,} have tickets but no rule we can point to (a sign probably exists that the city’s map doesn’t carry), '
      f'and {none:,} have no records at all. <strong>No record is not the same as free parking.</strong> '
      'No dataset covers red curbs, hydrants, driveways, loading zones, or temporary no-parking signs. '
      '<a href="/terms.html">Terms &amp; data notes</a> explain what is inferred and what is official.</p>')

    others = [f'<li><a href="/{k}/">{esc(v)}</a></li>' for k, v in HOODS.items() if k != slug]
    P(f'<h2>Other neighborhoods</h2><ul class="near">{"".join(others)}</ul>')

    desc = f'{name} street-sweeping days by street, permit-enforced streets, meters and ticket hot spots, from LA open data. Snapshot {date_txt(built)}.'
    ttl = f'{name} Parking Rules &amp; Street Sweeping · CurbWatch LA'
    ttl_plain = f'{name} Parking Rules & Street Sweeping · CurbWatch LA'
    ld = {
        '@context': 'https://schema.org', '@type': 'WebPage', 'name': ttl_plain, 'url': here, 'description': desc,
        'dateModified': built, 'inLanguage': 'en',
        'isPartOf': {'@type': 'WebSite', 'name': 'CurbWatch LA', 'url': SITE + '/'},
        'about': {'@type': 'Place', 'name': f'{name}, Los Angeles'},
        'breadcrumb': {'@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'CurbWatch LA', 'item': SITE + '/'},
            {'@type': 'ListItem', 'position': 2, 'name': name, 'item': here}]},
    }
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{ttl}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{here}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="icon" href="/FAVICON2.png" type="image/png">
<link rel="apple-touch-icon" href="/FAVICON2.png">
<meta name="theme-color" content="#EEEAE1" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1C1B18" media="(prefers-color-scheme: dark)">
<meta name="color-scheme" content="light dark">
<meta property="og:type" content="website">
<meta property="og:site_name" content="CurbWatch LA">
<meta property="og:title" content="{ttl}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{here}">
<meta property="og:image" content="{SITE}/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{ttl}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{SITE}/og-image.png">
<script type="application/ld+json">
{json.dumps(ld, indent=1, ensure_ascii=False)}
</script>
<script>try{{const t=localStorage.getItem('curbwatch-theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<style>
{CSS}
</style>
</head>
<body>
<!-- Built by tools/neighborhoods.py; don't hand-edit. -->
<main>
  <p class="top"><a href="/">← CurbWatch LA</a></p>
{chr(10).join('  ' + x for x in h)}
  <footer>
    <p>Sources: City of Los Angeles sweeping routes, meters and parking citations; LA County; OpenStreetMap contributors (ODbL). Neighborhood outlines: LA Times Mapping L.A., an informal set, not official city limits. Not affiliated with the City of Los Angeles or LADOT.</p>
  </footer>
</main>
</body>
</html>
"""


def main():
    slugs = [s for s in HOODS if s in HB]
    missing = [s for s in HOODS if s not in HB]
    if missing: sys.exit(f'no blocks for {missing}; check tools/neighborhoods.geojson')
    for slug in slugs:
        d = ROOT / slug
        d.mkdir(exist_ok=True)
        page = render(slug, HOODS[slug])
        f = d / 'index.html'
        if not f.exists() or f.read_text() != page:
            f.write_text(page)
            print('wrote', f.relative_to(ROOT))
    urls = [(SITE + '/', built), (SITE + '/terms.html', None)] + [(f'{SITE}/{s}/', built) for s in slugs]
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(
        f'  <url>\n    <loc>{u}</loc>\n' + (f'    <lastmod>{lm}</lastmod>\n' if lm else '') + '  </url>\n' for u, lm in urls) + '</urlset>\n'
    (ROOT / 'sitemap.xml').write_text(sm)
    print('sitemap', len(urls), 'urls')


main()
