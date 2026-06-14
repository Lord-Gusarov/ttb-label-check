# Users & Use Cases

## Why this document exists

This defines **the roles the system serves** and **the flows it must support**, so that
"correct" has a clear, grounded meaning when we validate. Every verification behavior — the
`PASS / NEEDS REVIEW / FAIL` verdicts, the <5 s budget, the choice to *flag rather than fail* on
uncertainty — exists to serve a role and a use case below.

It is written in terms of **roles, not individuals**. (The take-home brief's discovery
interviews describe specific people; their characteristics are folded into the roles here.)

---

## Users (roles)

The system serves **two human roles** plus the **automated reviewer** (not a person, but the
third actor in the flow). No real individuals and nothing sensitive are stored — these are roles.

### Role 1 — Applicant (Submitter)

**Who:** the party that must get a label approved before selling it — a bottler/packer, an
importer, or a relabeling wholesaler (or a third-party filer acting for them).

**Comes to the system to:** create and submit an application — the declared product details plus
the label artwork.

**Needs from the system:**
- Enter the **declared fields** (product type, brand name, class/type, alcohol content, net contents).
- Attach the **label image(s)**.
- **Submit** the application so it enters the review queue.

> In the real world this role uses TTB's COLAs Online; we don't integrate with it. In this
> standalone prototype the **"Submit application"** screen stands in for this role so the demo
> can show the whole flow end to end.

### Role 2 — Compliance Agent / Reviewer (TTB employee)

**Who:** a TTB labeling specialist whose job is to decide whether a submitted label may be
approved. **This is the primary user the tool is built for.**

**Role characteristics that shape the design** (from discovery):
- **Wide range of tech comfort** → the interface must be usable by non-technical staff: clean,
  obvious, no hunting for buttons.
- **High volume, routine-heavy** → most of the work is confirming the label matches the
  declaration; the tool must make that fast.
- **Needs to trust it and stay in control** → it must show *why* it flags something, and it
  **assists** rather than decides.
- **Exactness where it counts** → the government health warning must be checked precisely.

**Comes to the system to:** work the queue of submitted applications and reach a decision on each.

**Needs from the system:**
- See the **queue** of applications awaiting review.
- **Select one** application and review it in depth: the label, the automated per-field checks
  against the declared values and the regulations, and the supporting evidence.
- **Decide:** Approve / Needs Correction / Reject.
- **Select many** — a set or a **range** (e.g. applications N through M) — to process together
  during peak-season dumps, then work the results (Phase 2; see UC4).
- Get a result in **under 5 seconds**, never a crash, with anything uncertain **flagged** for the
  human rather than silently decided.

### Role 3 — The automated reviewer (the system itself)

**Who:** not a person — the local reading + rules engine.

**Does:** reads the label (local OCR / optional local VLM) and applies the deterministic rules,
producing per-field `PASS / NEEDS REVIEW / FAIL` plus evidence. **It never makes the decision** —
it informs the Agent. Listed as an actor because the human-in-the-loop boundary is a design
requirement, not an afterthought.

---

## Use cases (the flows)

Concrete flows each role performs. Phase-1 cases are built; Phase-2 is designed, not yet built.

**UC1 — Submit an application (check-then-confirm)** *(Applicant · built)*
The Applicant enters the declared fields and uploads the label image, then **Checks** it: the
automated reading + rules run as a pre-flight and the results are shown inline — nothing is
persisted yet. The Applicant either corrects a flagged field and re-checks, or **confirms**
("Submit" / "Submit anyway" — a TTB reviewer makes the final decision). → Only on confirmation
does a new application enter the review queue.

**UC2 — Review a single application** *(Agent · built)*
The Agent opens an application from the queue. The system reads the label and shows per-field
results — brand, alcohol content, and net contents **matched against the declared values**; the
government warning checked for **presence, ALL-CAPS, and bold** — each with evidence (declared
vs. read, highlighted on the label). → The Agent can see, at a glance, what matches and what needs
a closer look.

**UC3 — Decide** *(Agent · built)*
From the review, the Agent records **Approve / Needs Correction / Reject**. → The application's
status updates; the queue reflects it.

**UC4 — Batch-process many applications** *(Agent · Phase 2)*
The Agent selects multiple applications — a set, or a **range from N to M** — to verify together
(the peak-season "an importer dumped 300" case). → Each is verified **independently** (one bad
file can't sink the batch); the Agent gets a summary (counts of pass / needs-review / fail) and
works the results item by item. *Open design point: selection by checkbox vs. by id range — to be
settled when built.*

**UC5 — Handle an imperfect image** *(Agent + system · built)*
A label is shot at an angle, with glare, or at low resolution. → The affected checks resolve to
**NEEDS REVIEW** ("request a better image"), never a crash and never a confident-but-wrong verdict.

**Out of scope** (named so validation isn't held to them):
COLA integration; production PII/retention; *judgment* checks (misleading/health claims,
prohibited graphics, geographic substantiation); full beer/wine depth (spirits first); perfect
OCR of curved-rim "seal" text.

---

## What this means for validation

The roles and flows set the bar. We validate **these**, not abstract accuracy:

| Use case | We validate that… | How we check it |
|---|---|---|
| **UC1** submit | an application (fields + image) enters the queue cleanly; bad input is rejected with a clear message | API tests (create, validation, unsupported commodity) |
| **UC2** review | the right fields are checked against the *declared* values + regs, with explainable evidence | golden tests per field; end-to-end on sample labels; the UI shows declared-vs-read |
| **UC2** routine speed | clean compliant labels read **PASS** and **fast** | corpus PASS rate + per-label latency in `docs/evaluation.md` (<5 s) |
| **UC2** warning | exact wording / ALL-CAPS / bold are caught (incl. title-case reject, non-bold) | warning + bold-detector golden tests |
| **UC2** judgment | uncertainty → **NEEDS REVIEW**, not false PASS/FAIL; `STONE'S THROW` ≈ `Stone's Throw` passes | comparator tests; verdict distribution on the hard corpus |
| **UC3** decide | a decision updates and persists the application's status | API decision tests; end-to-end approve flow |
| **UC4** batch *(Phase 2)* | each item is verified independently; one failure can't sink the batch | per-item isolation tests (when built) |
| **UC5** images | degraded inputs **flag** for review and never crash | hard-corpus run; error-handling tests; Playwright asserts zero console errors |
| **All** | <5 s per label, **zero external calls**, usable by non-technical 50+ staff | latency report; local-first ADR 0001; accessible routed UI |

**The throughline:** the tool is an **assistant for the compliance agent — it reads and flags;
the agent decides.** Validation succeeds when it makes the *routine* fast, the *fiddly* reliable,
and the *uncertain* honestly flagged — within the <5 s, local-first, dead-simple constraints.
