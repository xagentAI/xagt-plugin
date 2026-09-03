# Proof model

Global claims require global coverage. For NONE/ALL/EXACT_COUNT/MIN/MAX the gate
checks: SCOPE_STABLE (filter hash unchanged), NO_UNRESOLVED_FAILURES,
RESULT_SET_COMPLETE (last page has_more=false), NO_CURSOR_GAPS (chain/loop/dup
checks), SNAPSHOT_ACCEPTABLE (STRICT: any change blocks; BEST_EFFORT yields
CONDITIONAL), plus type-specific checks (count match, zero matches, candidate is
true extreme over observed field values). Missing snapshot info is a warning,
not a block. Verdicts are pure functions of ledger state — rerunning the same
evidence always yields the same verdict.
