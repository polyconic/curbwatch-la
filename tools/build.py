import json, math, re, collections, datetime, os
from pathlib import Path
import numpy as np
from shapely.geometry import LineString, Point, Polygon, MultiPolygon, shape
from shapely.strtree import STRtree
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT / 'data' / 'raw')
RANGE = json.load(open('meta.json'))

LON0, LAT0 = -118.40, 34.04
K = math.cos(math.radians(34.08))

def q(lon, lat):
    return round((lon - LON0) * 1e5), round((lat - LAT0) * 1e5)

def proj(lon, lat):
    return ((lon + 118.3) * K * 111320, (lat - 34.08) * 110574)

def unproj(x, y):
    return (x / (K * 111320) - 118.3, y / 110574 + 34.08)

def enc(coords):
    out = []; px = py = 0
    for lon, lat in coords:
        x, y = q(lon, lat)
        out += [x - px, y - py]; px, py = x, y
    return out

def simp_line(coords, tol=1.5):
    ls = LineString([proj(*c) for c in coords])
    s = ls.simplify(tol)
    return [unproj(*c) for c in s.coords]

def simp_ring(ring, tol):
    p = Polygon([proj(*c) for c in ring])
    if not p.is_valid: p = p.buffer(0)
    s = p.simplify(tol)
    if s.is_empty: return None
    if s.geom_type == 'MultiPolygon': s = max(s.geoms, key=lambda g: g.area)
    return [unproj(*c) for c in s.exterior.coords]

BBOX = (-118.395, 34.045, -118.230, 34.115)
def inb(lon, lat, pad=0.0):
    return BBOX[0]-pad <= lon <= BBOX[2]+pad and BBOX[1]-pad <= lat <= BBOX[3]+pad

D = {}

# ---------- OSM roads + labels
CLS = {'motorway':0,'trunk':1,'motorway_link':0,'trunk_link':1,'primary':1,'primary_link':1,'secondary':2,'secondary_link':2,
       'tertiary':3,'tertiary_link':3,'unclassified':4,'residential':4,'living_street':4}
ABBR = [('Street','St'),('Avenue','Ave'),('Boulevard','Blvd'),('Drive','Dr'),('Place','Pl'),('Road','Rd'),('Terrace','Ter'),
        ('Court','Ct'),('Lane','Ln'),('Parkway','Pkwy'),('Circle','Cir'),('Freeway','Fwy'),('North ','N '),('South ','S '),('East ','E '),('West ','W ')]
def short(n):
    for a, b in ABBR: n = re.sub(r'\b' + a + r'\b', b, n) if not a.endswith(' ') else (b + n[len(a):] if n.startswith(a) else n)
    return n
roads = []; labels = []
for e in json.load(open('osm_roads.json'))['elements']:
    c = CLS.get(e['tags']['highway'])
    if c is None: continue
    pts = [(g['lon'], g['lat']) for g in e['geometry']]
    s = simp_line(pts, 1.5)
    roads.append([c] + enc(s))
    nm = e['tags'].get('name')
    if nm and not e['tags']['highway'].endswith('_link'):
        ls = LineString([proj(*p) for p in s])
        if ls.length > 70:
            m = ls.interpolate(0.5, normalized=True)
            a = ls.interpolate(max(0, ls.length/2 - 15)); b = ls.interpolate(min(ls.length, ls.length/2 + 15))
            ang = math.degrees(math.atan2(b.y - a.y, b.x - a.x))
            if ang > 90: ang -= 180
            if ang < -90: ang += 180
            lon, lat = unproj(m.x, m.y)
            labels.append([*q(lon, lat), round(ang), c, short(nm), round(ls.length)])
D['roads'] = roads
D['labels'] = labels

# ---------- green / water
green = []
for e in json.load(open('osm_green.json'))['elements']:
    t = e.get('tags', {})
    kind = 1 if t.get('natural') == 'water' else 0
    rings = []
    if e['type'] == 'way' and 'geometry' in e:
        rings = [[(g['lon'], g['lat']) for g in e['geometry']]]
    elif e['type'] == 'relation':
        for m in e.get('members', []):
            if m.get('role') == 'outer' and 'geometry' in m:
                rings.append([(g['lon'], g['lat']) for g in m['geometry']])
    for r in rings:
        if len(r) < 4 or r[0] != r[-1]: continue
        s = simp_ring(r, 4)
        if s and Polygon([proj(*p) for p in s]).area > 1500:
            green.append([kind] + enc(s))
D['green'] = green

# ---------- city boundaries (WeHo outline + LA city polygon for lookups)
cities = json.load(open('cities.json'))
city_polys = {}
for f in cities:
    nm = f['attributes']['CITY_NAME']
    polys = [Polygon(r) for r in f['geometry']['rings']]
    city_polys[nm] = polys
weho_rings = []
for r in [f for f in cities if f['attributes']['CITY_NAME'] == 'West Hollywood'][0]['geometry']['rings']:
    s = simp_ring(r, 3)
    if s and Polygon([proj(*p) for p in s]).area > 20000: weho_rings.append(enc(s))
D['weho'] = weho_rings

# Beverly Hills is inside the bbox but outside coverage — it publishes none of this, so the app
# marks it out of coverage rather than implying its curbs are unrestricted.
bh_rings = []
for r in [f for f in cities if f['attributes']['CITY_NAME'] == 'Beverly Hills'][0]['geometry']['rings']:
    s2 = simp_ring(r, 3)
    if s2 and Polygon([proj(*p) for p in s2]).area > 20000: bh_rings.append(enc(s2))
D['bh'] = bh_rings

# ---------- LA sweep routes
DAYS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
def tmin(s):
    s = s.strip().lower().replace('-pm', 'pm').replace(' ', '')
    m = re.match(r'(\d+)(?::(\d+))?(am|pm)', s)
    h = int(m.group(1)) % 12 + (12 if m.group(3) == 'pm' else 0)
    return h * 60 + int(m.group(2) or 0)
def dmask(s):
    s = s.strip()
    if s == 'Daily': return 127
    if s in ('Monday to Friday', 'Monday-Friday'): return 0b0111110
    if s == 'Tuesday-Thursday': return 0b0011100
    return 1 << DAYS.index(s)
sweep = json.load(open('sweep.json'))
routes = []; route_polys = []
for f in sweep:
    a = f['attributes']
    # StreetsLA classes four downtown routes as Route_Type "Downtown": swept overnight, but not
    # posted no-parking the way the rest are. We have no sign to show there, so don't draw one.
    if a['Route_Type'] == 'Downtown': continue
    t0, t1 = [tmin(x) for x in re.split(r'\s+-\s+', a['Posted_Time'])]
    wk = {'1 & 3': 0b0101, '2 & 4': 0b1010, 'Weekly': 0}[a['Weeks']]
    routes.append([a['Route'], dmask(a['Posted_Day']), t0, t1, wk, a['Boundaries'] or ''])
    polys = [Polygon(r) for r in f['geometry']['rings']]
    route_polys.append(unary_union([p if p.is_valid else p.buffer(0) for p in polys]))
D['routes'] = routes

# LA's permit-district map hasn't been published since 2015 and doesn't match the curb; permit streets come from tickets below.
D['ppd'] = []

# ---------- LA centerline blocks
cl = json.load(open('centerline.json'))
blocks = []; block_geoms = []
def nm_of(a):
    parts = [a['TDIR'], a['STNAME'], a['STSFX'], a['SFXDIR']]
    return ' '.join(p.strip() for p in parts if p and p.strip())
for f in cl:
    a = f['attributes']
    if not f.get('geometry') or not a['STNAME']: continue
    path = f['geometry']['paths'][0]
    if len(path) < 2: continue
    s = simp_line(path, 1.5)
    ls = LineString([proj(*p) for p in s])
    if ls.length < 5: continue
    nums = [a[k] for k in ('ADLF','ADLT','ADRF','ADRT') if a[k]]
    blocks.append({'name': nm_of(a), 'lo': min(nums) if nums else 0, 'hi': max(nums) if nums else 0, 'enc': enc(s), 'len': ls.length})
    block_geoms.append(ls)
btree = STRtree(block_geoms)
print('blocks', len(blocks))

# sweep routes per block via side samples
rtree = STRtree(route_polys)
samples = []; owner = []
for i, ls in enumerate(block_geoms):
    m = ls.interpolate(0.5, normalized=True)
    a = ls.interpolate(max(0, ls.length/2 - 3)); b = ls.interpolate(min(ls.length, ls.length/2 + 3))
    dx, dy = b.x - a.x, b.y - a.y; n = math.hypot(dx, dy) or 1
    nx, ny = -dy / n, dx / n
    for side in (1, -1):
        samples.append(Point(*unproj(m.x + nx * 9 * side, m.y + ny * 9 * side))); owner.append(i)
pi, ri = rtree.query(samples, predicate='within')
bsweep = collections.defaultdict(set)
for p, r in zip(pi, ri): bsweep[owner[p]].add(int(r))

# ---------- match tickets to blocks by the address the officer wrote, not just GPS
import shapely
DIRS = {'N', 'S', 'E', 'W', 'NORTH', 'SOUTH', 'EAST', 'WEST'}
SUFS = {'ST', 'STREET', 'AVE', 'AV', 'AVENUE', 'BL', 'BLVD', 'BOULEVARD', 'DR', 'DRIVE', 'PL', 'PLACE', 'RD', 'ROAD', 'TER', 'TERR', 'TERRACE',
        'WAY', 'WY', 'CT', 'COURT', 'LN', 'LANE', 'CIR', 'CIRCLE', 'PKWY', 'PARKWAY', 'TRL', 'TRAIL', 'WALK', 'ALY', 'ALLEY', 'PLZ', 'PLAZA'}
def core(s):
    return ' '.join(t for t in re.sub(r'[^A-Z0-9 ]', ' ', (s or '').upper()).split() if t not in DIRS and t not in SUFS and not t.isdigit())
def parse_loc(loc):
    loc = (loc or '').upper().split('/')[0].strip()
    m = re.match(r'^(\d+)\s+(.*)$', loc)
    return (int(m.group(1)), core(m.group(2))) if m else (None, core(loc))
block_core = [core(b['name']) for b in blocks]
def name_ok(a, b):
    return bool(a and b) and (a == b or (len(a) >= 5 and len(b) >= 5 and (a.startswith(b) or b.startswith(a))))
def match_blocks(pts, locs, fallback=0):
    gi_p, gi_b = btree.query(pts, predicate='dwithin', distance=90)
    dist = shapely.distance(np.array(pts, dtype=object)[gi_p], np.array(block_geoms, dtype=object)[gi_b])
    order = np.lexsort((dist, gi_p)); gi_p, gi_b, dist = gi_p[order], gi_b[order], dist[order]
    out = [None] * len(pts); starts = np.flatnonzero(np.r_[True, gi_p[1:] != gi_p[:-1]]); ends = np.r_[starts[1:], len(gi_p)]
    for s0, e0 in zip(starts, ends):
        p = gi_p[s0]; num, nm = locs[p]; best = None
        for k in range(s0, e0):
            b = gi_b[k]
            if not name_ok(nm, block_core[b]): continue
            if num is None or blocks[b]['lo'] <= num <= blocks[b]['hi']: best = b; break
            if best is None and dist[k] < 60: best = b
        if best is None and fallback and dist[s0] < fallback: best = gi_b[s0]
        out[p] = None if best is None else int(best)
    return out

# ---------- citations
def cat(v):
    v = (v or '').upper()
    if 'CLEAN' in v or 'ST CLN' in v: return 0
    if 'PREF' in v or 'OVNIGHT' in v or 'OVERNIGHT' in v or 'PERMIT' in v or 'PRK W/OUT PE' in v: return 1
    if 'METER' in v or 'MTR' in v or 'TIME LIMIT' in v or 'OVERTIME' in v or 'OVER TIME' in v: return 2
    if any(k in v for k in ('RED ZONE','RED CURB','NO PARK','NO STOP','STOP/STAND','STAND','GRIDLOCK','GRID LOCK','BUS','WHITE ZONE',
                            'YELLOW ZONE','GREEN ZONE','LOAD','TAXI','PROH','TOW','CHARGING','CHRGING','FIRE LANE')): return 3
    return 4
cit = json.load(open('cit.json'))
cpts = []; cmeta = []; fines = collections.defaultdict(collections.Counter); vio = collections.defaultdict(collections.Counter)
latest = ''
for r in cit:
    try:
        lat, lon = float(r['loc_lat']), float(r['loc_long'])
        t = int(r.get('issue_time') or -1)
    except (KeyError, ValueError, TypeError):
        continue
    if t < 0 or t >= 2400 or not inb(lon, lat): continue
    d = datetime.date.fromisoformat(r['issue_date'][:10])
    dow = (d.weekday() + 1) % 7
    c = cat(r.get('violation_description'))
    cpts.append(Point(proj(lon, lat))); cmeta.append((c, dow * 24 + t // 100, r.get('violation_description') or '', r.get('fine_amount'), r['issue_date'][:10], parse_loc(r.get('location'))))
    latest = max(latest, r['issue_date'][:10])
cmatch = match_blocks(cpts, [m[5] for m in cmeta], fallback=20)
games = json.load(open(ROOT / 'tools' / 'dodgers-home.json'))['games']
games.sort()
game_days = {g[0][:10] for g in games}
D['games'] = games
bev = collections.defaultdict(lambda: [0, 0])
bcit = collections.defaultdict(collections.Counter)
bvio = collections.defaultdict(collections.Counter)
snapped = 0
for p, b in enumerate(cmatch):
    if b is None: continue
    snapped += 1
    c, slot, v, fine, day, _ = cmeta[p]
    if v in ('NO PARKING', 'PREFERENTIAL PARKING'): bev[int(b)][0 if day in game_days else 1] += 1
    bcit[int(b)][c * 168 + slot] += 1
    bvio[int(b)][v] += 1
    if fine: fines[v][fine] += 1
print('citations', len(cpts), 'snapped', snapped, 'latest', latest)

# ---------- meters
meters = json.load(open('meters.json'))
occ = {o['spaceid']: o for o in json.load(open('occ.json'))}
occ_time = max(o['eventtime'] for o in occ.values())
rates = []; limits = []; faces = []
def ix(lst, v):
    if v not in lst: lst.append(v)
    return lst.index(v)
mout = []; mpts = []
for m in meters:
    lat, lon = float(m['latlng']['latitude']), float(m['latlng']['longitude'])
    o = occ.get(m['spaceid'])
    st = 0
    age = 0
    if o:
        st = {'OCCUPIED': 1, 'VACANT': 2}.get(o['occupancystate'], 3)
        age = round((datetime.datetime.fromisoformat(occ_time) - datetime.datetime.fromisoformat(o['eventtime'])).total_seconds() / 60)
    mout.append([*q(lon, lat), ix(rates, m.get('raterange') or '?'), ix(limits, m.get('timelimit') or '?'), 1 if m['metertype'] == 'Multi-Space' else 0,
                 ix(faces, m.get('blockface') or ''), m['spaceid'], st, age, ('TOD' if m.get('ratetype') == 'TOD' else 'JUMP' if m.get('ratetype') == 'JUMP' else '')])
    mpts.append(Point(proj(lon, lat)))
idx = btree.query_nearest(mpts, max_distance=25)
bmet = collections.defaultdict(list)
for p, b in zip(idx[0], idx[1]): bmet[int(b)].append(int(p))
D['meters'] = mout; D['rates'] = rates; D['limits'] = limits; D['faces'] = faces
D['occTime'] = occ_time

# ---------- permit enforcement detected from 18 months of permit citations
pc_pts = []; pc_meta = []; pc_last = ''
for r in json.load(open('permit_cit.json')):
    try:
        lat, lon = float(r['loc_lat']), float(r['loc_long']); t = int(r.get('issue_time') or -1)
    except (KeyError, ValueError, TypeError):
        continue
    if t < 0 or t >= 2400: continue
    pc_pts.append(Point(proj(lon, lat))); pc_meta.append((1 if 'OVNIGHT' in r['violation_description'] else 0, t // 100, r['issue_date'][:10], parse_loc(r.get('location'))))
    pc_last = max(pc_last, r['issue_date'][:10])
pmatch = match_blocks(pc_pts, [m[3] for m in pc_meta])
bperm = {}; bdays = collections.defaultdict(set)
for p, b in enumerate(pmatch):
    if b is None: continue
    kind, hr, day, _ = pc_meta[p]
    e = bperm.setdefault(b, [0, 0, [0] * 24, ''])
    e[kind] += 1; e[2][hr] += 1; e[3] = max(e[3], day); bdays[b].add(day)
print('permit tickets matched by address', sum(1 for x in pmatch if x is not None), 'of', len(pmatch))
# Enough tickets, on enough separate days, spread over enough months that routine enforcement is
# the only explanation. A few tickets on one or two days is as easily a miscoded violation or a
# neighboring block's address, and calling that a permit street is a guess.
PERMIT_MIN = dict(tickets=8, days=5, months=3)
bmonths = {b: {d[:7] for d in days} for b, days in bdays.items()}
bperm = {b: e for b, e in bperm.items()
         if e[0] + e[1] >= PERMIT_MIN['tickets'] and len(bdays[b]) >= PERMIT_MIN['days'] and len(bmonths[b]) >= PERMIT_MIN['months']}
D['permitRange'] = [RANGE['permit_from'], pc_last]
print('confirmed permit blocks', len(bperm))

# ---------- Dodger Stadium District D special-event zone
ZONE_D = {'DOUGLAS ST', 'QUINTERO ST', 'SUTHERLAND ST', 'MACBETH ST', 'ELYSIAN PARK DR', 'MONTANA ST', 'SCOTT AVE'}
STADIUM = proj(-118.2400, 34.0739)
bzone = {}
for i, b in enumerate(blocks):
    base = re.sub(r'^(N|S|E|W) ', '', b['name'])
    m = block_geoms[i].interpolate(0.5, normalized=True); lon, lat = unproj(m.x, m.y)
    g, o = bev.get(i, (0, 0))
    if base in ZONE_D and -118.2530 < lon < -118.2480 and 34.0738 < lat < 34.0800 and not (base == 'DOUGLAS ST' and b['hi'] < 1300):
        bzone[i] = 1
    elif g >= 8 and g / (g + o) >= 0.85 and math.hypot(m.x - STADIUM[0], m.y - STADIUM[1]) < 2200:
        bzone[i] = 2
print('zone D blocks', sorted(set(blocks[i]['name'] + f" {blocks[i]['lo']}" for i, z in bzone.items() if z == 1)))
print('detected', sorted(set(blocks[i]['name'] + f" {blocks[i]['lo']}" for i, z in bzone.items() if z == 2)))

# ---------- assemble blocks
bout = []
for i, b in enumerate(blocks):
    cc = bcit.get(i, {})
    flat = []
    for k in sorted(cc): flat += [k, cc[k]]
    top = [[v, n] for v, n in bvio.get(i, collections.Counter()).most_common(4)]
    bout.append([b['name'], b['lo'], b['hi'], round(b['len']), sorted(bsweep.get(i, [])), [], len(bmet.get(i, [])), flat, top, b['enc'],
                 [bzone.get(i, 0), *bev.get(i, (0, 0))],
                 (lambda e: [e[0], e[1], e[2], e[3]] if e else 0)(bperm.get(i))])
D['blocks'] = bout
D['fines'] = {v: int(c.most_common(1)[0][0]) for v, c in fines.items() if c and str(c.most_common(1)[0][0]).isdigit()}
D['citeRange'] = [RANGE['cite_from'], latest]

# ---------- WeHo
weho = json.load(open('weho.json'))
def parse_hours(s):
    rules = []
    for seg in re.split(r';', s or ''):
        seg = seg.strip()
        if not seg: continue
        typ = 'permit'
        if seg.lower().startswith('2hr'):
            typ = '2hr'; seg = seg[3:].strip()
            # a bare "2hr" (9040-9072 Harland) has no hours; every other WeHo 2hr rule is daytime, mostly 7am-7pm
            if not seg: rules.append([typ, 127, 420, 1140]); continue
        # 82 blocks (districts 1R, 2R, 3R, 6R) say just "24 Hours", with no days: permit-only around the clock
        if seg.lower().startswith('24'): seg = 'Everyday ' + seg
        m = re.match(r'(Everyday|Mon-Sun|Mon-Sat|Mon-Fri|M-F|Sat-Sun|Sun)\s+(.*)', seg)
        if not m: continue
        days = {'Everyday':127,'Mon-Sun':127,'Mon-Sat':0b1111110,'Mon-Fri':0b0111110,'M-F':0b0111110,'Sat-Sun':0b1000001,'Sun':1}[m.group(1)]
        tm = m.group(2).strip()
        if tm.lower().startswith('24'): t0, t1 = 0, 1440
        else:
            a, b = tm.split('-'); t0, t1 = tmin(a), tmin(b)
        rules.append([typ, days, t0, t1])
    return rules
wp = []
for f in weho['permit']:
    a = f['attributes']
    if not f.get('geometry'): continue
    dist = re.search(r'District: ([^<]+)', a['PopupInfo'] or '')
    # Enforcement_Hrs is blank on a few blocks (Palm Ave, 801-899 Larrabee) whose popup still carries the hours
    hrs = (a['Enforcement_Hrs'] or '').strip() or (lambda m: m.group(1).strip() if m else '')(re.search(r'Permit-Only Hours: ([^<]+)', a['PopupInfo'] or ''))
    for path in f['geometry']['paths']:
        wp.append([a['Name'] or '', dist.group(1).strip() if dist else '', hrs, parse_hours(hrs), enc(simp_line(path, 1))])
D['wehoPermit'] = wp
wd = []
for f in weho['districts']:
    for r in f['geometry']['rings']:
        s = simp_ring(r, 3)
        if s: wd.append([f['attributes']['District']] + enc(s))
D['wehoDistricts'] = wd
ws = []
for f in weho['sweep']:
    a = f['attributes']
    if not f.get('geometry'): continue
    sch = a['Schedule'].replace('12-pm', '12pm')
    t0, t1 = [tmin(x) for x in sch.split('-')]
    for path in f['geometry']['paths']:
        ws.append([a['Zone'] or '', dmask(a['Day']), t0, t1, a['Day'], enc(simp_line(path, 1))])
D['wehoSweep'] = ws

# ---------- lots / garages
lots = []
for f in json.load(open('lalots.json')):
    a = f['attributes']
    if a['Status'] != 'Operational': continue
    lots.append(dict(k='city', n=a['LotName'], a=a['Address'], p=[*q(float(a['Lon']), float(a['Lat']))], h=a['Hours'].strip(), r=(a['HourlyCost'] or '').strip(),
                     d=(a['DailyCost'] or '').strip(), s=(a['Spaces'] or '').replace(',', ''), sf=(a['SpecialFeatures'] or '').strip(), src='LADOT'))
for r in json.load(open('weho_lots.json')):
    loc = r.get('location') or {}
    if 'latitude' not in loc: continue
    addr = json.loads(loc.get('human_address') or '{}').get('address', '')
    lots.append(dict(k='city', n=r['lot_name'], a=addr.replace(' West', ''), p=[*q(float(loc['longitude']), float(loc['latitude']))], s=r.get('total_spaces', ''),
                     ph=r.get('phone_number', ''), src='WeHo'))
for e in json.load(open('osm_parking.json'))['elements']:
    t = e.get('tags', {})
    if t.get('amenity') != 'parking': continue
    acc = t.get('access')
    if acc in ('private', 'no', 'permit', 'unknown', 'delivery'): continue
    kind = t.get('parking')
    if not (t.get('name') or t.get('fee') or kind in ('multi-storey', 'underground', 'rooftop') or acc in ('yes', 'customers', 'permissive') or t.get('capacity')):
        continue
    c = e.get('center') or {'lat': e.get('lat'), 'lon': e.get('lon')}
    if c['lat'] is None or not inb(c['lon'], c['lat']): continue
    lots.append(dict(k='garage' if kind in ('multi-storey', 'underground', 'rooftop') else 'lot', n=t.get('name') or t.get('operator') or '',
                     p=[*q(c['lon'], c['lat'])], s=t.get('capacity', ''), fee=t.get('fee', ''), acc=acc or '', op=t.get('operator', ''),
                     h=t.get('opening_hours', ''), a=' '.join(x for x in (t.get('addr:housenumber'), t.get('addr:street')) if x), src='OSM'))
D['lots'] = lots

# ---------- addresses
seen = {}
for num, suf, pre, st, typ, post, comm, lon, lat in json.load(open('addrpts.json')):
    if comm == 'Beverly Hills' or not num or not st or not num.isdigit(): continue
    key = ' '.join(x.upper() for x in (pre, st, typ, post) if x)
    seen.setdefault((key, int(num)), (lon, lat))
streets = collections.defaultdict(list)
for (key, n), (lon, lat) in seen.items(): streets[key].append((n, lon, lat))
addr = []
for key in sorted(streets):
    pts = sorted(streets[key])
    flat = []; pn = 0; px = py = 0
    for n, lon, lat in pts:
        x, y = q(lon, lat)
        flat += [n - pn, x - px, y - py]; pn, px, py = n, x, y
    addr.append([key, flat])
D['addr'] = addr

# ---------- ALPR cameras (OSM surveillance:type=ALPR, the data behind DeFlock)
alpr = []
for e in json.load(open('alpr.json'))['elements']:
    t = e.get('tags', {})
    lat, lon = (e['lat'], e['lon']) if 'lat' in e else (e['center']['lat'], e['center']['lon'])
    if not inb(lon, lat): continue
    blob = ' '.join(t.get(k, '') for k in ('manufacturer', 'brand', 'operator', 'description', 'note'))
    dirs = []
    for d in re.split(r'[;,]', t.get('direction', '') or t.get('camera:direction', '')):
        d = d.strip()
        card = {'N':0,'NNE':22,'NE':45,'ENE':67,'E':90,'ESE':112,'SE':135,'SSE':157,'S':180,'SSW':202,'SW':225,'WSW':247,'W':270,'WNW':292,'NW':315,'NNW':337}
        if re.fullmatch(r'-?\d+(\.\d+)?', d): dirs.append(round(float(d)) % 360)
        elif d.upper() in card: dirs.append(card[d.upper()])
    alpr.append([*q(lon, lat), 1 if 'flock' in blob.lower() else 0, dirs, t.get('manufacturer') or t.get('brand') or '', t.get('operator') or '', e['id']])
D['alpr'] = alpr
print('alpr', len(alpr), sum(a[2] for a in alpr))

D['meta'] = dict(built=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), lon0=LON0, lat0=LAT0)
s = json.dumps(D, separators=(',', ':'))
NOTICE = ('/*! CurbWatch LA data snapshot. Street geometry, labels, parks/water, off-street lots tagged src "OSM" and the alpr\n'
          ' * (plate-reader) points are derived from OpenStreetMap, (c) OpenStreetMap contributors, licensed under the\n'
          ' * Open Database License (ODbL) 1.0 - https://opendatacommons.org/licenses/odbl/1-0/ . Those fields form a\n'
          ' * derivative database: redistribute them under ODbL. Remaining layers (sweeping routes, street blocks,\n'
          ' * meters, citations, city lots, addresses, West Hollywood permit/sweeping data) come from City of Los Angeles,\n'
          ' * LA County and City of West Hollywood open data under their own terms. See DATA-LICENSE.md. */\n')
(ROOT / 'curb-data.js').write_text(NOTICE + 'window.CURB=' + s + ';')
print('size MB', len(s) / 1e6, {k: len(json.dumps(v, separators=(',', ':'))) // 1000 for k, v in D.items()})
