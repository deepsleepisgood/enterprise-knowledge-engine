# Format invariance — 14 Nov 2026 00:07

Baseline: original .docx, 170 facts, 76 passages.

| variant | F1 | precision | recall | rule F1 | passages | scenarios | target | pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pdf | 0.94 | 0.96 | 0.92 | 0.94 | 47% | 100% | F1 >= 0.9 | PASS |
| md | 1.00 | 1.00 | 1.00 | 1.00 | 50% | 100% | F1 >= 0.9 | PASS |
| html | 1.00 | 1.00 | 1.00 | 1.00 | 50% | 100% | F1 >= 0.9 | PASS |
| xlsx | 0.84 | 0.84 | 0.83 | 0.88 | 5% | 80% | F1 >= 0.9 | FAIL |
| eml | 0.93 | 0.92 | 0.94 | 0.93 | 50% | 97% | F1 >= 0.9 | PASS |
| flat_docx | 0.00 | 0.00 | 0.00 | 0.00 | 50% | 0% | F1 >= 0.9 | FAIL |
| pptx | 0.00 | 0.00 | 0.00 | 0.00 | 50% | 0% | F1 >= 0.9 | FAIL |

## Facts lost or changed: pdf (first 15)

- ('duplicate invoice check', 'duplicate_check.flag_action', 'all', 'dup suspect')
- ('duplicate invoice check', 'duplicate_check.lookback_months', 'all', 18.0)
- ('duplicate invoice check', 'duplicate_check.match_criteria', 'all', 'supplier gstin and normalised number match or supplier invoice date and total amount within rs 1 match')
- ('duplicate invoice check', 'duplicate_check.normalisation_rules', 'all', 'remove spaces slashes hyphens and leading zeros and drop a trailing suffix of a r or rev')
- ('exception codes and resolution targets', 'exception_handling.dup_suspect_routing', 'all', 'cleared by a senior processor')
- ('invoice approval authority', 'invoice_approval_authority.exceptions_cleared_by_senior_processor_threshold', 'all', 'up to rs 10 lakh')
- ('irn requirement', 'irn_requirement.effective_date', 'all', '1 apr 2026')
- ('price var', 'exception_handling.price_var_resolution_process', 'all', 'a line that fails the price tolerance is held with exception price var and sent to the buyer who raised the po the buyer either amends the po or asks the supplier for a credit note.')
- ('tds deduction rules', 'tds_deduction.base_calculation', 'all', 'on the excess')
- ('tds deduction rules', 'tds_deduction.goods_purchase_rate', 'all', 0.1)
- ('tds deduction rules', 'tds_deduction.section_determination_basis', 'all', 'the nature of the payment not from the supplier s description')
- ('tds section unclear', 'tds_deduction.unclear_section_action', 'all', 'raise tds section unclear to the tax desk. do not guess.')
- ('vendor master team', 'tds_deduction.lower_deduction_certificate_check', 'all', 'applied only within its validity dates and up to its amount limit both of which are held in the vendor master')

## Facts lost or changed: xlsx (first 15)

- ('194j', 'tds_deduction.section_determination_basis', 'all', 'fees for technical services not professional including software support fall under section 194j')
- ('ap controller', 'invoice_approval_authority.threshold_amount', 'all', 1000000.0)
- ('ap processor', 'ap_processor_responsibilities.responsibilities', 'all', 'indexes invoices runs matching and statutory checks raises exceptions posts clean invoices')
- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'gstin inactive')
- ('exception codes and resolution targets', 'exception_handling.tax_desk_referral_codes', 'all', 'tds section unclear and rcm review')
- ('msme due', 'msme_payment_terms.escalation_trigger_days', 'all', 7.0)
- ('non po invoice categories', 'non_po_categories.courier_travel_agency_require_po', 'all', 'true')
- ('payment run schedule', 'payment_run_schedule.run_day', 'all', 'tuesday and friday')
- ('tds deduction rules', 'tds_deduction.base_calculation', 'all', 'on the excess')
- ('tds deduction rules', 'tds_deduction.goods_purchase_rate', 'all', 0.1)
- ('tds deduction rules', 'tds_deduction.goods_purchase_threshold', 'all', 5000000.0)
- ('treasury', 'payment_run_schedule.payment_file_releaser', 'all', 'treasury client')
- ('vendor master team', 'vendor_master.team_responsibility', 'all', 'creates and changes supplier records including bank details')

## Facts lost or changed: eml (first 15)

- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'gstin inactive')
- ('invoice approval authority', 'invoice_approval_authority.exceptions_cleared_by_senior_processor_threshold', 'all', 'up to rs 10 lakh')
- ('medium enterprise payment terms', 'medium_enterprise_payment_terms.terms_description', 'all', 'medium enterprises follow normal terms')
- ('msme due', 'msme_payment_terms.escalation_trigger_days', 'all', 7.0)
- ('msme payment terms', 'msme_payment_terms.late_payment_consequences', 'all', 'late payment to a micro or small enterprise makes the client liable for compound interest and can disallow the expense for income tax')
- ('payment run schedule', 'payment_run_schedule.cutoff_time', 'all', '1 pm on the previous working day')
- ('payment run schedule', 'payment_run_schedule.default_payment_terms_days', 'all', 60.0)
- ('payment run schedule', 'payment_run_schedule.timing_rule', 'all', 'pay on the last payment run that falls on or before the due date never pay early without treasury approval')
- ('tds deduction rules', 'tds_deduction.section_determination_basis', 'all', 'the nature of the payment not from the supplier s description')
- ('tds section unclear', 'tds_deduction.unclear_section_action', 'all', 'raise tds section unclear to the tax desk. do not guess.')
- ('vendor master team', 'tds_deduction.lower_deduction_certificate_check', 'all', 'applied only within its validity dates and up to its amount limit both of which are held in the vendor master')

## Facts lost or changed: flat_docx (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('194i', 'tds_deduction.rent_building_rate', 'all', 10.0)
- ('194i', 'tds_deduction.rent_plant_machinery_rate', 'all', 2.0)
- ('194j', 'tds_deduction.professional_rate', 'all', 10.0)
- ('194j', 'tds_deduction.section_determination_basis', 'all', 'fees for technical services not professional including software support fall under section 194j')
- ('194j', 'tds_deduction.technical_services_rate', 'all', 2.0)
- ('aato bands for irn requirement', 'aato_bands.recorded_at_creation_reviewed_april', 'all', 'recorded at creation and reviewed every april')
- ('ap controller', 'invoice_approval_authority.ap_controller_approves_payment_proposals', 'all', 'true')
- ('ap controller', 'invoice_approval_authority.ap_controller_max_approval_amount', 'all', 5000000.0)
- ('ap controller', 'invoice_approval_authority.threshold_amount', 'all', 1000000.0)
- ('ap processor', 'ap_processor_responsibilities.responsibilities', 'all', 'indexes invoices runs matching and statutory checks raises exceptions posts clean invoices')
- ('credit note processing', 'credit_note_processing.apply_against_original_invoice', 'all', 'true')
- ('credit note processing', 'credit_note_processing.if_paid_setoff_against_next_invoice_and_record_link', 'all', 'if the invoice is already paid set it off against the next invoice from the same supplier and record the link')
- ('credit note processing', 'credit_note_processing.must_quote_original_invoice_number_and_date', 'all', 'true')

## Facts lost or changed: pptx (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('194i', 'tds_deduction.rent_building_rate', 'all', 10.0)
- ('194i', 'tds_deduction.rent_plant_machinery_rate', 'all', 2.0)
- ('194j', 'tds_deduction.professional_rate', 'all', 10.0)
- ('194j', 'tds_deduction.section_determination_basis', 'all', 'fees for technical services not professional including software support fall under section 194j')
- ('194j', 'tds_deduction.technical_services_rate', 'all', 2.0)
- ('aato bands for irn requirement', 'aato_bands.recorded_at_creation_reviewed_april', 'all', 'recorded at creation and reviewed every april')
- ('ap controller', 'invoice_approval_authority.ap_controller_approves_payment_proposals', 'all', 'true')
- ('ap controller', 'invoice_approval_authority.ap_controller_max_approval_amount', 'all', 5000000.0)
- ('ap controller', 'invoice_approval_authority.threshold_amount', 'all', 1000000.0)
- ('ap processor', 'ap_processor_responsibilities.responsibilities', 'all', 'indexes invoices runs matching and statutory checks raises exceptions posts clean invoices')
- ('credit note processing', 'credit_note_processing.apply_against_original_invoice', 'all', 'true')
- ('credit note processing', 'credit_note_processing.if_paid_setoff_against_next_invoice_and_record_link', 'all', 'if the invoice is already paid set it off against the next invoice from the same supplier and record the link')
- ('credit note processing', 'credit_note_processing.must_quote_original_invoice_number_and_date', 'all', 'true')