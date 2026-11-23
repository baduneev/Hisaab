# Local verification, 23 November 2026

| Check | Observed result |
|---|---|
| Complete PostgreSQL pytest suite | **38 passed**, using separately created `hisaab_test_*` databases |
| Playwright browser suite | **7 passed** in Chromium against Vite, then **7 passed against the built Docker application** |
| TypeScript and Vite production build | Passed |
| Docker multi-stage image build | Passed |
| Docker runtime | API and PostgreSQL healthy; standalone deep links and login passed; a queued insight job completed in the separate worker |
| Database migration | `003 (head)` |
| Per-company book monitoring | Journal balanced and stock/control account reconciled |
| Encrypted backup and restore | `release-003.enc` restored to a new `hisaab_restore_release003`; checksum, source counts, ledger totals, and inventory reconciliation matched |
| Bilingual PDF | Text extraction regression passed; final PDF rendered with Poppler and inspected visually |
| Desktop, mobile, and Nepali screen images | Captured and inspected; mobile collection queue fits the viewport |
| Design static checks | 0 failures; one primary-button recipe warning explicitly waived because neutral control surfaces are not competing primary actions |

The backend suite includes tenant/role isolation, denied posting-key replay, immutable posted records, denied balanced appends to posted journals, balanced journals, atomic rollback on stock errors, concurrent overselling, concurrent idempotency, full purchase/sale/collection/return reconciliation, supplier returns, original sale costs, pack conversion and penny rounding, period locks, backdated stock rejection, BS/AD and fiscal-year boundaries, historical valuation, advance allocation, CSV previews/commits, exact bank matching, PDF font coverage, provider outage fallback, AI prompt minimization, request caps, and job access rechecks.

The browser suite exercises contact creation and statements, English/Nepali mobile navigation, invoice recovery through reload and posting, reports and evidence links, offline draft recovery, screenshot capture without runtime crashes, and delayed warehouse data during draft restoration. An earlier sign-in routing failure, query-cache observer issue, and draft-loading race were reproduced and fixed before the passing run.

One test-framework deprecation warning remains: the installed Starlette test client warns about its `httpx` integration. It does not fail the suite. The Hallmark render tier could not run because `puppeteer-core` is unavailable; visual checks used actual Playwright screenshots and Poppler PDF renders instead.

AI integration tests use HTTP transport stubs. No live model result, production performance benchmark, statutory compliance approval, remote CI execution, or real customer pilot is claimed.

Generated screenshots, rendered PDFs, local database backups, and traces remain in ignored local output folders. The application’s real-data launch requirements are listed in [launch readiness](launch-readiness.md).
