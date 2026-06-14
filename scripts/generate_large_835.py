#!/usr/bin/env python3
"""
Generate a large synthetic 835 EDI fixture for stress testing.

Produces a well-formed 835 with N claims, each with M service lines,
CAS adjustments, and entity segments.

Usage:
    python scripts/generate_large_835.py [--claims N] [--svc-lines M] [--output PATH]
"""

import argparse
import random
import sys
from datetime import date, timedelta

# ── Deterministic pseudo-random helpers ───────────────────────────────────────

SEED = 42
rng = random.Random(SEED)

PROCEDURE_CODES = [
    "99213", "99214", "99215", "99203", "99204", "99205",
    "99281", "99282", "99283", "99284", "99285",
    "90834", "90837", "90847",
    "99495", "99496", "99497", "99498",
    "36415", "81000", "85025", "80053",
    "27130", "27447", "29825",
]

REASON_CODES = ["CO", "PR", "PI", "AO", "WO", "CV", "DISC"]
PAYER_NAMES = ["BLUE CROSS BLUE SHIELD", "AETNA LIFE INSURANCE", "UNITED HEALTHCARE", "CIGNA HEALTH", "MEDICARE PART B", "ANTHEM BLUE CROSS", "HUMANA"]
PROVIDER_NAMES = ["CITY HOSPITAL", "MEDICAL ASSOCIATES CLINIC", "URGENT CARE CENTER", "SPECIALTY PHYSICIANS GROUP", "COMMUNITY HEALTH CENTER"]
LAST_NAMES = ["SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ", "MARTINEZ", "ANDERSON", "TAYLOR", "THOMAS", "MOORE", "JACKSON"]
FIRST_NAMES = ["JAMES", "MARY", "JOHN", "PATRICIA", "ROBERT", "JENNIFER", "MICHAEL", "LINDA", "WILLIAM", "ELIZABETH", "DAVID", "BARBARA", "RICHARD", "SUSAN", "JOSEPH"]


def rnd_choice(seq):
    return rng.choice(seq)


def rnd_int(a, b):
    return rng.randint(a, b)


def generate_isa():
    return "ISA*00*          *00*          *ZZ*SUBMITTER     *ZZ*RECEIVER      *250413*1522*^*00501*000000001*0*P*:~"


def generate_gs():
    return "GS*HP*SUBMITTER*RECEIVER*20250413*1522*1*X*005010X221A1~"


def generate_st(n):
    return f"ST*835*{n:04d}*005010X221A1~"


def generate_bpr(total_amount):
    return f"BPR*H*{total_amount:.2f}*C*ACH*CTX*01*012345678*DA*1234567890*0***ACH*CC*0123456789~"


def generate_trn(check_num):
    return f"TRN*1*{check_num:010d}*0123456789~"


def generate_dtm():
    return "DTM*001*20250413~"


def generate_n1_pr(payer_name):
    return f"N1*PR*{payer_name}*PI*123456789~"


def generate_n3():
    return "N3*123 MAIN STREET~"


def generate_n4():
    return "N4*CITY*ST*12345~"


def generate_ref():
    return "REF*2U*123456789~"


def generate_n1_pe(provider_name):
    return f"N1*PE*{provider_name}*XX*987654321~"


def generate_per():
    return "PER*IC*JOHN DOE*TE*8005551234~"


def generate_lx(seq):
    return f"LX*{seq}~"


def generate_clp(claim_id, status, billed, paid, patient_resp):
    return f"CLP*{claim_id}*{status}*{billed:.2f}*{paid:.2f}*{patient_resp:.2f}**CL*12*345~"


def generate_cas_co(amount):
    reason = rnd_choice(["45", "1", "2", "3", "4", "5"])
    return f"CAS*CO*{reason}*{amount:.2f}~"


def generate_cas_pr(amount):
    return f"CAS*PR*1*{amount:.2f}~"


def generate_nm1_qc(last, first, claim_id):
    return f"NM1*QC*1*{last}*{first}****34*{claim_id}~"


def generate_dtm_svc():
    return "DTM*001*20250412~"


def generate_svc(proc_code, billed, paid):
    return f"SVC*HC:{proc_code}*{billed:.2f}*{paid:.2f}***1~"


def generate_dt():
    return "DTP*001*20250412~"


def generate_se(seg_count, st_num):
    return f"SE*{seg_count}*{st_num:04d}~"


def generate_ge(n):
    return f"GE*1*{n}~"


def generate_iea(n):
    return f"IEA*1*{n:010d}~"


def generate_claim(claim_num, n_svc_lines, payer_name, provider_name):
    """Generate one claim with n_svc_lines service lines."""
    claim_id = f"CLM{claim_num:06d}"
    status = rng.choice(["1", "2", "3", "4", "19", "20", "21"])
    patient_last = rnd_choice(LAST_NAMES)
    patient_first = rnd_choice(FIRST_NAMES)

    # Generate service lines with random amounts
    svc_billed_total = 0.0
    svc_paid_total = 0.0
    svc_lines = []
    for i in range(1, n_svc_lines + 1):
        proc = rnd_choice(PROCEDURE_CODES)
        billed = float(rnd_int(50, 500))
        paid = billed * rng.uniform(0.5, 0.95)
        svc_billed_total += billed
        svc_paid_total += paid
        svc_lines.append((proc, billed, paid))

    clp_billed = svc_billed_total
    clp_paid = svc_paid_total
    patient_resp = clp_billed - clp_paid

    segs = []
    segs.append(generate_lx(1))
    segs.append(generate_clp(claim_id, status, clp_billed, clp_paid, patient_resp))

    # CAS adjustments — only if there's a difference
    if patient_resp > 0.01:
        cas_amount = patient_resp * rng.uniform(0.3, 0.7)
        segs.append(generate_cas_co(cas_amount))
        remaining = patient_resp - cas_amount
        if remaining > 0.01:
            segs.append(generate_cas_pr(remaining))

    segs.append(generate_nm1_qc(patient_last, patient_first, claim_id))
    segs.append(generate_dtm_svc())

    for proc, billed, paid in svc_lines:
        segs.append(generate_svc(proc, billed, paid))
        segs.append(generate_dt())

    return segs


def generate_large_835(n_claims, n_svc_per_claim):
    """Generate a complete large 835 EDI file."""
    payer_name = rnd_choice(PAYER_NAMES)
    provider_name = rnd_choice(PROVIDER_NAMES)
    check_num = 1000000000

    lines = []
    lines.append(generate_isa())
    lines.append(generate_gs())
    lines.append(generate_st(1))

    total_payment = 0.0
    claim_seg_counts = []

    for i in range(1, n_claims + 1):
        segs = generate_claim(i, n_svc_per_claim, payer_name, provider_name)
        for seg in segs:
            lines.append(seg)
        # Track payment from CLP segment
        claim_seg_counts.append(len(segs))
        # Approximate payment from last SVC paid amount
        total_payment += 100.0 + rng.uniform(0, 400)

    # BPR after claims to include total
    lines.append(generate_bpr(total_payment))
    lines.append(generate_trn(check_num))
    lines.append(generate_dtm())
    lines.append(generate_n1_pr(payer_name))
    lines.append(generate_n3())
    lines.append(generate_n4())
    lines.append(generate_ref())
    lines.append(generate_n1_pe(provider_name))
    lines.append(generate_n3())
    lines.append(generate_n4())
    lines.append(generate_per())

    # Calculate SE segment count: all segments since ST
    # ST + all claim segments + BPR + TRN + DTM + N1*PR + N3 + N4 + REF + N1*PE + N3 + N4 + PER + SE
    extra_header_segs = 12  # BPR, TRN, DTM, N1*PR, N3, N4, REF, N1*PE, N3, N4, PER
    seg_count = sum(claim_seg_counts) + extra_header_segs
    lines.append(generate_se(seg_count, 1))
    lines.append(generate_ge(1))
    lines.append(generate_iea(1))

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Generate large synthetic 835 fixture")
    parser.add_argument("--claims", type=int, default=1000, help="Number of claims (default: 1000)")
    parser.add_argument("--svc-lines", type=int, default=3, help="Service lines per claim (default: 3)")
    parser.add_argument("--output", type=str, default=None, help="Output path")
    args = parser.parse_args()

    n_claims = args.claims
    n_svc = args.svc_lines
    output = args.output

    print(f"Generating 835 with {n_claims} claims × {n_svc} service lines each...", file=sys.stderr)
    edi_text = generate_large_835(n_claims, n_svc)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(edi_text)
        size_kb = len(edi_text) / 1024
        print(f"Wrote {output} ({size_kb:.1f} KB, {n_claims} claims)", file=sys.stderr)
    else:
        sys.stdout.write(edi_text)


if __name__ == "__main__":
    main()
