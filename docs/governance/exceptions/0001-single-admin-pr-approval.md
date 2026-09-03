# Exception 0001: Single-admin pull request approval

## Status

The standing single-admin exception is no longer applicable. Its historical terms are retained below. The one-time authorization for PR #36 is recorded separately at the end of this document.

Original validity: 2026-08-03 through 2026-11-01, or until a second trusted maintainer receives write access, whichever happens first.

## Rule and scope

The engineering baseline requires the default branch to require review. This exception applies only to the minimum approving-review count and last-pusher approval requirement for `xagentAI/xagt-plugin:main`.

All changes must still arrive through pull requests. Branch deletion protection, force-push protection, required conversation resolution, automated submission validation, official archive refs, and immutable acceptance releases remain enabled.

## Owner and approver

- Owner: `@lessthanno`, repository administrator
- Approver: `@lessthanno`, repository administrator and sole current maintainer

## Business justification

The repository currently has one administrator with write access. Requiring an approval from another writer makes every legitimate pull request impossible to merge, including security and program-operation changes.

## Risk

The sole administrator can merge a pull request without independent human review. A compromised administrator account or mistaken judgment therefore has no second-person approval barrier.

## Compensating controls

- Direct changes to `main` remain prohibited; every change has a durable pull request record.
- Deletion and non-fast-forward updates remain prohibited.
- Submission code is validated without executing participant source in privileged CI.
- Accepted and rewarded submissions are bound to commit hashes, archive refs, acceptance receipts, immutable releases, and an independent backup gate.
- The administrator must review the final PR head and available automated evidence before merge.
- Repository administration must use strong authentication and GitHub two-factor authentication.

## Removal

When a second trusted maintainer receives write access, restore:

```json
{
  "required_approving_review_count": 1,
  "require_last_push_approval": true
}
```

The owner must review this exception no later than 2026-11-01 and either remove it or create a newly justified, time-bounded replacement.

## One-time authorization: PR #36

- **Scope:** Only [PR #36](https://github.com/xagentAI/xagt-plugin/pull/36), containing implementation commit `d476c7dde3b564aab3cd3a9385a063ff54162391` and this authorization record. It permits accountable maintainer approval in place of a separate maintainer review for this merge; it does not waive technical checks or change repository protection settings.
- **Owner and approver:** `@lessthanno`, repository administrator, explicitly authorized this one-time merge on 2026-09-03.
- **Reason:** Deliver the current event's submission-workflow improvements under the maintainer's direct approval.
- **Risk:** There is no independent second-maintainer review of this change. This authorization is not a claim that such a review occurred.
- **Mitigation:** Preserve the PR and merge history, require the existing code checks, 79 regression tests, and build to pass, retain the documented recovery procedure, and do not operate participant PRs as rollout tests. Live workflow verification remains a separate, explicitly authorized step.
- **Expiry and removal:** Consumed by the merge of PR #36 or expires at 2026-09-04 00:00 UTC, whichever comes first. Retain this record for audit; it grants no permission for subsequent changes, npm publication, acceptance releases, or reward payments.
