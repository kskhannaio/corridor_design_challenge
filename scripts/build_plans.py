"""Planned and existing structures for the "What's planned" tab: copied from the PDF pipeline repo's exports.

The drawings (the B-SMILE tender's 17 vector CAD sheets, the metro survey scans, the corridor's plan of the loop, the
corridor concept drawing and the tunnel's land acquisition plan) are traced and placed on the map in the pipeline repo
(github.com/kskhannaio/cad_drawings_extraction; `python main.py`). Its export step writes exports/website/plans.geojson
in exactly the form this site reads, so this script only checks it and copies it to data/plans.geojson:

  kind=structure  layer, what, area_m2; named parts also carry conf (high / medium / low) and basis (why that name);
                  shapes from sheets other than the tender carry scan = 'metro', 'loop', 'concept' or 'land';
                  the tunnel land carries statement and statement_total_m2 (the sheet's own area statement)
  kind=label      label, source, ocr (read by OCR from linework), moved (moved onto the structure it names)

Usage: python3 scripts/build_plans.py [path/to/pipeline/exports/website/plans.geojson]
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', '..', 'corridor_pdf_pipeline', 'exports', 'website', 'plans.geojson')
OUT = os.path.join(HERE, '..', 'data', 'plans.geojson')
if not os.path.exists(SRC): sys.exit(f'missing {SRC} - run `python main.py --only export` in the pipeline repo')

d = json.load(open(SRC))
kinds = {f['properties'].get('kind') for f in d['features']}
if d.get('type') != 'FeatureCollection' or not kinds <= {'structure', 'label'}: sys.exit(f'{SRC} is not the pipeline\'s website export')
json.dump(d, open(OUT, 'w'), separators=(',', ':'))
n = sum(f['properties']['kind'] == 'structure' for f in d['features'])
print(f'wrote {OUT}: {n} structures, {len(d["features"]) - n} labels, {os.path.getsize(OUT) // 1024} KB')
