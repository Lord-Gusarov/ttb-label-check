# Design decisions, tools & assumptions

Brief documentation of the approach, the tools chosen and why, the assumptions made, and the
trade-offs and known limitations — as the take-home asks. This is a **prototype**: a standalone
proof-of-concept, deliberately bounded, meant to demonstrate the *engineering judgment* behind a
production tool rather than to be one.

## Approach: two approaches in one, cheapest-first

The core idea is a **tiered cascade** that spends the least it can and escalates only when it
must:

1. **Local, deterministic tier (always on).** Fast OCR + a deterministic rules engine. This is
   the workhorse: it clears the clean/common labels in ~sub-2 s **on-box** (no outbound call),
   with exact, reproducible, auditable verdicts. Most of an agent's day is "does the number on
   the form match the number on the label" — that's deterministic matching, and it belongs here.
2. **Semantic-validation LLM tier (on by default).** An LLM re-read, invoked **only** when the
   local tier leaves a field unverified. It earns its cost/latency on the hard minority
   (curved/angled/low-contrast labels), is **fail-safe** (unavailable ⇒ degrade to the local
   verdict + human review), and is **decoupled** so it can run in-boundary in production (see
   *Network security & deployment strategy* below).
3. **Human (always).** Whatever neither tier can confidently clear is `NEEDS REVIEW`. The tool
   **advises; it never auto-rejects.**

Three principles fall out of this and run through the whole codebase:

- **The model reads; the deterministic engine decides.** A model may *transcribe* text, but the
  legal verdict is always rendered by deterministic rules — so compliance is auditable and no
  model "decides" legality. (The Tier-2 model is even declared-blind: it sees only the image,
  never the declared values, so it can't "helpfully" output a match.)
- **Flag, don't fail.** Uncertainty resolves to `NEEDS REVIEW`, never an automated rejection.
  This is why there is no auto-`FAIL` verdict — false-fails erode the trust the stakeholders
  said is essential ("don't make my life harder").
- **Shift verification left to the submission moment.** The same checks run at *submit* time as a
  non-persisting self-check (`/preview`): the applicant sees the full result and chooses "Submit"
  or "Submit anyway" before anything reaches the queue. This moves routine triage — the bulk of
  the agents' day ("drowning in routine stuff") — to the cheapest place to fix it (the applicant,
  pre-submission), so the agent queue carries fewer junk submissions and each one has already
  been seen by the person who can correct it. The tool advises at *both* ends; the human decides.

This directly serves the stakeholder constraints: **< 5 s** (Tier 1 is the fast path),
**network constraints** (handled by a decoupled, swappable LLM layer — see below — rather than
by disabling capability), **trust / human-in-the-loop** (advisory verdicts with visible
evidence), and **non-technical users** (a clean submit → review → decide flow).

## Network security & deployment strategy

Stakeholder discovery flagged that the internal network restricts outbound traffic to external
cloud APIs — a constraint that previously broke a third-party vendor integration. We address it
**by architecture, not by disabling capability**, while still meeting the sub-5-second budget:

- **Local edge processing (OCR).** Pixel processing, text extraction, and bounding-box
  coordination run entirely locally (RapidOCR) — the common case is cleared on-box, so most
  labels never require an outbound call and high-bandwidth image traffic is avoided.
- **Pluggable semantic-validation layer (LLM).** The harder minority escalate to an LLM that
  verifies the extracted content. This prototype uses the OpenAI API over HTTPS for ease of
  demonstration, but the client is **fully decoupled** — for an agency rollout it swaps, with no
  change to the verdict logic, for **Azure OpenAI** inside the agency's existing **FedRAMP**
  boundary, or an **internal inference enclave** (e.g. vLLM on government servers) requiring
  **zero outbound internet**.

The point is flexibility: the same design runs entirely inside the agency boundary in
production, while the prototype demonstrates end-to-end behavior over a standard HTTPS endpoint.

## How choices were made: measure, don't assume

A deliberate stance for this project was to treat recommendations and intuitions — including our
own and tooling's — as **hypotheses to verify against data**, not as truth. Several were
overturned, and that's the point:

- **Reader choice was a bake-off, not a reputation contest.** We compared multiple OCR engines
  (RapidOCR, EasyOCR, PaddleOCR, Tesseract) **and** a local vision-LLM (Florence-2) on a corpus
  with realistic intra-label variation, scoring field accuracy *and* latency. See
  [`evaluation.md`](evaluation.md). Result: RapidOCR wins the hot path (87% @ ~0.4 s);
  Tesseract reads rotated text confidently-but-wrong, so it can't be trusted as primary.
- **A tempting refactor was rejected on the evidence.** Folding the government-warning checks
  into the declarative `FieldPolicy` table looked cleaner on paper, but the warning checks need
  image pixels (bold detection) and iterative re-reads — unifying them would have *worsened* the
  design. We kept them separate, on purpose.
- **The local VLM was the accuracy ceiling — and still cut.** Florence-2 scored highest (96%
  field accuracy) but ran ~5.7 s/label on CPU, over the 5 s budget, and never activated as a
  fallback in practice. We removed it rather than ship dormant, dependency-heavy code; the
  benchmark is retained for the record (see [`docs/evaluation.md`](evaluation.md)).
  A GPU deployment would revisit it.
- **Ground truth itself was verified, not trusted.** Our eval golden set was first transcribed
  by reading label images; cross-checking surfaced real transcription errors, so the golden set
  was **human-verified** before being used to grade the model. (A model's reading is not
  authoritative ground truth for grading another model.)

## Where the deterministic layer hits its limit (and why that's correct)

We pushed the deterministic government-warning check until we found its edge, and named it
honestly: **the deterministic check verifies all the words, in order, plus the "(1)/(2)"
numbering and the ALL-CAPS / bold formatting — but it does not verify cosmetic punctuation
(commas, periods).**

This is not an oversight; it is a property of OCR. A period is a few pixels; OCR drops
punctuation it *did* print all the time. So OCR **cannot distinguish "the label is missing a
period" from "OCR didn't see the period."** Demanding exact punctuation deterministically
wouldn't catch defective labels — it would false-fail nearly every valid one. Character-level
exactness is therefore inherently a **precise-reader (model-tier) job**, and our eval confirms
the model does it faithfully (it transcribes a warning with a dropped legal word *without*
re-inserting it). So the honest division of labor is: **words + numbering + caps/bold locally;
character-exact wording via the model tier when enabled.** This is the tiered design working as
intended, not a gap in it.

The same logic applies to **responsible party**: real labels phrase it in unbounded ways
("Distilled & Aged by…", a circular brewer's seal with no verb, producer-vs-importer on
imports). Chasing every variant in a regex is the wrong fight — the deterministic check does a
loose presence check, and what it can't clear escalates / goes to a human.

## Tools used (and why)

| Area | Choice | Why |
|---|---|---|
| Backend | Python 3.12 + FastAPI | fast to build, typed, great multipart/file support |
| OCR (hot path) | RapidOCR (ONNX) | runs on-box (bundled models, no per-image upload), angle-robust, ~0.4 s |
| Image ops / bold | OpenCV | local stroke-width bold detection, decode guards |
| Rules | hand-rolled deterministic engine | auditable legal verdicts; no model decides legality |
| Model tier | LLM (OpenAI now; pluggable to Azure/vLLM) | precise reads for the hard minority; fail-safe, declared-blind |
| Store | SQLite (+ in-memory double) | trivial, local; nothing sensitive retained |
| Frontend | Vite + React + Tailwind | quick, modern, WCAG-AA; fonts vendored (no CDN) |
| Tooling | uv, pytest, mypy, Playwright | reproducible deps, type gate, real e2e |

## Assumptions

- **One combined image per application** (front/back/side stacked into a single image) — matches
  the single-image submit flow; multi-surface handling is out of scope.
- **Declared fields come from a form**, standing in for a COLA filing (no COLA integration —
  per IT, that's a separate authorization beast).
- **Three commodities**: distilled spirits (seeded deepest — the brief's sample), wine, and malt
  beverage (wired structurally).
- **Hybrid: local OCR + an on-by-default semantic-validation LLM tier**, decoupled so it can run
  in-boundary (Azure OpenAI / internal vLLM) in production (see *Network security & deployment
  strategy*). The prototype calls OpenAI over HTTPS for demonstration.
- **Prototype data posture**: no auth, nothing sensitive stored (per IT: "don't do anything
  crazy… we're not storing anything sensitive for this exercise").
- **The warning text is the fixed federal statement**; "exact" is checked at the word + numbering
  + caps/bold level locally (see the limit above).

## Batch upload: design choices and scope

The batch feature lets an applicant submit a JSON manifest (an array of application payloads,
each naming its image file) alongside the matching images. Valid rows are created and verified
in the background; invalid rows are skipped with a per-row reason and never abort the whole
batch.

**Why JSON for the manifest, not CSV?**
Declared fields like `responsible_party` contain commas and would need quoting rules; commodity
labels and class/type names are arbitrary text strings that would need escaping. JSON is
unambiguous for complex field values and requires no quoting convention. A CSV importer could
be added later, but requires a quoting/encoding spec and a more involved validation path.
Deferred.

**Why a plain multi-file upload, not a zip?**
Zip adds server-side extraction, traversal-path validation, and a second content-type path.
A browser's native `<input type="file" multiple>` is sufficient for the 200–300 file scenario;
the server receives named file entries directly. Zip would be worth revisiting for very large
batches where a single upload stream is preferable.

**Why an in-process ThreadPoolExecutor, not a durable queue?**
For a single-container prototype serving the stakeholder's 200–300 item batches, a small
in-process pool (two threads by default; tunable via `$BATCH_WORKERS`) is the simplest thing
that works. It has no external dependencies and keeps the deployment to one container. The
trade-off: in-flight jobs do not survive a process restart (the startup re-enqueue recovers
`pending`/`verifying` items from the store, but any task the executor was actively running at
shutdown time must re-run). A production deployment would replace this with a durable task
queue (e.g. Celery + Redis, or a managed service) and external workers — the interface is one
function (`enqueue(app_id)`) and one module boundary, so the swap is localized.

**Batch size cap**: 500 items per request — an unauthenticated-endpoint guard, comfortably above
the stakeholder's scenario on a single container. It is not designed for tens of thousands of
items.

**No per-batch filter on the main queue**: batch items land in the shared tabbed queue (Needs
attention / Recommended to approve / Verifying / Decided). A "show only batch X" view is a
natural next step but was out of scope for the prototype.

## Trade-offs & known limitations (future work)

- **Warning punctuation** is not verified by the local tier (see above); enabling the model tier
  and wiring a "warning exactness pass" would close it, at the cost of a model call per warning.
- **Responsible-party** matching is intentionally loose; the hardest cases (importer-vs-producer,
  curved seals) are left to escalation + human rather than an ever-growing regex.
- **Latency tail**: median local latency is well under 5 s, but the hardest labels (heavy
  geometry rescues) and the model tier can exceed it; with the model on, escalation currently
  fires often. Reducing false-flags (e.g. responsible party) would cut both.
- **OCR confidence vs. real photos**: tested on synthetic + a real COLA corpus, not phone photos
  under glare/angle at scale (Jenny's wish) — the model tier is the intended answer there.
- **No persistence/PII/retention, no auth** — explicitly out of scope for the prototype.
