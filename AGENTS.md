# Working on Crycon

- Read README.md and docs/AUDIT.md before changing the pipeline. Inspect callers.
- Preserve root CLI entry points and compatibility imports. Install with
  `python -m pip install -r requirements-dev.txt` before checking them.
- Keep scoring, normalization and deduplication pure in src/crycon. No network,
  database, credentials or environment reads in those modules.
- Keep both named scoring policies unless explicitly changing them. A formula
  change requires a version, explanation, boundary/regression tests and a decision
  about existing stored scores. Do not silently unify enrichment/recalculation.
- Environment access belongs in crycon.config. Never add another dotenv parser.
- Never print, copy into fixtures, commit or reuse credentials from .env/history.
  All historically tracked credentials are considered compromised.
- Do not run network/DB integration commands with real credentials as unit tests.
  `test_supabase_connection.py` writes a row; it is manual, not a pytest test.
- Use tests/ with synthetic fixtures and fake adapters. Keep the network guard.
- Schema changes belong in new numbered migrations. Do not edit already-applied
  migrations to change existing databases. Never auto-apply to production.
- Do not push, force-push, rewrite history, rotate external credentials, or deploy
  without an explicit request authorizing that action. This foundation is local.
- Preserve user changes and staging; do not reset or discard an existing checkout.
- Do not add React, broad service rewrites or speculative abstractions to core work.
- Run `python -m compileall -q src tests *.py`, `python -m pytest -q`, and
  `python -m pip check`; report failures and any unverified integration behavior.
- Never show an unfiltered Git diff containing .env deletion: removed lines contain
  the old secrets. Exclude .env from review output and describe its deletion separately.
- Confidence is an estimate of public signal matches, not proof of identity,
  wallet ownership, wrongdoing, or an authorization decision.
