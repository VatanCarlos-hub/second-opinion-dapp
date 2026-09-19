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

        # ---- Jury: tolerant consensus via prompt_non_comparative -----------
        # strict_eq forces every validator LLM to produce the IDENTICAL word,
        # which repeatedly went UNDETERMINED on subjective medical triage.
        # prompt_non_comparative instead lets the leader produce the word and
        # each validator judge whether it is a DEFENSIBLE classification for the
        # case, so a validator accepts a reasonable answer even if it would have
        # picked an adjacent label -> consensus is reached on subjective calls.
        # fn returns the input the validator also sees; task drives the leader;
        # criteria is how the validator judges the leader's output.
        def case_input() -> str:
            return case_text

        # ---- Jury question 1: plausibility ---------------------------------
        # Deterministic guard: no diagnosis -> no jury (unanswerable question).
        if diag_l:
            try:
                raw_p = gl.eq_principle.prompt_non_comparative(
                    case_input,
                    task=(
                        "You are a medical review panel giving a non-binding "
                        "second opinion. Decide whether the CURRENT DIAGNOSIS "
                        "stated in the case fits the reported symptoms and "
                        "history. Respond with EXACTLY ONE word and nothing "
                        "else: PLAUSIBLE (the diagnosis reasonably fits), "
                        "QUESTIONABLE (it does not fit well or is inconsistent), "
                        "or INSUFFICIENT_DATA (not enough information to judge)."
                    ),
                    criteria=(
                        "The answer must be exactly one of: PLAUSIBLE, "
                        "QUESTIONABLE, INSUFFICIENT_DATA. Accept the answer if it "
                        "is a medically DEFENSIBLE classification for the "
                        "described case, even if another of the three labels "
                        "could also be reasonably argued. Reject only if the "
                        "classification is clearly indefensible given the case."
                    ),
                )
            except Exception:
                raw_p = ""
            plausibility = _pick(
                raw_p, ["PLAUSIBLE", "QUESTIONABLE", "INSUFFICIENT_DATA"]
            ) or "UNREVIEWED"
        else:
            plausibility = "NO_DIAGNOSIS"

        # ---- Jury question 2: urgency --------------------------------------
        try:
            raw_u = gl.eq_principle.prompt_non_comparative(
                case_input,
                task=(
                    "You are a medical review panel giving a non-binding second "
                    "opinion. Decide how urgently an in-person specialist "
                    "consultation is warranted. Respond with EXACTLY ONE word "
                    "and nothing else: URGENT (red-flag features present, e.g. "
                    "sudden severe onset, chest pain, difficulty breathing, "
                    "sudden neurological change, signs of stroke or heart "
                    "attack, uncontrolled bleeding, high fever with stiff neck), "
                    "MODERATE (persistent, worsening, or clearly affecting daily "
                    "life), or ROUTINE (mild, stable, or long-standing with no "
                    "concerning features)."
                ),
                criteria=(
                    "The answer must be exactly one of: URGENT, MODERATE, "
                    "ROUTINE. Accept the answer if it is a medically DEFENSIBLE "
                    "urgency level for the described case, even if an adjacent "
                    "level could also be argued. Reject only if the level is "
                    "clearly wrong, e.g. ROUTINE despite clear red flags, or "
                    "URGENT for plainly trivial and stable symptoms."
                ),
            )
        except Exception:
            raw_u = ""
        urgency = _pick(raw_u, ["URGENT", "MODERATE", "ROUTINE"]) or "UNREVIEWED"

        # ---- Jury question 3: structured assessment ------------------------
        # Free-form text is exactly what prompt_non_comparative is best at: the
        # leader writes the assessment, validators accept it if it is medically
        # reasonable and appropriately cautious (no definitive diagnosis, no
        # specific self-prescription).
        try:
            assessment = gl.eq_principle.prompt_non_comparative(
                case_input,
                task=(
                    "You are a medical review panel providing a non-binding, "
                    "educational second opinion for a layperson. You are NOT the "
                    "treating physician and must NOT give a definitive diagnosis "
                    "or prescribe. Based only on the case, write a concise, "
                    "clearly structured assessment IN THE SAME LANGUAGE as the "
                    "symptoms text, with these four short sections:\n"
                    "1) Possible explanations: 2-4 conditions that could fit, "
                    "each with a one-sentence reason. Present them as "
                    "possibilities to investigate, NOT as a confirmed diagnosis.\n"
                    "2) What this could mean: 1-2 plain-language sentences.\n"
                    "3) What to do next: which type of doctor or specialist to "
                    "see, what to monitor, and any warning signs that mean urgent "
                    "care is needed.\n"
                    "4) Treatment to discuss with a doctor: general approaches or "
                    "medication CLASSES a physician might consider. Do NOT give "
                    "specific drug names with doses and do NOT tell the patient to "
                    "self-medicate; state clearly that only a doctor can "
                    "prescribe. Keep the whole answer under about 180 words."
                ),
                criteria=(
                    "Accept the assessment if it is medically reasonable, grounded "
                    "in the described case, appropriately cautious (frames "
                    "possibilities as possibilities, does NOT assert a single "
                    "definitive diagnosis, does NOT give specific prescription "
                    "doses or instruct self-medication), and includes sensible "
                    "next steps. Reject it only if it is dangerous, fabricated, "
                    "asserts a definitive diagnosis, or instructs specific "
                    "self-medication with doses."
                ),
            )
            assessment = str(assessment).strip()
        except Exception:
            assessment = ""

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
            "assessment": assessment,
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
