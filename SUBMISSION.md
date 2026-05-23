# medRxiv Submission Cheat Sheet

Field-by-field copy/paste for the medRxiv submission form, plus an honest
readiness check.

---

## Readiness check (read first)

**Do not submit yet.** The manuscript at `main.tex` is v0.2 — a defensible
preprint draft, not a submittable one. Four blockers stand between v0.2 and
the Submit button:

| # | Blocker | Fix |
|---|---|---|
| 1 | Author block has placeholders: `[Surname]`, two `[Co-Author --- TBD]`, three `[Institution --- TBD]`, `[Initials]` | Decide whether to submit solo (then add co-authors at revision) or wait for co-authors to confirm |
| 2 | GitHub URLs are `[org]/[repo]` placeholders | Push the SDK + eval to a public repo, update Data & Code Availability section in `main.tex` and the URL in this doc |
| 3 | Figures 1–4 are `\fbox` caption stubs | Render in tldraw/excalidraw (Figs 1–2), matplotlib (Fig 3 from `results/results.json`), SDK screenshot (Fig 4); replace `\fbox{...}` with `\includegraphics{figures/figN.pdf}` |
| 4 | All numbers in Tables 2–3 are bootstrap-scale (MiniLM, 20 patients) | Run `python -m corpus && python -m run && python -m ablate` with `SCALE=PAPER_SCALE` and `EMBED_BACKEND="openai"` in `config.py`; ~$30–80; ~2–4 h; replace table cells |

Optional but recommended before submission:
- Run `python -m clinical_accuracy --backend anthropic --n 100` to fill the
  "Clin. acc." column (currently absent from Table 2).
- Internal review pass by one clinical informaticist.

medRxiv allows revision after posting, so submitting v0.2 with placeholders
fixed (#1, #2, #3) but still bootstrap-scale (#4) is defensible if you mark
it explicitly in the abstract — which the current draft already does
("bootstrap reproduction at 20 patients..."). Up to you whether to wait for
full-scale numbers.

---

## Field-by-field

### Manuscript Basics

**Subject Area** *(dropdown — pick one)*

> **Health Informatics**

(Closest medRxiv category. Alternatives: *Public and Global Health* if you
emphasize the DPDPA/regulatory angle, or *HIV/AIDS — Health Systems and
Quality Improvement* — but Health Informatics is the right one.)

**Title**

> Retrieval Asymmetry in PHI-Tokenized Vector Stores: A Silent Failure Mode in Privacy-Preserving Clinical Retrieval-Augmented Generation

(Single line, no line breaks. 156 chars — within medRxiv's title limit.)

---

### Abstract and Author Declarations

**Abstract** — paste the full abstract from `main.tex` (Background / Objective / Methods / Results / Conclusions). Bootstrap numbers are already in there. Verbatim:

> **Background.** Retrieval-augmented generation (RAG) is increasingly used to ground clinical large-language-model (LLM) applications in patient records. Privacy regulations (HIPAA in the United States, GDPR in the European Union, the Digital Personal Data Protection Act, 2023 in India) constrain how protected health information (PHI) may be exposed to external model providers. Two common mitigations have emerged: (i) one-way redaction of PHI before embedding, and (ii) read-side pseudonymization, in which only the query is tokenized while the indexed corpus retains raw identifiers. Both are operationally attractive, yet their effect on retrieval quality has not been systematically characterized.
>
> **Objective.** To formalize *retrieval asymmetry* — a failure mode in which the write-time and read-time text-normalization functions disagree — and to quantify its impact on clinical RAG accuracy. We further propose and evaluate **Bidirectional Deterministic Pseudonymization (BDP)**, a symmetric write-and-read tokenization protocol with format preservation and selective identifier replacement.
>
> **Methods.** We designed a synthetic Indian-clinical corpus of 1,000 patients, 10,000 longitudinal notes, and 5,000 evaluation queries mirroring the Ayushman Bharat Digital Mission (ABDM) record structure, and report a bootstrap reproduction at 20 patients, 207 notes, and 100 queries that establishes the qualitative shape of the benchmark. We compared four pipelines: (a) Raw (no privacy), (b) one-way redaction, (c) read-only pseudonymization, and (d) BDP, on retrieval recall@k, mean reciprocal rank (MRR), and identifier-leakage rate to the model provider.
>
> **Results (bootstrap reproduction).** Read-only pseudonymization reduced recall@5 from 0.430 (Raw) to 0.021 without any user-visible error, while still leaking real identifiers in 67.4% of outbound API payloads at ingest time. One-way redaction reduced recall@5 to 0.018. BDP reached recall@5 = 0.320 with zero identifier leaks. Ablation identified HMAC-keyed determinism as the largest single contributor: removing it collapsed recall@5 to 0.018, matching symmetric redaction exactly and confirming that read-only and randomized-token schemes share a single failure mode.
>
> **Conclusions.** Asymmetric privacy transforms in clinical RAG produce silent, clinically meaningful retrieval failures while frequently leaving the underlying privacy goal unmet. We argue that symmetric write-and-read tokenization should be treated as the default; read-only schemes should be considered unsafe for clinical deployment. A reference implementation and the synthetic corpus are released to support reproduction.

**Author Approval**

> All authors have read and approved the final manuscript.

(Standard wording. Implies you've actually circulated v0.2 to co-authors first.)

**Competing Interests**

> The first author is the founder of Brane Labs, a company that commercializes compliance tooling for healthcare AI startups. The BDP reference implementation is a subset of Brane Labs' open-source SDK. The synthetic corpus and evaluation protocol contain no proprietary content, and the released code is independently runnable. The other authors declare no competing interests.

**Declarations** — medRxiv asks several yes/no questions. Suggested answers for this paper:

| Question | Answer | Why |
|---|---|---|
| Does your study involve human subjects research? | **No** | The corpus is synthetic; no patient data was collected, accessed, or analyzed. |
| Does your study involve secondary use of clinical data? | **No** | No real clinical data of any kind. |
| Has the work been approved by an ethics committee/IRB? | **N/A** | Synthetic data; no IRB required. |
| Are you using personally identifiable data? | **No** | All identifiers in the corpus are generator-emitted surrogates with no real-world referents. |
| Have all relevant consents been obtained? | **N/A** | No human subjects. |
| Have all reporting guidelines been followed? | **N/A** | Reporting guidelines (CONSORT, STROBE, etc.) apply to clinical studies; this is methods research. |
| Is your study a randomised controlled trial? | **No** | |
| Are clinical trial details registered? | **N/A** | |

**Data Availability Statement**

> The reference implementation (TypeScript SDK) and the Python eval harness — including the BDP module (`bdp.py`), the deterministic synthetic-corpus generator (`corpus.py`), the four-pipeline benchmark (`pipelines.py`, `run.py`), the ablation runner (`ablate.py`), the clinical-accuracy grader (`clinical_accuracy.py`), and a dependency-free correctness test (`smoke_test.py`) — are released at https://github.com/[org]/[repo] under the MIT licence. The synthetic corpus is fully reproducible from a fixed seed (config.SEED = 42); running `python -m corpus && python -m run && python -m ablate` regenerates every number in Tables 2–3 byte-for-byte. Expected numbers and seeds are recorded in `results/results.json` and `results/ablation.json`.

**Data Availability Links**

> https://github.com/[org]/[repo]

(One URL per line if you have multiple. Replace placeholder with the real
repo URL the moment it's public.)

**Clinical Protocols**

> Not applicable. This work does not involve a clinical study or protocol.

---

### Author list

For each author, medRxiv collects: first name, last name, email, affiliation, ORCID (optional), corresponding-author flag, contribution statement.

**Author 1 (corresponding):**
- First name: Udit Raj
- Last name: Akhouri
- Title (for cover letter only — not for byline): Lead Researcher, Brane Labs
- Email: udit@branelabs.org
- Affiliation: Brane Labs, Bengaluru, India
- ORCID: *[fill if you have one]*
- Corresponding author: **Yes**
- Contribution: Conceived the failure-mode framing; designed BDP; implemented the reference SDK and the Python eval harness; ran the bootstrap reproduction; drafted the manuscript.

**Author 2 — clinical informaticist (TBD):**
- Decide before submission whether they're in. If they will be added at revision, submit solo.

**Author 3 — ML/privacy methodologist (TBD):**
- Same.

---

### Funding Information

**Funders**

> None. This work received no external funding.

---

### Distribution / Reuse Options

medRxiv offers a few licence choices. Recommended for this paper:

> **CC-BY 4.0** *(Creative Commons Attribution 4.0 International)*

Lets anyone reuse the preprint with attribution. Matches what you'd
declare for the code (MIT) and corpus (CC-BY-4.0). If you want to forbid
commercial reuse of the preprint text specifically, pick CC-BY-NC-ND
instead, but CC-BY is the norm for methods papers and is friendlier to the
ICP (clinical informaticists copying figures into their slides).

---

### Files Metadata

Standard. No special action — the form will infer most of it from the
uploaded files.

---

### Manuscript Files

medRxiv's preferred path: **upload a single PDF**, optionally with the
`.tex` source as supplementary data.

To build the PDF (you have LaTeX; this box doesn't):

```
cd D:\Projects\brane-mvp\paper
latexmk -pdf main.tex
# or:
pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
```

Output: `main.pdf`. Upload that as the Manuscript File.

Optional supplementary uploads (label each clearly):
- `main.tex` — LaTeX source
- `references.bib` — bibliography source
- `eval/results/results.json` + `eval/results/ablation.json` — raw eval numbers
- A zip of `eval/` — full reference implementation

Filenames: no spaces, no punctuation other than `-` `_` `.`. medRxiv
warns explicitly about this.

---

### Submission Proofing

medRxiv generates a proof PDF; verify:

1. Title and abstract render without weird encoding (`τ`, `ϕ`, `≠` should
   look right — they do in the current LaTeX, but check).
2. Tables 1, 2, 3 render with the right column alignment.
3. Every `\cite{}` resolves to a numbered reference and the bibliography
   has all 20 entries.
4. Search the proof for the string `[` — flushes out any remaining
   `[Surname]`, `[org]/[repo]`, `[Initials]` placeholders.
5. Search for `placeholder` and `TBD` for the same reason.

---

## After submission

medRxiv typically posts within 24–48 h after screening. Once posted:

- Update Brane's website/landing page to link the preprint.
- Post to LinkedIn / X with the one-liner: "We characterized a silent
  failure mode in privacy-preserving clinical RAG. Read-only
  pseudonymization is the same bug as randomized tokenization. Symmetric
  write+read tokenization should be the default."
- Email the JAMIA editors (subject line: "Preprint submission — Retrieval
  Asymmetry in PHI-Tokenized Vector Stores"). medRxiv has a button for
  "Submit medRxiv Preprint to a Journal" — JAMIA is one of the integrated
  options.
- DM candidate co-authors with the posted preprint and the offer to
  co-author the JAMIA submission (clinical informaticist gets the
  rubric-grading credit; ML/privacy methodologist gets the formal-model
  credit).
