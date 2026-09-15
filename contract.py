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
    # Medical second opinion.
    #
    # A user submits a case (age, sex, symptoms, current diagnosis,
    # current treatment). A GenLayer validator jury answers two separate
    # single-word questions with strict equivalence:
    #   1) Plausibility of the current diagnosis:
    #        PLAUSIBLE | QUESTIONABLE | INSUFFICIENT_DATA
    #   2) Urgency of specialist referral:
    #        URGENT | MODERATE | ROUTINE
    # Single tokens are what let independent validator models reach consensus.
    #
    # IMPORTANT: this contract stores case data unencrypted on-chain. The
    # "private" behaviour is only a UI filter (list_cases_by scopes to one
    # wallet address); anyone with a case id can call get_case and read the
    # payload. The frontend must warn users not to submit personal identifiers.
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
        current_diagnosis: str,
        current_treatment: str,
        year: str,
    ) -> str:
        age_l = _norm(age)
        sex_l = _norm(sex)
        symptoms_l = _norm(symptoms)
        diag_l = _norm(current_diagnosis)
        treat_l = _norm(current_treatment)

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
        case_text = (
            "Age: " + age_l + "\n"
            + "Sex: " + sex_l + "\n"
            + "Symptoms: " + symptoms_l + "\n"
            + "Current diagnosis (as reported by the patient): " + diag_l + "\n"
            + "Current treatment (as reported by the patient): " + treat_l
        )

        # ---- Jury question 1: plausibility ---------------------------------
        def get_plausibility() -> str:
            prompt = (
                "You are one member of a medical review panel providing a "
                "non-binding second opinion. You are NOT giving medical "
                "advice to a patient. Given ONLY the case description below, "
                "judge whether the currently proposed diagnosis plausibly "
                "fits the reported symptoms in the given age and sex context.\n\n"
                "Answer with EXACTLY ONE of these three words, uppercase, "
                "no punctuation, no explanation:\n"
                "  PLAUSIBLE          - the diagnosis reasonably fits the symptoms\n"
                "  QUESTIONABLE       - the diagnosis does not fit well or "
                "something is inconsistent\n"
                "  INSUFFICIENT_DATA  - not enough information to judge\n\n"
                "Case:\n" + case_text + "\n\n"
                "Answer with one word only."
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
                "You are one member of a medical review panel providing a "
                "non-binding second opinion. You are NOT giving medical "
                "advice to a patient. Given ONLY the case description below, "
                "judge how urgently a specialist consultation is warranted.\n\n"
                "Answer with EXACTLY ONE of these three words, uppercase, "
                "no punctuation, no explanation:\n"
                "  URGENT   - same-day or 24-48h specialist consultation warranted\n"
                "  MODERATE - specialist consultation within 1-2 weeks warranted\n"
                "  ROUTINE  - no immediate specialist consultation needed\n\n"
                "Case:\n" + case_text + "\n\n"
                "Answer with one word only."
            )
            try:
                raw = gl.nondet.exec_prompt(prompt)
            except Exception:
                return "UNREVIEWED"
            token = _pick(raw, ["URGENT", "MODERATE", "ROUTINE"])
            return token if token else "UNREVIEWED"

        plausibility = gl.eq_principle.strict_eq(get_plausibility)
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
            "current_diagnosis": diag_l,
            "current_treatment": treat_l,
            "plausibility": plausibility,
            "urgency": urgency,
            "version": 1,
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
