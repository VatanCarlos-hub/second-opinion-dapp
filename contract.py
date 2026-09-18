# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }

import genlayer as gl
from genlayer.types import *

import json
import typing


# ---- Deterministic helpers -------------------------------------------------
# Run identically on every validator, so they never cause disagreement.

def _norm(text: str) -> str:
    try:
        return str(text).strip()
    except Exception:
        return ""


def _pick(text: str, options: list) -> str:
    """Reduce a model answer to one allowed option. Returns '' if none match."""
    try:
        t = str(text).strip().upper()
    except Exception:
        return ""
    for opt in options:
        if opt.upper() == t:
            return opt
    for opt in options:
        if opt.upper() in t:
            return opt
    return ""


class SecondOpinion(gl.contract.Contract):
    # Medical second opinion with a comprehensive intake and an optional
    # document field (e.g. a doctor's report pasted as text).
    #
    # A GenLayer validator jury answers TWO separate single-word questions
    # with strict equivalence:
    #   1) Plausibility of the current diagnosis:
    #        PLAUSIBLE | QUESTIONABLE | INSUFFICIENT_DATA
    #   2) Urgency of specialist referral:
    #        URGENT | MODERATE | ROUTINE
    # Single tokens are what let independent validator models reach consensus.
    #
    # PRIVACY: this contract stores case data unencrypted on-chain, AND every
    # argument passed to submit_case is permanently public in the transaction
    # calldata regardless of what is stored. The "private" behaviour is only a
    # UI filter (list_cases_by scopes to one wallet). Do NOT submit real
    # patient records; use synthetic data only.
    #
    # Storage:
    #   cases        : case_id (str) -> JSON string of the full case record
    #   sender_index : wallet address (str) -> JSON array of case_ids
    #   index        : JSON string {"count": n, "ids": [...]}
    cases: gl.storage.TreeMap[str, str]
    sender_index: gl.storage.TreeMap[str, str]
    index: str

    def __init__(self):
        self.index = ""

    # ---- Internal deterministic bookkeeping --------------------------------

    def _load_index(self) -> dict:
        try:
            if self.index:
                obj = json.loads(self.index)
                if isinstance(obj, dict):
                    if "ids" not in obj:
                        obj["ids"] = []
                    if "count" not in obj:
                        obj["count"] = 0
                    return obj
        except Exception:
            pass
        return {"count": 0, "ids": []}

    def _save_index(self, idx: dict) -> None:
        try:
            self.index = json.dumps(idx)
        except Exception:
            pass

    def _append_sender_case(self, sender_str: str, case_id: str) -> None:
        try:
            if sender_str in self.sender_index:
                existing = self.sender_index[sender_str]
                arr = json.loads(existing) if existing else []
                if not isinstance(arr, list):
                    arr = []
            else:
                arr = []
            arr.append(case_id)
            self.sender_index[sender_str] = json.dumps(arr)
        except Exception:
            self.sender_index[sender_str] = json.dumps([case_id])

    # ---- Read methods ------------------------------------------------------

    @gl.public.view
    def case_count(self) -> int:
        idx = self._load_index()
        try:
            return int(idx.get("count", 0))
        except Exception:
            return 0

    @gl.public.view
    def get_case(self, case_id: str) -> str:
        if case_id in self.cases:
            return self.cases[case_id]
        return json.dumps({"error": "not_found", "case_id": case_id})

    @gl.public.view
    def list_cases_by(self, owner: str) -> str:
        """Return a JSON array of case_ids submitted by the given wallet."""
        key = _norm(owner)
        if key in self.sender_index:
            return self.sender_index[key]
        return json.dumps([])

    # ---- Write method: submit a case ---------------------------------------

    @gl.public.write
    def submit_case(
        self,
        age: str,
        sex: str,
        symptoms: str,
        duration: str,
        severity: str,
        conditions: str,
        medications: str,
        allergies: str,
        family_history: str,
        current_diagnosis: str,
        current_treatment: str,
        document: str,
        year: str,
    ) -> str:
        age_l = _norm(age)
        sex_l = _norm(sex)
        symptoms_l = _norm(symptoms)
        duration_l = _norm(duration)
        severity_l = _norm(severity)
        conditions_l = _norm(conditions)
        medications_l = _norm(medications)
        allergies_l = _norm(allergies)
        family_l = _norm(family_history)
        diag_l = _norm(current_diagnosis)
        treat_l = _norm(current_treatment)
        document_l = _norm(document)

        # Year is passed in, never read from a clock: a contract has no
        # consensus-safe wall clock, so validators must all receive the same
        # value from the caller.
        year_l = _norm(year)
        if len(year_l) != 4 or not year_l.isdigit():
            year_l = "0000"

        # Record who actually submitted this filing (on-chain identity).
        try:
            filed_by = str(gl.message.sender_address)
        except Exception:
            filed_by = ""

        # Deterministic input digest that both jury prompts share.
        doc_block = ""
        if document_l:
            doc_block = "\nAttached document (e.g. doctor's report):\n" + document_l

        case_text = (
            "Age: " + age_l + "\n"
            + "Sex: " + sex_l + "\n"
            + "Main symptoms: " + symptoms_l + "\n"
            + "Duration of symptoms: " + duration_l + "\n"
            + "Severity (patient-reported): " + severity_l + "\n"
            + "Pre-existing conditions: " + conditions_l + "\n"
            + "Current medications: " + medications_l + "\n"
            + "Allergies: " + allergies_l + "\n"
            + "Relevant family history: " + family_l + "\n"
            + "Current diagnosis (as reported by the patient): " + diag_l + "\n"
            + "Current treatment (as reported by the patient): " + treat_l
            + doc_block
        )

        # ---- Jury question 1: plausibility ---------------------------------
        # Prescriptive, ordered decision procedure: different validator LLMs
        # converge on the SAME single word far more reliably than with an
        # open-ended judgment, which keeps strict_eq consensus stable.
        def get_plausibility() -> str:
            prompt = (
                "You are one member of a medical review panel giving a "
                "non-binding second opinion. Decide whether the CURRENT "
                "DIAGNOSIS in the case fits the reported symptoms and history.\n\n"
                "Apply these rules IN ORDER and stop at the FIRST that matches:\n"
                "1. If the reported symptoms are too few or too vague to judge "
                "the diagnosis at all -> INSUFFICIENT_DATA\n"
                "2. If at least one reported symptom is clearly NOT explained by "
                "the current diagnosis, or a clearly more likely diagnosis fits "
                "the symptoms better -> QUESTIONABLE\n"
                "3. Otherwise, if the current diagnosis is a standard and "
                "reasonable explanation for the reported symptoms -> PLAUSIBLE\n\n"
                "Answer with EXACTLY ONE word, uppercase, no punctuation, no "
                "explanation: PLAUSIBLE or QUESTIONABLE or INSUFFICIENT_DATA.\n\n"
                "Case:\n" + case_text + "\n\n"
                "One word only."
            )
            try:
                raw = gl.nondet.exec_prompt(prompt)
            except Exception:
                return "UNREVIEWED"
            token = _pick(raw, ["PLAUSIBLE", "QUESTIONABLE", "INSUFFICIENT_DATA"])
            return token if token else "UNREVIEWED"

        # ---- Jury question 2: urgency --------------------------------------
        def get_urgency() -> str:
            prompt = (
                "You are one member of a medical review panel giving a "
                "non-binding second opinion. Decide how urgently an in-person "
                "specialist consultation is warranted.\n\n"
                "Apply these rules IN ORDER and stop at the FIRST that matches:\n"
                "1. If the case contains ANY red-flag feature -> URGENT. "
                "Red flags include: sudden severe onset of a symptom; chest pain "
                "or pressure; difficulty breathing; sudden neurological change "
                "(weakness, vision loss, confusion, slurred speech); signs of "
                "stroke or heart attack; uncontrolled bleeding; high fever with "
                "a stiff neck.\n"
                "2. Else, if symptoms are persistent, worsening, or clearly "
                "affecting daily life -> MODERATE\n"
                "3. Otherwise, if symptoms are mild, stable, or long-standing "
                "with no concerning features -> ROUTINE\n\n"
                "Answer with EXACTLY ONE word, uppercase, no punctuation, no "
                "explanation: URGENT or MODERATE or ROUTINE.\n\n"
                "Case:\n" + case_text + "\n\n"
                "One word only."
            )
            try:
                raw = gl.nondet.exec_prompt(prompt)
            except Exception:
                return "UNREVIEWED"
            token = _pick(raw, ["URGENT", "MODERATE", "ROUTINE"])
            return token if token else "UNREVIEWED"

        # Deterministic guard: asking "is the diagnosis plausible" makes no
        # sense when no diagnosis was provided. Set it deterministically so the
        # jury is never split over an unanswerable question.
        if diag_l:
            plausibility = gl.eq_principle.strict_eq(get_plausibility)
        else:
            plausibility = "NO_DIAGNOSIS"

        urgency = gl.eq_principle.strict_eq(get_urgency)

        # ---- Deterministic case_id + storage -------------------------------
        idx = self._load_index()
        new_num = int(idx.get("count", 0)) + 1
        case_id = "SO-" + year_l + "-" + str(new_num).rjust(4, "0")

        payload = {
            "case_id": case_id,
            "filed_by": filed_by,
            "year": year_l,
            "age": age_l,
            "sex": sex_l,
            "symptoms": symptoms_l,
            "duration": duration_l,
            "severity": severity_l,
            "conditions": conditions_l,
            "medications": medications_l,
            "allergies": allergies_l,
            "family_history": family_l,
            "current_diagnosis": diag_l,
            "current_treatment": treat_l,
            "document": document_l,
            "plausibility": plausibility,
            "urgency": urgency,
            "version": 2,
        }
        self.cases[case_id] = json.dumps(payload)

        # Update global docket index.
        idx["count"] = new_num
        ids = idx.get("ids", [])
        if not isinstance(ids, list):
            ids = []
        ids.append(case_id)
        idx["ids"] = ids
        self._save_index(idx)

        # Update per-wallet index (string key, matches Precedent pattern).
        if filed_by:
            self._append_sender_case(filed_by, case_id)

        return case_id
