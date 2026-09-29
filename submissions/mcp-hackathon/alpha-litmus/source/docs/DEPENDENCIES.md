# Dependency Release Tools

## Locks

`requirements.in` holds runtime bounds. `requirements-dev.in` includes those
inputs and constrains every shared package to `requirements.txt`. The two `.txt`
files are the standard pip-tools transitive SHA-256 locks; no duplicate `.lock`
files are needed. Install runtime alone for production or the complete dev lock
for development. Both are valid pip requirements and pip-audit inputs.

Generated with CPython 3.12.10 on Windows AMD64, pip-tools 7.6.1 and pip 25.0.1.
Tooling is isolated in `tools/__pycache__/release-venv`; global application
dependencies were not changed. To recreate that environment with Python 3.12:

```powershell
python -m venv tools/__pycache__/release-venv
tools/__pycache__/release-venv/Scripts/python.exe -m pip install pip-tools==7.6.1 pip-audit==2.10.1
tools/__pycache__/release-venv/Scripts/python.exe -m piptools compile --generate-hashes --resolver=backtracking --strip-extras --output-file=requirements.txt requirements.in
tools/__pycache__/release-venv/Scripts/python.exe -m piptools compile --generate-hashes --resolver=backtracking --strip-extras --output-file=requirements-dev.txt requirements-dev.in
python -m pip install --require-hashes -r requirements.txt
```

Compile runtime before dev. Existing pins are reused; add `--upgrade` to both
compile commands for an intentional refresh, then review both locks, regenerate
the inventory and run tests/audit. Never hand-edit generated hashes. Hashes
authenticate selected artifacts, not their safety. Source builds may use build
dependencies outside these locks; use `--only-binary=:all:` to require wheels.

### Platform Limits

pip-compile evaluates transitive markers on its host. These are Windows-resolved
locks, not an assertion of cross-OS reproducibility. MCP's Windows-only pywin32
dependency is explicitly marked `sys_platform == "win32"` in the input so Linux
does not attempt to install it. Other host-selected dependencies can remain
unconditional (for example dev colorama), and foreign-platform-only dependencies
can be absent. Hash lists covering multiple wheels do not prove graph parity.

Docker now requires hashes, but its Linux Python 3.12 installation/build must
still be verified on Linux. Before a Linux release, compile on the intended
Linux architecture/Python with the same inputs, compare the dependency graph,
and maintain a separate platform lock if it differs. Do not silently replace
Windows pins or remove hash enforcement to make a build pass. The existing
`python:3.12-slim` tag is mutable; a hash lock does not pin the container OS.

## License Evidence

Download wheels without installing application dependencies, then generate:

```powershell
tools/__pycache__/release-venv/Scripts/python.exe -m pip download --require-hashes --only-binary=:all: --dest tools/__pycache__/release-wheels -r requirements-dev.txt
python tools/license_inventory.py --wheels tools/__pycache__/release-wheels
```

Use a fresh wheel directory after updates (stale/duplicate wheels are rejected).
The inventory reads actual `*.dist-info/METADATA` from downloaded wheels. It
requires each observed name/version and artifact SHA-256 to match every supplied
lock, requires all pins to have evidence, and records lock digests, artifact
filenames, hashes and metadata member paths. It inventories downloaded versions,
not the possibly different global installed environment. Default scope is the
union of runtime/dev pins; Windows is needed to download the Windows-only pin
with these commands. No source package code is executed by the generator.

License expression, raw License field, license classifiers, homepage and project
URLs are copied from metadata. Absent textual values are `UNKNOWN`; an empty
classifier list means none were supplied. Legacy license prose is not converted
to an invented SPDX expression. Metadata is publisher evidence, not legal
verification of the wheel contents. This inventory makes no claim about the
project's license, ownership or rights, and does not replace legal review.

## Secret Scan

```powershell
python tools/secret_scan.py
python -m pytest tests/test_release_tools.py -q
tools/__pycache__/release-venv/Scripts/python.exe -m pip_audit -r requirements.txt
```

The scanner is offline and emits only JSON `rule`, relative `path`, and `line`;
never source text or matched values. Exit 0 means no findings within scope; exit
1 means findings or coverage errors. It detects long Nexus key-shaped tokens,
private-key headers and high-specificity literal secret assignments. Tests
construct synthetic tokens at runtime; no captured secrets or snapshots exist.

Scope: UTF-8 text, at most 1 MiB per file and 20,000 candidate files. Oversized
files, file-count overflow and read errors fail closed with location-only rules.
Binary/NUL-containing or non-UTF-8 files, symlinks/junction directories, caches,
virtualenvs, node_modules, docs, public/catalog/image directories, common image
extensions/PDF/fonts, `nexus-docs.txt`, generated license inventory, `.lock` files
and `requirements*.txt` hash locks are excluded. `.env` files and source/tests
are scanned. Excluded documentation/assets require separate review. This is a
bounded heuristic, not a guarantee of no credentials: short, encoded, split,
unrecognized or placeholder-looking secrets may be missed.

pip-audit is available in the isolated tooling environment for the parent release
gate. It queries package vulnerability services, not Nexus. No live Nexus calls
are needed for any command above.
