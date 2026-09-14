# Security notes

This is a qualification tool, not a system of record. Do not submit confidential client, site, utility, pricing, or ownership information.

The application has no database, wallet, key, payment integration, shell execution, remote download, or outbound network client. It does not persist request data.

The provided Compose profile is a local starting point: loopback-only port binding, read-only root filesystem, a small non-executable temporary filesystem, dropped Linux capabilities, `no-new-privileges`, non-root UID, process limit, 1 GiB memory limit, and one CPU limit. It does not mount the Docker socket, host paths, or use host networking.

Before any public deployment, add HTTPS and authentication/rate limiting as appropriate, pin and review dependency hashes, set a real reviewed Git commit, scan the image and dependencies, and confirm that submitted examples contain no confidential data.
