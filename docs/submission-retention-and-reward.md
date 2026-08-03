# Submission retention and reward release policy

## Non-negotiable rule

X-Agent does not issue a reward because a demo worked once or because an external repository existed at review time. Reward eligibility begins only after the complete reviewed source is merged into this official repository and sealed in a published immutable release.

Closing a pull request before merge is a withdrawal. Deleting a fork, branch, deployment, or external source repository after merge does not remove the official copy or the sealed acceptance package.

## Updates are additive, not destructive

- Before acceptance, a submitter may push updates to the same PR. Every validated PR head is copied to a new official archive ref; an earlier archived version is never overwritten.
- Every push reruns the hard gates and dismisses stale approval. Reviewers score and approve the latest exact PR head, not the project name or a moving branch.
- X-Agent merges only after the latest head passes verification and receives approval. There is no need to race the submitter to merge.
- After acceptance or payment, fixes and upgrades use a new PR and a new immutable release. The reward remains bound to the original acceptance receipt and source archive.

## Preservation layers

1. **Validated PR archive ref.** After the automated hard gates pass, the exact PR head commit is copied into a unique `submission-archive/pr-<number>-<sha>` branch in the official repository. Synchronizing the PR creates another ref instead of replacing the previous one.
2. **Official main-branch copy.** Accepted source is merged under `submissions/mcp-hackathon/<slug>/`. Main blocks deletion and force pushes and requires changes to arrive through a pull request.
3. **Immutable acceptance release.** Before payment, maintainers run `Seal accepted submission before reward`. It validates the merged project again, creates a full source archive and an acceptance receipt containing Git tree and SHA-256 hashes, and publishes both in an immutable GitHub Release.
4. **Independent backup.** Program operations must mirror published acceptance releases to X-Agent-controlled storage or a second controlled repository. The mirror location and restore test are internal operational records. A reward must not be sent if this backup check is incomplete.

## Reward gate

The reward operator verifies all of the following before payment:

- the submission PR is merged, not merely open or approved;
- the merged directory contains the complete reviewed source and rights declaration;
- automated online validation passes on the merged copy;
- the official archive ref exists;
- the immutable acceptance release is published and its source archive hash matches the receipt;
- the independent backup is confirmed;
- the final review decision and recipient identity are recorded.

The payment record references the immutable release URL and acceptance-receipt hash. Corrections produce a new release and receipt; an earlier acceptance package is never silently replaced.

## Rights and exceptional removal

Program terms must grant X-Agent the continuing right to retain, reproduce, audit, and publish the submitted program artifact for judging, fraud prevention, dispute handling, and post-award accountability. This clause must be reviewed by qualified counsel for the event's governing law.

If source contains exposed secrets, personal data, malware, or material that X-Agent is legally required to remove, maintainers quarantine access and preserve hashes, decision records, and the legally permitted audit trail. This is an incident process, not a silent deletion or history rewrite.
