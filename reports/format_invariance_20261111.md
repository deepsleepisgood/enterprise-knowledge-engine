# Format invariance — 11 Nov 2026 13:34

Baseline: original .docx, 171 facts, 76 passages.

| variant | F1 | precision | recall | passages | scenarios | target | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pdf | 0.65 | 0.68 | 0.62 | 47% | n/a | F1 >= 0.9 | FAIL |
| md | 0.99 | 0.99 | 0.99 | 50% | n/a | F1 >= 0.9 | PASS |
| html | 0.99 | 0.99 | 0.99 | 50% | n/a | F1 >= 0.9 | PASS |
| xlsx | 0.00 | 0.00 | 0.00 | 5% | n/a | F1 >= 0.9 | FAIL |
| eml | 0.61 | 0.75 | 0.51 | 50% | n/a | F1 >= 0.9 | FAIL |
| flat_docx | 0.92 | 0.92 | 0.92 | 50% | n/a | F1 >= 0.9 | PASS |

## Facts lost or changed: pdf (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('194i', 'tds_deduction.rent_building_rate', 'all', 10.0)
- ('ap sop v4.0', 'sop_scope.applicable_clients', 'all', 'all clients')
- ('dup suspect', 'exception_handling.exception_code_meaning', 'all', 'possible duplicate 3.3')
- ('dup suspect', 'exception_handling.exception_code_owner', 'all', 'senior processor')
- ('duplicate invoice check', 'duplicate_check.first_step_is_duplicate_check', 'all', 'before indexing every invoice is compared with invoices received in the last 18 months for the same supplier.')
- ('duplicate invoice check', 'duplicate_check.flag_action', 'all', 'go to the exception queue as dup suspect and are never posted until a senior processor clears them')
- ('duplicate invoice check', 'duplicate_check.lookback_months', 'all', 18.0)
- ('duplicate invoice check', 'duplicate_check.match_criteria', 'all', 'supplier gstin and normalised number match or when the supplier invoice date and total amount within rs 1 match')
- ('duplicate invoice check', 'duplicate_check.normalisation_rules', 'all', 'remove spaces slashes hyphens and leading zeros and drop a trailing suffix of a r or rev')
- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'gstin inactive')
- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'irn missing')
- ('exception codes and resolution targets', 'exception_handling.default_resolution_target_days', 'all', 5.0)
- ('exception codes and resolution targets', 'exception_handling.gstin_inactive_resolution_target_days', 'all', 2.0)

## Facts lost or changed: md (first 15)

- ('vendor bank account change process', 'vendor_bank_account_change.approval_chain', 'all', 'vendor master lead and the ap controller')

## Facts lost or changed: html (first 15)

- ('vendor bank account change process', 'vendor_bank_account_change.approval_chain', 'all', 'vendor master lead and the ap controller')

## Facts lost or changed: xlsx (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('194i', 'tds_deduction.rent_building_rate', 'all', 10.0)
- ('ap processor', 'ap_processor_responsibilities.responsibilities', 'all', 'indexes invoices runs matching and statutory checks raises exceptions posts clean invoices')
- ('dup suspect', 'exception_handling.dup_suspect_target_days', 'all', 1.0)
- ('dup suspect', 'exception_handling.exception_code_meaning', 'all', 'possible duplicate 3.3')
- ('dup suspect', 'exception_handling.exception_code_owner', 'all', 'senior processor')
- ('duplicate invoice check', 'duplicate_check.match_criteria', 'all', 'normalised invoice number or supplier date amount')
- ('duplicate invoice check', 'duplicate_check.normalisation_rules', 'all', 'normalised invoice number or supplier date amount')
- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'gstin inactive')
- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'irn missing')
- ('exception codes and resolution targets', 'exception_handling.default_resolution_target_days', 'all', 5.0)
- ('exception codes and resolution targets', 'exception_handling.gstin_inactive_resolution_target_days', 'all', 2.0)
- ('exception codes and resolution targets', 'exception_handling.missing_grn_exception_code', 'all', 'no grn')
- ('exception codes and resolution targets', 'exception_handling.no_grn_owner', 'all', 'requester')

## Facts lost or changed: eml (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('194i', 'tds_deduction.rent_building_rate', 'all', 10.0)
- ('ap processor', 'ap_processor_responsibilities.responsibilities', 'all', 'indexes invoices runs matching and statutory checks raises exceptions posts clean invoices')
- ('ap sop v4.0', 'sop_scope.applicable_clients', 'all', 'all clients')
- ('credit note processing', 'credit_note_processing.apply_against_original_invoice', 'all', 'true')
- ('credit note processing', 'credit_note_processing.if_paid_setoff_against_next_invoice_and_record_link', 'all', 'if the original invoice is already paid set off the credit note against the next invoice from the same supplier and record the link.')
- ('credit note processing', 'credit_note_processing.must_quote_original_invoice_number_and_date', 'all', 'true')
- ('debit note processing', 'debit_note_processing.approved_by_requester', 'all', 'true')
- ('debit note processing', 'debit_note_processing.issued_within_days_of_grn_rejection', 'all', 7.0)
- ('debit note processing', 'debit_note_processing.raised_for_short_supply_or_rejected_material', 'all', 'debit notes are raised by the client for short supply or rejected material.')
- ('dup suspect', 'exception_handling.dup_suspect_target_days', 'all', 1.0)
- ('dup suspect', 'exception_handling.exception_code_meaning', 'all', 'possible duplicate 3.3')
- ('dup suspect', 'exception_handling.exception_code_owner', 'all', 'senior processor')
- ('duplicate invoice check', 'duplicate_check.first_step_is_duplicate_check', 'all', 'before indexing every invoice is compared with invoices received in the last 18 months for the same supplier.')

## Facts lost or changed: flat_docx (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('invoice intake channels', 'invoice_intake.email_processing_description', 'all', 'the inbox is read by the intake bot pdf and image attachments are sent to ocr.')
- ('invoice intake channels', 'invoice_intake.paper_invoice_accepted_from', 'all', 'arvana infra projects construction sites')
- ('medium enterprise payment terms', 'medium_enterprise_payment_terms.terms_description', 'all', 'medium enterprises follow normal payment terms 60 days from invoice acceptance .')
- ('payment run schedule', 'payment_run_schedule.cutoff_day', 'all', 'previous working day')
- ('payment run schedule', 'payment_run_schedule.frequency', 'all', 'twice weekly')
- ('payment run schedule', 'payment_run_schedule.run_day', 'all', 'tuesday and friday')
- ('payment run schedule', 'payment_run_schedule.timing_rule', 'all', 'pay on the last payment run that falls on or before the due date. never pay early without treasury approval.')
- ('tds deduction rules', 'tds_deduction.amc_classification_rule', 'all', 'annual maintenance contracts amcs are classified by what is mostly supplied mainly manpower and repairs is 194c mainly technical or software support is 194j at 2%.')
- ('tds deduction rules', 'tds_deduction.base_calculation', 'all', 'taxable value excluding gst wherever gst is shown separately on the invoice')
- ('tds deduction rules', 'tds_deduction.lower_deduction_certificate_check', 'all', 'applied only within its validity dates and up to its amount limit both of which are held in the vendor master')
- ('tds deduction rules', 'tds_deduction.section_determination_basis', 'all', 'the section and rate come from the nature of the payment not from the supplier s description.')
- ('vendor bank account change process', 'vendor_bank_account_change.approval_chain', 'all', 'vendor master lead and the ap controller')