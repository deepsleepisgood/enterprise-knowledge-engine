# Format invariance — 14 Nov 2026 00:00

Baseline: original .docx, 170 facts, 76 passages.

| variant | F1 | precision | recall | passages | scenarios | target | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| xlsx | 0.83 | 0.82 | 0.83 | 5% | n/a | F1 >= 0.9 | FAIL |
| eml | 0.93 | 0.92 | 0.94 | 50% | n/a | F1 >= 0.9 | PASS |
| pptx | 0.71 | 0.73 | 0.69 | 50% | n/a | F1 >= 0.9 | FAIL |

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

## Facts lost or changed: pptx (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('194i', 'tds_deduction.rent_building_rate', 'all', 10.0)
- ('194i', 'tds_deduction.rent_plant_machinery_rate', 'all', 2.0)
- ('194j', 'tds_deduction.professional_rate', 'all', 10.0)
- ('194j', 'tds_deduction.section_determination_basis', 'all', 'fees for technical services not professional including software support fall under section 194j')
- ('194j', 'tds_deduction.technical_services_rate', 'all', 2.0)
- ('aato bands for irn requirement', 'aato_bands.recorded_at_creation_reviewed_april', 'all', 'recorded at creation and reviewed every april')
- ('dup suspect', 'exception_handling.exception_code_meaning', 'all', 'possible duplicate 3.3')
- ('dup suspect', 'exception_handling.exception_code_owner', 'all', 'senior processor')
- ('duplicate invoice check', 'duplicate_check.match_criteria', 'all', 'supplier gstin and normalised number match or supplier invoice date and total amount within rs 1 match')
- ('exception codes and resolution targets', 'exception_handling.codes', 'all', 'gstin inactive')
- ('exception codes and resolution targets', 'exception_handling.dup_suspect_routing', 'all', 'cleared by a senior processor')
- ('exception codes and resolution targets', 'exception_handling.tax_desk_referral_codes', 'all', 'tds section unclear and rcm review')
- ('grn posting timeline', 'grn_posting_timeline.grn_missing_action', 'all', 'hold it as no grn and notify the requester automatically')