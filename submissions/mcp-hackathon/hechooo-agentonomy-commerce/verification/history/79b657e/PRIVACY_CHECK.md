# Source privacy checks

The current submission includes 733 source files exported from the exact Git commit in submission.json. The application change replaced 67 occurrences of a personal sample identifier across 18 files with `telegram_demo_user`. A byte-level comparison verified that the source change consists only of those literal replacements.

Targeted scans of the tracked source and final submission artifact found no confirmed live credentials, private key material, customer records, personal workstation paths or private production connection configurations. Test fixtures, documented example endpoints and public chain addresses were reviewed separately from actual runtime material. Runtime state, private deployment configuration and credentials are excluded from the package.

This is a targeted current-snapshot check, not a history rewrite or comprehensive security audit. It does not claim that prior Git commits were deleted. The support email in the outer submission was explicitly supplied for public contact.
