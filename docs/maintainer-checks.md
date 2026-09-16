# Single-maintainer merge checks

Changes to `main` must go through a pull request. The active repository rules
require the `Repository checks` check from GitHub Actions to pass against the
latest base branch, prohibit force pushes and branch deletion, and require review
conversations to be resolved. A second person's approval is not required.
The maintainer reviews the diff and merges manually; passing CI is not an
independent security review.

`repository-checks.yml` runs lint, the package test suite, and the build on Node 24
for all pull requests targeting `main`. There is no path filter that could leave
the required check permanently pending. The job uses a hosted runner, read-only
repository permission, no configured secrets, pinned action commits, a lockfile,
and dependency installation with lifecycle scripts disabled. Checkout credentials
are not persisted. `submissions/` is excluded from the working directory and its
absence is checked before installing dependencies or executing package code.
The job also checks dependencies against npm's advisory database and fails for
known moderate-or-higher vulnerabilities. This is a point-in-time advisory check,
not proof that a dependency is safe; advisory service failures also block the job.

The separate submission-validation workflow still checks submission source,
commit, and deployment proof without executing submitted projects. Repository CI
passing does not establish that a submitted API works or that an entry is eligible.
Check that submission's validation result before merging it.

Review changes to workflows, dependencies, package scripts, and test configuration
carefully: CI executes the proposed package code, and a workflow change can alter
the checks themselves. Automatic checks cannot protect against every malicious
change or a compromised maintainer account.

After this workflow first merges, existing PRs need to update to the latest `main`
and trigger validation again before they can satisfy the new required check.
