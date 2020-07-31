#!/bin/bash

here=$(dirname "$0")
test -n "$here" -a -d "$here" || (echo "Cannot determine build dir. FIXME!" && exit 1)

. "$here"/../../base.sh # functions we use below (fail, et al)

if [ ! -z "$1" ]; then
    REV="$1"
else
    fail "Please specify a release tag or branch to build (eg: master or 4.0.0, etc)"
fi

if [ ! -d 'contrib' ]; then
    fail "Please run this script form the top-level DeLight git directory"
fi

pushd .

docker_version=`docker --version`

if [ "$?" != 0 ]; then
    echo ''
    echo "Please install docker by issuing the following commands (assuming you are on Ubuntu):"
    echo ''
    echo '$ curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -'
    echo '$ sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"'
    echo '$ sudo apt-get update'
    echo '$ sudo apt-get install -y docker-ce'
    echo ''
    fail "Docker is required to build for Windows"
fi

set -e

info "Using docker: $docker_version"

SUDO=""  # on macOS (and others?) we don't do sudo for the docker commands ...
if [ $(uname) = "Linux" ]; then
    # .. on Linux we do
    SUDO="sudo"
fi


info "Creating docker image ..."
$SUDO docker build -t delight-srcdist-builder-img \
    contrib/build-linux/srcdist_docker \
    || fail "Failed to create docker image"

# This is the place where we checkout and put the exact revision we want to work
# on. Docker will run mapping this directory to /opt/delight
# which inside wine will look lik c:\delight
FRESH_CLONE=`pwd`/contrib/build-linux/fresh_clone2
FRESH_CLONE_DIR=$FRESH_CLONE/$GIT_DIR_NAME

(
    $SUDO rm -fr $FRESH_CLONE && \
        mkdir -p $FRESH_CLONE && \
        cd $FRESH_CLONE  && \
        git clone $GIT_REPO && \
        cd $GIT_DIR_NAME && \
        git checkout $REV
) || fail "Could not create a fresh clone from git"

mkdir "$FRESH_CLONE_DIR/contrib/build-linux/home" || fail "Failed to create home directory"

(
    # NOTE: We propagate forward the GIT_REPO override to the container's env,
    # just in case it needs to see it.
    $SUDO docker run $DOCKER_RUN_TTY \
    -e HOME="/opt/delight/contrib/build-linux/home" \
    -e GIT_REPO="$GIT_REPO" \
    --name delight-srcdist-builder-cont \
    -v $FRESH_CLONE_DIR:/opt/delight \
    --rm \
    --workdir /opt/delight/contrib/build-linux/srcdist_docker \
    -u $(id -u $USER):$(id -g $USER) \
    delight-srcdist-builder-img \
    ./_build.sh $REV
) || fail "Build inside docker container failed"

popd

info "Copying built files out of working clone..."
mkdir -p dist/
cp -fpvR $FRESH_CLONE_DIR/dist/* dist/ || fail "Could not copy files"

info "Removing $FRESH_CLONE ..."
$SUDO rm -fr $FRESH_CLONE

echo ""
info "Done. Built SrdDist archives (.tar.gz, .zip) have been placed in dist/"
