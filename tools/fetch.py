"""Download every source CurbWatch LA is built from into data/raw/. Then run build.py."""
import json, sys, time, datetime, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / 'data' / 'raw'
RAW.mkdir(parents=True, exist_ok=True)
BBOX = (-118.395, 34.045, -118.230, 34.115)
TODAY = datetime.date.today()
CITE_FROM = (TODAY - datetime.timedelta(days=183)).isoformat()
PERMIT_FROM = (TODAY - datetime.timedelta(days=548)).isoformat()
UA = {'User-Agent': 'CurbWatchLA/1.0'}


def get(url, data=None, timeout=300):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            if attempt == 3: raise
            print('  retry', url[:80], e, file=sys.stderr); time.sleep(5 * (attempt + 1))


def save(name, obj):
    (RAW / name).write_text(json.dumps(obj))
    n = len(obj) if isinstance(obj, list) else len(obj.get('elements', obj))
    print(f'{name}: {n}')


def arcgis(url, fields='*', bbox=BBOX):
    q = dict(where='1=1', geometry=','.join(map(str, bbox)), geometryType='esriGeometryEnvelope', inSR=4326,
             spatialRel='esriSpatialRelIntersects', returnIdsOnly='true', f='json')
    ids = sorted(json.loads(get(url + '/query?' + urllib.parse.urlencode(q)))['objectIds'] or [])
    chunks = [ids[i:i + 1000] for i in range(0, len(ids), 1000)]
    def page(c):
        body = urllib.parse.urlencode(dict(objectIds=','.join(map(str, c)), outFields=fields, returnGeometry='true', outSR=4326, f='json')).encode()
        return json.loads(get(url + '/query', body))['features']
    with ThreadPoolExecutor(6) as ex:
        return [f for r in ex.map(page, chunks) for f in r]


def socrata(dataset, where=None, select=None, page=50000):
    rows, off = [], 0
    while True:
        q = {'$limit': page, '$offset': off, '$order': ':id'}
        if where: q['$where'] = where
        if select: q['$select'] = select
        r = json.loads(get(f'https://data.lacity.org/resource/{dataset}.json?' + urllib.parse.urlencode(q)))
        rows += r; off += len(r)
        if len(r) < page: return rows


def overpass(body):
    return json.loads(get('https://overpass-api.de/api/interpreter', urllib.parse.urlencode({'data': body}).encode(), timeout=400))


S, W, N, E = BBOX[1], BBOX[0], BBOX[3], BBOX[2]
box = f'({S},{W},{N},{E})'
IN_BOX = f'loc_lat between {S} and {N} and loc_long between {W} and {E}'

# LA City: sweeping routes, street blocks with address ranges, city lots
save('sweep.json', arcgis('https://services1.arcgis.com/PTh9WC0Sf2WS7AAq/arcgis/rest/services/Posted_Street_Sweeping_Routes_Update/FeatureServer/0',
                          'Route,Posted_Time,Boundaries,Posted_Day,Weeks,Odd_Even,Day_Short,Route_Type'))
save('centerline.json', arcgis('https://maps.lacity.org/lahub/rest/services/Street_Information/MapServer/36',
                               'ADLF,ADLT,ADRF,ADRT,TDIR,STNAME,STSFX,SFXDIR,ZIP_L,ZIP_R,STATUS'))
save('lalots.json', arcgis('https://maps.lacity.org/lahub/rest/services/LADOT/MapServer/2'))
save('cities.json', arcgis('https://public.gis.lacounty.gov/public/rest/services/LACounty_Dynamic/Political_Boundaries/MapServer/19', 'CITY_NAME,CITY_TYPE'))

# LADOT meters, live occupancy, citations
save('meters.json', socrata('s49e-q6j2', where=f'within_box(latlng,{N},{W},{S},{E})'))
save('occ.json', socrata('e7h6-4a3e'))
save('cit.json', socrata('4f5p-udkv', select='issue_date,issue_time,violation_description,fine_amount,loc_lat,loc_long,location',
                         where=f"issue_date between '{CITE_FROM}' and '{TODAY + datetime.timedelta(days=1)}' and {IN_BOX}"))
save('permit_cit.json', socrata('4f5p-udkv', select='issue_date,issue_time,violation_description,loc_lat,loc_long,location',
                                where=f"issue_date between '{PERMIT_FROM}' and '{TODAY + datetime.timedelta(days=1)}' and {IN_BOX} "
                                      "and violation_description in ('PREFERENTIAL PARKING','OVNIGHT PRK W/OUT PE')"))

# West Hollywood: permit blocks with hours, districts, sweeping lines, public lots
WH = 'https://gis.weho.org/arcgis/rest/services'
wbox = (-118.40, 34.07, -118.34, 34.11)
weho = {'permit': arcgis(WH + '/Parking/Parking/MapServer/0', 'Name,PopupInfo,Enforcement_Hrs', wbox),
        'districts': arcgis(WH + '/Parking/Parking/MapServer/1', 'District', wbox), 'sweep': []}
for i in range(6):
    for f in arcgis(WH + f'/DPW/Street_Sweeping/MapServer/{i}', 'Zone,Day,Schedule', wbox):
        f['attributes']['layer'] = i; weho['sweep'].append(f)
save('weho.json', weho)
save('weho_lots.json', json.loads(get('https://data.weho.org/resource/fiyy-83j4.json?$limit=500')))

# LA County address points (search)
ap = arcgis('https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/eGIS_Addressing_ADDRESS_POINTSv2/FeatureServer/0',
            'Number,NumSuffix,PreDirAbbr,StreetName,PostTypeAbbr,PostDirAbbr,LegalComm')
save('addrpts.json', [[f['attributes'][k] for k in ('Number', 'NumSuffix', 'PreDirAbbr', 'StreetName', 'PostTypeAbbr', 'PostDirAbbr', 'LegalComm')]
                      + [round(f['geometry']['x'], 6), round(f['geometry']['y'], 6)] for f in ap if f.get('geometry')])

# OpenStreetMap: streets, parks/water, parking lots, plate-reader cameras (the data DeFlock shows)
save('osm_roads.json', overpass(f'[out:json][timeout:180];(way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link|service)$"]{box};);out tags geom;'))
save('osm_green.json', overpass(f'[out:json][timeout:180];(way["leisure"~"^(park|golf_course)$"]{box};relation["leisure"="park"]{box};way["natural"="water"]{box};relation["natural"="water"]{box};way["landuse"="cemetery"]{box};);out tags geom;'))
save('osm_parking.json', overpass(f'[out:json][timeout:120];(nwr["amenity"="parking"]{box};nwr["parking"]["amenity"!="parking"]{box};);out tags center;'))
# named places for search (businesses, parks, schools, stations...), so people can type a place instead of an address
PLACES = ('["amenity"]', '["shop"]', '["leisure"~"^(park|garden|playground|sports_centre|stadium|fitness_centre|dog_park|swimming_pool|pitch|golf_course|nature_reserve)$"]',
          '["tourism"]', '["historic"]', '["office"]', '["healthcare"]', '["craft"]', '["club"]',
          '["railway"="station"]', '["public_transport"="station"]', '["landuse"="retail"]', '["building"~"^(church|school|hospital|university|college|civic|public|stadium|hotel|retail|commercial)$"]')
save('osm_places.json', overpass('[out:json][timeout:240];(' + ''.join(f'nwr["name"]{t}{box};' for t in PLACES) + ');out tags center;'))
save('alpr.json', overpass(f'[out:json][timeout:120];(nwr["surveillance:type"="ALPR"]{box};nwr["surveillance:type"="alpr"]{box};);out tags center;'))

# Dodger Stadium home dates (District D game-day restrictions) are kept by hand in tools/dodgers-home.json —
# schedule facts, no API terms attached. Add next season from the published schedule.

(RAW / 'meta.json').write_text(json.dumps({'fetched': datetime.datetime.now().isoformat(timespec='minutes'), 'cite_from': CITE_FROM, 'permit_from': PERMIT_FROM}))
print('done — now run: python tools/build.py')
