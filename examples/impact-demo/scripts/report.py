import argparse, json

p = argparse.ArgumentParser()
p.add_argument("--analysed")
p.add_argument("--qc")
p.add_argument("--reference")
p.add_argument("--out")
a = p.parse_args()
threshold = int(open(a.reference).read().split("=")[1])
an = json.load(open(a.analysed))
qc = json.load(open(a.qc))
json.dump(
    {
        "total": an["total"],
        "rows": qc["rows"],
        "over": an["total"] > threshold,
    },
    open(a.out, "w"),
    indent=1,
    sort_keys=True,
)
