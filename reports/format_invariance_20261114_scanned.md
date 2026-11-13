# Format invariance — 14 Nov 2026 00:15

Baseline: original .docx, 170 facts, 76 passages.

| variant | F1 | precision | recall | rule F1 | passages | scenarios | target | pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| scanned | 0.90 | 0.93 | 0.88 | 0.94 | 47% | 100% | F1 >= 0.8 | PASS |

## Facts lost or changed: scanned (first 15)

- ('194c', 'tds_deduction.contractor_rate_individual', 'all', 1.0)
- ('194c', 'tds_deduction.contractor_rate_other', 'all', 2.0)
- ('194i', 'tds_deduction.rent_building_rate', 'all', 10.0)
- ('194i', 'tds_deduction.rent_plant_machinery_rate', 'all', 2.0)
- ('194j', 'tds_deduction.professional_rate', 'all', 10.0)
- ('194j', 'tds_deduction.section_determination_basis', 'all', 'fees for technical services not professional including software support fall under section 194j')
- ('194j', 'tds_deduction.technical_services_rate', 'all', 2.0)
- ('duplicate invoice check', 'duplicate_check.flag_action', 'all', 'dup suspect')
- ('duplicate invoice check', 'duplicate_check.lookback_months', 'all', 18.0)
- ('duplicate invoice check', 'duplicate_check.match_criteria', 'all', 'supplier gstin and normalised number match or supplier invoice date and total amount within rs 1 match')
- ('duplicate invoice check', 'duplicate_check.normalisation_rules', 'all', 'remove spaces slashes hyphens and leading zeros and drop a trailing suffix of a r or rev')
- ('exception codes and resolution targets', 'exception_handling.dup_suspect_routing', 'all', 'cleared by a senior processor')
- ('invoice approval authority', 'invoice_approval_authority.exceptions_cleared_by_senior_processor_threshold', 'all', 'up to rs 10 lakh')
- ('irn requirement', 'irn_requirement.effective_date', 'all', '1 apr 2026')
- ('price var', 'exception_handling.price_var_resolution_process', 'all', 'a line that fails the price tolerance is held with exception price var and sent to the buyer who raised the po the buyer either amends the po or asks the supplier for a credit note.')