# Rights and authorization

## Ownership

All implementation in `source/` was written for this submission by the Agent3
team. The repository is `https://github.com/agent3-666/agent3-handshake` at commit `2571a1be25c6595d871b060c510767dd0ed0ce84`.

## License

MIT, as stated in `source/LICENSE`. The event organizers may read, build, run
and deploy this source for review.

## Third-party dependencies

Two, both MIT licensed and pinned in `source/package.json`:

- `tsx` — runs the TypeScript sources directly, so there is no build artifact
  standing between the reviewed source and the running service.
- `typescript` — type checking.

No other runtime dependency. Everything else is the Node 20 standard library.

## External services

One outbound call, to the public Agent3 registry listing. It is read-only,
unauthenticated, and serves a public directory. No credential is held by this
service and none is needed to review it.

## Authorization

The submitter is authorized to enter this work, to license it as above, and to
operate the deployed service at `https://agent3-handshake-production.up.railway.app` for the review period.

## Data

No personal data is collected, processed or stored. The only state is an
in-memory copy of a public listing, discarded and refreshed every 120 seconds.
