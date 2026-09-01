import argparse, csv, json

p = argparse.ArgumentParser()
p.add_argument("--raw")
p.add_argument("--out")
a = p.parse_args()
rows = [
    {"id": r["id"], "value": int(r["value"])}
    for r in csv.DictReader(open(a.raw))
]
json.dump(rows, open(a.out, "w"), indent=1, sort_keys=True)
