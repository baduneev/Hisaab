# Launch readiness

## Delivered and locally verified

The repository contains the operational accounting MVP, React interface, PostgreSQL migrations, server-side tenant/role checks, accounting guard triggers, imports, bank matching, reports, PDF generation, evidence-based insights, optional AI provider support, durable jobs, encrypted backup tooling, CI, and local/Docker launch configuration.

The implementation has been exercised against PostgreSQL with isolated test databases, including same-key concurrent requests, competing stock withdrawals, linked returns, weighted-average costs, penny rounding, pack conversion, period locks, fiscal rollover, historical valuation, allocations, provider outages, and tenant access. See the handoff’s verification results for the exact latest counts. Browser and PDF artifacts are generated locally under ignored output folders.

## External requirements still outstanding

| Requirement | Status | Exit evidence |
|---|---|---|
| Five target wholesaler interviews | Not performed | Document actual receiving/billing/collection workflows, pack units, volume, and accountant handoff |
| Nepal accountant review | Not performed | Signed-off account mapping, openings, valuation, returns, corrections, statements, and monthly close |
| Current IRD procedure and enlistment | Not verified | Applicable 2082 procedure, current notices, software/vendor listing process, invoice fields and numbering rules |
| CBMS contract and test credentials | Not available | Official current API specification, authenticated sandbox results, idempotent reporting policy and failure handling |
| Production tax invoice issuance | Disabled | Reviewed implementation, applicable approvals, accountant acceptance, and successful official integration tests |
| Production TLS, secrets, backup scheduling and off-device retention | Configuration supplied; deployment not performed | Verified HTTPS origin, secure cookies, separately managed keys, scheduled encrypted backups and restore evidence |
| Three-customer supervised pilot | Not performed | Reconciled opening balances and one completed monthly close against existing books |

Official starting points: [IRD CBMS technical documentation](https://ird.gov.np/content/9052/cbmsapitechnicaldocumentfor/) and [IRD electronic billing notice](https://ird.gov.np/content/13488/notice-regarding-electrical-appliances/). Both document endpoints timed out during this build. No API field mapping, turnover threshold, or compliance approval was inferred from that failure.

The application intentionally refuses startup if `TAX_BILLING_ENABLED=true`. Internal PDFs carry an explicit tax-billing limitation. The current supplier-bill workflow settles a full goods receipt without input VAT; live VAT business use is outside the verified release.

## Review points for the pilot

- Use general non-perishable goods, one legal company per tenant, NPR, and online posting. Verify the actual operating volumes before setting performance targets.
- Reconcile opening stock with the inventory control ledger and exclude inventory from the separate opening journal.
- Have the accountant review purchase returns after cost changes and the v1 restriction on billing a receipt after an unbilled return.
- Check the distinction between a cash movement summary and statutory cash flow reporting, and between net contact balances and invoice aging after advances or credits.
- On real hosting, add account verification, password recovery, shared rate limiting if scaling beyond one worker, and appropriate employee offboarding controls. Initial password distribution needs a secure process.
- Confirm cloud location, retention obligations, BS calendar range, invoice print layouts, and bilingual terminology with the accountant and the customers.
- AI recommendations remain reviewable hypotheses. Do not enable model-directed posting, arbitrary SQL, raw customer-data prompts, or unsupported forecasts.
