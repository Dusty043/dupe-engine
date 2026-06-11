#!/usr/bin/env python3
"""Synthetic Corpus v2 generator (medium profile).

Creates synthetic PDF records, page metadata, cluster truth, pair truth, and a generation log.
All content is fabricated and marked synthetic; no real PHI is used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import random
import shutil
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4, legal
from reportlab.pdfgen import canvas

SEED = 24042026
RNG = random.Random(SEED)

PAGE_SIZES = {
    "letter": letter,
    "a4": A4,
    "legal": legal,
}

GROUPS = {
    "received_records": "group_a_received_records",
    "ere_records": "group_b_ere_records",
    "claimant_uploads": "group_c_claimant_uploads",
    "fax_records": "group_d_fax_records",
    "email_records": "group_e_email_records",
}

SOURCE_PATTERN_NOTES = {
    "received_records": [
        "clean born-digital PDFs",
        "provider headers",
        "normal page numbers",
    ],
    "ere_records": [
        "batch cover sheets",
        "ERE stamps",
        "barcodes and page stamps",
        "some page order changes",
    ],
    "claimant_uploads": [
        "image-only phone camera scans",
        "rotation/crop/shadows",
        "mixed page sizes",
    ],
    "fax_records": [
        "image-only low resolution scans",
        "fax headers",
        "black borders/noise/skew",
    ],
    "email_records": [
        "clean born-digital PDFs",
        "duplicate attachments",
        "repeated cover pages",
    ],
}

PROVIDERS = [
    "Lakeside Primary Care",
    "North River Imaging",
    "Metro Lab Partners",
    "Summit Orthopedics",
    "Cedar Valley Hospital",
    "Pine Street Pulmonary",
    "Beacon Behavioral Health",
]

DIAGNOSES = [
    "type 2 diabetes mellitus",
    "essential hypertension",
    "chronic low back pain",
    "major depressive disorder",
    "chronic obstructive pulmonary disease",
    "lumbar radiculopathy",
    "hyperlipidemia",
]

MED_LIST_COMMON = [
    ("lisinopril", "20 mg", "once daily", "active"),
    ("metformin", "500 mg", "twice daily", "active"),
    ("atorvastatin", "40 mg", "nightly", "active"),
    ("albuterol inhaler", "2 puffs", "as needed", "active"),
]

BOILERPLATE = [
    "Medication reconciliation completed.",
    "This record was electronically signed by the rendering provider.",
    "Please consult your provider for questions about this synthetic record.",
    "Patient verbalized understanding of the plan.",
]

CASE_DESCRIPTIONS = {
    "case_001": "exact duplicates",
    "case_002": "same text different formatting",
    "case_003": "fax degraded duplicate",
    "case_004": "OCR-only duplicate",
    "case_005": "rotated/cropped camera scan duplicate",
    "case_006": "same template different visit",
    "case_007": "same diagnosis different visit",
    "case_008": "repeated medication list trap",
    "case_009": "repeated fax cover sheet trap",
    "case_010": "lab panel same layout different values",
    "case_011": "imaging report same template different findings",
    "case_012": "partial overlap medication list",
    "case_013": "partial overlap visit summary",
    "case_014": "multi-page duplicate packet",
    "case_015": "mixed source A/B workflow",
    "case_016": "blank/separator/signature-only pages",
    "case_017": "page-number/header/footer noise",
    "case_018": "same visit different pages, related not duplicate",
    "case_019": "paraphrased same content",
    "case_020": "OCR corruption trap",
}

TRUTH_LABELS = [
    "duplicate",
    "likely_duplicate",
    "possible_duplicate",
    "partial_overlap",
    "not_duplicate",
    "needs_review",
    "low_information_ignore",
]

@dataclass
class Content:
    record_type: str
    title: str
    subtitle: str = ""
    patient_id: str = "patient_001"
    provider_id: str = "provider_001"
    provider_name: str = "Lakeside Primary Care"
    visit_id: str = "visit_001"
    visit_date: str = "2024-01-12"
    sections: List[Tuple[str, List[str]]] = field(default_factory=list)
    table_title: Optional[str] = None
    table_columns: List[str] = field(default_factory=list)
    table_rows: List[List[str]] = field(default_factory=list)
    footer_lines: List[str] = field(default_factory=list)
    watermark: Optional[str] = None
    body_note: Optional[str] = None
    low_info_kind: Optional[str] = None
    order_variant: str = "standard"

@dataclass
class PageSpec:
    page_id: str
    doc_key: str
    source_group: str
    content: Content
    case_id: str
    page_family: str
    content_version: str = "original"
    duplicate_cluster_id: Optional[str] = None
    expected_cluster_label: Optional[str] = None
    duplicate_category: Optional[str] = None
    text_availability: str = "native_text"
    ocr_difficulty: str = "none"
    visual_quality: str = "clean"
    is_low_information_page: bool = False
    transformations: List[str] = field(default_factory=list)
    rendering_method: str = "native_pdf"
    format_variant: str = "standard"
    page_size_name: str = "letter"
    synthetic_patient_id: str = "patient_001"
    synthetic_provider_id: str = "provider_001"
    synthetic_visit_id: str = "visit_001"
    hard_negative_trap_type: Optional[str] = None
    partial_overlap_group_id: Optional[str] = None
    related_group_id: Optional[str] = None
    packet_id: Optional[str] = None
    ab_scenarios: List[str] = field(default_factory=list)
    document_name: Optional[str] = None
    relative_pdf_path: Optional[str] = None
    page_number: Optional[int] = None
    page_size_points: Optional[List[float]] = None
    content_fingerprint: Optional[str] = None
    intended_text_fingerprint: Optional[str] = None
    notes: str = ""

@dataclass
class DocSpec:
    doc_key: str
    source_group: str
    filename: str
    pages: List[PageSpec] = field(default_factory=list)

class Builder:
    def __init__(self, root: Path):
        self.root = root
        self.docs: Dict[str, DocSpec] = {}
        self.pages: List[PageSpec] = []
        self.cluster_defs: Dict[str, Dict[str, Any]] = {}
        self.pair_truth = {
            "must_match": [],
            "should_not_match": [],
            "partial_overlap": [],
            "related_but_not_duplicate": [],
            "low_information_ignore": [],
        }
        self.log_events: List[Dict[str, Any]] = []
        self._page_counter = 0

    def add_doc(self, doc_key: str, source_group: str, filename: str) -> None:
        if doc_key in self.docs:
            return
        self.docs[doc_key] = DocSpec(doc_key=doc_key, source_group=source_group, filename=filename)

    def add_page(self, doc_key: str, source_group: str, content: Content, case_id: str, page_family: str,
                 **kwargs) -> PageSpec:
        self._page_counter += 1
        page_id = kwargs.pop("page_id", f"v2_{case_id}_{self._page_counter:04d}")
        spec = PageSpec(
            page_id=page_id,
            doc_key=doc_key,
            source_group=source_group,
            content=content,
            case_id=case_id,
            page_family=page_family,
            synthetic_patient_id=content.patient_id,
            synthetic_provider_id=content.provider_id,
            synthetic_visit_id=content.visit_id,
            **kwargs,
        )
        spec.intended_text_fingerprint = fingerprint_content(content, normalize=True)
        self.docs[doc_key].pages.append(spec)
        self.pages.append(spec)
        if spec.duplicate_cluster_id:
            c = self.cluster_defs.setdefault(spec.duplicate_cluster_id, {
                "cluster_id": spec.duplicate_cluster_id,
                "description": "",
                "category": spec.duplicate_category,
                "expected_label": spec.expected_cluster_label or "duplicate",
                "pages": [],
                "case_ids": sorted(set([case_id])),
            })
            c["category"] = c.get("category") or spec.duplicate_category
            c["expected_label"] = spec.expected_cluster_label or c.get("expected_label") or "duplicate"
            c["case_ids"] = sorted(set(c.get("case_ids", []) + [case_id]))
        return spec

    def add_cluster_description(self, cluster_id: str, description: str, category: str, expected_label: str) -> None:
        c = self.cluster_defs.setdefault(cluster_id, {
            "cluster_id": cluster_id,
            "description": description,
            "category": category,
            "expected_label": expected_label,
            "pages": [],
            "case_ids": [],
        })
        c["description"] = description
        c["category"] = category
        c["expected_label"] = expected_label

    def add_pair(self, bucket: str, p1: PageSpec, p2: PageSpec, label: str, category: str, reason: str,
                 scenario: Optional[str] = None) -> None:
        self.pair_truth[bucket].append({
            "page_1_id": p1.page_id,
            "page_2_id": p2.page_id,
            "expected_label": label,
            "category": category,
            "reason": reason,
            "scenario": scenario,
        })

# ---------- content builders ----------

def fingerprint_content(content: Content, normalize: bool = True) -> str:
    parts = [content.record_type, content.title, content.subtitle, content.provider_name, content.visit_date]
    for head, lines in content.sections:
        parts.append(head)
        parts.extend(lines)
    if content.table_title:
        parts.append(content.table_title)
        parts.extend(content.table_columns)
        for row in content.table_rows:
            parts.extend(row)
    parts.extend(content.footer_lines)
    text = "\n".join(parts)
    if normalize:
        text = " ".join(text.lower().split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]

def patient_id(n: int) -> str:
    return f"patient_{n:03d}"

def provider_id(n: int) -> str:
    return f"provider_{n:03d}"

def visit_id(n: int) -> str:
    return f"visit_{n:03d}"

def date_str(days: int) -> str:
    # Keep synthetic encounter dates in a plausible 2024-2025 calibration window even for high index filler pages.
    return (date(2024, 1, 3) + timedelta(days=days % 540)).isoformat()

def make_visit_note(idx: int, diagnosis: str, symptom: str, assessment: str, plan: str,
                    provider_name: str = "Lakeside Primary Care", patient_num: int = 1,
                    visit_num: Optional[int] = None, visit_days: Optional[int] = None,
                    meds: Optional[List[Tuple[str, str, str, str]]] = None,
                    order_variant: str = "standard",
                    paraphrase: bool = False) -> Content:
    if visit_num is None:
        visit_num = idx
    if visit_days is None:
        visit_days = idx * 7
    meds = meds or MED_LIST_COMMON
    chief = symptom
    hpi = f"Synthetic patient reports {symptom.lower()} with onset noted during routine follow-up. No real person is represented."
    ros = "Denies fever, acute neurologic deficit, or new trauma. Reports stable appetite and sleep."
    exam = "Alert and oriented. Respirations nonlabored. Gait steady. No acute distress observed."
    if paraphrase:
        ros = "No fever, new trauma, or acute neurologic symptoms are reported. Appetite and sleep remain stable."
        exam = "Patient is awake, oriented, and comfortable. Breathing is unlabored and gait is stable."
        hpi = f"The synthetic patient describes {symptom.lower()} during a scheduled follow-up; this is not a real clinical record."
    sections = [
        ("Chief Complaint", [chief]),
        ("History", [hpi, ros]),
        ("Exam", [exam]),
        ("Assessment", [diagnosis, assessment]),
        ("Plan", [plan, "Continue medication reconciliation and safety counseling."]),
    ]
    if order_variant == "assessment_first":
        sections = [sections[3], sections[4], sections[1], sections[0], sections[2]]
    elif order_variant == "plan_first":
        sections = [sections[4], sections[3], sections[0], sections[1], sections[2]]
    c = Content(
        record_type="visit_note",
        title="Progress Note",
        subtitle=f"Visit Date: {date_str(visit_days)} | Encounter Type: Office Visit",
        patient_id=patient_id(patient_num),
        provider_id=provider_id((idx % 7) + 1),
        provider_name=provider_name,
        visit_id=visit_id(visit_num),
        visit_date=date_str(visit_days),
        sections=sections,
        table_title="Current Medications",
        table_columns=["Medication", "Dose", "Directions", "Status"],
        table_rows=[list(row) for row in meds],
        footer_lines=BOILERPLATE[:3],
        order_variant=order_variant,
    )
    return c

def make_med_list(idx: int, patient_num: int = 1, provider_name: str = "Lakeside Primary Care",
                  meds: Optional[List[Tuple[str, str, str, str]]] = None) -> Content:
    meds = meds or MED_LIST_COMMON
    return Content(
        record_type="medication_list",
        title="Medication List",
        subtitle=f"Medication Review Date: {date_str(10 + idx)}",
        patient_id=patient_id(patient_num),
        provider_id=provider_id(1),
        provider_name=provider_name,
        visit_id=visit_id(200 + idx),
        visit_date=date_str(10 + idx),
        sections=[("Medication Reconciliation", ["The medication list below is synthetic and used only for duplicate-detection testing."])],
        table_title="Active Medications",
        table_columns=["Medication", "Dose", "Frequency", "Status"],
        table_rows=[list(row) for row in meds],
        footer_lines=[BOILERPLATE[0], BOILERPLATE[2]],
    )

def make_lab_result(idx: int, patient_num: int = 1, panel: str = "CBC", values_shift: int = 0) -> Content:
    base_rows = [
        ["WBC", f"{6.1 + values_shift * 0.2:.1f}", "10^3/uL", "4.0-11.0"],
        ["RBC", f"{4.6 + values_shift * 0.1:.1f}", "10^6/uL", "4.2-5.8"],
        ["Hemoglobin", f"{13.8 + values_shift * 0.3:.1f}", "g/dL", "12.0-16.0"],
        ["Hematocrit", f"{41.2 + values_shift * 0.4:.1f}", "%", "36-46"],
        ["Platelets", f"{250 + values_shift * 9}", "10^3/uL", "150-400"],
    ]
    if panel == "CMP":
        base_rows = [
            ["Glucose", f"{96 + values_shift * 7}", "mg/dL", "70-99"],
            ["Creatinine", f"{0.8 + values_shift * 0.1:.1f}", "mg/dL", "0.6-1.3"],
            ["Sodium", f"{139 + values_shift}", "mmol/L", "135-145"],
            ["Potassium", f"{4.1 + values_shift * 0.1:.1f}", "mmol/L", "3.5-5.1"],
            ["ALT", f"{22 + values_shift * 3}", "U/L", "7-56"],
        ]
    return Content(
        record_type="lab_result",
        title=f"Laboratory Results - {panel} Panel",
        subtitle=f"Collection Date: {date_str(4 + idx * 5)} | Accession: SYN-LAB-{idx:04d}",
        patient_id=patient_id(patient_num),
        provider_id=provider_id(3),
        provider_name="Metro Lab Partners",
        visit_id=visit_id(300 + idx),
        visit_date=date_str(4 + idx * 5),
        sections=[("Specimen", ["Blood specimen received and processed in the synthetic laboratory workflow."])],
        table_title=f"{panel} Components",
        table_columns=["Component", "Result", "Units", "Reference Range"],
        table_rows=base_rows,
        footer_lines=["Result values are synthetic and are not valid for clinical use.", BOILERPLATE[1]],
    )

def make_imaging_report(idx: int, patient_num: int = 1, finding_variant: int = 0) -> Content:
    findings = [
        "Mild multilevel degenerative disc change without high-grade canal stenosis.",
        "Moderate left foraminal narrowing at L4-L5 with mild facet arthropathy.",
        "No acute fracture. Alignment is preserved. Small disc bulge at L5-S1.",
        "Mild chronic compression deformity at T12 without marrow edema.",
    ]
    impressions = [
        "Mild degenerative lumbar spondylosis. No acute abnormality.",
        "Moderate left L4-L5 foraminal narrowing. Correlate clinically.",
        "Small L5-S1 disc bulge. No high-grade stenosis.",
        "Chronic T12 compression deformity. No acute osseous finding.",
    ]
    v = finding_variant % len(findings)
    return Content(
        record_type="imaging_report",
        title="MRI Lumbar Spine Report",
        subtitle=f"Exam Date: {date_str(18 + idx * 6)} | Exam ID: SYN-MRI-{idx:04d}",
        patient_id=patient_id(patient_num),
        provider_id=provider_id(2),
        provider_name="North River Imaging",
        visit_id=visit_id(400 + idx),
        visit_date=date_str(18 + idx * 6),
        sections=[
            ("Indication", ["Synthetic report for low back pain with intermittent leg symptoms."]),
            ("Technique", ["Multiplanar multisequence MRI of the lumbar spine without contrast."]),
            ("Findings", [findings[v]]),
            ("Impression", [impressions[v]]),
        ],
        footer_lines=[BOILERPLATE[1], "Synthetic imaging report - not for clinical use."],
    )

def make_procedure_note(idx: int, patient_num: int = 1) -> Content:
    return Content(
        record_type="procedure_note",
        title="Procedure Note",
        subtitle=f"Procedure Date: {date_str(22 + idx)} | Procedure: Lumbar Injection",
        patient_id=patient_id(patient_num),
        provider_id=provider_id(4),
        provider_name="Summit Orthopedics",
        visit_id=visit_id(500 + idx),
        visit_date=date_str(22 + idx),
        sections=[
            ("Indication", ["Synthetic chronic low back pain with radicular symptoms."]),
            ("Procedure", ["Timeout performed. Sterile preparation completed. Synthetic medication administered under imaging guidance."]),
            ("Findings", ["No immediate complication observed in this fabricated record."]),
            ("Disposition", ["Discharged with routine synthetic post-procedure instructions."]),
        ],
        footer_lines=[BOILERPLATE[1], BOILERPLATE[2]],
    )

def make_discharge_summary(idx: int, patient_num: int = 1, include_prior_dx: bool = False) -> Content:
    sections = [
        ("Admission", [f"Admitted {date_str(30 + idx)} for synthetic shortness of breath observation."]),
        ("Hospital Course", ["Symptoms improved with supportive care. No real patient is represented."]),
        ("Discharge Diagnoses", ["COPD exacerbation", "hypertension", "type 2 diabetes mellitus"]),
        ("Follow Up", ["Follow up with primary care in 7 to 10 days."]),
    ]
    if include_prior_dx:
        sections.insert(3, ("Prior Diagnoses Repeated", ["type 2 diabetes mellitus; essential hypertension; chronic low back pain; hyperlipidemia"] * 2))
    return Content(
        record_type="discharge_summary",
        title="Discharge Summary",
        subtitle=f"Discharge Date: {date_str(33 + idx)} | Facility: Cedar Valley Hospital",
        patient_id=patient_id(patient_num),
        provider_id=provider_id(5),
        provider_name="Cedar Valley Hospital",
        visit_id=visit_id(600 + idx),
        visit_date=date_str(33 + idx),
        sections=sections,
        table_title="Discharge Medications",
        table_columns=["Medication", "Dose", "Directions", "Status"],
        table_rows=[list(row) for row in MED_LIST_COMMON[:3]],
        footer_lines=[BOILERPLATE[1], BOILERPLATE[3]],
    )

def make_cover_sheet(idx: int, kind: str = "fax", recipient: str = "Records Processing", page_count: int = 12,
                     date_days: int = 0) -> Content:
    title = "Fax Cover Sheet" if kind == "fax" else "Batch Cover Sheet"
    return Content(
        record_type="cover_sheet",
        title=title,
        subtitle=f"Transmission Date: {date_str(date_days)} | Page Count: {page_count}",
        patient_id=patient_id((idx % 9) + 1),
        provider_id=provider_id((idx % 7) + 1),
        provider_name=PROVIDERS[idx % len(PROVIDERS)],
        visit_id=visit_id(700 + idx),
        visit_date=date_str(date_days),
        sections=[
            ("To", [recipient]),
            ("From", [PROVIDERS[idx % len(PROVIDERS)]]),
            ("Subject", ["Synthetic records transmission for duplicate-detection testing."]),
            ("Confidentiality Notice", ["This fabricated cover page contains no real patient information."]),
        ],
        footer_lines=["Synthetic cover sheet. Do not use for real-world records."],
        low_info_kind="cover_sheet",
    )

def make_instructions(idx: int, patient_num: int = 1) -> Content:
    return Content(
        record_type="patient_instruction_page",
        title="Patient Instructions",
        subtitle=f"Instruction Date: {date_str(45 + idx)}",
        patient_id=patient_id(patient_num),
        provider_id=provider_id(1),
        provider_name="Lakeside Primary Care",
        visit_id=visit_id(800 + idx),
        visit_date=date_str(45 + idx),
        sections=[
            ("Activity", ["Resume routine activity as tolerated. Stop and seek care for worsening synthetic symptoms."]),
            ("Medication", ["Take medications only as directed in this fabricated example."]),
            ("When to Call", ["Call the clinic for fever, severe pain, or other urgent concerns in this synthetic page."]),
        ],
        footer_lines=[BOILERPLATE[2], BOILERPLATE[3]],
    )

def make_signature_page(idx: int) -> Content:
    return Content(
        record_type="signature_page",
        title="Electronic Signature Page",
        subtitle=f"Signed: {date_str(60 + idx)}",
        patient_id=patient_id((idx % 8) + 1),
        provider_id=provider_id((idx % 7) + 1),
        provider_name=PROVIDERS[idx % len(PROVIDERS)],
        visit_id=visit_id(900 + idx),
        visit_date=date_str(60 + idx),
        sections=[
            ("Signature", ["/s/ Synthetic Provider", "Electronically signed. Identity intentionally fabricated."]),
        ],
        footer_lines=[BOILERPLATE[1]],
        low_info_kind="signature_only",
    )

def make_blank_page(idx: int, kind: str = "blank") -> Content:
    title = "" if kind == "blank" else "Separator Page"
    body = "" if kind == "blank" else "Records continue after this page."
    return Content(
        record_type="blank_page" if kind == "blank" else "separator_page",
        title=title,
        subtitle="",
        patient_id=patient_id((idx % 8) + 1),
        provider_id=provider_id(1),
        provider_name="Synthetic Records Intake",
        visit_id=visit_id(950 + idx),
        visit_date=date_str(70 + idx),
        sections=[],
        body_note=body,
        low_info_kind=kind,
    )

def make_authorization_page(idx: int, patient_num: int = 1) -> Content:
    return Content(
        record_type="insurance_authorization",
        title="Insurance Authorization Notice",
        subtitle=f"Authorization Date: {date_str(80 + idx)} | Auth ID: SYN-AUTH-{idx:04d}",
        patient_id=patient_id(patient_num),
        provider_id=provider_id(6),
        provider_name="Synthetic Benefit Review Unit",
        visit_id=visit_id(1000 + idx),
        visit_date=date_str(80 + idx),
        sections=[
            ("Service Requested", ["Physical therapy evaluation and follow-up visits."]),
            ("Decision", ["Approved for synthetic testing purposes only."]),
            ("Limitations", ["This authorization page is fabricated and does not create coverage."]),
        ],
        footer_lines=["Synthetic insurance page. No real policy data."],
    )

# ---------- drawing helpers ----------

_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}

def pil_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = ("bold" if bold else "regular", size)
    if key not in _FONT_CACHE:
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
        for p in paths:
            if os.path.exists(p):
                _FONT_CACHE[key] = ImageFont.truetype(p, size=size)
                break
        else:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]

def wrap_text_reportlab(c: canvas.Canvas, text: str, font_name: str, font_size: float, max_width: float) -> List[str]:
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if c.stringWidth(test, font_name, font_size) <= max_width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def draw_wrapped_reportlab(c: canvas.Canvas, text: str, x: float, y: float, max_width: float,
                           font_name: str = "Helvetica", font_size: float = 9.5, leading: float = 12,
                           max_lines: Optional[int] = None) -> float:
    lines = wrap_text_reportlab(c, text, font_name, font_size, max_width)
    if max_lines is not None:
        lines = lines[:max_lines]
    c.setFont(font_name, font_size)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y

def draw_barcode_reportlab(c: canvas.Canvas, x: float, y: float, width: float = 80, height: float = 28) -> None:
    c.saveState()
    c.setFillColor(colors.black)
    RNG_local = random.Random(12345)
    cur = x
    while cur < x + width:
        w = RNG_local.choice([1.2, 1.8, 2.4, 3.0])
        gap = RNG_local.choice([1.0, 1.6, 2.2])
        c.rect(cur, y, w, height, stroke=0, fill=1)
        cur += w + gap
    c.restoreState()

def group_header(c: canvas.Canvas, spec: PageSpec, page_w: float, page_h: float) -> float:
    content = spec.content
    top = page_h - 36
    c.saveState()
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)
    if spec.format_variant == "exact_clean":
        c.setFont("Helvetica-Bold", 10)
        c.drawString(54, top, "SYNTHETIC HEALTH RECORD - NOT REAL PHI")
        c.setFont("Helvetica", 8)
        c.drawRightString(page_w - 54, top, "Duplicate Test Page")
        c.line(54, top - 8, page_w - 54, top - 8)
        y = top - 26
    elif spec.source_group == "received_records":
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(42, top, content.provider_name.upper())
        c.setFont("Helvetica", 8)
        c.drawRightString(page_w - 42, top, "RECEIVED RECORDS - SYNTHETIC")
        c.line(42, top - 8, page_w - 42, top - 8)
        y = top - 28
    elif spec.source_group == "ere_records":
        c.setFont("Helvetica-Bold", 10)
        c.drawString(38, top, "ERE BATCH COPY - SYNTHETIC")
        c.setFont("Helvetica", 7.5)
        c.drawString(38, top - 12, f"Batch: ERE-{spec.doc_key[-3:]} | Source page stamp added")
        draw_barcode_reportlab(c, page_w - 130, top - 20, 90, 24)
        c.setStrokeColor(colors.darkgrey)
        c.rect(34, top - 28, page_w - 68, 36, stroke=1, fill=0)
        y = top - 48
    elif spec.source_group == "email_records":
        c.setFont("Helvetica-Bold", 10)
        c.drawString(48, top, "EMAIL ATTACHMENT - SYNTHETIC MEDICAL RECORD")
        c.setFont("Helvetica", 8)
        c.drawRightString(page_w - 48, top, "Clean PDF")
        c.line(48, top - 8, page_w - 48, top - 8)
        y = top - 28
    else:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(48, top, "SYNTHETIC RECORD")
        y = top - 30
    c.restoreState()
    return y

def draw_native_page(c: canvas.Canvas, spec: PageSpec, temp_dir: Path) -> None:
    page_w, page_h = PAGE_SIZES[spec.page_size_name]
    c.setPageSize((page_w, page_h))
    content = spec.content

    # image-only pages are drawn by PIL and embedded.
    if spec.rendering_method == "image_pdf":
        img = make_pil_page(spec)
        img_path = temp_dir / f"{spec.page_id}.jpg"
        # high compression for degraded pages, cleaner otherwise
        quality = 55 if any("jpeg_quality_45" in t or "fax" in t for t in spec.transformations) else 82
        img.save(img_path, "JPEG", quality=quality)
        c.drawImage(str(img_path), 0, 0, width=page_w, height=page_h, preserveAspectRatio=False, mask=None)
        c.showPage()
        return

    c.setFillColor(colors.white)
    c.rect(0, 0, page_w, page_h, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)
    y = group_header(c, spec, page_w, page_h)

    if spec.format_variant == "compact":
        margin_x = 38
        font_size = 8.8
        leading = 10.5
        section_gap = 4
    elif spec.format_variant == "wide":
        margin_x = 72
        font_size = 10.3
        leading = 13
        section_gap = 8
    elif spec.format_variant == "large_font":
        margin_x = 58
        font_size = 11.0
        leading = 14
        section_gap = 8
    else:
        margin_x = 54
        font_size = 9.4
        leading = 11.6
        section_gap = 6
    usable_w = page_w - 2 * margin_x

    # low-information blank/separator handling
    if content.low_info_kind == "blank":
        if spec.content_version == "intentionally_left_blank":
            c.setFont("Helvetica", 11)
            c.drawCentredString(page_w / 2, page_h / 2, "This page intentionally left blank")
        c.showPage()
        return
    if content.low_info_kind == "separator":
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(page_w / 2, page_h / 2 + 18, "SYNTHETIC RECORDS SEPARATOR")
        c.setFont("Helvetica", 10)
        c.drawCentredString(page_w / 2, page_h / 2 - 4, content.body_note or "Records continue after this page.")
        c.showPage()
        return

    # title block
    c.setFont("Helvetica-Bold", 15 if spec.format_variant != "compact" else 13)
    c.drawString(margin_x, y, content.title or "Synthetic Page")
    if content.watermark:
        c.saveState()
        c.setFillColor(colors.Color(0.85, 0.85, 0.85))
        c.setFont("Helvetica-Bold", 42)
        c.translate(page_w / 2, page_h / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, content.watermark)
        c.restoreState()
        c.setFillColor(colors.black)
    y -= 18
    c.setFont("Helvetica", 8.4)
    meta_line = f"{content.subtitle} | Patient: {content.patient_id} | Provider: {content.provider_id}"
    y = draw_wrapped_reportlab(c, meta_line, margin_x, y, usable_w, "Helvetica", 8.2, 10, max_lines=2)
    y -= 5

    # section drawing
    for head, lines in content.sections:
        if y < 110:
            break
        c.setFont("Helvetica-Bold", font_size + 0.4)
        c.drawString(margin_x, y, head)
        y -= leading
        for line in lines:
            bullet_prefix = "- " if spec.format_variant in ("compact", "wide") and head in ("Plan", "Follow Up", "Activity", "Medication") else ""
            y = draw_wrapped_reportlab(c, bullet_prefix + line, margin_x + 10, y, usable_w - 10, "Helvetica", font_size, leading, max_lines=4)
        y -= section_gap

    # table
    if content.table_title and content.table_rows and y > 150:
        c.setFont("Helvetica-Bold", font_size + 0.2)
        c.drawString(margin_x, y, content.table_title)
        y -= leading + 1
        cols = content.table_columns
        n = len(cols)
        col_w = usable_w / n
        row_h = leading + 5
        c.setStrokeColor(colors.grey)
        c.setFillColor(colors.lightgrey)
        c.rect(margin_x, y - row_h + 3, usable_w, row_h, stroke=1, fill=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", max(7.2, font_size - 1.2))
        for i, col in enumerate(cols):
            c.drawString(margin_x + i * col_w + 3, y - row_h + 8, col[:24])
        y -= row_h
        c.setFont("Helvetica", max(7.0, font_size - 1.5))
        for row in content.table_rows[:8]:
            if y < 90:
                break
            c.rect(margin_x, y - row_h + 3, usable_w, row_h, stroke=1, fill=0)
            for i, val in enumerate(row[:n]):
                c.drawString(margin_x + i * col_w + 3, y - row_h + 8, str(val)[:28])
            y -= row_h
        y -= 6

    if content.body_note and y > 120:
        y = draw_wrapped_reportlab(c, content.body_note, margin_x, y, usable_w, "Helvetica", font_size, leading, max_lines=8)

    # footer boilerplate
    footer_y = 48
    c.setFont("Helvetica", 7.2)
    for i, line in enumerate(content.footer_lines[:3]):
        c.drawString(margin_x, footer_y + i * 9, line)
    # source overlays that keep native text available
    if "page_stamp" in spec.transformations or spec.source_group == "ere_records":
        c.saveState()
        c.setFillColor(colors.darkgrey)
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(page_w - 38, 24, f"STAMP {spec.page_id[-4:]} | PAGE {spec.page_number or 0}")
        c.restoreState()
    if "footer_overlay" in spec.transformations:
        c.saveState()
        c.setFillColor(colors.Color(0.2, 0.2, 0.2, alpha=0.6))
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(page_w / 2, 18, "RECEIVED BY SYNTHETIC INTAKE - FOOTER OVERLAY")
        c.restoreState()
    c.showPage()

# ---------- PIL image generation and transformations ----------

def pil_text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]

def wrap_text_pil(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if pil_text_size(draw, test, font)[0] <= max_width or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def draw_wrapped_pil(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, max_width: int,
                     font: ImageFont.FreeTypeFont, fill=(0, 0, 0), leading: Optional[int] = None,
                     max_lines: Optional[int] = None) -> int:
    lines = wrap_text_pil(draw, text, font, max_width)
    if max_lines is not None:
        lines = lines[:max_lines]
    if leading is None:
        leading = int(font.size * 1.25)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += leading
    return y

def draw_barcode_pil(draw: ImageDraw.ImageDraw, x: int, y: int, width: int = 160, height: int = 40) -> None:
    rng = random.Random(54321)
    cur = x
    while cur < x + width:
        w = rng.choice([2, 3, 4, 5])
        gap = rng.choice([2, 3, 4])
        draw.rectangle([cur, y, cur + w, y + height], fill=(0, 0, 0))
        cur += w + gap

def apply_noise(img: Image.Image, amount: float) -> Image.Image:
    arr = np.asarray(img).astype(np.int16)
    noise = np.random.default_rng(SEED).normal(0, amount, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)

def add_shadow(img: Image.Image) -> Image.Image:
    w, h = img.size
    overlay = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(overlay)
    # diagonal gradient-like shadow band
    for i in range(0, w, 6):
        shade = int(80 * (i / max(1, w)))
        draw.line([(i, 0), (0, i)], fill=shade, width=18)
    shadow = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(Image.blend(img, shadow, 0.18), img, overlay)

def transform_image(img: Image.Image, transformations: List[str], spec: PageSpec) -> Image.Image:
    out = img
    draw = ImageDraw.Draw(out)
    if "ocr_trap_substitutions" in transformations:
        # This is handled in text rendering through content_version, not here.
        pass
    if "add_fax_header" in transformations:
        draw.rectangle([0, 0, out.size[0], 42], fill=(245, 245, 245), outline=(0, 0, 0))
        f = pil_font(18, bold=True)
        draw.text((20, 10), f"FAX  SYNTHETIC HEADER  {date_str(11)}  PAGE {spec.page_number or 1}", font=f, fill=(0, 0, 0))
    if "add_page_stamp" in transformations:
        f = pil_font(17, bold=True)
        draw.text((out.size[0] - 260, out.size[1] - 42), f"STAMP {spec.page_id[-5:]}", font=f, fill=(40, 40, 40))
    if "add_ere_barcode" in transformations:
        draw_barcode_pil(draw, out.size[0] - 220, 56, 160, 38)
        draw.text((out.size[0] - 220, 98), "ERE SYN", font=pil_font(14), fill=(0, 0, 0))
    if "watermark" in transformations:
        wm = Image.new("RGBA", out.size, (255, 255, 255, 0))
        wd = ImageDraw.Draw(wm)
        f = pil_font(72, bold=True)
        wd.text((out.size[0] // 5, out.size[1] // 2), "COPY", font=f, fill=(120, 120, 120, 60))
        wm = wm.rotate(28, resample=Image.Resampling.BICUBIC, center=(out.size[0] // 2, out.size[1] // 2))
        out = Image.alpha_composite(out.convert("RGBA"), wm).convert("RGB")
    if "black_border" in transformations:
        draw = ImageDraw.Draw(out)
        bw = max(8, out.size[0] // 80)
        draw.rectangle([0, 0, out.size[0] - 1, out.size[1] - 1], outline=(0, 0, 0), width=bw)
    if "rotate_1_degree" in transformations:
        out = out.rotate(1.0, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255))
    if "rotate_3_degrees" in transformations:
        out = out.rotate(3.0, resample=Image.Resampling.BICUBIC, fillcolor=(245, 245, 245))
    if "skew_1_degree" in transformations:
        w, h = out.size
        shift = int(0.02 * h)
        out = out.transform((w, h), Image.Transform.AFFINE, (1, 0.02, -shift, 0, 1, 0), fillcolor=(255, 255, 255), resample=Image.Resampling.BICUBIC)
    if "crop_margin_5_percent" in transformations:
        w, h = out.size
        dx, dy = int(w * 0.05), int(h * 0.05)
        cropped = out.crop((dx, dy, w - dx, h - dy))
        out = cropped.resize((w, h), Image.Resampling.BICUBIC)
    if "crop_edge_left" in transformations:
        w, h = out.size
        cropped = out.crop((int(w * 0.06), 0, w, h))
        out = cropped.resize((w, h), Image.Resampling.BICUBIC)
    if "crop_bottom_50_percent" in transformations:
        w, h = out.size
        cropped = out.crop((0, 0, w, int(h * 0.52)))
        out = cropped.resize((w, h), Image.Resampling.BICUBIC)
    if "blur_light" in transformations:
        out = out.filter(ImageFilter.GaussianBlur(radius=0.7))
    if "blur_medium" in transformations:
        out = out.filter(ImageFilter.GaussianBlur(radius=1.4))
    if "add_noise_light" in transformations:
        out = apply_noise(out, 7)
    if "add_noise_medium" in transformations:
        out = apply_noise(out, 16)
    if "contrast_shift" in transformations:
        out = ImageEnhance.Contrast(out).enhance(0.72)
    if "brightness_low" in transformations:
        out = ImageEnhance.Brightness(out).enhance(0.82)
    if "low_contrast" in transformations:
        out = ImageEnhance.Contrast(out).enhance(0.50)
    if "shadow" in transformations:
        out = add_shadow(out)
    if "resolution_downsample_100dpi" in transformations:
        w, h = out.size
        small = out.resize((max(1, w // 2), max(1, h // 2)), Image.Resampling.BILINEAR)
        out = small.resize((w, h), Image.Resampling.BILINEAR)
    if "jpeg_quality_45" in transformations:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            out.save(tmp.name, "JPEG", quality=45)
            tmp_path = tmp.name
        out = Image.open(tmp_path).convert("RGB")
        os.unlink(tmp_path)
    return out.convert("RGB")

def text_for_image(content: Content, spec: PageSpec) -> Content:
    if "ocr_trap_substitutions" not in spec.transformations:
        return content
    # clone-like substitution in visible text
    replacements = {
        "pain": "pa1n",
        "lisinopril": "IisinopriI",
        "chest": "cfiest",
        "normal": "norrnal",
        "hypertension": "hypertens1on",
    }
    def sub(s: str) -> str:
        out = s
        for a, b in replacements.items():
            out = out.replace(a, b).replace(a.title(), b.title())
        return out
    return Content(
        record_type=content.record_type,
        title=sub(content.title),
        subtitle=sub(content.subtitle),
        patient_id=content.patient_id,
        provider_id=content.provider_id,
        provider_name=content.provider_name,
        visit_id=content.visit_id,
        visit_date=content.visit_date,
        sections=[(sub(h), [sub(x) for x in lines]) for h, lines in content.sections],
        table_title=sub(content.table_title) if content.table_title else None,
        table_columns=[sub(x) for x in content.table_columns],
        table_rows=[[sub(str(x)) for x in row] for row in content.table_rows],
        footer_lines=[sub(x) for x in content.footer_lines],
        watermark=content.watermark,
        body_note=sub(content.body_note) if content.body_note else None,
        low_info_kind=content.low_info_kind,
        order_variant=content.order_variant,
    )

def make_pil_page(spec: PageSpec) -> Image.Image:
    page_w_pt, page_h_pt = PAGE_SIZES[spec.page_size_name]
    # 150 dpi equivalent for Letter = 1275 x 1650; keep proportional for other sizes
    scale = 110 / 72.0
    w, h = int(page_w_pt * scale), int(page_h_pt * scale)
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    content = text_for_image(spec.content, spec)

    margin = 90 if spec.format_variant != "compact" else 65
    y = 60
    # scan/camera source header patterns
    if spec.source_group == "fax_records":
        draw.rectangle([0, 0, w - 1, 48], fill=(248, 248, 248), outline=(0, 0, 0))
        draw.text((18, 12), "FAX IMAGE COPY - SYNTHETIC", font=pil_font(20, True), fill=(0, 0, 0))
        y = 72
    elif spec.source_group == "claimant_uploads":
        draw.text((margin, y), "PHONE CAMERA UPLOAD - SYNTHETIC", font=pil_font(18, True), fill=(35, 35, 35))
        y += 34
    elif spec.source_group == "ere_records":
        draw.text((margin, y), "ERE SCANNED COPY - SYNTHETIC", font=pil_font(18, True), fill=(0, 0, 0))
        draw_barcode_pil(draw, w - margin - 170, y - 10, 150, 36)
        y += 44
    else:
        draw.text((margin, y), "SYNTHETIC HEALTH RECORD - IMAGE ONLY", font=pil_font(18, True), fill=(0, 0, 0))
        y += 34
    draw.line([margin, y, w - margin, y], fill=(0, 0, 0), width=2)
    y += 25

    if content.low_info_kind == "blank":
        if spec.content_version == "intentionally_left_blank":
            txt = "This page intentionally left blank"
            f = pil_font(24)
            tw, th = pil_text_size(draw, txt, f)
            draw.text(((w - tw) // 2, (h - th) // 2), txt, font=f, fill=(0, 0, 0))
        return transform_image(img, spec.transformations, spec)
    if content.low_info_kind == "separator":
        f = pil_font(34, True)
        txt = "SYNTHETIC RECORDS SEPARATOR"
        tw, th = pil_text_size(draw, txt, f)
        draw.text(((w - tw) // 2, h // 2 - 30), txt, font=f, fill=(0, 0, 0))
        f2 = pil_font(18)
        txt2 = content.body_note or "Records continue after this page."
        tw, th = pil_text_size(draw, txt2, f2)
        draw.text(((w - tw) // 2, h // 2 + 18), txt2, font=f2, fill=(0, 0, 0))
        return transform_image(img, spec.transformations, spec)

    title_font = pil_font(30 if spec.format_variant != "compact" else 26, True)
    draw.text((margin, y), content.title or "Synthetic Page", font=title_font, fill=(0, 0, 0))
    y += int(title_font.size * 1.25)
    meta = f"{content.subtitle} | Patient: {content.patient_id} | Provider: {content.provider_id}"
    y = draw_wrapped_pil(draw, meta, margin, y, w - 2 * margin, pil_font(15), leading=21, max_lines=2)
    y += 10

    body_font = pil_font(17 if spec.format_variant != "compact" else 15)
    head_font = pil_font(18 if spec.format_variant != "compact" else 16, True)
    leading = 23 if spec.format_variant != "compact" else 20
    for head, lines in content.sections:
        if y > h - 330:
            break
        draw.text((margin, y), head, font=head_font, fill=(0, 0, 0))
        y += leading
        for line in lines:
            y = draw_wrapped_pil(draw, line, margin + 20, y, w - 2 * margin - 20, body_font, leading=leading, max_lines=4)
        y += 8

    if content.table_title and content.table_rows and y < h - 260:
        draw.text((margin, y), content.table_title, font=head_font, fill=(0, 0, 0))
        y += leading
        n = len(content.table_columns)
        table_w = w - 2 * margin
        col_w = table_w // max(1, n)
        row_h = 32
        draw.rectangle([margin, y, margin + table_w, y + row_h], fill=(225, 225, 225), outline=(0, 0, 0), width=2)
        for i, col in enumerate(content.table_columns):
            draw.text((margin + i * col_w + 7, y + 8), col[:22], font=pil_font(13, True), fill=(0, 0, 0))
        y += row_h
        for row in content.table_rows[:8]:
            if y > h - 160:
                break
            draw.rectangle([margin, y, margin + table_w, y + row_h], outline=(0, 0, 0), width=1)
            for i, val in enumerate(row[:n]):
                draw.text((margin + i * col_w + 7, y + 8), str(val)[:24], font=pil_font(13), fill=(0, 0, 0))
            y += row_h
        y += 18

    # Footer boilerplate
    foot_font = pil_font(12)
    fy = h - 86
    for line in content.footer_lines[:3]:
        draw.text((margin, fy), line, font=foot_font, fill=(0, 0, 0))
        fy += 16
    return transform_image(img, spec.transformations, spec)

# ---------- cases and filler ----------

def build_corpus(root: Path) -> Builder:
    b = Builder(root)
    # docs by group
    docs_to_create = [
        ("received_001", "received_records", "received_records_001.pdf"),
        ("received_002", "received_records", "received_records_002.pdf"),
        ("received_003", "received_records", "received_records_followups_003.pdf"),
        ("ere_001", "ere_records", "ere_batch_001.pdf"),
        ("ere_002", "ere_records", "ere_batch_002.pdf"),
        ("ere_003", "ere_records", "ere_reordered_batch_003.pdf"),
        ("claimant_001", "claimant_uploads", "claimant_upload_camera_001.pdf"),
        ("claimant_002", "claimant_uploads", "claimant_upload_mixed_002.pdf"),
        ("fax_001", "fax_records", "fax_records_001.pdf"),
        ("fax_002", "fax_records", "fax_records_002.pdf"),
        ("email_001", "email_records", "email_attachments_001.pdf"),
        ("email_002", "email_records", "email_duplicate_attachments_002.pdf"),
    ]
    for d in docs_to_create:
        b.add_doc(*d)

    # Case 001 - exact rendered duplicate (3 pages, includes intra-group and cross-group)
    c001 = make_visit_note(1, "essential hypertension", "Blood pressure follow-up", "Blood pressure is stable on current regimen.", "Continue current plan and home blood pressure log.", patient_num=1, visit_num=1, visit_days=9)
    b.add_cluster_description("cluster_001_exact_rendered", "Same native page rendered identically in received and email records, with an intra-group received duplicate.", "exact_rendered_duplicate", "duplicate")
    p001a = b.add_page("received_001", "received_records", c001, "case_001", "visit_note_template_a", page_id="v2_case_001_doc_received_p001", duplicate_cluster_id="cluster_001_exact_rendered", expected_cluster_label="duplicate", duplicate_category="exact_rendered_duplicate", format_variant="exact_clean", ab_scenarios=["received_vs_ere", "multi_source_batch"])
    p001b = b.add_page("received_001", "received_records", c001, "case_001", "visit_note_template_a", page_id="v2_case_001_doc_received_p002", duplicate_cluster_id="cluster_001_exact_rendered", expected_cluster_label="duplicate", duplicate_category="exact_rendered_duplicate", format_variant="exact_clean", ab_scenarios=["intra_group_received"])
    p001c = b.add_page("email_001", "email_records", c001, "case_001", "visit_note_template_a", page_id="v2_case_001_doc_email_p001", duplicate_cluster_id="cluster_001_exact_rendered", expected_cluster_label="duplicate", duplicate_category="exact_rendered_duplicate", format_variant="exact_clean", ab_scenarios=["email_duplicate_attachment"])

    # Case 002 - same text, different formatting
    c002 = make_visit_note(2, "type 2 diabetes mellitus", "Diabetes follow-up", "Glycemic control is acceptable in this synthetic record.", "Continue metformin and repeat synthetic A1c in 3 months.", patient_num=2, visit_num=2, visit_days=20)
    b.add_cluster_description("cluster_002_same_text_format", "Same visit note text in different margins, fonts, headers, line breaks, and source footers.", "same_text_different_formatting", "duplicate")
    p002a = b.add_page("received_001", "received_records", c002, "case_002", "visit_note_template_a", page_id="v2_case_002_received_format_a", duplicate_cluster_id="cluster_002_same_text_format", expected_cluster_label="duplicate", duplicate_category="same_text_different_formatting", format_variant="wide", ab_scenarios=["received_vs_ere"])
    p002b = b.add_page("ere_001", "ere_records", c002, "case_002", "visit_note_template_a", page_id="v2_case_002_ere_format_b", duplicate_cluster_id="cluster_002_same_text_format", expected_cluster_label="duplicate", duplicate_category="same_text_different_formatting", format_variant="compact", transformations=["page_stamp", "footer_overlay", "add_ere_barcode"], content_version="format_variant_compact", ab_scenarios=["received_vs_ere"])
    p002c = b.add_page("email_001", "email_records", c002, "case_002", "visit_note_template_a", page_id="v2_case_002_email_format_c", duplicate_cluster_id="cluster_002_same_text_format", expected_cluster_label="duplicate", duplicate_category="same_text_different_formatting", format_variant="large_font", content_version="format_variant_large_font", ab_scenarios=["email_duplicate_attachment"])

    # Case 003 - fax degraded duplicate
    c003 = make_imaging_report(3, patient_num=3, finding_variant=1)
    b.add_cluster_description("cluster_003_fax_degraded", "Clean imaging report duplicated as a degraded fax scan with header, noise, skew, border, compression, and low resolution.", "same_page_different_scan_quality", "likely_duplicate")
    p003a = b.add_page("email_001", "email_records", c003, "case_003", "imaging_report_template_a", page_id="v2_case_003_email_clean", duplicate_cluster_id="cluster_003_fax_degraded", expected_cluster_label="likely_duplicate", duplicate_category="same_page_different_scan_quality", ab_scenarios=["fax_vs_email"])
    p003b = b.add_page("fax_001", "fax_records", c003, "case_003", "imaging_report_template_a", page_id="v2_case_003_fax_degraded", duplicate_cluster_id="cluster_003_fax_degraded", expected_cluster_label="likely_duplicate", duplicate_category="same_page_different_scan_quality", text_availability="image_only", ocr_difficulty="medium", visual_quality="fax_degraded", rendering_method="image_pdf", transformations=["add_fax_header", "black_border", "skew_1_degree", "resolution_downsample_100dpi", "add_noise_medium", "jpeg_quality_45"], ab_scenarios=["fax_vs_email"])

    # Case 004 - OCR-only duplicate
    c004 = make_instructions(4, patient_num=4)
    b.add_cluster_description("cluster_004_ocr_only", "Born-digital instruction page paired with a clean image-only scan; OCR is needed for text on scan side.", "ocr_only_duplicate", "likely_duplicate")
    p004a = b.add_page("received_001", "received_records", c004, "case_004", "patient_instruction_template_a", page_id="v2_case_004_received_native", duplicate_cluster_id="cluster_004_ocr_only", expected_cluster_label="likely_duplicate", duplicate_category="ocr_only_duplicate", ab_scenarios=["claimant_vs_provider"])
    p004b = b.add_page("claimant_001", "claimant_uploads", c004, "case_004", "patient_instruction_template_a", page_id="v2_case_004_claimant_scan_easy", duplicate_cluster_id="cluster_004_ocr_only", expected_cluster_label="likely_duplicate", duplicate_category="ocr_only_duplicate", text_availability="image_only", ocr_difficulty="easy", visual_quality="clean_scan", rendering_method="image_pdf", transformations=["resolution_downsample_100dpi"], ab_scenarios=["claimant_vs_provider"])

    # Case 005 - rotated/cropped camera duplicate
    c005 = make_authorization_page(5, patient_num=5)
    b.add_cluster_description("cluster_005_camera_crop", "Clean authorization page paired with a rotated, cropped, shadowed claimant camera upload.", "same_page_different_scan_quality", "likely_duplicate")
    p005a = b.add_page("received_001", "received_records", c005, "case_005", "authorization_template_a", page_id="v2_case_005_provider_clean", duplicate_cluster_id="cluster_005_camera_crop", expected_cluster_label="likely_duplicate", duplicate_category="camera_scan_duplicate", ab_scenarios=["claimant_vs_provider"])
    p005b = b.add_page("claimant_001", "claimant_uploads", c005, "case_005", "authorization_template_a", page_id="v2_case_005_claimant_camera", duplicate_cluster_id="cluster_005_camera_crop", expected_cluster_label="likely_duplicate", duplicate_category="camera_scan_duplicate", text_availability="image_only", ocr_difficulty="hard", visual_quality="camera_shadow_crop", rendering_method="image_pdf", transformations=["rotate_3_degrees", "crop_margin_5_percent", "shadow", "brightness_low", "blur_light"], page_size_name="a4", ab_scenarios=["claimant_vs_provider"])

    # Case 006 - same template different visit hard negatives
    case006_pages = []
    for i in range(12):
        c = make_visit_note(60 + i, "essential hypertension", "Blood pressure follow-up", f"Visit details differ: home readings average {128 + i}/{76 + i % 6}.", f"Plan differs: adjust lifestyle goal number {i + 1}; no duplicate of other visits.", patient_num=6, visit_num=60 + i, visit_days=45 + i * 11)
        doc_key = "received_002" if i < 7 else "ere_002"
        group = b.docs[doc_key].source_group
        p = b.add_page(doc_key, group, c, "case_006", "visit_note_template_a", page_id=f"v2_case_006_same_template_visit_{i+1:02d}", hard_negative_trap_type="same_template_different_visit", notes="Same provider template; different date/details/assessment/plan.")
        case006_pages.append(p)
    for p1, p2 in zip(case006_pages, case006_pages[1:]):
        b.add_pair("should_not_match", p1, p2, "not_duplicate", "same_template_different_visit", "Same visit note template and diagnosis but different visit date and clinical details.", "candidate_explosion")

    # Case 007 - same diagnosis different record hard negatives
    case007_pages = []
    dx_terms = ["type 2 diabetes mellitus", "essential hypertension", "chronic low back pain", "major depressive disorder", "COPD"]
    for i, dx in enumerate(dx_terms * 3):
        c = make_visit_note(90 + i, dx, f"Follow-up for {dx}", f"Assessment text unique to record {i + 1}; no duplicated page content.", f"Plan text unique to record {i + 1}; follow-up interval differs.", provider_name=PROVIDERS[i % len(PROVIDERS)], patient_num=7 + (i % 4), visit_num=90 + i, visit_days=52 + i * 9)
        doc_key = ["received_002", "ere_002", "email_002"][i % 3]
        group = b.docs[doc_key].source_group
        p = b.add_page(doc_key, group, c, "case_007", "diagnosis_reuse_template", page_id=f"v2_case_007_same_dx_diff_record_{i+1:02d}", hard_negative_trap_type="same_diagnosis_different_record", notes="Same diagnosis topic, different record type/date/details.")
        case007_pages.append(p)
    for i in range(0, len(case007_pages) - 1, 2):
        b.add_pair("should_not_match", case007_pages[i], case007_pages[i + 1], "not_duplicate", "same_diagnosis_different_record", "Both discuss a common diagnosis but the page contents are different visits.", "candidate_explosion")

    # Case 008 - repeated medication list trap
    case008_pages = []
    for i in range(18):
        c = make_visit_note(120 + i, DIAGNOSES[i % len(DIAGNOSES)], f"Routine follow-up {i+1}", f"Meaningful assessment is unique for medication-list trap page {i+1}.", f"Plan contains unique counseling item {i+1}; shared medication list should not dominate.", provider_name="Lakeside Primary Care", patient_num=8, visit_num=120 + i, visit_days=70 + i * 10, meds=MED_LIST_COMMON)
        doc_key = ["received_002", "received_003", "ere_002", "email_002"][i % 4]
        group = b.docs[doc_key].source_group
        p = b.add_page(doc_key, group, c, "case_008", "visit_note_shared_med_list", page_id=f"v2_case_008_med_trap_visit_{i+1:02d}", hard_negative_trap_type="same_medication_list_different_context", notes="Shares a common medication list with many pages; not duplicate.")
        case008_pages.append(p)
    for i in range(0, len(case008_pages) - 3, 3):
        b.add_pair("should_not_match", case008_pages[i], case008_pages[i + 3], "not_duplicate", "same_medication_list_different_context", "Medication table repeats but chief complaint, assessment, and plan differ.", "candidate_explosion")

    # Case 009 - repeated fax cover sheet trap plus identical low-info duplicate
    fax_covers = []
    for i in range(14):
        c = make_cover_sheet(150 + i, kind="fax", recipient=f"Records Unit {i % 5}", page_count=7 + (i % 4), date_days=100 + i)
        p = b.add_page("fax_001" if i < 8 else "fax_002", "fax_records", c, "case_009", "fax_cover_template_a", page_id=f"v2_case_009_fax_cover_{i+1:02d}", text_availability="image_only", ocr_difficulty="medium", visual_quality="fax_cover", rendering_method="image_pdf", transformations=["add_fax_header", "black_border", "add_noise_light", "jpeg_quality_45"], hard_negative_trap_type="same_cover_template_different_fax", is_low_information_page=True, notes="Cover-sheet template reused with different recipient/date/page count.")
        fax_covers.append(p)
    for p1, p2 in zip(fax_covers, fax_covers[1:]):
        b.add_pair("should_not_match", p1, p2, "not_duplicate", "same_cover_template_different_fax", "Same fax cover template but different transmission metadata.", "fax_vs_email")
    # Identical low-information cover duplicate should be ignored, not reported as useful duplicate.
    c009_ident = make_cover_sheet(199, kind="fax", recipient="Central Intake", page_count=3, date_days=130)
    b.add_cluster_description("cluster_009_lowinfo_identical_cover", "Two identical generic fax cover sheets; technically duplicate but low-information ignore.", "low_information_cover", "low_information_ignore")
    p009x = b.add_page("fax_002", "fax_records", c009_ident, "case_009", "fax_cover_template_lowinfo", page_id="v2_case_009_identical_cover_a", duplicate_cluster_id="cluster_009_lowinfo_identical_cover", expected_cluster_label="low_information_ignore", duplicate_category="low_information_cover", text_availability="image_only", ocr_difficulty="medium", visual_quality="fax_cover", rendering_method="image_pdf", transformations=["add_fax_header", "black_border", "jpeg_quality_45"], is_low_information_page=True)
    p009y = b.add_page("fax_002", "fax_records", c009_ident, "case_009", "fax_cover_template_lowinfo", page_id="v2_case_009_identical_cover_b", duplicate_cluster_id="cluster_009_lowinfo_identical_cover", expected_cluster_label="low_information_ignore", duplicate_category="low_information_cover", text_availability="image_only", ocr_difficulty="medium", visual_quality="fax_cover", rendering_method="image_pdf", transformations=["add_fax_header", "black_border", "jpeg_quality_45"], is_low_information_page=True)
    b.add_pair("low_information_ignore", p009x, p009y, "low_information_ignore", "identical_generic_cover_sheet", "Identical generic cover pages are not useful reviewer matches.", "fax_vs_email")

    # Case 010 - lab panel same layout different values
    lab_pages = []
    for i in range(20):
        c = make_lab_result(200 + i, patient_num=10, panel="CBC" if i % 2 == 0 else "CMP", values_shift=i)
        doc_key = ["received_003", "ere_002", "email_002", "fax_001"][i % 4]
        group = b.docs[doc_key].source_group
        rendering = "image_pdf" if group == "fax_records" else "native_pdf"
        text_avail = "image_only" if rendering == "image_pdf" else "native_text"
        transforms = ["add_fax_header", "black_border", "add_noise_light", "jpeg_quality_45"] if rendering == "image_pdf" else []
        p = b.add_page(doc_key, group, c, "case_010", "lab_panel_template_a", page_id=f"v2_case_010_lab_layout_diff_values_{i+1:02d}", rendering_method=rendering, text_availability=text_avail, ocr_difficulty="medium" if rendering == "image_pdf" else "none", visual_quality="fax_lab" if rendering == "image_pdf" else "clean", transformations=transforms, hard_negative_trap_type="same_lab_layout_different_values", notes="Same lab panel layout but different values/date/accession.")
        lab_pages.append(p)
    for i in range(0, len(lab_pages) - 2, 2):
        b.add_pair("should_not_match", lab_pages[i], lab_pages[i + 2], "not_duplicate", "same_lab_layout_different_values", "Same lab layout/components but values and collection dates differ.", "candidate_explosion")

    # Case 011 - imaging template different findings
    imaging_pages = []
    for i in range(16):
        c = make_imaging_report(250 + i, patient_num=11, finding_variant=i)
        doc_key = ["received_003", "ere_002", "email_002", "fax_002"][i % 4]
        group = b.docs[doc_key].source_group
        rendering = "image_pdf" if group == "fax_records" else "native_pdf"
        text_avail = "image_only" if rendering == "image_pdf" else "native_text"
        transforms = ["add_fax_header", "black_border", "skew_1_degree", "add_noise_light"] if rendering == "image_pdf" else []
        p = b.add_page(doc_key, group, c, "case_011", "imaging_report_template_a", page_id=f"v2_case_011_imaging_template_diff_{i+1:02d}", rendering_method=rendering, text_availability=text_avail, ocr_difficulty="medium" if rendering == "image_pdf" else "none", visual_quality="fax_imaging" if rendering == "image_pdf" else "clean", transformations=transforms, hard_negative_trap_type="same_imaging_template_different_findings", notes="Same imaging headings/template, different findings/impression.")
        imaging_pages.append(p)
    for i in range(0, len(imaging_pages) - 1, 2):
        b.add_pair("should_not_match", imaging_pages[i], imaging_pages[i + 1], "not_duplicate", "same_imaging_template_different_findings", "Same MRI report template but findings/impression differ.", "candidate_explosion")

    # Case 012 - partial overlap medication list
    med_only = make_med_list(12, patient_num=12, meds=MED_LIST_COMMON)
    visit_with_meds = make_visit_note(312, "hyperlipidemia", "Medication review", "Assessment contains additional lipid management details.", "Continue medications and add diet counseling unique to the visit summary.", patient_num=12, visit_num=312, visit_days=120, meds=MED_LIST_COMMON)
    p012a = b.add_page("received_001", "received_records", med_only, "case_012", "medication_list_template_a", page_id="v2_case_012_med_list_only", partial_overlap_group_id="partial_012_med_list_inside_visit", notes="Medication list only page.")
    p012b = b.add_page("received_001", "received_records", visit_with_meds, "case_012", "visit_note_shared_med_list", page_id="v2_case_012_visit_summary_with_med_list", partial_overlap_group_id="partial_012_med_list_inside_visit", notes="Contains same medication list plus assessment and plan.")
    b.add_pair("partial_overlap", p012a, p012b, "partial_overlap", "medication_list_contained_in_visit_note", "Medication table is contained in visit summary, but page has additional meaningful clinical content.", "partial_overlap")

    # Case 013 - partial overlap visit/discharge summary
    dx_section = Content(
        record_type="diagnosis_summary",
        title="Prior Diagnosis Summary",
        subtitle="Summary Date: 2024-05-12",
        patient_id=patient_id(13),
        provider_id=provider_id(5),
        provider_name="Cedar Valley Hospital",
        visit_id=visit_id(313),
        visit_date="2024-05-12",
        sections=[("Prior Diagnoses", ["type 2 diabetes mellitus; essential hypertension; chronic low back pain; hyperlipidemia"] * 3)],
        footer_lines=[BOILERPLATE[2]],
    )
    discharge = make_discharge_summary(13, patient_num=13, include_prior_dx=True)
    p013a = b.add_page("email_001", "email_records", dx_section, "case_013", "diagnosis_summary_template_a", page_id="v2_case_013_prior_dx_summary", partial_overlap_group_id="partial_013_dx_inside_discharge")
    p013b = b.add_page("received_002", "received_records", discharge, "case_013", "discharge_summary_template_a", page_id="v2_case_013_discharge_repeats_dx", partial_overlap_group_id="partial_013_dx_inside_discharge")
    b.add_pair("partial_overlap", p013a, p013b, "partial_overlap", "diagnosis_section_contained_in_discharge_summary", "Discharge summary repeats prior diagnosis section but adds admission/course/follow-up.", "partial_overlap")

    # Additional partial-overlap examples: lab table contained in a summary, split note, and cropped half page.
    lab_overlap = make_lab_result(1314, patient_num=13, panel="CBC", values_shift=4)
    lab_summary = Content(
        record_type="visit_summary",
        title="Visit Summary with Lab Review",
        subtitle="Summary Date: 2024-05-20",
        patient_id=patient_id(13),
        provider_id=provider_id(1),
        provider_name="Lakeside Primary Care",
        visit_id=visit_id(1314),
        visit_date="2024-05-20",
        sections=[
            ("Assessment", ["Synthetic follow-up visit reviews the CBC results and adds hypertension counseling."]),
            ("Plan", ["Repeat laboratory testing later only if clinically indicated in this fabricated example."]),
        ],
        table_title=lab_overlap.table_title,
        table_columns=lab_overlap.table_columns,
        table_rows=lab_overlap.table_rows,
        footer_lines=[BOILERPLATE[0], BOILERPLATE[2]],
    )
    p013c = b.add_page("email_001", "email_records", lab_overlap, "case_013", "lab_panel_template_a", page_id="v2_case_013_lab_table_only", partial_overlap_group_id="partial_013_lab_inside_summary")
    p013d = b.add_page("received_001", "received_records", lab_summary, "case_013", "visit_summary_with_lab_table", page_id="v2_case_013_visit_summary_with_lab_table", partial_overlap_group_id="partial_013_lab_inside_summary")
    b.add_pair("partial_overlap", p013c, p013d, "partial_overlap", "lab_table_contained_in_visit_summary", "Lab table appears inside a larger visit summary that has additional assessment and plan text.", "partial_overlap")

    split_full = make_visit_note(1315, "major depressive disorder", "Mood follow-up", "Mood symptoms improved with counseling and stable sleep.", "Continue counseling and follow up in six weeks.", provider_name="Beacon Behavioral Health", patient_num=13, visit_num=1315, visit_days=138)
    split_part = Content(
        record_type="visit_note_extract",
        title="Progress Note Extract",
        subtitle="Visit Date: 2024-05-20 | Extracted Sections",
        patient_id=split_full.patient_id,
        provider_id=split_full.provider_id,
        provider_name=split_full.provider_name,
        visit_id=split_full.visit_id,
        visit_date=split_full.visit_date,
        sections=[split_full.sections[3], split_full.sections[4]],
        table_title=None,
        table_columns=[],
        table_rows=[],
        footer_lines=[BOILERPLATE[1]],
    )
    p013e = b.add_page("received_002", "received_records", split_full, "case_013", "visit_note_template_a", page_id="v2_case_013_full_visit_note", partial_overlap_group_id="partial_013_split_note")
    p013f = b.add_page("ere_001", "ere_records", split_part, "case_013", "visit_note_split_extract", page_id="v2_case_013_split_note_extract", partial_overlap_group_id="partial_013_split_note", transformations=["page_stamp"], content_version="section_extract")
    b.add_pair("partial_overlap", p013e, p013f, "partial_overlap", "two_page_note_split_differently", "One source contains the full note while another source contains only assessment and plan sections.", "partial_overlap")

    cropped_full = make_instructions(1316, patient_num=13)
    p013g = b.add_page("received_003", "received_records", cropped_full, "case_013", "patient_instruction_template_a", page_id="v2_case_013_full_instruction_page", partial_overlap_group_id="partial_013_cropped_half")
    p013h = b.add_page("claimant_001", "claimant_uploads", cropped_full, "case_013", "patient_instruction_template_a", page_id="v2_case_013_cropped_half_instruction", partial_overlap_group_id="partial_013_cropped_half", rendering_method="image_pdf", text_availability="image_only", ocr_difficulty="hard", visual_quality="cropped_half_camera_scan", transformations=["crop_bottom_50_percent", "rotate_1_degree", "shadow", "blur_light"], content_version="cropped_half")
    b.add_pair("partial_overlap", p013g, p013h, "partial_overlap", "cropped_page_contains_half_of_full_page", "Claimant upload contains only the upper half of a full instruction page.", "partial_overlap")

    # Case 014 - multi-page duplicate packet: received five-page packet appears inside ERE batch with stamps and extra pages.
    packet_contents = [
        make_cover_sheet(1401, kind="batch", recipient="ERE Intake", page_count=5, date_days=140),
        make_visit_note(1402, "chronic low back pain", "Back pain follow-up", "Pain pattern stable without new neurologic deficit.", "Continue physical therapy and home exercise program.", patient_num=14, visit_num=1402, visit_days=141),
        make_lab_result(1403, patient_num=14, panel="CBC", values_shift=2),
        make_imaging_report(1404, patient_num=14, finding_variant=2),
        make_instructions(1405, patient_num=14),
    ]
    packet_received = []
    packet_ere = []
    for i, content in enumerate(packet_contents, start=1):
        cl = f"cluster_014_packet_page_{i:02d}"
        b.add_cluster_description(cl, f"Page {i} of a five-page packet duplicated across received records and an ERE batch.", "multi_page_duplicate_packet", "likely_duplicate")
        p_r = b.add_page("received_002", "received_records", content, "case_014", f"packet_template_page_{i}", page_id=f"v2_case_014_received_packet_p{i:03d}", duplicate_cluster_id=cl, expected_cluster_label="likely_duplicate", duplicate_category="multi_page_duplicate_packet", packet_id="packet_014", ab_scenarios=["received_vs_ere", "multi_page_packet"])
        p_e = b.add_page("ere_003", "ere_records", content, "case_014", f"packet_template_page_{i}", page_id=f"v2_case_014_ere_embedded_packet_p{i:03d}", duplicate_cluster_id=cl, expected_cluster_label="likely_duplicate", duplicate_category="multi_page_duplicate_packet", format_variant="compact" if i % 2 else "standard", transformations=["page_stamp", "add_ere_barcode"] if i != 3 else ["page_stamp", "footer_overlay"], content_version="ere_batch_copy", packet_id="packet_014", ab_scenarios=["received_vs_ere", "multi_page_packet"])
        packet_received.append(p_r)
        packet_ere.append(p_e)
    # ERE batch cover and noise around embedded packet.
    for i in range(15):
        content = make_cover_sheet(1450 + i, kind="batch", recipient=f"ERE Processing Team {i % 3}", page_count=20, date_days=145 + i) if i % 5 == 0 else make_visit_note(1450 + i, DIAGNOSES[i % len(DIAGNOSES)], f"ERE filler visit {i+1}", f"Unique ERE filler assessment {i+1}.", f"Unique ERE filler plan {i+1}.", patient_num=15 + i % 3, visit_num=1450 + i, visit_days=145 + i * 4)
        p = b.add_page("ere_003", "ere_records", content, "case_014", "ere_batch_noise_template", page_id=f"v2_case_014_ere_noise_{i+1:02d}", hard_negative_trap_type="batch_noise_same_source", transformations=["page_stamp"], ab_scenarios=["received_vs_ere", "multi_page_packet"])
        if i > 0:
            b.add_pair("should_not_match", p, packet_ere[i % len(packet_ere)], "not_duplicate", "batch_noise_near_packet", "ERE batch filler page is near the duplicate packet but is not a duplicate.", "received_vs_ere")

    # Case 016 - low information blank/separator/signature pages (some repeated)
    low_info_pages = []
    b.add_cluster_description("cluster_016_blank_pages", "Multiple blank/near-blank pages that should be grouped or ignored instead of dominating reports.", "blank_or_near_blank", "low_information_ignore")
    for i in range(22):
        kind = "blank" if i % 3 == 0 else ("separator" if i % 3 == 1 else "signature")
        if kind == "signature":
            content = make_signature_page(1600 + i)
            record_family = "signature_only_template"
            rt = "signature_page"
        else:
            content = make_blank_page(1600 + i, kind=kind)
            record_family = f"{kind}_template"
            rt = content.record_type
        doc_key = ["received_003", "ere_001", "fax_002", "claimant_002", "email_002"][i % 5]
        group = b.docs[doc_key].source_group
        image = group in ("fax_records", "claimant_uploads")
        transforms = []
        if group == "fax_records":
            transforms = ["add_fax_header", "black_border", "add_noise_light", "jpeg_quality_45"]
        elif group == "claimant_uploads":
            transforms = ["rotate_1_degree", "shadow"]
        p = b.add_page(doc_key, group, content, "case_016", record_family, page_id=f"v2_case_016_low_info_{i+1:02d}", duplicate_cluster_id="cluster_016_blank_pages" if kind == "blank" else None, expected_cluster_label="low_information_ignore" if kind == "blank" else None, duplicate_category="blank_or_near_blank" if kind == "blank" else None, content_version="intentionally_left_blank" if kind == "blank" and i % 2 == 0 else "low_information", rendering_method="image_pdf" if image else "native_pdf", text_availability="image_only" if image else "native_text", ocr_difficulty="medium" if image else "none", visual_quality="low_information_scan" if image else "clean", transformations=transforms, is_low_information_page=True, notes=f"Low-information {rt}; should not dominate reports.")
        low_info_pages.append(p)
    for p1, p2 in zip(low_info_pages, low_info_pages[1:]):
        if p1.content.low_info_kind in ("blank", "separator") or p2.content.low_info_kind in ("blank", "separator"):
            b.add_pair("low_information_ignore", p1, p2, "low_information_ignore", "low_information_page", "Blank/separator/signature-style pages should be grouped or ignored carefully.", "low_information")

    # Case 017 - page-number/header/footer noise
    c017 = make_procedure_note(17, patient_num=17)
    b.add_cluster_description("cluster_017_source_noise", "Same procedure note with source-added page stamps, footer overlays, watermark, and barcode.", "source_added_noise", "likely_duplicate")
    p017a = b.add_page("received_003", "received_records", c017, "case_017", "procedure_note_template_a", page_id="v2_case_017_clean_procedure", duplicate_cluster_id="cluster_017_source_noise", expected_cluster_label="likely_duplicate", duplicate_category="source_added_noise", ab_scenarios=["received_vs_ere"])
    p017b = b.add_page("ere_001", "ere_records", c017, "case_017", "procedure_note_template_a", page_id="v2_case_017_ere_stamped_procedure", duplicate_cluster_id="cluster_017_source_noise", expected_cluster_label="likely_duplicate", duplicate_category="source_added_noise", transformations=["page_stamp", "footer_overlay", "add_ere_barcode"], content_version="ere_stamped", ab_scenarios=["received_vs_ere"])
    p017c = b.add_page("fax_001", "fax_records", c017, "case_017", "procedure_note_template_a", page_id="v2_case_017_fax_border_procedure", duplicate_cluster_id="cluster_017_source_noise", expected_cluster_label="likely_duplicate", duplicate_category="source_added_noise", rendering_method="image_pdf", text_availability="image_only", ocr_difficulty="medium", visual_quality="fax_degraded", transformations=["add_fax_header", "black_border", "add_noise_medium", "jpeg_quality_45"], ab_scenarios=["fax_vs_email"])

    # Case 018 - related same visit different pages
    p18_content_1 = make_visit_note(18, "COPD", "Shortness of breath follow-up", "Symptoms stable; inhaler technique reviewed.", "Continue inhaler and pulmonary follow-up.", provider_name="Pine Street Pulmonary", patient_num=18, visit_num=18, visit_days=180)
    p18_content_2 = Content(
        record_type="visit_note_continuation",
        title="Progress Note - Continuation",
        subtitle="Visit Date: 2024-06-30 | Page 2 of 2",
        patient_id=patient_id(18),
        provider_id=provider_id(6),
        provider_name="Pine Street Pulmonary",
        visit_id=visit_id(18),
        visit_date="2024-06-30",
        sections=[
            ("Pulmonary Function Review", ["Synthetic spirometry narrative appears on page 2 and is not a duplicate of page 1."]),
            ("Education", ["Reviewed inhaler timing, symptom diary, and emergency plan."]),
            ("Follow Up", ["Return in 3 months or sooner for worsening synthetic symptoms."]),
        ],
        footer_lines=[BOILERPLATE[1], BOILERPLATE[3]],
    )
    p018a = b.add_page("received_002", "received_records", p18_content_1, "case_018", "visit_note_template_a", page_id="v2_case_018_same_visit_page_1", related_group_id="related_018_same_visit")
    p018b = b.add_page("received_002", "received_records", p18_content_2, "case_018", "visit_note_template_a_continuation", page_id="v2_case_018_same_visit_page_2", related_group_id="related_018_same_visit")
    b.add_pair("related_but_not_duplicate", p018a, p018b, "not_duplicate", "same_visit_different_page", "Same provider, patient, date, and visit ID, but page 1 and page 2 contain different content.", "related_not_duplicate")

    # Case 019 - paraphrased same content
    c019a = make_visit_note(19, "chronic low back pain", "Back pain follow-up", "Patient denies chest pain and reports no falls.", "Continue home exercise; follow up in eight weeks.", patient_num=19, visit_num=19, visit_days=190, paraphrase=False)
    c019b = make_visit_note(19, "chronic low back pain", "Back discomfort recheck", "No chest pain reported and no falls are described.", "Maintain home exercises; return in about two months.", patient_num=19, visit_num=19, visit_days=190, paraphrase=True)
    b.add_cluster_description("cluster_019_paraphrase", "Same underlying visit content expressed with semantic paraphrases; embedding/LLM-relevant later.", "semantic_paraphrase", "likely_duplicate")
    p019a = b.add_page("email_002", "email_records", c019a, "case_019", "visit_note_template_a", page_id="v2_case_019_original_text", duplicate_cluster_id="cluster_019_paraphrase", expected_cluster_label="likely_duplicate", duplicate_category="semantic_paraphrase", content_version="original")
    p019b = b.add_page("received_003", "received_records", c019b, "case_019", "visit_note_template_a", page_id="v2_case_019_paraphrased_text", duplicate_cluster_id="cluster_019_paraphrase", expected_cluster_label="likely_duplicate", duplicate_category="semantic_paraphrase", content_version="semantic_paraphrase")

    # Medical abbreviation variation: hypertension/HTN, shortness of breath/SOB, diabetes mellitus/DM, follow up/f/u.
    c019c = make_visit_note(191, "hypertension and diabetes mellitus", "Shortness of breath follow up", "Patient reports shortness of breath has improved; diabetes mellitus is stable.", "Follow up in four weeks for hypertension review.", patient_num=19, visit_num=191, visit_days=194)
    c019d = Content(
        record_type="visit_note",
        title="Progress Note",
        subtitle="Visit Date: 2024-07-15 | Encounter Type: Office Visit",
        patient_id=patient_id(19),
        provider_id=provider_id(3),
        provider_name="Lakeside Primary Care",
        visit_id=visit_id(191),
        visit_date="2024-07-15",
        sections=[
            ("Chief Complaint", ["SOB f/u"]),
            ("History", ["Synthetic patient reports SOB has improved; DM is stable. No real person is represented."]),
            ("Assessment", ["HTN and DM", "Clinical meaning matches the expanded terminology page."]),
            ("Plan", ["F/u in four weeks for HTN review."]),
        ],
        table_title="Current Medications",
        table_columns=["Medication", "Dose", "Directions", "Status"],
        table_rows=[list(row) for row in MED_LIST_COMMON],
        footer_lines=BOILERPLATE[:3],
    )
    b.add_cluster_description("cluster_019_abbreviation_variants", "Same visit content expressed with medical abbreviation variants: hypertension/HTN, shortness of breath/SOB, diabetes mellitus/DM, follow up/f/u.", "medical_abbreviation_variation", "likely_duplicate")
    p019c = b.add_page("received_001", "received_records", c019c, "case_019", "visit_note_abbreviation_template", page_id="v2_case_019_expanded_medical_terms", duplicate_cluster_id="cluster_019_abbreviation_variants", expected_cluster_label="likely_duplicate", duplicate_category="medical_abbreviation_variation", content_version="expanded_terms")
    p019d = b.add_page("ere_002", "ere_records", c019d, "case_019", "visit_note_abbreviation_template", page_id="v2_case_019_abbreviated_medical_terms", duplicate_cluster_id="cluster_019_abbreviation_variants", expected_cluster_label="likely_duplicate", duplicate_category="medical_abbreviation_variation", content_version="abbreviated_terms", transformations=["page_stamp", "add_ere_barcode"])

    # Case 020 - OCR corruption trap
    c020 = make_visit_note(20, "essential hypertension", "Chest pain follow-up", "Chest pain resolved and blood pressure is normal today.", "Continue lisinopril and call for recurrent chest pain.", patient_num=20, visit_num=20, visit_days=200)
    b.add_cluster_description("cluster_020_ocr_trap", "Born-digital note paired with scan containing OCR-trap substitutions such as pain->pa1n and lisinopril->IisinopriI.", "ocr_corruption_trap", "needs_review")
    p020a = b.add_page("received_003", "received_records", c020, "case_020", "visit_note_ocr_trap_template", page_id="v2_case_020_native_clean", duplicate_cluster_id="cluster_020_ocr_trap", expected_cluster_label="needs_review", duplicate_category="ocr_corruption_trap")
    p020b = b.add_page("claimant_002", "claimant_uploads", c020, "case_020", "visit_note_ocr_trap_template", page_id="v2_case_020_image_ocr_trap", duplicate_cluster_id="cluster_020_ocr_trap", expected_cluster_label="needs_review", duplicate_category="ocr_corruption_trap", rendering_method="image_pdf", text_availability="image_only", ocr_difficulty="trap", visual_quality="ocr_trap_scan", transformations=["ocr_trap_substitutions", "low_contrast", "blur_medium", "crop_edge_left", "rotate_1_degree", "add_noise_medium"], page_size_name="legal", content_version="ocr_trap_substitutions")

    # Additional candidate explosion pages to reach medium size and stress thresholds.
    add_candidate_explosion_filler(b)

    return b

def add_candidate_explosion_filler(b: Builder) -> None:
    # More same-template visit notes across sources.
    visit_pages = []
    for i in range(70):
        dx = DIAGNOSES[i % len(DIAGNOSES)]
        c = make_visit_note(2000 + i, dx, f"Template follow-up {i+1}", f"Assessment sentence number {i+1} is unique and contains source-specific facts.", f"Plan sentence number {i+1} differs; schedule interval {(i % 6) + 2} weeks.", provider_name="Lakeside Primary Care", patient_num=30 + (i % 6), visit_num=2000 + i, visit_days=210 + i * 3, meds=MED_LIST_COMMON)
        doc_key = ["received_002", "received_003", "ere_001", "ere_002", "email_001", "email_002"][i % 6]
        group = b.docs[doc_key].source_group
        p = b.add_page(doc_key, group, c, "case_015", "candidate_explosion_visit_template", page_id=f"v2_case_015_explosion_visit_{i+1:03d}", hard_negative_trap_type="same_template_boilerplate_medlist", transformations=["page_stamp"] if group == "ere_records" else [], notes="Filler page for candidate explosion: same provider template, boilerplate, medication list; unique clinical details.", ab_scenarios=["received_vs_ere", "candidate_explosion"])
        visit_pages.append(p)
    for i in range(0, len(visit_pages) - 10, 10):
        b.add_pair("should_not_match", visit_pages[i], visit_pages[i + 10], "not_duplicate", "same_template_boilerplate_medlist", "Many shared template/boilerplate/medication-list features but unique visit content.", "candidate_explosion")

    # Repeated medication list standalone pages with different dates/status notes.
    med_pages = []
    for i in range(24):
        meds = list(MED_LIST_COMMON)
        if i % 5 == 0:
            meds = meds + [("gabapentin", f"{100 + i*10} mg", "nightly", "active")]
        c = make_med_list(3000 + i, patient_num=40 + i % 4, meds=meds)
        c.sections.append(("Context", [f"Medication review context differs for standalone med list page {i+1}."]))
        doc_key = ["received_001", "ere_001", "email_002", "claimant_001"][i % 4]
        group = b.docs[doc_key].source_group
        image = group == "claimant_uploads"
        p = b.add_page(doc_key, group, c, "case_015", "standalone_med_list_trap", page_id=f"v2_case_015_standalone_med_trap_{i+1:02d}", rendering_method="image_pdf" if image else "native_pdf", text_availability="image_only" if image else "native_text", ocr_difficulty="hard" if image else "none", visual_quality="camera_med_list" if image else "clean", transformations=["rotate_1_degree", "shadow", "crop_margin_5_percent"] if image else (["page_stamp"] if group == "ere_records" else []), hard_negative_trap_type="standalone_med_list_repeated", notes="Standalone medication lists share medication names but differ by context/status/date.", ab_scenarios=["claimant_vs_provider", "candidate_explosion"])
        med_pages.append(p)
    for i in range(0, len(med_pages) - 1, 4):
        b.add_pair("should_not_match", med_pages[i], med_pages[i+1], "not_duplicate", "standalone_med_list_repeated", "Medication list format and drugs repeat, but context/date/status differ.", "candidate_explosion")

    # More lab and imaging hard negatives.
    lab_more = []
    for i in range(32):
        c = make_lab_result(4000 + i, patient_num=50 + i % 5, panel="CBC", values_shift=20 + i)
        doc_key = ["received_002", "ere_003", "email_001", "fax_001"][i % 4]
        group = b.docs[doc_key].source_group
        image = group == "fax_records"
        p = b.add_page(doc_key, group, c, "case_015", "candidate_explosion_lab_template", page_id=f"v2_case_015_explosion_lab_{i+1:02d}", rendering_method="image_pdf" if image else "native_pdf", text_availability="image_only" if image else "native_text", ocr_difficulty="medium" if image else "none", visual_quality="fax_lab" if image else "clean", transformations=["add_fax_header", "black_border", "add_noise_medium", "jpeg_quality_45"] if image else (["page_stamp"] if group == "ere_records" else []), hard_negative_trap_type="same_lab_layout_different_values", notes="Candidate-explosion lab page: same layout, distinct values/accession/date.", ab_scenarios=["fax_vs_email", "candidate_explosion"])
        lab_more.append(p)
    for i in range(0, len(lab_more)-3, 4):
        b.add_pair("should_not_match", lab_more[i], lab_more[i+3], "not_duplicate", "same_lab_layout_different_values", "Same components and table layout, different results/accession/date.", "candidate_explosion")

    imaging_more = []
    for i in range(24):
        c = make_imaging_report(5000 + i, patient_num=55 + i % 4, finding_variant=i+1)
        doc_key = ["received_003", "ere_001", "email_002", "claimant_002"][i % 4]
        group = b.docs[doc_key].source_group
        image = group == "claimant_uploads"
        p = b.add_page(doc_key, group, c, "case_015", "candidate_explosion_imaging_template", page_id=f"v2_case_015_explosion_imaging_{i+1:02d}", rendering_method="image_pdf" if image else "native_pdf", text_availability="image_only" if image else "native_text", ocr_difficulty="hard" if image else "none", visual_quality="camera_imaging" if image else "clean", transformations=["rotate_3_degrees", "crop_margin_5_percent", "shadow", "blur_light"] if image else (["page_stamp"] if group == "ere_records" else []), hard_negative_trap_type="same_imaging_template_different_findings", notes="Candidate-explosion imaging page: same headings, different findings/impression.", ab_scenarios=["claimant_vs_provider", "candidate_explosion"])
        imaging_more.append(p)
    for i in range(0, len(imaging_more)-2, 3):
        b.add_pair("should_not_match", imaging_more[i], imaging_more[i+2], "not_duplicate", "same_imaging_template_different_findings", "Imaging template repeats but findings/impression differ.", "candidate_explosion")

    # Procedure, discharge, authorization diverse filler.
    for i in range(28):
        if i % 3 == 0:
            c = make_procedure_note(6000 + i, patient_num=60 + i % 4)
            fam = "procedure_note_template_a"
        elif i % 3 == 1:
            c = make_discharge_summary(6000 + i, patient_num=60 + i % 4, include_prior_dx=(i % 6 == 1))
            fam = "discharge_summary_template_a"
        else:
            c = make_authorization_page(6000 + i, patient_num=60 + i % 4)
            fam = "authorization_template_a"
        doc_key = ["received_001", "ere_002", "fax_002", "email_001", "claimant_001"][i % 5]
        group = b.docs[doc_key].source_group
        image = group in ("fax_records", "claimant_uploads")
        if group == "fax_records":
            transforms = ["add_fax_header", "black_border", "add_noise_medium", "jpeg_quality_45"]
            oq = "medium"
            vq = "fax_degraded"
        elif group == "claimant_uploads":
            transforms = ["rotate_1_degree", "shadow", "crop_margin_5_percent"]
            oq = "hard"
            vq = "camera_shadow_crop"
        elif group == "ere_records":
            transforms = ["page_stamp", "add_ere_barcode"]
            oq = "none"
            vq = "clean_with_stamp"
        else:
            transforms = []
            oq = "none"
            vq = "clean"
        b.add_page(doc_key, group, c, "case_015", fam, page_id=f"v2_case_015_diverse_filler_{i+1:02d}", rendering_method="image_pdf" if image else "native_pdf", text_availability="image_only" if image else "native_text", ocr_difficulty=oq, visual_quality=vq, transformations=transforms, hard_negative_trap_type="same_boilerplate_different_content" if i % 2 == 0 else None, notes="Diverse filler with common boilerplate but unique meaningful content.", ab_scenarios=["multi_source_batch", "candidate_explosion"])

    # Additional OCR difficulty samples not necessarily duplicates.
    ocr_levels = ["easy", "medium", "hard", "trap"]
    for i, level in enumerate(ocr_levels * 5):
        c = make_visit_note(7000 + i, DIAGNOSES[i % len(DIAGNOSES)], f"OCR stress note {i+1}", f"OCR stress assessment for {level} sample {i+1}.", f"OCR stress plan sample {i+1}; content differs from other OCR pages.", patient_num=70 + i % 3, visit_num=7000 + i, visit_days=300 + i)
        doc_key = "fax_002" if level in ("medium", "trap") else "claimant_002"
        group = b.docs[doc_key].source_group
        if level == "easy":
            transforms = ["resolution_downsample_100dpi"]
            vq = "clean_scan"
        elif level == "medium":
            transforms = ["add_fax_header", "skew_1_degree", "add_noise_medium", "jpeg_quality_45"]
            vq = "fax_degraded"
        elif level == "hard":
            transforms = ["low_contrast", "blur_medium", "rotate_3_degrees", "crop_edge_left", "shadow"]
            vq = "hard_camera_scan"
        else:
            transforms = ["ocr_trap_substitutions", "low_contrast", "blur_medium", "crop_edge_left", "add_noise_medium"]
            vq = "ocr_trap_scan"
        b.add_page(doc_key, group, c, "case_015", "ocr_stress_nonduplicate_template", page_id=f"v2_case_015_ocr_stress_{level}_{i+1:02d}", rendering_method="image_pdf", text_availability="image_only", ocr_difficulty=level, visual_quality=vq, transformations=transforms, hard_negative_trap_type="ocr_stress_nonduplicate", notes="OCR stress page with unique content; not part of duplicate truth.", ab_scenarios=["ocr_stress", "candidate_explosion"])

# ---------- rendering and outputs ----------

def render_pdfs(builder: Builder) -> None:
    pdf_root = builder.root / "pdfs"
    temp_dir = builder.root / "_tmp_images"
    temp_dir.mkdir(parents=True, exist_ok=True)
    for group, folder in GROUPS.items():
        (pdf_root / folder).mkdir(parents=True, exist_ok=True)

    for doc in builder.docs.values():
        folder = GROUPS[doc.source_group]
        pdf_path = pdf_root / folder / doc.filename
        # Assign page numbers and document info before drawing.
        for i, p in enumerate(doc.pages, start=1):
            p.page_number = i
            p.document_name = doc.filename
            p.relative_pdf_path = str(Path("pdfs") / folder / doc.filename)
            page_w, page_h = PAGE_SIZES[p.page_size_name]
            p.page_size_points = [round(page_w, 2), round(page_h, 2)]
        c = canvas.Canvas(str(pdf_path), pagesize=letter, pageCompression=1, invariant=1)
        c.setTitle(f"Synthetic Corpus v2 - {doc.filename}")
        c.setAuthor("OpenAI synthetic data generator")
        c.setSubject("Synthetic PDF duplicate detection corpus; no real PHI")
        for p in doc.pages:
            draw_native_page(c, p, temp_dir)
            p.content_fingerprint = fingerprint_content(p.content, normalize=True)
        c.save()
    shutil.rmtree(temp_dir, ignore_errors=True)

def page_ref(spec: PageSpec) -> Dict[str, Any]:
    return {
        "page_id": spec.page_id,
        "document": spec.document_name,
        "relative_pdf_path": spec.relative_pdf_path,
        "page": spec.page_number,
        "source_group": spec.source_group,
        "record_type": spec.content.record_type,
    }

def finalize_truth(builder: Builder) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    page_by_id = {p.page_id: p for p in builder.pages}
    # Populate cluster page refs.
    for cl_id, c in builder.cluster_defs.items():
        c["pages"] = [page_ref(p) for p in builder.pages if p.duplicate_cluster_id == cl_id]
        if not c.get("description"):
            c["description"] = f"Synthetic duplicate cluster {cl_id}."
    duplicate_clusters = [c for c in builder.cluster_defs.values() if c.get("expected_label") != "low_information_ignore"]
    low_information_clusters = [c for c in builder.cluster_defs.values() if c.get("expected_label") == "low_information_ignore"]

    # Auto-generate must_match for duplicate clusters and low info ignore for low-info clusters.
    existing_pairs = set()
    for bucket, pairs in builder.pair_truth.items():
        for item in pairs:
            key = tuple(sorted([item["page_1_id"], item["page_2_id"]]))
            existing_pairs.add((bucket, key))
    for c in builder.cluster_defs.values():
        cluster_pages = [p for p in builder.pages if p.duplicate_cluster_id == c["cluster_id"]]
        for p1, p2 in itertools.combinations(cluster_pages, 2):
            if c.get("expected_label") == "low_information_ignore" or p1.is_low_information_page or p2.is_low_information_page:
                bucket = "low_information_ignore"
                label = "low_information_ignore"
                reason = "Low-information duplicate/near-duplicate should be grouped or suppressed in reviewer reports."
            else:
                bucket = "must_match"
                label = c.get("expected_label", "duplicate")
                reason = c.get("description", "Duplicate cluster pair.")
            key = tuple(sorted([p1.page_id, p2.page_id]))
            if (bucket, key) not in existing_pairs:
                builder.add_pair(bucket, p1, p2, label, c.get("category") or p1.duplicate_category or "duplicate", reason)
                existing_pairs.add((bucket, key))

    # Expand pair items with document/page details.
    expanded = {}
    for bucket, pairs in builder.pair_truth.items():
        expanded[bucket] = []
        for item in pairs:
            p1 = page_by_id[item["page_1_id"]]
            p2 = page_by_id[item["page_2_id"]]
            expanded[bucket].append({
                **item,
                "page_1": page_ref(p1),
                "page_2": page_ref(p2),
                "source_groups": [p1.source_group, p2.source_group],
                "same_document": p1.document_name == p2.document_name,
                "cross_group": p1.source_group != p2.source_group,
            })
    truth_pairs = {
        "schema_version": "synthetic_corpus_v2_truth_pairs_v1",
        "labels": TRUTH_LABELS,
        "description": "Pair-level truth buckets for Synthetic Corpus v2. Page IDs are canonical; document/page fields are conveniences.",
        **expanded,
    }
    truth_clusters = {
        "schema_version": "synthetic_corpus_v2_truth_clusters_v1",
        "duplicate_clusters": sorted(duplicate_clusters, key=lambda x: x["cluster_id"]),
        "low_information_clusters": sorted(low_information_clusters, key=lambda x: x["cluster_id"]),
        "notes": [
            "duplicate_clusters include expected duplicate/likely/needs_review clusters.",
            "low_information_clusters are technically duplicate-ish but should be grouped or suppressed.",
        ],
    }
    return truth_pairs, truth_clusters

def write_outputs(builder: Builder) -> None:
    render_pdfs(builder)
    truth_pairs, truth_clusters = finalize_truth(builder)

    # Page metadata.
    page_meta = []
    for p in builder.pages:
        d = {
            "page_id": p.page_id,
            "document_name": p.document_name,
            "relative_pdf_path": p.relative_pdf_path,
            "page_number": p.page_number,
            "source_group": p.source_group,
            "synthetic_patient_id": p.synthetic_patient_id,
            "synthetic_provider_id": p.synthetic_provider_id,
            "synthetic_visit_id": p.synthetic_visit_id,
            "record_type": p.content.record_type,
            "duplicate_cluster_id": p.duplicate_cluster_id,
            "page_family": p.page_family,
            "content_version": p.content_version,
            "text_availability": p.text_availability,
            "ocr_difficulty": p.ocr_difficulty,
            "visual_quality": p.visual_quality,
            "is_low_information_page": p.is_low_information_page,
            "transformations": p.transformations,
            "rendering_method": p.rendering_method,
            "format_variant": p.format_variant,
            "page_size": p.page_size_name,
            "page_size_points": p.page_size_points,
            "case_id": p.case_id,
            "case_description": CASE_DESCRIPTIONS.get(p.case_id),
            "duplicate_category": p.duplicate_category,
            "expected_cluster_label": p.expected_cluster_label,
            "hard_negative_trap_type": p.hard_negative_trap_type,
            "partial_overlap_group_id": p.partial_overlap_group_id,
            "related_group_id": p.related_group_id,
            "packet_id": p.packet_id,
            "ab_scenarios": p.ab_scenarios,
            "content_fingerprint": p.content_fingerprint,
            "intended_text_fingerprint": p.intended_text_fingerprint,
            "notes": p.notes,
        }
        page_meta.append(d)

    # Counts.
    counts = {
        "pages_total": len(builder.pages),
        "documents_total": len(builder.docs),
        "pages_by_source_group": {},
        "pages_by_record_type": {},
        "pages_by_text_availability": {},
        "pages_by_ocr_difficulty": {},
        "pages_by_visual_quality": {},
        "pages_by_case_id": {},
        "low_information_pages": sum(1 for p in builder.pages if p.is_low_information_page),
        "image_only_pages": sum(1 for p in builder.pages if p.text_availability == "image_only"),
        "duplicate_clusters": len(truth_clusters["duplicate_clusters"]),
        "low_information_clusters": len(truth_clusters["low_information_clusters"]),
        "truth_pair_counts": {bucket: len(truth_pairs[bucket]) for bucket in ["must_match", "should_not_match", "partial_overlap", "related_but_not_duplicate", "low_information_ignore"]},
    }
    for p in builder.pages:
        counts["pages_by_source_group"][p.source_group] = counts["pages_by_source_group"].get(p.source_group, 0) + 1
        rt = p.content.record_type
        counts["pages_by_record_type"][rt] = counts["pages_by_record_type"].get(rt, 0) + 1
        counts["pages_by_text_availability"][p.text_availability] = counts["pages_by_text_availability"].get(p.text_availability, 0) + 1
        counts["pages_by_ocr_difficulty"][p.ocr_difficulty] = counts["pages_by_ocr_difficulty"].get(p.ocr_difficulty, 0) + 1
        counts["pages_by_visual_quality"][p.visual_quality] = counts["pages_by_visual_quality"].get(p.visual_quality, 0) + 1
        counts["pages_by_case_id"][p.case_id] = counts["pages_by_case_id"].get(p.case_id, 0) + 1

    manifest = {
        "schema_version": "synthetic_corpus_v2_manifest_v1",
        "corpus_name": "Synthetic Corpus v2 - medium calibration",
        "profile_generated": "medium_calibration",
        "seed": SEED,
        "generated_date": date.today().isoformat(),
        "main_goal": "Test whether deterministic high-recall duplicate candidate generation catches real duplicate candidates without exploding into useless false positives.",
        "size_profiles": {
            "small_dev": {"target_pages": "50-100", "purpose": "fast repeated runs during code changes", "status": "generator profile planned"},
            "medium_calibration": {"target_pages": "250-500", "purpose": "threshold tuning and false positive calibration", "status": "generated"},
            "large_stress": {"target_pages": "1000-2000", "purpose": "runtime, candidate explosion, report usability", "status": "generator profile planned"},
        },
        "labels": TRUTH_LABELS,
        "source_groups": {k: {"folder": v, "formatting_patterns": SOURCE_PATTERN_NOTES[k]} for k, v in GROUPS.items()},
        "case_list": CASE_DESCRIPTIONS,
        "ab_scenarios": {
            "received_vs_ere": {
                "group_a": "received_records",
                "group_b": "ere_records",
                "features": ["exact duplicates", "ERE stamps", "missing pages", "page order changes", "extra cover pages"],
            },
            "fax_vs_email": {
                "group_a": "fax_records",
                "group_b": "email_records",
                "features": ["fax degradation", "fax headers", "black borders", "clean email PDFs"],
            },
            "claimant_vs_provider": {
                "group_a": "claimant_uploads",
                "group_b": "received_records",
                "features": ["phone camera scans", "cropped pages", "rotation", "shadow", "clean provider pages"],
            },
        },
        "candidate_explosion_sets": {
            "same_provider_template": "page_family=candidate_explosion_visit_template",
            "same_medication_list": "page_family=standalone_med_list_trap or visit_note_shared_med_list",
            "same_boilerplate": "hard_negative_trap_type=same_boilerplate_different_content",
            "same_fax_cover_template": "page_family=fax_cover_template_a",
            "same_lab_layout": "page_family=lab_panel_template_a or candidate_explosion_lab_template",
            "same_imaging_template": "page_family=imaging_report_template_a or candidate_explosion_imaging_template",
        },
        "outputs": {
            "manifest": "synthetic_v2_manifest.json",
            "page_metadata": "synthetic_v2_page_metadata.json",
            "truth_pairs": "synthetic_v2_truth_pairs.json",
            "truth_clusters": "synthetic_v2_truth_clusters.json",
            "generation_log": "synthetic_v2_generation_log.json",
            "engine_result_templates": [
                "templates/synthetic_v2_all_pairs_results.schema.json",
                "templates/synthetic_v2_eval.schema.json",
                "templates/synthetic_v2_report.schema.html",
                "templates/synthetic_v2_candidate_summary.schema.csv",
                "templates/synthetic_v2_false_positive_review.schema.csv",
                "templates/synthetic_v2_false_negative_review.schema.csv",
            ],
        },
        "counts": counts,
    }

    generation_log = {
        "schema_version": "synthetic_corpus_v2_generation_log_v1",
        "seed": SEED,
        "generator_script": "generate_synthetic_v2.py",
        "events": [
            {"event": "initialized", "detail": "Created grouped synthetic medical-looking PDFs with no real PHI."},
            {"event": "built_cases", "detail": "Implemented cases case_001 through case_020."},
            {"event": "added_candidate_explosion_filler", "detail": "Added repeated templates, medication lists, boilerplate, lab layouts, imaging layouts, and OCR stress pages."},
            {"event": "rendered_pdfs", "detail": "Rendered native and image-only PDF pages with controlled transformations."},
        ],
        "transformation_catalog": [
            "rotation", "skew", "crop", "border", "compression", "blur", "noise", "contrast", "brightness", "resolution change", "page stamp", "watermark", "fax header", "barcode", "page number overlay", "shadow", "OCR trap substitutions"
        ],
        "text_variation_catalog": [
            "formatting-only differences", "line break changes", "font/margin changes", "minor OCR-like substitutions", "medical abbreviation differences", "semantic paraphrase"
        ],
        "notes": [
            "Engine-run outputs are schema templates only until a detector is run against the corpus.",
            "All patient/provider identifiers are synthetic and generated for duplicate-testing only.",
        ],
    }

    # Engine output schemas/templates.
    templates_dir = builder.root / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    all_pairs_schema = {
        "schema_version": "synthetic_v2_all_pairs_results_schema_v1",
        "description": "Expected shape for engine all-pairs output after running duplicate detection.",
        "required_pair_fields": ["page_1_id", "page_2_id", "candidate_label", "score", "pass_band", "passes_triggered"],
        "allowed_candidate_labels": TRUTH_LABELS,
        "example": {
            "page_1_id": "v2_case_001_doc_received_p001",
            "page_2_id": "v2_case_001_doc_email_p001",
            "candidate_label": "duplicate",
            "score": 0.99,
            "pass_band": "strict",
            "passes_triggered": ["exact_image_hash"],
        },
    }
    eval_schema = {
        "schema_version": "synthetic_v2_eval_schema_v1",
        "required_metrics": [
            "must_match_recall",
            "must_match_recall_by_category",
            "known_false_positives",
            "false_positives_by_trap_type",
            "partial_overlap_detection_rate",
            "candidate_count_per_100_pages",
            "average_candidates_per_page",
            "low_information_false_positives",
            "strict_standard_loose_pass_contribution",
            "ocr_needed_match_recall",
            "visual_degradation_match_recall",
            "same_template_hard_negative_rejection_rate",
            "true_duplicates_only_found_in_loose_pass",
            "false_positives_introduced_by_loose_pass",
            "loose_pass_pairs_to_escalate_to_embeddings",
        ],
    }
    (templates_dir / "synthetic_v2_all_pairs_results.schema.json").write_text(json.dumps(all_pairs_schema, indent=2), encoding="utf-8")
    (templates_dir / "synthetic_v2_eval.schema.json").write_text(json.dumps(eval_schema, indent=2), encoding="utf-8")
    report_schema_html = """<!doctype html>
<html>
<head><meta charset=\"utf-8\"><title>Synthetic v2 Report Schema</title></head>
<body>
<h1>Synthetic v2 Report</h1>
<p>Expected sections after engine run: corpus summary, pass-band contribution, must-match recall by category, false positives by trap type, partial-overlap review, OCR-needed recall, visual-degradation recall, low-information suppression, and loose-pass escalation list.</p>
</body>
</html>
"""
    (templates_dir / "synthetic_v2_report.schema.html").write_text(report_schema_html, encoding="utf-8")
    for fname, cols in {
        "synthetic_v2_candidate_summary.schema.csv": ["pass_band", "candidate_pairs", "true_positive_pairs", "false_positive_pairs", "partial_overlap_pairs", "low_information_pairs", "candidate_pairs_per_100_pages"],
        "synthetic_v2_false_positive_review.schema.csv": ["page_1_id", "page_2_id", "predicted_label", "truth_bucket", "trap_type", "pass_band", "score", "review_note"],
        "synthetic_v2_false_negative_review.schema.csv": ["page_1_id", "page_2_id", "expected_label", "category", "missed_by_passes", "ocr_needed", "visual_transformations", "review_note"],
    }.items():
        with (templates_dir / fname).open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols)

    # README.
    readme = f"""# Synthetic Corpus v2 - Medium Calibration

This corpus contains fabricated medical-looking PDFs for duplicate candidate testing. It contains no real PHI.

Generated profile: medium_calibration
Pages: {counts['pages_total']}
Documents: {counts['documents_total']}

Primary question: Does multipass deterministic detection catch likely duplicates without creating an unreviewable candidate explosion?

## Top-level files

- synthetic_v2_manifest.json
- synthetic_v2_page_metadata.json
- synthetic_v2_truth_pairs.json
- synthetic_v2_truth_clusters.json
- synthetic_v2_generation_log.json

PDFs are under pdfs/group_a_received_records through pdfs/group_e_email_records.

## Notes

Engine-run outputs are not populated because no detection engine was run here. Schema/templates are under templates/ for:

- synthetic_v2_all_pairs_results.json
- synthetic_v2_eval.json
- synthetic_v2_candidate_summary.csv
- synthetic_v2_false_positive_review.csv
- synthetic_v2_false_negative_review.csv

Use page_id as the canonical join key between engine output and truth files.
"""
    (builder.root / "README.md").write_text(readme, encoding="utf-8")

    # Write JSONs.
    (builder.root / "synthetic_v2_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (builder.root / "synthetic_v2_page_metadata.json").write_text(json.dumps({"schema_version": "synthetic_corpus_v2_page_metadata_v1", "pages": page_meta}, indent=2), encoding="utf-8")
    (builder.root / "synthetic_v2_truth_pairs.json").write_text(json.dumps(truth_pairs, indent=2), encoding="utf-8")
    (builder.root / "synthetic_v2_truth_clusters.json").write_text(json.dumps(truth_clusters, indent=2), encoding="utf-8")
    (builder.root / "synthetic_v2_generation_log.json").write_text(json.dumps(generation_log, indent=2), encoding="utf-8")

    # Save a copy of the generator in the corpus root.
    src = Path(__file__).resolve()
    dst = builder.root / "tools" / "generate_synthetic_v2.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src != dst:
        shutil.copy2(src, dst)

    # Compact summary CSV for quick inspection (not engine output).
    with (builder.root / "synthetic_v2_page_index.csv").open("w", newline="", encoding="utf-8") as f:
        cols = ["page_id", "document_name", "page_number", "source_group", "record_type", "case_id", "duplicate_cluster_id", "text_availability", "ocr_difficulty", "visual_quality", "is_low_information_page", "hard_negative_trap_type"]
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for p in page_meta:
            writer.writerow({k: p.get(k) for k in cols})

def make_zip(root: Path) -> Path:
    zip_path = root.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(root), "zip", root)
    return zip_path

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/mnt/data/synthetic_corpus_v2_medium", help="Output folder")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    if args.clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    builder = build_corpus(out)
    write_outputs(builder)
    zip_path = make_zip(out)
    print(json.dumps({"output_dir": str(out), "zip_path": str(zip_path), "pages": len(builder.pages), "documents": len(builder.docs)}, indent=2))

if __name__ == "__main__":
    main()
