"""
X12 Taxonomy — Mapping tables for healthcare EDI transactions.

This module contains all lookup tables used for parsing X12 835/837 transactions.
Extracted from parser.py to enable modular maintenance.
"""

from typing import Dict

# ── 835 Loop Descriptions ─────────────────────────────────────────────────────

_LOOP_DESCRIPTIONS_835: Dict[str, str] = {
    "1000A": "Submitter Name",
    "1000B": "Receiver Name",
    "1000C": "Billing Provider Name",
    "1500": "Payment Information",
    "2000": "Service Payment Information",
    "2100": "Claim Payment Information",
    "2110": "Service Payment Detail",
    "2200": "Adjustment",
    "2300": "Remark Codes",
    # NM1 entity qualifiers (pragmatic labels)
    "PR": "Payer Name",
    "PE": "Provider Name",
    "QC": "Patient/Claimant Name",
    "NM1": "Entity Name",
    # Known-optional 835 segments (recognized but not deeply semanticized)
    "TS2": "Transaction Statistics (Provider)",
    "TS3": "Transaction Statistics (Insured)",
    "MIA": "Medicare Inpatient Adjudication",
    "MOA": "Medicare Outpatient Adjudication",
}

# ── 837 Loop Descriptions ─────────────────────────────────────────────────────

_LOOP_DESCRIPTIONS_837: Dict[str, str] = {
    "1000A": "Submitter Name",
    "1000B": "Receiver Name",
    "1000C": "Billing Provider Name",
    "1000D": "Subscriber Name",
    "1000E": "Patient Name",
    "2000A": "Hierarchical Parent",
    "2000B": "Billing Provider Hierarchical Level",
    "2000C": "Subscriber Hierarchical Level",
    "2000D": "Patient Hierarchical Level",
    "2300": "Claim Information",
    "2305": "Prior Authorization or Referral",
    "2310A": "Physician or Facility Name",
    "2310B": "Operating Physician Name",
    "2310C": "Service Facility Location",
    "2310D": "Referring Provider Name",
    "2320": "Subscriber or Patient Amount",
    "2330A": "Subscriber Name",
    "2330B": "Payer Name",
    "2330C": "Patient Name",
    "2330D": "Responsible Party Name",
    "2400": "Service Line Number",
    "2410": "Drug Identification",
    "2420A": "Operating Physician Name",
    "2420B": "Other Physician Name",
    "2420C": "Service Facility Location",
    "2430": "Line Adjudication Information",
    "2440": "Form Identification",
    # NM1 entity qualifiers
    "41": "Submitter Name",
    "40": "Receiver Name",
    "85": "Billing Provider Name",
    "IL": "Subscriber Name",
    "QC": "Patient Name",
    "PR": "Payer Name",
    "NM1": "Entity Name",
}


# ── Loop Kinds (practical categories) ────────────────────────────────────────

_LOOP_KINDS: Dict[str, str] = {
    # NM1 entity type codes → kind
    "QC": "entity",  # patient/claimant
    "IL": "entity",  # insured/subscriber
    "PR": "entity",  # payer
    "PE": "entity",  # payee/provider
    "85": "entity",  # billing provider
    "41": "entity",  # submitter
    "40": "entity",  # receiver
    "77": "entity",  # service facility location
    "8": "entity",  # 配偶
    # Claim / service leaders
    "CLM": "claim",
    "CLP": "claim",
    "LX": "service",
    "SV1": "service",
    "SV2": "service",
    "SV3": "service",
    "SV4": "service",
    "SV5": "service",
    "HI": "diagnosis",
    "HCP": "pricing",
    "BHT": "header",
    "PLB": "adjustment",
    "ADJ": "adjustment",
    "CAS": "adjustment",
    "AMT": "amount",
    "QTY": "quantity",
    "DTM": "date",
    "REF": "reference",
    "N1": "entity",
    "N3": "address",
    "N4": "geography",
    "PER": "contact",
    "DMG": "demographic",
    "PAT": "patient",
    "SBR": "subscriber",
    "CUR": "currency",
    "NTE": "note",
    "LIN": "line_item",
    "CTP": "pricing",
    "RDM": "remittance",
    "HL": "hierarchy",
    "CR1": "ambulance",
    "CR2": "spine",
    "CR3": "oxygen",
    "CR4": "durable_medical",
    "CR5": "vision",
    "ENT": "entity",
    "BPR": "payment",
    "TRN": "trace",
    # Known-optional 835 segments — recognized as loop leaders, not deeply semanticized
    "TS2": "statistics",
    "TS3": "statistics",
    "MIA": "statistics",
    "MOA": "statistics",
}


# ── CLP Status Codes ─────────────────────────────────────────────────────────

_CLP_STATUS_CODES: Dict[str, Dict[str, str]] = {
    "1": {"label": "Processed as Primary", "category": "paid"},
    "2": {"label": "Processed as Secondary", "category": "paid"},
    "3": {"label": "Processed as Tertiary", "category": "paid"},
    "4": {"label": "Denied", "category": "denied"},
    "5": {"label": "Pended", "category": "pended"},
    "6": {"label": "Pending", "category": "pended"},
    "7": {"label": "Received — Not Yet Processed", "category": "pended"},
    "8": {"label": "Not Processed", "category": "denied"},
    "9": {"label": "Processed as Primary — Forwarded to Another Payer", "category": "forwarded"},
    "10": {"label": "Processed as Secondary — Forwarded to Another Payer", "category": "forwarded"},
    "11": {"label": "Processed as Tertiary — Forwarded to Another Payer", "category": "forwarded"},
    "12": {"label": "Resubmission", "category": "resubmission"},
    "13": {"label": "Audit Complete", "category": "completed"},
    "14": {"label": "Matched to Original Claim", "category": "pended"},
    "15": {"label": "Claim Contains No Payment or Return Claim Information", "category": "informational"},
    "16": {"label": "Claim Was Returned — More Information Needed", "category": "pended"},
    "17": {"label": "Claim Was Returned — Invalid", "category": "denied"},
    "19": {"label": "Processed as Primary — Forwarded to Dental", "category": "forwarded"},
    "20": {"label": "Processed as Secondary — Forwarded to Dental", "category": "forwarded"},
    "21": {"label": "Processed as Tertiary — Forwarded to Dental", "category": "forwarded"},
    "22": {"label": "Forwarded to Dental — Additional Information Needed", "category": "pended"},
    "23": {"label": "Forwarded to Dental — Already Paid", "category": "informational"},
    "24": {"label": "Forwarded to Dental — Cannot Process", "category": "denied"},
    "25": {"label": "Cannot Process — Forwarded to Another Payer", "category": "forwarded"},
    "27": {"label": "Processed as Primary — Forwarded to Vision", "category": "forwarded"},
    "28": {"label": "Processed as Secondary — Forwarded to Vision", "category": "forwarded"},
    "29": {"label": "Processed as Tertiary — Forwarded to Vision", "category": "forwarded"},
}


# ── PLB Adjustment Reason Codes ─────────────────────────────────────────────

_PLB_REASON_CODES: Dict[str, Dict[str, str]] = {
    "CO": {"label": "Contractual Obligation", "category": "contractual"},
    "PR": {"label": "Patient Responsibility", "category": "patient"},
    "PI": {"label": "Payer Initiated Reduction", "category": "payer"},
    "AO": {"label": "Administrative/Scientific", "category": "administrative"},
    "WO": {"label": "Write-Off", "category": "writeoff"},
    "CV": {"label": "Covered", "category": "covered"},
    "CAD": {"label": "Carve-Out", "category": "carveout"},
    "DISC": {"label": "Discount", "category": "discount"},
    "LAB": {"label": "Laboratory", "category": "lab"},
    "ODO": {"label": "Dental", "category": "dental"},
}


# ── Discrepancy Taxonomy ───────────────────────────────────────────────────

_DISCREPANCY_TAXONOMY: Dict[str, Dict[str, str]] = {
    "billed_mismatch": {
        "severity": "warning",
        "description": "CLP billed amount differs from sum of SVC billed amounts",
    },
    "paid_mismatch": {
        "severity": "warning",
        "description": "CLP paid amount differs from sum of SVC paid amounts",
    },
    "zero_pay_inconsistency": {
        "severity": "info",
        "description": "CLP status indicates denied/pending but service lines show non-zero payment",
    },
    "cas_adjustment_mismatch": {
        "severity": "info",
        "description": "Sum of CAS adjustments does not equal the reported CLP adjustment amount",
    },
}


# ── Transaction Registry ────────────────────────────────────────────────────

_TRANSACTION_REGISTRY: Dict[str, Dict[str, str]] = {
    # 835 — Healthcare Claim Payment/Advice
    "005010X221A1": {
        "set_id": "835",
        "name": "Healthcare Claim Payment/Advice",
        "description": "835 — Payment/Remittance",
        "category": "payment",
    },
    # 837 — Healthcare Claim
    "005010X222A1": {
        "set_id": "837",
        "name": "Healthcare Claim — Professional (CMS-1500)",
        "description": "837P — Professional Claim",
        "category": "claim",
        "variant": "professional",
    },
    "005010X223A1": {
        "set_id": "837",
        "name": "Healthcare Claim — Institutional (UB-04)",
        "description": "837I — Institutional Claim",
        "category": "claim",
        "variant": "institutional",
    },
    "005010X224A1": {
        "set_id": "837",
        "name": "Healthcare Claim — Dental",
        "description": "837D — Dental Claim",
        "category": "claim",
        "variant": "dental",
    },
}


# ── GS Functional Codes ──────────────────────────────────────────────────────

_GS_FUNCTIONAL_CODES: Dict[str, Dict[str, str]] = {
    "HP": {"set_id": "835", "name": "Healthcare Claim Payment/Advice", "category": "payment"},
    "HC": {"set_id": "837", "name": "Healthcare Claim", "category": "claim"},
    "HI": {"set_id": "837", "name": "Healthcare Claim — Institutional", "category": "claim"},
}


# ── Public API ──────────────────────────────────────────────────────────────

__all__ = [
    "_LOOP_DESCRIPTIONS_835",
    "_LOOP_DESCRIPTIONS_837",
    "_LOOP_KINDS",
    "_CLP_STATUS_CODES",
    "_PLB_REASON_CODES",
    "_DISCREPANCY_TAXONOMY",
    "_TRANSACTION_REGISTRY",
    "_GS_FUNCTIONAL_CODES",
]