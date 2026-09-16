# Submission retention and reward release policy

This policy covers the current MCP Hackathon under `submissions/mcp-hackathon/`. Historical activity directories are not reprocessed. Start with the [submission instructions](../submissions/README.md) for required files and the [event rules](mcp-hackathon.md) for participation requirements.

## What each status means

| Status | Meaning | What it does not mean |
| --- | --- | --- |
| Submission received | The official repository received the PR. One English receipt is posted. | The entry has not been declared complete, eligible, approved, or awarded. |
| Automated checks passed | The inspected version passed the listed packaging, source-version, and deployment-evidence checks. | The code has not been fully audited or proven reproducible. This is not a judging result. |
| Source archived | The exact checked version has an official preservation reference. | Archiving does not approve, merge, rank, or award the entry. |
| Source merged | Maintainers have incorporated the source into the official repository. | A merge for preservation is not, on its own, eligibility approval or an award. |
| Review decision recorded | Reviewers have explicitly recorded their decision and its scope. | An eligibility or technical decision alone does not establish the final ranking or authorize payment. |
| Acceptance release sealed | A maintainer has published an immutable source package with a recorded final decision. | The workflow does not send rewards or verify an independent backup. |

The repository does not automatically approve, merge, close, or score participants' PRs. Workflow summaries report checks separately from human decisions. A failed workflow is not a rejection; if it fails before inspecting the entry, there is no validation result to infer.

## Non-negotiable rule

X-Agent does not issue a reward because a demo worked once or because an external repository existed at review time. Reward eligibility begins only after the complete reviewed source is merged into this official repository and sealed in a published immutable release.

Closing a pull request before merge is a withdrawal. Deleting a fork, branch, deployment, or external source repository after merge does not remove the official copy or the sealed acceptance package.

## Updates are additive, not destructive

- Before acceptance and while submissions remain open, a submitter may push updates to the same PR. Each version is checked again. A successfully rechecked current PR head gets its own official archive ref; an earlier archived version is never overwritten. Superseded or closed PR heads are skipped, not reported as archived.
- A push triggers new automated checks. Stale review approvals are dismissed only when that repository protection is configured. Reviewers score and approve an exact commit, not the project name or a moving branch.
- Any merge requires a maintainer decision after checking the latest version. State whether the merge is for preservation or follows a recorded review decision; the merge itself must not be presented as a prize decision.
- After acceptance or payment, fixes and upgrades use a new PR and a new immutable release. The reward remains bound to the original acceptance receipt and source archive.

## Source must be included, not merely linked

Include the actual implementation under `source/`, along with dependency manifests and applicable lockfiles, configuration examples without secrets, and setup/build/run instructions. Explain what each external API or private service does. A README, Git submodule, symbolic link, Git LFS pointer, compiled bundle, or external repository URL alone is not a retained source copy.

The source scan is deliberately limited. It checks file types, size limits, a baseline set of secret patterns, and whether implementation files are present. It cannot establish that every necessary file is included, that a private dependency is acceptable, or that the deployment was built from the declared commit. A public health response that names a commit is evidence to inspect, not cryptographic build provenance.

Before recording a final technical decision, reviewers must check that the source in the PR corresponds to the declared version, can be built and run using the documented dependencies, and covers the submitted capability. Reviewers must also assess ownership and declared rights, external/private dependencies, security, and the event's eligibility criteria. Run participant code only in a separately isolated review environment without repository credentials. The repository automation never installs participant dependencies or executes their code.

## Preservation layers

1. **Validated PR archive ref.** A successful `pull_request` check triggers a separate, official `workflow_run` task. That task independently rechecks the current PR using the official validator before creating `submission-archive/pr-<number>-<full-40-character-head-sha>`. It does not trust an uploaded artifact or a success flag alone. It never replaces an existing ref. Older 12-character ref names are read only for compatibility during sealing.
2. **Official main-branch copy.** Accepted source is merged under `submissions/mcp-hackathon/<slug>/`. Main blocks deletion and force pushes and requires changes to arrive through a pull request.
3. **Immutable acceptance release.** Before payment, maintainers run `Seal accepted submission before reward`. It validates the merged project again, creates a full source archive and an acceptance receipt containing Git tree and SHA-256 hashes, and publishes both in an immutable GitHub Release.
4. **Independent backup.** Program operations must mirror published acceptance releases to X-Agent-controlled storage or a second controlled repository. The mirror location and restore test are internal operational records. A reward must not be sent if this backup check is incomplete.

The workflows do not provision branch protections or independent storage. An archive job succeeds only after the official ref can be read back at the expected commit. If GitHub permissions or source availability prevent creation, the job fails; it does not silently claim the code was preserved. Archive refs must block updates, deletion, and force pushes. Release immutability is checked before publishing the acceptance release. An immutable release in the same GitHub repository is not an independent backup.

Sealing verifies that the selected merged PR belongs to the requested project and that the archived, merged, and release copies of the project have identical Git trees. It records the actual merge commit separately from the release commit. Once the official archived copy exists, sealing does not depend on the participant's external repository remaining available; the existing live-service evidence requirements still apply.

## If a check fails

| Message or symptom | Who should act | Next step |
| --- | --- | --- |
| Missing files, inconsistent commit or deployment evidence, or a change outside the project directory | Submitter | Correct the same PR while submissions remain open. Follow the file-specific error and submission instructions. |
| Potential secret or unsupported source pointer | Submitter and maintainer | Do not paste credentials into a comment. Replace pointers with actual source. If a real credential was exposed, revoke it and notify maintainers; deleting the latest line alone does not remove it from history. |
| Checkout refusal, token permission failure, or runner/API failure | Maintainer | Inspect the workflow failure. Do not describe it as a failed judging decision or ask the submitter to bypass GitHub protections. |
| PR changed during inspection | Submitter or maintainer | Use the latest version's run. An old successful run cannot establish the status of the new code. |
| Archive or release cannot be verified | Maintainer | Keep the status incomplete. Inspect permissions and the exact commit; never overwrite an existing archive to make a run pass. |

Existing valid receipts are reused, including receipts already posted by maintainers. The automation does not repeatedly comment on every push. Detailed check results appear in the workflow summary instead.

## Maintainer rollout and verification

Before enabling this change, run `npm run lint`, `npm test`, and `npm run build`, and review the workflow permissions. Publish repository changes only after authorization. Code checked locally is not a deployed GitHub workflow.

After the reviewed change reaches the default branch, use a separately authorized test submission to verify the real GitHub behavior: one receipt, successful read-only checks, an exact archive ref, no duplicate receipt after another push, and no stale archive after a superseding update. Include an intentionally invalid package to confirm that it cannot produce a successful archive. Do not use an existing participant PR as a test without permission.

A rerun of an old `pull_request_target` failure can still use the old workflow definition. Verify a fresh `pull_request` event after the updated default branch is available; do not enable `allow-unsafe-pr-checkout` to repair an old run. GitHub may require a maintainer to approve a first-time contributor's workflow run under the repository's Actions policy. The receipt is separate from that approval.

The manual sealing workflow is a separate operation. Test its source checks locally; publishing an actual acceptance release requires a real recorded review decision and explicit authorization. Verify immutable-release settings, protected archive refs, and an independent backup/restore check before relying on the full retention process for rewards.

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
