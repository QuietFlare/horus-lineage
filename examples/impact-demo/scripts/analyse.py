import argparse, json

p = argparse.ArgumentParser()
p.add_argument("--prepared")
p.add_argument("--calibration")
p.add_argument("--out")
a = p.parse_args()
factor = int(open(a.calibration).read().split("=")[1])
rows = json.load(open(a.prepared))
json.dump(
    {"total": sum(r["value"] for r in rows) * factor},
    open(a.out, "w"),
    indent=1,
    sort_keys=True,
)
