# Acceptance tests T1–T11 on the public URL — 11 Nov 2026

- Site: https://ps07-knowledge-engine.vercel.app (Vercel) → API and worker on this laptop through a
  Cloudflare quick tunnel → Neon Postgres (the deployed knowledge base).
- LLM: Isoquant, `deepseek-v4.1-flash-1017-fast` (OpenAI-compatible, zero data retention requested),
  reasoning `none` where the pipeline turns thinking off, `low` elsewhere. NVIDIA NIM was throttled to
  minutes per call this afternoon, so the demo moved to Isoquant.
- T1–T8 were asked through the public API exactly as the web app asks (`POST /ask/jobs`, then poll),
  as a processor sees them, with the checks of `tests/acceptance/test_answers_live.py`. T9 was run on
  the deployed database; T11 was done by hand in the browser on the public site.

| Test | Result | Time | What the answer says |
| --- | --- | --- | --- |
| T1 price tolerance | PASS | 18.4 s | lower of 1% of the PO line value and ₹500; cites SOP v4.0 |
| T1 as of 1 Mar 2026 | PASS | 18.2 s | lower of 2% and ₹1,000, "the rule in force on 2026-03-01" |
| T2 ₹8.9 crore, no IRN | PASS | 14.6 s | not acceptable, IRN_MISSING; ₹5 crore threshold; ₹10 crore not stated as current |
| T3 Pharma excipients | PASS | 18.3 s | yes, QA release in QMS first; cites the Pharma memo; FAQ flagged |
| T4 Infra Saturday, no GRN | PASS | 17.9 s | hold as NO_GRN (§4.6, reminder after two working days) + expert practice (Tuesday), Interview 1 |
| T5 ₹395 vs ₹400 × 500 | PASS | 14.6 s | excess ₹2,500 over the ₹500 limit (1% would be ₹1,975), PRICE_VAR |
| T6 software support ₹4,80,000 | PASS | 18.2 s | 194J at 2% = ₹9,600, base excludes GST |
| T7 micro, accepted 1 Aug 2026 | PASS | 25.1 s | due 16 Aug 2026; pay in the Friday 14 Aug run |
| T8 canteen subsidy | PASS | 11.2 s | not covered; routed to HR / Admin team |
| T9 conflict scan | PASS | 7 s scan | 15/15 known conflicts, authoritative source right 14/15 (`reports/conflicts_20261111.md`) |
| T11 escalation to an expert | PASS | — | see below |

Times are end to end through the tunnel with two questions in flight at once.

## T11, step by step (public site, browser)

1. Asked T8 → "The documents don't cover this", route to HR / Admin team, button "Send to HR / Admin team".
2. Sent → "Sent to HR / Admin team · waiting"; the question appeared under Questions for experts on the
   owner's Review page with a reply box.
3. Expert replied (labelled `[TEST DATA - T11 check]`) → the asker was notified at once: "Expert reply —
   not yet part of the knowledge base".
4. The reply entered as an `expert_answer` episode and passed extraction and governance: review item
   "1 fact from Canteen subsidy is held for your decision. Not applied: answers ignore it until you
   approve. Why: HR / Admin team is not a registered owner for these topics." Asked again before
   approval: still not covered (the unapproved reply is never used).
5. Owner approved → the fact became current, the question was re-asked automatically and the asker was
   notified: "Your question has a new answer from the knowledge base".
6. Asked again on the site → cited answer "Night-shift staff get a canteen subsidy of Rs 60 per meal",
   shown as Expert entry · Canteen subsidy (9.5 s). Screenshot: `reports/screenshots/t11_public_after_approval.png`.
7. Test data removed from Neon afterwards (`scripts/delete_episodes.py`): 1 episode, 2 facts, 2 review
   items, 1 escalation, 2 changes; the question is "not covered" again.

The last clause of T11 (a bank-details change from a non-owner stays pending) is covered by the intake
check: the spoofed bank-change email is held as pending (`reports/intake_20261111.md`, email 03).

## Fixed on the way (found by these tests)

- **Tunnel timeout:** a Cloudflare quick tunnel closes requests after ~100 s, so slow answers failed with
  HTTP 524. The web app now starts an answer (`POST /ask/jobs`) and polls (`GET /ask/jobs/{id}`);
  `POST /ask` is unchanged.
- **Garbled model replies:** a reply with no JSON is now asked again from scratch (not fed back), and a
  routing failure falls back to lookup instead of failing the question with a 500.
- **First extraction of the expert reply produced nothing** while NIM was failing (the episode still
  showed as published); re-queued on Isoquant it worked. Open issue: an extraction that fails on every
  passage should mark the episode for attention instead of published.
