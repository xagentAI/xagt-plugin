#!/bin/sh
# Stable release entrypoint. The installer verifies the payload before this
# script can be used; no user-controlled shell text is interpreted.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
release_root=${CLINK_RELEASE_ROOT:-}

if [ -z "$release_root" ]; then
	probe=$script_dir
	while [ "$probe" != "/" ]; do
		if [ -L "$probe/current" ] && [ -d "$probe/versions" ]; then
			release_root=$probe
			break
		fi
		probe=$(dirname -- "$probe")
	done
fi

if [ -z "$release_root" ] || [ ! -L "$release_root/current" ]; then
	echo "clink-launcher: installed release is unavailable" >&2
	exit 1
fi

release_root=$(CDPATH= cd -- "$release_root" && pwd -P)
current_release=$release_root/current
python_runtime=$current_release/payload/runtime/bin/python3
runtime_root=$current_release/payload/app
if [ ! -x "$python_runtime" ]; then
	echo "clink-launcher: verified Python runtime is unavailable" >&2
	exit 1
fi
if [ ! -d "$runtime_root" ]; then
	echo "clink-launcher: verified application root is unavailable" >&2
	exit 1
fi

export CLINK_RELEASE_ROOT=$release_root
export CLINK_RUNTIME_ROOT=$runtime_root
export CLINK_HOME=${CLINK_HOME:-${HOME:?}/.clink}
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PATH=$current_release/payload/runtime/bin${PATH:+:$PATH}
export PYTHONPATH=$runtime_root/apps/node:$runtime_root/apps/core

exec "$python_runtime" -m clink_node "$@"
