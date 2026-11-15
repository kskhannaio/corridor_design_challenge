"""Planned and existing structures from the elevated-corridor tender drawings, for the "What's planned" tab.

The drawings (B-SMILE tender, Schedule A-I, 17 vector CAD sheets at 1:2000) are georeferenced and traced in the
SUMO repo (src/sumo_poc/qgis/contract/: register.py, ocr.py, extract.py, name_parts.py). This script copies its two outputs
into one site data file, rounding coordinates to ~10 cm:

  data/plans.geojson
    kind=structure  layer, what, area_m2; named parts also carry conf (high / medium / low) and basis (why that name)
                    layers: proposed_deck, proposed_deck_level2, existing_flyover, ejipura_flyover, underpass,
                    metro, metro_tunnel, bmrcl_land, land_acquisition
    kind=label      label, source, ocr (true if the label is drawn as linework and was read by OCR),
                    moved (true if name_parts.py moved it from where the drawing writes it onto the structure it names)

Usage: python3 scripts/build_plans.py [path/to/sumo_poc/qgis/contract/out]
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', '..', 'sumo_poc', 'qgis', 'contract', 'out')

def rnd(c):
    return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 6), round(c[1], 6)]

feats = []
for f in json.load(open(os.path.join(SRC, 'contract_structures.geojson')))['features']:
    p = f['properties']
    props = {'kind': 'structure', 'layer': p['layer'], 'what': p['what'], 'area_m2': p['area_m2']}
    if p.get('name_confidence'): props.update(conf=p['name_confidence'], basis=p['name_basis'])
    feats.append({'type': 'Feature', 'properties': props,
                  'geometry': {'type': f['geometry']['type'], 'coordinates': rnd(f['geometry']['coordinates'])}})
for f in json.load(open(os.path.join(SRC, 'contract_labels.geojson')))['features']:
    p = f['properties']
    feats.append({'type': 'Feature', 'properties': {'kind': 'label', 'label': p['label'], 'source': p['source'].split(' (')[0],
                  'ocr': 'OCR' in p['source'], 'moved': 'drawn_lon' in p}, 'geometry': {'type': 'Point', 'coordinates': rnd(f['geometry']['coordinates'])}})
out = os.path.join(DATA, 'plans.geojson')
json.dump({'type': 'FeatureCollection', 'features': feats}, open(out, 'w'), separators=(',', ':'))
n = sum(f['properties']['kind'] == 'structure' for f in feats)
print(f'wrote {out}: {n} structures, {len(feats) - n} labels, {os.path.getsize(out) // 1024} KB')
