# Format invariance — 11 Nov 2026 14:13

Baseline: original .docx, 171 facts, 76 passages.

| variant | F1 | precision | recall | passages | scenarios | target | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pdf | 0.88 | 0.89 | 0.86 | 47% | n/a | F1 >= 0.9 | FAIL |
| xlsx | 0.00 | 0.00 | 0.00 | 5% | n/a | F1 >= 0.9 | FAIL |
| eml | 0.77 | 0.80 | 0.74 | 49% | n/a | F1 >= 0.9 | FAIL |

## Facts lost or changed: pdf (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('ap sop v4.0', 'sop_scope.applicable_clients', 'all', 'all clients')
- ('duplicate invoice check', 'duplicate_check.first_step_is_duplicate_check', 'all', 'before indexing every invoice is compared with invoices received in the last 18 months for the same supplier.')
- ('duplicate invoice check', 'duplicate_check.flag_action', 'all', 'go to the exception queue as dup suspect and are never posted until a senior processor clears them')
- ('duplicate invoice check', 'duplicate_check.lookback_months', 'all', 18.0)
- ('duplicate invoice check', 'duplicate_check.match_criteria', 'all', 'supplier gstin and normalised number match or when the supplier invoice date and total amount within rs 1 match')
- ('duplicate invoice check', 'duplicate_check.normalisation_rules', 'all', 'remove spaces slashes hyphens and leading zeros and drop a trailing suffix of a r or rev')
- ('exception codes and resolution targets', 'exception_handling.price_var_owner', 'all', 'po buyer')
- ('gst compliance checks', 'gst_compliance.einvoice_turnover_threshold', 'all', 50000000.0)
- ('invoice approval authority', 'invoice_approval_authority.ap_controller_approves_payment_proposals', 'all', 'true')
- ('irn missing', 'exception_handling.irn_missing_meaning', 'all', 'e invoice required but absent referencing section 5.4')
- ('irn missing', 'exception_handling.irn_missing_resolution_target', 'all', 'when the e invoice is received')
- ('irn requirement', 'irn_requirement.do_not_pay_base_value_for_missing_irn', 'all', 'do not pay the base value either a valid invoice will follow.')
- ('irn requirement', 'irn_requirement.irn_missing_invalid_for_itc', 'all', 'the invoice is not valid for input tax credit')

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
- ('credit note processing', 'credit_note_processing.if_paid_setoff_against_next_invoice_and_record_link', 'all', 'if the original invoice is already paid set off the credit note against the next invoice from the same supplier and record the link.')
- ('dup suspect', 'exception_handling.dup_suspect_target_days', 'all', 1.0)
- ('duplicate invoice check', 'duplicate_check.first_step_is_duplicate_check', 'all', 'before indexing every invoice is compared with invoices received in the last 18 months for the same supplier.')
- ('duplicate invoice check', 'duplicate_check.flag_action', 'all', 'go to the exception queue as dup suspect and are never posted until a senior processor clears them')
- ('duplicate invoice check', 'duplicate_check.normalisation_rules', 'all', 'normalised invoice number or supplier date amount')
- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'gstin inactive')
- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'irn missing')
- ('exception codes and resolution targets', 'exception_handling.default_resolution_target_days', 'all', 5.0)
- ('exception codes and resolution targets', 'exception_handling.no_grn_owner', 'all', 'requester')
- ('exception codes and resolution targets', 'exception_handling.no_grn_resolution_target_days', 'all', 5.0)