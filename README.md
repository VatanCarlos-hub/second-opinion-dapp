# Second Opinion

A non-binding **medical second opinion** as a GenLayer Intelligent Contract. A person
submits a structured, anonymous case (age, sex, symptoms, history, current diagnosis and
treatment, and an optional pasted report). A jury of independent LLM validators reaches
consensus on two categorical findings and one written assessment, and the result is stored
on-chain.

> **Not medical advice.** Second Opinion is an educational tool. It does not diagnose, does
> not prescribe, and does not replace a physician. For serious or worsening symptoms, see a
> doctor.

- **Repository:** https://github.com/VatanCarlos-hub/second-opinion-dapp
- **Live demo:** https://second-opinion-v2.vercel.app/second-opinion.html
- **Network:** GenLayer Studio NEXT — `studioDevnet`, chain id `61997`, RPC `https://studio-dev.genlayer.com/api`
- **Contract address:** `0x62C4C91290c5C28c11d603254E9f09fa9A169Ac1`
- **Explorer:** https://explorer-studio-dev.genlayer.com/address/0x62C4C91290c5C28c11d603254E9f09fa9A169Ac1
- **Category:** Project

---

## The problem

Getting a second medical opinion is slow, expensive, and hard to access. At the same time,
an AI opinion delivered by a single hidden model is easy to distrust: there is no way to see
whether the judgment was a fluke of one model or a view several independent reviewers would
share.

GenLayer's value here is exactly that: a **panel of different LLMs** must independently reach
consensus before a finding is recorded, and the finding is written to a public ledger. The
output is not "what one model said" but "what an independent panel agreed was defensible."

## What it does

1. A user connects an EVM wallet and fills in a structured case:
   - Basics: age, sex
   - Complaints: main symptoms, duration, self-assessed severity
   - History: pre-existing conditions, current medications, allergies, relevant family history
   - Current assessment: existing diagnosis (if any), current treatment (if any)
   - Optional document: a doctor's report pasted as text (or loaded from a `.txt` file)
2. The case is sent to the contract's `submit_case` write method.
3. A validator jury produces three outputs by consensus:
   - **Plausibility of the current diagnosis** — `PLAUSIBLE` / `QUESTIONABLE` / `INSUFFICIENT_DATA`
     (or `NO_DIAGNOSIS`, set deterministically when no diagnosis was entered)
   - **Urgency of a specialist referral** — `URGENT` / `MODERATE` / `ROUTINE`
   - **A short structured assessment** — possible explanations, plain-language meaning, next
     steps, and treatment topics to discuss with a doctor
4. The finding is stored on-chain and shown back in the interface.

---

## Why this is hard on GenLayer, and how it is solved

The core engineering problem with an LLM jury is consensus. When validators run on
**different underlying models** (e.g. GPT, Claude, Gemini, DeepSeek) and are asked to produce
matching free-form text, they almost never agree byte-for-byte, and the transaction ends
`UNDETERMINED` — nothing is written. Subjective medical judgment makes this worse: two
qualified reviewers can reasonably disagree on whether a case is `MODERATE` or `ROUTINE`.

Second Opinion handles this by **matching the consensus method to the shape of each output**:

- **The two categorical findings** are reduced to a single word each and validated with a
  *tolerant* equivalence principle (`gl.eq_principle.prompt_non_comparative`). Validators do
  not have to produce the identical word; they accept the leader's label if it is a
  **medically defensible** classification for the case, and reject only clearly wrong calls.
  This is what lets a subjective 3-way judgment reach agreement instead of splitting.
- **The written assessment** is free-form text — exactly the case non-comparative validation
  is designed for. The leader writes the assessment; validators accept it if it is reasonable,
  grounded in the case, and appropriately cautious (frames possibilities as possibilities, no
  definitive diagnosis, no specific self-prescription).
- **Everything deterministic runs outside the non-deterministic block.** The case id, the
  running counters, and the per-wallet index are computed in plain Python so they never cause
  disagreement. Asking the jury a question that cannot be answered is avoided entirely: when
  no diagnosis is entered, plausibility is set to `NO_DIAGNOSIS` deterministically, with no
  jury call.
- **The year is passed in by the client**, never read from a clock, because a contract has no
  consensus-safe wall clock.

This mirrors the lesson from a sister project (Precedent): keep the jury's actual decision as
small and well-scoped as possible, and do all arithmetic deterministically around it.

---

## Contract reference

Source: `contract.py` — GenLayer Intelligent Contract, header `# v0.3.0`.

### Storage

| Field          | Type                          | Purpose                                             |
| -------------- | ----------------------------- | --------------------------------------------------- |
| `cases`        | `gl.storage.TreeMap[str,str]` | case id → JSON record of the full case + findings   |
| `sender_index` | `gl.storage.TreeMap[str,str]` | wallet address → JSON array of that wallet's case ids |
| `index`        | `str`                         | JSON `{ "count": n, "ids": [...] }` global docket    |

### Methods

| Method                                   | Kind  | Returns | Purpose                                            |
| ---------------------------------------- | ----- | ------- | -------------------------------------------------- |
| `submit_case(age, sex, symptoms, duration, severity, conditions, medications, allergies, family_history, current_diagnosis, current_treatment, document, year)` | write | `str` (case id) | Runs the jury, stores the case, returns its id |
| `get_case(case_id)`                      | view  | `str` (JSON)   | Full record for one case, or a `not_found` object |
| `list_cases_by(owner)`                   | view  | `str` (JSON)   | JSON array of case ids submitted by one wallet     |
| `case_count()`                           | view  | `int`          | Number of cases stored                             |

### Case id format

`SO-<year>-<NNNN>`, e.g. `SO-2026-0007`. The number is a global running counter; the year is
the value passed by the caller (falls back to `0000` if not four digits).

### Deployments

| Version | Contract address | Notes |
| ------- | ---------------- | ----- |
| Current | `0x62C4C91290c5C28c11d603254E9f09fa9A169Ac1` | Plausibility + urgency + written assessment |

> Earlier iterations exist in the commit history; the address above is the current one the
> frontend points to.

---

## Frontend

Single self-contained file: `second-opinion.html` (no build step).

- **SDK:** `genlayer-js@2.0.0-rc.1`, loaded as an ES module from jsDelivr
  (`https://cdn.jsdelivr.net/npm/genlayer-js@2.0.0-rc.1/+esm` and `/chains/+esm`). The `rc`
  line is required because it exports the `studioDevnet` chain (id 61997); the stable line
  does not.
- **Wallet:** EIP-6963 discovery with a `window.ethereum` fallback and a custom picker — no
  WalletConnect. The app switches the wallet to `studioDevnet` (`0xf22d`) itself
  (`wallet_switchEthereumChain` / `wallet_addEthereumChain`).
- **Writes:** every write estimates fees first (`estimateTransactionFees`) and passes the
  result to `writeContract`, as required by the current fee stack.
- **Confirmation:** after a write, the app waits for the transaction to be *decided*, then
  reads `case_count()` before/after to confirm state was actually written (an `UNDETERMINED`
  round decides but writes nothing), and reads the new case back to display it.
- **"My findings":** cases are matched to the connected wallet by comparing the stored
  `filed_by` field case-insensitively, so address-casing differences never hide a stored case.
- **Languages:** German, English, Turkish, Spanish, Russian (switchable) in the header.

---

## Privacy and safety

This is important and stated plainly:

- **Everything submitted is stored unencrypted and permanently on a public blockchain**, and
  is readable by anyone. The transaction calldata is public even beyond stored state.
  **Deletion is not possible** — an erasure request (e.g. GDPR Art. 17) cannot be fulfilled on
  an immutable chain.
- Health data is a **special category of personal data** (GDPR Art. 9). **Use synthetic
  example data only** — no real patient records, names, dates of birth, or addresses. The
  interface shows this warning prominently, and the "private" view is only a per-wallet filter,
  not a confidentiality guarantee.
- **By design, the tool does not give a definitive diagnosis and does not tell users which
  specific medication to take.** It offers possibilities to investigate and treatment topics to
  discuss with a physician. Diagnosis and prescription are a doctor's responsibility (in
  Germany: Arztvorbehalt / prescription-only medicines under the AMG).

---

## Run locally

The frontend needs to be served over HTTP (wallets do not inject into `file://` pages).

```bash
# from the repo root
python3 -m http.server 8000
# then open http://localhost:8000/second-opinion.html
```

Connect a wallet funded with test GEN on `studioDevnet`, approve the network switch, and
submit a case.

## Deploy the contract

1. Open `contract.py` in GenLayer Studio NEXT.
2. Load, then Deploy.
3. Put the new address into the frontend (`CONTRACT_FALLBACK` in `second-opinion.html`) or open
   the app with `?contract=0x...` to override it at runtime.

---

## Test evidence

> To be completed after a confirmed finalized run on the current contract. Do not leave
> placeholders in the submitted version.

- Deploy transaction: `TODO: tx hash / explorer link`
- Example `submit_case` transaction (finalized): `TODO: tx hash / explorer link`
- Expected success signals: `statusName: FINALIZED`, `resultName: MAJORITY_AGREE`,
  `txExecutionResultName: FINISHED_WITH_RETURN`
- Example stored case id: `SO-2026-0001` (readable via `get_case("SO-2026-0001")`)
- Screenshots / short video: `TODO`

## Limitations and roadmap

Stated honestly:

- **Consensus is probabilistic on genuinely borderline cases.** Even with tolerant validation,
  a case that sits exactly between two categories can occasionally end `UNDETERMINED` and store
  nothing; retrying or using a clearer case resolves it. This is a property of subjective
  medical judgment, not a contract fault.
- **Three consensus gates.** The current version runs three jury steps (plausibility, urgency,
  assessment); each is an independent consensus round, so more steps mean a slightly higher
  chance one round is undetermined. A planned option is to fold the categorical findings into
  the single assessment step to reduce this to one gate.
- **Not a diagnostic device.** This is deliberate; see Privacy and safety.
- **On-chain storage of health text** is inappropriate for real data; a production design would
  keep only a hash on-chain and the content off-chain/encrypted.

## Repository structure

```
contract.py            # GenLayer Intelligent Contract (the jury + storage)
second-opinion.html    # single-file frontend (wallet, forms, reads/writes, i18n)
vercel.json            # Vercel deployment config
```

## License

MIT — see the `LICENSE` file.
