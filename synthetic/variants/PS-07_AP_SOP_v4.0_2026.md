PS-07 · DATA PACK

Accounts Payable SOP — version 4.0

Meridian Shared Services (fictional) · effective 1 April 2026

SYNTHETIC — generated for the Masters' Union Applied AI Challenge to protect privacy. This document describes a fictional case company. Names, identifiers, numbers and events are invented and do not represent any real organisation or person.

| Document | Accounts Payable Standard Operating Procedure |
| --- | --- |
| Version | 4.0 |
| Effective | 1 April 2026 |
| Replaces | Version 3.1 (effective 1 July 2023) |
| Owner | AP Process Excellence, Meridian Shared Services |
| Approved by | Head of Finance Operations; Arvana Group Financial Controller |
| Applies to | Arvana Retail Pvt Ltd, Arvana Pharma Ltd, Arvana Infra Projects Ltd |

Statutory references (GST, TDS, MSME) are simplified for this teaching case and reflect the fictional company's policy as written. They are not tax or legal advice; check current law before relying on any rate or threshold.

# 1. Purpose and scope

This procedure explains how Meridian Shared Services receives, checks, approves, posts and pays supplier invoices for the three Arvana Group companies it serves. It applies to every AP Processor, Senior Processor, Team Lead and AP Controller in the Hyderabad centre. Where a client has agreed a different rule, the client memo in the desk instructions takes precedence over this SOP for that client only, and the memo is referenced here.

Version 4.0 tightens tolerances, introduces twice-weekly payment runs, aligns the e-invoice check with the current GST threshold and replaces e-mail confirmation of supplier bank changes with a call-back control after two attempted frauds in 2025. Every rule that changed from version 3.1 is listed in section 14.

# 2. Roles

| Role | Responsibility |
| --- | --- |
| AP Processor | Indexes invoices, runs matching and statutory checks, raises exceptions, posts clean invoices. |
| Senior Processor | Resolves exceptions a Processor cannot, reviews a 10% sample of a new joiner's postings for their first 60 days. |
| Team Lead | Owns queue age and service levels for one client; approves write-offs up to ₹1,000. |
| AP Controller | Approves invoices between ₹10 lakh and ₹50 lakh, payment proposals and vendor bank changes. |
| Tax Desk | Decides GST and TDS treatment where this SOP sends a case to them (codes TDS_SECTION_UNCLEAR and RCM_REVIEW). |
| Vendor Master team | Creates and changes supplier records, including bank details. |
| Treasury (client) | Releases payment files prepared by Meridian. |

# 3. Invoice intake

## 3.1 Channels

- The supplier portal is the preferred channel. Invoices arrive with PO number and GSTIN already validated.
- E-mail to the AP inbox is accepted for all clients. The inbox is read by the intake bot; PDF and image attachments are sent to OCR.
- Paper invoices are accepted only from Arvana Infra Projects construction sites, scanned at the Hyderabad mail room within one working day of receipt.
## 3.2 Mandatory fields

An invoice must show: supplier legal name and GSTIN; buyer legal name and the buyer GSTIN for the state of delivery; invoice number and date; PO number (unless the invoice falls in a non-PO category under 4.5); HSN or SAC code per line; taxable value, tax rate and tax amount per line; place of supply; and, where required by 5.4, the IRN and QR code. An invoice missing any mandatory field is returned to the supplier with code INV_INCOMPLETE. Do not correct supplier invoices by hand.

## 3.3 Duplicate check

Before indexing, every invoice is compared with invoices received in the last 18 months for the same supplier. The comparison uses a normalised invoice number: remove spaces, slashes, hyphens and leading zeros, and drop a trailing suffix of /A, /R or -REV. Two invoices are a suspected duplicate when the supplier GSTIN and normalised number match, or when the supplier, invoice date and total amount (within ₹1) match. Suspected duplicates go to the exception queue as DUP_SUSPECT and are never posted until a Senior Processor clears them.

# 4. Matching

## 4.1 Match type

Goods invoices are matched three ways: purchase order, goods receipt note (GRN) and invoice. Service invoices are matched two ways against the PO and the approved service entry sheet. The match type is taken from the PO, not from the invoice.

## 4.2 Price tolerance

Where the invoice unit price is higher than the PO unit price, the line passes only if the total excess on that line is no more than the lower of 1% of the PO line value and ₹500. Where the invoice price is lower than the PO price, accept it and pay the invoice price. A line that fails is held with exception PRICE_VAR and sent to the buyer who raised the PO; the buyer either amends the PO or asks the supplier for a credit note.

## 4.3 Quantity tolerance

Invoice quantity must not exceed the GRN quantity. There is no quantity tolerance for any client, except the bulk-material tolerance agreed with Arvana Infra Projects in Client Memo CM-INF-02 (see desk instructions). Short invoicing (invoice quantity below GRN quantity) is accepted, and the balance stays open on the GRN.

## 4.4 Rounding

Differences of up to ₹10 at invoice-total level caused by line-level tax rounding are accepted automatically and posted to the rounding-difference account. Anything above ₹10 is a mismatch.

## 4.5 Non-PO invoices

Only these categories may be processed without a PO: electricity, water and telecom utilities; store and office rent under a registered lease; statutory payments and government fees; and insurance premiums. Every other invoice needs a PO. Courier and travel-agency invoices, which were non-PO under version 3.1, now need a PO. A non-PO invoice of any amount needs the budget owner's approval in the workflow.

## 4.6 Missing GRN

If a goods invoice has no GRN, hold it as NO_GRN and notify the requester automatically. The system sends a reminder after two working days and escalates to the requester's manager after five working days. Do not post a goods invoice against a PO without a GRN, whatever the requester says on the phone.

# 5. GST checks

## 5.1 Supplier GSTIN

The supplier GSTIN must be active on the GST portal on the invoice date. A cancelled or suspended GSTIN means the invoice is held as GSTIN_INACTIVE and the Tax Desk is informed. Pay nothing, including the base value, until the Tax Desk decides.

## 5.2 Buyer GSTIN and place of supply

The buyer GSTIN on the invoice must be the client entity's registration in the state where the goods were delivered or the service was received. A mismatch is held as GSTIN_MISMATCH and returned to the supplier for a corrected invoice; a credit note and re-issue is acceptable.

## 5.3 Tax type

Intra-state supplies carry CGST and SGST in equal halves; inter-state supplies carry IGST. An invoice with the wrong tax type is returned to the supplier as TAX_TYPE_WRONG.

## 5.4 E-invoices

A supplier whose aggregate annual turnover (AATO) in any financial year since 2017-18 has exceeded ₹5 crore must issue an e-invoice with an Invoice Reference Number (IRN) and QR code. The vendor master records each supplier's AATO band. If such a supplier sends an invoice without an IRN, the invoice is not valid for input tax credit: return it as IRN_MISSING and ask for an e-invoice. Do not pay the base value either; a valid invoice will follow.

## 5.5 GSTR-2B reconciliation

Input tax credit is claimed only for invoices that appear in the client's GSTR-2B. GSTR-2B for a month is generated on the 14th of the following month. If an invoice does not appear in GSTR-2B by then, pay the base value on the due date and hold the GST amount until the invoice appears. If it is still missing after two further GSTR-2B cycles, raise NOT_IN_2B to the vendor relationship owner.

## 5.6 Reverse charge

Services on which the buyer pays GST under reverse charge — for example legal services from an advocate or a firm of advocates — are flagged RCM_REVIEW and routed to the Tax Desk before posting.

# 6. Tax deducted at source (TDS)

TDS is deducted on the taxable value excluding GST wherever GST is shown separately on the invoice. The section and rate come from the nature of the payment, not from the supplier's description. Section numbers refer to the Income-tax Act, 1961; the Tax Desk is mapping them to the new Income-tax Act and will issue a circular. Until then, use the codes below.

| Nature of payment | Section | Rate |
| --- | --- | --- |
| Work contracts, transport, repairs, manpower — payee an individual or HUF | 194C | 1% |
| Work contracts, transport, repairs, manpower — any other payee | 194C | 2% |
| Professional services (legal, audit, consulting, architects) | 194J | 10% |
| Fees for technical services (not professional), including software support | 194J | 2% |
| Rent of plant, machinery or equipment | 194I | 2% |
| Rent of land, building or furniture | 194I | 10% |
| Purchase of goods, once purchases from the supplier exceed ₹50 lakh in the financial year (on the excess) | 194Q | 0.1% |

- If the supplier has not furnished a valid PAN, deduct at 20% or the applicable rate, whichever is higher.
- A lower-deduction certificate under section 197 is applied only within its validity dates and up to its amount limit, both of which are held in the vendor master.
- Annual maintenance contracts (AMCs) are classified by what is mostly supplied: mainly manpower and repairs is 194C; mainly technical or software support is 194J at 2%. When a contract is mixed or unclear, raise TDS_SECTION_UNCLEAR to the Tax Desk. Do not guess.
# 7. Approvals

| Invoice total (including GST) | Approval needed before posting |
| --- | --- |
| Up to ₹10 lakh | None beyond a clean match. Exceptions are cleared by a Senior Processor. |
| Above ₹10 lakh up to ₹50 lakh | AP Controller |
| Above ₹50 lakh | Client CFO, through the approval workflow |
| Any non-PO invoice | Budget owner, in addition to the above |

# 8. Vendor master

## 8.1 New suppliers

A new supplier is created only with: PAN, GST registration certificate (or a declaration of non-registration), a cancelled cheque or bank letter, Udyam registration certificate if the supplier is a micro, small or medium enterprise, and the signed Supplier Code of Conduct. The AATO band for the e-invoice check and the QRMP filing flag are recorded at creation and reviewed every April.

## 8.2 Bank account changes

- The supplier sends a request on letterhead signed by an authorised signatory, with a cancelled cheque for the new account.
- The Vendor Master team calls the supplier on the phone number already held in the vendor master — never on a number given in the request — and confirms the change with a named person.
- The change is approved by the Vendor Master lead and the AP Controller.
- No payment is made to the new account until 24 hours after approval.
- No bank changes are made in the three working days before month-end close.
# 9. Payments

- Payment runs are on Tuesday and Friday. The cut-off for an invoice to be included is 1 pm on the previous working day.
- Default terms for suppliers that are not micro or small enterprises are 60 days from invoice acceptance, unless the PO says otherwise.
- Micro and small enterprises registered on Udyam must be paid within the agreed term, which can never exceed 45 days from the day of acceptance. If there is no written agreement on terms, pay within 15 days. Medium enterprises follow normal terms.
- Late payment to a micro or small enterprise makes the client liable for compound interest and can disallow the expense for income tax. Treat every MSME_DUE flag as urgent.
- Pay on the last payment run that falls on or before the due date. Never pay early without Treasury approval.
# 10. Exceptions

| Code | Meaning | Owner | Target to resolve |
| --- | --- | --- | --- |
| PRICE_VAR | Unit price above tolerance (4.2) | PO buyer | 3 working days |
| QTY_VAR | Invoice quantity above GRN (4.3) | Requester | 3 working days |
| NO_GRN | Goods invoice without GRN (4.6) | Requester | 5 working days |
| DUP_SUSPECT | Possible duplicate (3.3) | Senior Processor | 1 working day |
| GSTIN_MISMATCH | Wrong buyer GSTIN (5.2) | Supplier | Until corrected invoice |
| GSTIN_INACTIVE | Supplier GSTIN not active (5.1) | Tax Desk | 2 working days |
| IRN_MISSING | E-invoice required but absent (5.4) | Supplier | Until e-invoice received |
| NOT_IN_2B | Invoice missing from GSTR-2B after two further cycles (5.5) | Vendor owner | Next cycle |
| TDS_SECTION_UNCLEAR | TDS section not clear (6) | Tax Desk | 2 working days |
| RCM_REVIEW | Reverse-charge service (5.6) | Tax Desk | 2 working days |
| NON_PO_NOT_ALLOWED | Non-PO invoice outside 4.5 | Requester | 5 working days |
| MSME_DUE | Micro/small supplier within 7 days of due date | Team Lead | Before due date |
| QA_RELEASE_PENDING | Pharma batch not released (CM-PHA-01) | Client QA | Before due date |

# 11. Month-end close

Invoices received after the third-last working day of the month are not posted in that month; goods received but not invoiced are accrued from open GRNs instead. The vendor master is frozen for bank changes for the three working days before close. The Team Lead signs off the open-exception report on the last working day.

# 12. Credit and debit notes

A credit note must quote the original invoice number and date. Apply it against that invoice; if the invoice is already paid, set it off against the next invoice from the same supplier and record the link. Debit notes raised by the client for short supply or rejected material are approved by the requester and issued within seven days of the GRN rejection.

# 13. Records and data protection

Invoices and supporting documents are kept for eight years. Supplier bank details, PAN and contact numbers are personal or confidential data: they are visible only to the Vendor Master team and AP Controllers, and are never pasted into e-mail, chat or any external tool.

# 14. What changed from version 3.1

| Topic | Version 3.1 | Version 4.0 |
| --- | --- | --- |
| Price tolerance | Lower of 2% of line value and ₹1,000 | Lower of 1% of line value and ₹500 |
| Quantity tolerance | 2% over GRN for all goods | None, except client memo CM-INF-02 |
| Rounding | Up to ₹50 auto-accepted | Up to ₹10 auto-accepted |
| E-invoice threshold | AATO above ₹10 crore | AATO above ₹5 crore |
| ITC check | GSTR-2A by the 20th | GSTR-2B (generated on the 14th) |
| Bank changes | E-mail confirmation, one approval | Call-back to known number, two approvals, 24-hour cooling-off |
| Payment runs | Weekly, Thursday | Tuesday and Friday |
| Approvals | AP Controller above ₹25 lakh; CFO above ₹1 crore | AP Controller above ₹10 lakh; CFO above ₹50 lakh |
| Non-PO categories | Included courier and travel agencies | Courier and travel agencies need a PO |
| MSME payment | Within 60 days | Agreed term up to 45 days; 15 days without agreement |
| Duplicate check | Exact invoice number and supplier | Normalised invoice number, or supplier + date + amount |
