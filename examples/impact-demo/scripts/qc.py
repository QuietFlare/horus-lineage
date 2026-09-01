import argparse, json

p = argparse.ArgumentParser()
p.add_argument("--prepared")
p.add_argument("--out")
a = p.parse_args()
rows = json.load(open(a.prepared))
json.dump({"rows": len(rows)}, open(a.out, "w"), indent=1, sort_keys=True)
