"""Run the parsers over generated samples and compare against ground truth.

Usage: python tests/check_parsers.py <samples_dir>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.extract import sniff_kind  # noqa: E402
from backend.statement_parser import parse_file  # noqa: E402


def compare(name, rows, truth, ordered=True):
    exp = [(t["date"], round(t["amount"] * 100), t["dir"]) for t in truth]
    got = [(r["date"], r["amount_minor"], r["direction"]) for r in rows]
    if ordered:
        hits = sum(1 for a, b in zip(exp, got) if a == b)
    else:
        remaining = list(got)
        hits = 0
        for e in exp:
            if e in remaining:
                remaining.remove(e)
                hits += 1
    pct = 100 * hits / max(len(exp), 1)
    print(f"{name:20s} expected={len(exp):3d} parsed={len(got):3d} exact={hits:3d} ({pct:5.1f}%)")
    return hits, len(exp), got, exp


def main(d):
    d = Path(d)
    truth = json.loads((d / "truth.json").read_text())
    ok = True
    for name in ["hdfc_ruled.pdf", "plain_dr_cr.pdf", "amount_drcr.pdf", "gpay.pdf"]:
        p = d / name
        kind = sniff_kind(p.read_bytes()[:16])
        res = parse_file(str(p), kind)
        hits, n, got, exp = compare(name, res.rows, truth[name])
        print(f"   source={res.source_type} parser={res.parser} account={res.account_name}/{res.account_last4} warnings={res.warnings}")
        if res.rows:
            r = res.rows[0]
            print(f"   first: {r['date']} {r['amount_minor']} {r['direction']} | merchant={r['merchant']!r} | {r['description'][:70]!r}")
        if hits < n:
            ok = False
            for i, (a, b) in enumerate(zip(exp, got)):
                if a != b:
                    print("   MISMATCH at", i, "expected", a, "got", b)
                    break
    # OCR variants: first page of the HDFC sample only, so compare against the rows on page 1.
    full = truth["hdfc_ruled.pdf"]
    for name in ["hdfc_page1.png", "hdfc_page1.jpg", "hdfc_scanned.pdf"]:
        p = d / name
        kind = sniff_kind(p.read_bytes()[:16])
        res = parse_file(str(p), kind)
        n_page = len(res.rows)
        hits, n, got, exp = compare(name + " (OCR)", res.rows, full[:n_page] if n_page else full[:1])
        print(f"   source={res.source_type} parser={res.parser} warnings={res.warnings}")
    print("ALL EXACT" if ok else "SOME MISMATCHES (see above)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/samples")
