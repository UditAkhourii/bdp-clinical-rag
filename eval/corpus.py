"""
Synthetic clinical-corpus generator.

Produces:
    data/patients.jsonl   one JSON object per patient with full identifier roster
    data/notes.jsonl      one JSON object per note (admission/progress/discharge/opd)
    data/queries.jsonl    one JSON object per query with ground-truth note_id(s)
    data/roster.json      flat list of (category, value) pairs across the corpus

Notes are templated and slot-filled deterministically from seeded RNG -- no LLM
calls. This is intentional: it makes the eval byte-reproducible from SEED, and
keeps the bootstrap runnable with zero API keys. The trade-off (notes read more
uniformly than real clinical text) is acknowledged in the paper's limitations.

Run:  python -m corpus
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path

from config import DATA_DIR, SCALE, SEED


# ---------------------------------------------------------------------------
# Source vocabularies (disjoint from BDP surrogate vocabularies)
# ---------------------------------------------------------------------------

REAL_FIRST_NAMES = [
    # Regionally diverse Indian names; deliberately disjoint from surrogate pool
    "Rahul", "Priya", "Anil", "Sneha", "Vikram", "Pooja", "Ramesh", "Sunita",
    "Karthik", "Lakshmi", "Manoj", "Deepa", "Suresh", "Kavita", "Rajesh",
    "Anjali", "Sanjay", "Meena", "Harsha", "Geetha", "Bhavesh", "Nisha",
    "Tarun", "Shweta", "Naveen", "Rekha", "Prakash", "Madhuri", "Ganesh",
    "Anita",
]
REAL_LAST_NAMES = [
    "Kumar", "Singh", "Pillai", "Hegde", "Bhat", "Naidu", "Choudhary",
    "Agarwal", "Mishra", "Tiwari", "Mukherjee", "Sen", "Dutta", "Roy",
    "Khan", "Pandey", "Yadav",
]

PINCODE_PREFIXES = ["56", "11", "40", "60", "70", "80", "44", "20", "33", "39"]

ICD10 = [
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("I10",   "Essential (primary) hypertension"),
    ("J45.9", "Asthma, unspecified"),
    ("K21.9", "GERD without esophagitis"),
    ("N18.3", "Chronic kidney disease, stage 3"),
    ("M54.5", "Low back pain"),
    ("E78.5", "Hyperlipidemia, unspecified"),
    ("F32.9", "Major depressive disorder, single episode"),
]

DRUGS = [
    ("Metformin", "500 mg BD"),
    ("Amlodipine", "5 mg OD"),
    ("Atorvastatin", "20 mg HS"),
    ("Telmisartan", "40 mg OD"),
    ("Pantoprazole", "40 mg OD"),
    ("Salbutamol", "100 mcg PRN"),
    ("Sertraline", "50 mg OD"),
    ("Aspirin", "75 mg OD"),
]

LABS = ["HbA1c", "FBS", "PPBS", "Creatinine", "eGFR", "LDL", "HDL", "TSH"]

NOTE_TYPES = ["admission", "progress", "discharge", "outpatient"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Patient:
    patient_id: str
    name: str
    age: int
    sex: str
    phone: str
    mrn: str
    abha_id: str
    pincode: str
    address: str

    def identifiers(self) -> list[tuple[str, str]]:
        return [
            ("NAME",    self.name),
            ("PHONE",   self.phone),
            ("MRN",     self.mrn),
            ("ABHA",    self.abha_id),
            ("PINCODE", self.pincode),
            ("ADDR",    self.address),
        ]


@dataclass
class Note:
    note_id: str
    patient_id: str
    note_type: str
    visit_date: str
    text: str
    # Annotations consumed by the query generator (not used at retrieval time)
    icd10: str
    drugs: list[str]
    vitals: dict
    labs: dict


@dataclass
class Query:
    query_id: str
    patient_id: str
    category: str            # lookup | longitudinal | reasoning
    text: str
    ground_truth_note_ids: list[str]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def gen_patient(rng: random.Random, idx: int) -> Patient:
    first = rng.choice(REAL_FIRST_NAMES)
    last = rng.choice(REAL_LAST_NAMES)
    pin = rng.choice(PINCODE_PREFIXES) + f"{rng.randint(0, 9999):04d}"
    return Patient(
        patient_id=f"P{idx:04d}",
        name=f"{first} {last}",
        age=rng.randint(28, 78),
        sex=rng.choice(["M", "F"]),
        phone=f"+91-9{rng.randint(100_000_000, 999_999_999)}",
        mrn=f"MRN-{rng.randint(1_000_000, 9_999_999):07d}",
        abha_id=f"{rng.randint(10, 99)}-{rng.randint(1000,9999)}-"
                f"{rng.randint(1000,9999)}-{rng.randint(1000,9999)}",
        pincode=pin,
        address=f"{rng.randint(1, 300)} {rng.choice(['Main','Cross','Park'])} "
                f"Road, {rng.choice(['Bengaluru','Mumbai','Chennai','Kolkata','Delhi'])}",
    )


def _vitals(rng: random.Random) -> dict:
    return {
        "bp_systolic": rng.randint(110, 160),
        "bp_diastolic": rng.randint(70, 100),
        "pulse": rng.randint(64, 102),
        "spo2": rng.randint(94, 100),
        "temp_c": round(rng.uniform(36.4, 38.4), 1),
    }


def _labs(rng: random.Random) -> dict:
    return {
        "HbA1c": round(rng.uniform(5.4, 11.2), 1),
        "FBS":   rng.randint(82, 240),
        "Creatinine": round(rng.uniform(0.7, 2.1), 2),
        "LDL":   rng.randint(70, 190),
    }


def gen_note(rng: random.Random, patient: Patient, n: int, base_day: date) -> Note:
    note_type = NOTE_TYPES[n % len(NOTE_TYPES)] if n < len(NOTE_TYPES) \
        else rng.choice(["progress", "outpatient"])
    visit = base_day + timedelta(days=n * rng.randint(20, 60))
    icd_code, icd_text = rng.choice(ICD10)
    drug_pick = rng.sample(DRUGS, k=rng.randint(1, 3))
    vitals = _vitals(rng)
    labs = _labs(rng)

    drug_lines = "; ".join(f"{name} {dose}" for name, dose in drug_pick)

    text = (
        f"{note_type.upper()} NOTE\n"
        f"Patient: {patient.name} ({patient.sex}, {patient.age}y) "
        f"MRN {patient.mrn}  ABHA {patient.abha_id}\n"
        f"Contact: {patient.phone}  Address: {patient.address} "
        f"(pin {patient.pincode})\n"
        f"Visit date: {visit.isoformat()}\n"
        f"Diagnosis: {icd_code} -- {icd_text}.\n"
        f"Vitals: BP {vitals['bp_systolic']}/{vitals['bp_diastolic']} mmHg, "
        f"pulse {vitals['pulse']}/min, SpO2 {vitals['spo2']}%, "
        f"temp {vitals['temp_c']} C.\n"
        f"Labs: HbA1c {labs['HbA1c']}%, FBS {labs['FBS']} mg/dL, "
        f"Creatinine {labs['Creatinine']} mg/dL, LDL {labs['LDL']} mg/dL.\n"
        f"Medications: {drug_lines}.\n"
        f"Plan: Continue current regimen. Review in 4 weeks."
    )

    return Note(
        note_id=f"{patient.patient_id}-N{n:02d}",
        patient_id=patient.patient_id,
        note_type=note_type,
        visit_date=visit.isoformat(),
        text=text,
        icd10=icd_code,
        drugs=[d[0] for d in drug_pick],
        vitals=vitals,
        labs=labs,
    )


# ---------------------------------------------------------------------------
# Query generation
# ---------------------------------------------------------------------------

def _latest_note_with(notes: list[Note], pred) -> Note | None:
    for note in sorted(notes, key=lambda n: n.visit_date, reverse=True):
        if pred(note):
            return note
    return None


def gen_query(
    rng: random.Random,
    patient: Patient,
    notes: list[Note],
    category: str,
    idx: int,
) -> Query | None:
    pnotes = [n for n in notes if n.patient_id == patient.patient_id]
    if not pnotes:
        return None

    if category == "lookup":
        lab = rng.choice(list(pnotes[0].labs.keys()))
        target = _latest_note_with(pnotes, lambda n: lab in n.labs)
        if target is None:
            return None
        return Query(
            query_id=f"Q{idx:05d}",
            patient_id=patient.patient_id,
            category=category,
            text=f"What was {patient.name}'s most recent {lab} value?",
            ground_truth_note_ids=[target.note_id],
        )

    if category == "longitudinal":
        # Span the patient's full series
        gt = [n.note_id for n in pnotes]
        return Query(
            query_id=f"Q{idx:05d}",
            patient_id=patient.patient_id,
            category=category,
            text=f"How has {patient.name}'s blood pressure trended over time?",
            ground_truth_note_ids=gt,
        )

    if category == "reasoning":
        drug = rng.choice([d[0] for d in DRUGS])
        target = _latest_note_with(pnotes, lambda n: drug in n.drugs)
        if target is None:
            return None
        return Query(
            query_id=f"Q{idx:05d}",
            patient_id=patient.patient_id,
            category=category,
            text=(
                f"Given {patient.name}'s recent labs and current medication, "
                f"is the {drug} dose still appropriate?"
            ),
            ground_truth_note_ids=[target.note_id],
        )

    raise ValueError(category)


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------

def build_corpus(scale: dict = SCALE) -> tuple[list[Patient], list[Note], list[Query]]:
    rng = random.Random(SEED)
    base_day = date(2024, 1, 1)

    patients: list[Patient] = [gen_patient(rng, i) for i in range(scale["n_patients"])]

    notes: list[Note] = []
    for p in patients:
        lo, hi = scale["notes_per_patient"]
        for n in range(rng.randint(lo, hi)):
            notes.append(gen_note(rng, p, n, base_day))

    queries: list[Query] = []
    cats = list(scale["query_split"].keys())
    weights = list(scale["query_split"].values())
    qi = 0
    while len(queries) < scale["n_queries"]:
        patient = rng.choice(patients)
        category = rng.choices(cats, weights=weights, k=1)[0]
        q = gen_query(rng, patient, notes, category, qi)
        qi += 1
        if q is not None:
            queries.append(q)

    return patients, notes, queries


def _write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    patients, notes, queries = build_corpus()

    _write_jsonl(DATA_DIR / "patients.jsonl", patients)
    _write_jsonl(DATA_DIR / "notes.jsonl", notes)
    _write_jsonl(DATA_DIR / "queries.jsonl", queries)

    roster: list[tuple[str, str]] = []
    for p in patients:
        roster.extend(p.identifiers())
    (DATA_DIR / "roster.json").write_text(json.dumps(roster, indent=2, ensure_ascii=False))

    print(f"[corpus] wrote {len(patients)} patients, "
          f"{len(notes)} notes, {len(queries)} queries -> {DATA_DIR}")


if __name__ == "__main__":
    main()
