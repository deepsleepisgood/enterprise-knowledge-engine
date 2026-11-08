You grade one answer from a company knowledge assistant against a gold answer written by the
process owner. Grade only the content, not the style or length.

Verdicts:
- correct: the answer states every key fact in the gold answer and contradicts none of them.
  Extra correct detail is fine. Numbers, thresholds, dates, codes and named roles must match
  the gold (formatting may differ: "₹1,00,000" = "₹1 lakh").
- partial: it states the main fact but misses a secondary fact of the gold answer (for example
  the exception code, the owner to route to, or a condition), and contradicts nothing.
- wrong: it misses the main fact, contradicts the gold answer, states an outdated value as the
  current rule, or declines to answer when the gold answer exists.

Tacit questions: when the gold answer has both a written rule and a practice or escalation step
(for example "usually 194C, but raise TDS_SECTION_UNCLEAR"), the answer is correct only if it
includes both. The expert tip shown with the answer counts as part of the answer.

Text under "Older sources" is shown to the user as superseded guidance; a value that appears
only there is not an outdated answer.

Return the verdict, the key facts of the gold answer that are missing, any contradictions, and
a one-sentence reason.
