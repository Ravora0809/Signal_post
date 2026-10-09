# Signalpost history-tracking fix

This patch changes:
- `signalpost/phases/p6_change_detection.py`: compares canonical typed values and no longer infers a deletion from missing extraction output.
- `signalpost/phases/p8_registry_import.py`: records first-seen additions, seeds transparent `baseline` records for older profiles without history, and records actual old/new changes during official Brreg CSV imports. It also retires the old verified value so only one current value remains published.
- `signalpost/phases/p9_evaluation.py`: baseline/initial-added records do not falsely earn the extra update-performance credit; valid `changed`/`removed` events are required.
- `tests/test_history_tracking.py`: tests numeric comparisons, no false removal, import history, and honest update scoring.

## Apply to an existing checkout

1. Back up your working tree and database first.
2. Copy the included `signalpost/` and `tests/test_history_tracking.py` into your existing project root, preserving folders. The patch does not include `.env` or a database file.
3. Run:

   ```bash
   python -m compileall -q signalpost tests
   pytest -q tests/test_change_detection.py tests/test_history_tracking.py tests/test_validation_conflict.py
   ```

4. Re-import the official registry CSV (or research a company) to initialize missing baseline history and track actual future changes.
5. Check a company's ledger at `GET /companies/{orgnr}/history`.
6. Re-run `POST /evaluate?sample_size=100`.

`baseline` means “state first observed when history tracking was enabled,” not a claim that the fact changed. A same-value refresh should not add a change event. A changed authoritative value should add a `changed` row with distinct `old` and `new` values.


## Follow-up correction: source/schema reconciliation

- The registry importer now marks a differing value as `changed` only when the old and new observations both came from `brreg_csv`. Cross-source differences (for example, a previous API-derived multi-activity industry string compared with the CSV primary-industry label) are recorded as `reconciled`, not claimed as a real-world update.
- The history API includes a `meaning` field and a `type_meanings` legend so `added`, `baseline`, `reconciled`, `changed`, and `removed` are not confused.
- `debt` was removed as an extraction/validation key in favor of `total_liabilities`. Run `python migrate_history_semantics.py` once after backing up the database to normalize legacy facts/history and conservatively reclassify historical cross-source `changed` events when the corresponding source records establish that they came from different source kinds.
- Regression coverage includes a cross-source industry-label difference and confirms a later same-feed employee-count change is still recorded as a true `changed` event.
