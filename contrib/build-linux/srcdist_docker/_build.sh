#!/bin/bash

set -e

PROJECT_ROOT="$(dirname "$(readlink -e "$0")")/../../.."
CONTRIB="$PROJECT_ROOT/contrib"
DISTDIR="$PROJECT_ROOT/dist"

. "$CONTRIB"/base.sh

rm -fvr "$DISTDIR"
mkdir -p "$DISTDIR"

python3 --version || fail "No python"

pushd $PROJECT_ROOT

python3 -m venv env
source env/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install --upgrade setuptools
python3 -m pip install --upgrade requests

contrib/make_linux_sdist

popd
