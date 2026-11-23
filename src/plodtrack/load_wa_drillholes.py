"""Download real open-file drillhole collars from the WA government's ArcGIS service.

Source: Mineral exploration drillholes (open file) (DMIRS-046), Government of Western Australia,
licensed CC BY 4.0. https://catalogue.data.wa.gov.au/dataset/mineral-exploration-drillholes-open-file
"""
import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

URL = ("https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/"
       "Industry_and_Mining/MapServer/28/query")
FIELDS = ["holeid", "holetype", "maxdepth", "operator", "project", "target_commodity",
          "latitude", "longitude", "period_from", "period_to", "collarid"]
KALGOORLIE_BBOX = "120.8,-31.5,122.0,-30.2"


def fetch(limit=6000, page=1000, bbox=KALGOORLIE_BBOX, where="target_commodity='GOLD' AND maxdepth>0"):
    rows = []
    while len(rows) < limit:
        q = {"where": where, "geometry": bbox, "geometryType": "esriGeometryEnvelope", "inSR": 4326,
             "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(FIELDS),
             "returnGeometry": "false", "orderByFields": "objectid",
             "resultOffset": len(rows), "resultRecordCount": min(page, limit - len(rows)), "f": "json"}
        with urllib.request.urlopen(f"{URL}?{urllib.parse.urlencode(q)}", timeout=90) as r:
            feats = json.load(r).get("features", [])
        if not feats:
            break
        rows += [f["attributes"] for f in feats]
    return rows


def main(out="data/external/wa_drillholes/holes.csv", limit=6000):
    rows = fetch(int(limit))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k) for k in FIELDS} for r in rows)
    print(f"Saved {len(rows)} real drillholes to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
