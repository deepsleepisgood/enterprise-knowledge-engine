# Scenario misses (induced schema) — 90 of 92 correct

## Q092 (price)
- Question: Arvana Infra Projects Ltd: PO unit price ₹120 for 100 units; the invoice charges ₹121 per unit. Can the line pass the price match?
- Gold: No — raise PRICE_VAR. Excess ₹132 on a line value of ₹12,000; limit is the lower of 1% (₹120) and ₹500 = ₹120.
- Expected: {'passed': False, 'excess': 132.0, 'limit': 120.0}
- Got: {'passed': True, 'excess': 100.0, 'limit': 120.0}
- Engine decision: Pass — excess within the price tolerance
- Cause: mismatch; inputs={'po_unit_price': 120.0, 'invoice_unit_price': 121.0, 'quantity': 100.0, 'client': None}

## Q112 (tds)
- Question: An invoice for hire of a crane: taxable value ₹1,500,000 plus GST ₹270,000. What TDS should be deducted?
- Gold: Section 194I at 2% on the taxable value excluding GST: ₹30,000.
- Expected: {'section': '194I', 'rate': 2.0, 'amount': 30000.0}
- Got: None
- Engine decision: None
- Cause: extraction: NimError: NIM request failed after retries: NIM HTTP 429: {"status":429,"title":"Too Many Requests"}
