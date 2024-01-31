#!/bin/bash

set -e

PROJECT_ROOT="$(dirname "$(readlink -e "$0")")/../../.."
CONTRIB="$PROJECT_ROOT/contrib"
DISTDIR="$PROJECT_ROOT/dist"
BUILDDIR="$CONTRIB/build-linux/appimage/build/appimage"
APPDIR="$BUILDDIR/DeLight.AppDir"
CACHEDIR="$CONTRIB/build-linux/appimage/.cache/appimage"
PYDIR="$APPDIR"/usr/lib/python3.8

# pinned versions
SQUASHFSKIT_COMMIT="ae0d656efa2d0df2fcac795b6823b44462f19386"
PKG2APPIMAGE_COMMIT="eb8f3acdd9f11ab19b78f5cb15daa772367daf15"


VERSION=`git describe --tags --dirty --always`
APPIMAGE="$DISTDIR/DeLight-$VERSION-x86_64.AppImage"

rm -rf "$BUILDDIR"
mkdir -p "$APPDIR" "$CACHEDIR" "$DISTDIR"


. "$CONTRIB"/base.sh

info "Refreshing submodules ..."
git submodule update --init

info "downloading some dependencies."
download_if_not_exist "$CACHEDIR/functions.sh" "https://raw.githubusercontent.com/AppImage/pkg2appimage/$PKG2APPIMAGE_COMMIT/functions.sh"
verify_hash "$CACHEDIR/functions.sh" "78b7ee5a04ffb84ee1c93f0cb2900123773bc6709e5d1e43c37519f590f86918"

download_if_not_exist "$CACHEDIR/appimagetool" "https://github.com/AppImage/AppImageKit/releases/download/12/appimagetool-x86_64.AppImage"
verify_hash "$CACHEDIR/appimagetool" "d918b4df547b388ef253f3c9e7f6529ca81a885395c31f619d9aaf7030499a13"

download_if_not_exist "$CACHEDIR/Python-$PYTHON_VERSION.tar.xz" "https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tar.xz"
verify_hash "$CACHEDIR/Python-$PYTHON_VERSION.tar.xz" $PYTHON_SRC_TARBALL_HASH



info "Building Python"
tar xf "$CACHEDIR/Python-$PYTHON_VERSION.tar.xz" -C "$BUILDDIR"
(
    cd "$BUILDDIR/Python-$PYTHON_VERSION"
    export SOURCE_DATE_EPOCH=1530212462
    LC_ALL=C export BUILD_DATE=$(date -u -d "@$SOURCE_DATE_EPOCH" "+%b %d %Y")
    LC_ALL=C export BUILD_TIME=$(date -u -d "@$SOURCE_DATE_EPOCH" "+%H:%M:%S")
    # Patch taken from Ubuntu python3.6_3.6.8-1~18.04.1.debian.tar.xz
    patch -p1 < "$CONTRIB/build-linux/appimage/patches/python-3.8.6-reproducible-buildinfo.diff" || fail "Could not patch Python build system for reproducibility"
    ./configure \
      --cache-file="$CACHEDIR/python.config.cache" \
      --prefix="$APPDIR/usr" \
      --enable-ipv6 \
      --enable-shared \
      --with-threads \
      -q || fail "Python configure failed"
    make -j 4 -s || fail "Could not build Python"
    make -s install > /dev/null || fail "Failed to install Python"
    # When building in docker on macOS, python builds with .exe extension because the
    # case insensitive file system of macOS leaks into docker. This causes the build
    # to result in a different output on macOS compared to Linux. We simply patch
    # sysconfigdata to remove the extension.
    # Some more info: https://bugs.python.org/issue27631
    sed -i -e 's/\.exe//g' "$PYDIR"/_sysconfigdata*
)

info "Building squashfskit"
git clone "https://github.com/squashfskit/squashfskit.git" "$BUILDDIR/squashfskit"
(
    cd "$BUILDDIR/squashfskit"
    git checkout -b pinned "$SQUASHFSKIT_COMMIT" || fail "Could not find squashfskit commit $SQUASHFSKIT_COMMIT"
    make -C squashfs-tools mksquashfs || fail "Could not build squashfskit"
)
MKSQUASHFS="$BUILDDIR/squashfskit/squashfs-tools/mksquashfs"

#info "Building libsecp256k1"  # make_secp below already prints this
(
    pushd "$PROJECT_ROOT"

    "$CONTRIB"/make_secp || fail "Could not build libsecp"

    popd
)

#info "Building libzbar"  # make_zbar below already prints this
(
    pushd "$PROJECT_ROOT"

    "$CONTRIB"/make_zbar || fail "Could not build libzbar"

    popd
)


appdir_python() {
  env \
    PYTHONNOUSERSITE=1 \
    LD_LIBRARY_PATH="$APPDIR/usr/lib:$APPDIR/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH+:$LD_LIBRARY_PATH}" \
    "$APPDIR/usr/bin/python3.8" "$@"
}

python='appdir_python'


info "Installing pip"
"$python" -m ensurepip


info "Preparing electrum-locale"
(
    cd "$PROJECT_ROOT"

    pushd "$CONTRIB"/electrum-locale
    if ! which msgfmt > /dev/null 2>&1; then
        fail "Please install gettext"
    fi
    for i in ./locale/*; do
        dir="$PROJECT_ROOT/lib/$i/LC_MESSAGES"
        mkdir -p $dir
        msgfmt --output-file="$dir/electron-cash.mo" "$i/electron-cash.po" || true
    done
    popd
)


info "Installing DeLight and its dependencies"
mkdir -p "$CACHEDIR/pip_cache"
"$python" -m pip install --no-warn-script-location --cache-dir "$CACHEDIR/pip_cache" -r "$CONTRIB/deterministic-build/requirements.txt"
"$python" -m pip install --no-warn-script-location --cache-dir "$CACHEDIR/pip_cache" -r "$CONTRIB/deterministic-build/requirements-binaries.txt"
"$python" -m pip install --no-warn-script-location --cache-dir "$CACHEDIR/pip_cache" -r "$CONTRIB/deterministic-build/requirements-hw.txt"
"$python" -m pip install --no-warn-script-location --cache-dir "$CACHEDIR/pip_cache" "$PROJECT_ROOT"


info "Copying desktop integration"
cp -fp "$PROJECT_ROOT/delight.desktop" "$APPDIR/delight.desktop"
cp -fp "$PROJECT_ROOT/icons/delight.png" "$APPDIR/delight.png"


# add launcher
info "Adding launcher"
cp -fp "$CONTRIB/build-linux/appimage/scripts/common.conf" "$APPDIR/common.conf" || fail "Could not copy python script"
cp -fp "$CONTRIB/build-linux/appimage/scripts/apprun.sh" "$APPDIR/AppRun" || fail "Could not copy AppRun script"
cp -fp "$CONTRIB/build-linux/appimage/scripts/python.sh" "$APPDIR/python" || fail "Could not copy python script"

info "Finalizing AppDir"
(
    export PKG2AICOMMIT="$PKG2APPIMAGE_COMMIT"
    . "$CACHEDIR/functions.sh"

    cd "$APPDIR"
    # copy system dependencies
    copy_deps
    move_lib

    # apply global appimage blacklist to exclude stuff
    # move usr/include out of the way to preserve usr/include/python3.6m.
    mv usr/include usr/include.tmp
    delete_blacklisted
    mv usr/include.tmp usr/include
) || fail "Could not finalize AppDir"

# We copy some libraries here that are on the AppImage excludelist
info "Copying additional libraries"

# On some systems it can cause problems to use the system libusb
cp -fp /usr/lib/x86_64-linux-gnu/libusb-1.0.so "$APPDIR"/usr/lib/x86_64-linux-gnu/. || fail "Could not copy libusb"

# Ubuntu 14.04 lacks a recent enough libfreetype / libfontconfig, so we include one here
mkdir -p "$APPDIR"/usr/lib/fonts/freetype
mkdir -p "$APPDIR"/usr/lib/fonts/fontconfig
cp -fp /usr/lib/x86_64-linux-gnu/libfreetype.so.6 "$APPDIR"/usr/lib/fonts/freetype/. || fail "Could not copy libfreetype"
cp -fp /usr/lib/x86_64-linux-gnu/libfontconfig.so.1 "$APPDIR"/usr/lib/fonts/fontconfig/. || fail "Could not copy libfontconfig"
cp -f "$CONTRIB/build-linux/appimage/scripts/test-freetype.py" "$APPDIR" || fail "Could not copy test-freetype.py"
cp -f "$CONTRIB/build-linux/appimage/scripts/test-fontconfig.py" "$APPDIR" || fail "Could not copy test-fontconfig.py"

# libfreetype needs a recent enough zlib
cp -f /lib/x86_64-linux-gnu/libz.so.1 "$APPDIR"/usr/lib/x86_64-linux-gnu || fail "Could not copy zlib"


info "Stripping binaries of debug symbols"
# "-R .note.gnu.build-id" also strips the build id
strip_binaries()
{
  chmod u+w -R "$APPDIR"
  {
    printf '%s\0' "$APPDIR/usr/bin/python3.8"
    find "$APPDIR" -type f -regex '.*\.so\(\.[0-9.]+\)?$' -print0
  } | xargs -0 --no-run-if-empty --verbose -n1 strip -R .note.gnu.build-id
}
strip_binaries

remove_emptydirs()
{
  find "$APPDIR" -type d -empty -print0 | xargs -0 --no-run-if-empty rmdir -vp --ignore-fail-on-non-empty
}
remove_emptydirs


info "Removing some unneeded files to decrease binary size"
rm -rf "$APPDIR"/usr/{share,include}
rm -rf "$PYDIR"/{test,ensurepip,lib2to3,idlelib,turtledemo}
rm -rf "$PYDIR"/{ctypes,sqlite3,tkinter,unittest}/test
rm -rf "$PYDIR"/distutils/{command,tests}
rm -rf "$PYDIR"/config-3.6m-x86_64-linux-gnu
rm -rf "$PYDIR"/site-packages/{opt,pip,setuptools,wheel}
rm -rf "$PYDIR"/site-packages/Cryptodome/SelfTest
rm -rf "$PYDIR"/site-packages/{psutil,qrcode,websocket}/tests
for component in connectivity declarative help location multimedia quickcontrols2 serialport webengine websockets xmlpatterns ; do
  rm -rf "$PYDIR"/site-packages/PyQt5/Qt/translations/qt${component}_*
  rm -rf "$PYDIR"/site-packages/PyQt5/Qt/resources/qt${component}_*
done
rm -rf "$PYDIR"/site-packages/PyQt5/Qt/{qml,libexec}
rm -rf "$PYDIR"/site-packages/PyQt5/{pyrcc.so,pylupdate.so,uic}
rm -rf "$PYDIR"/site-packages/PyQt5/Qt/plugins/{bearer,gamepads,geometryloaders,geoservices,playlistformats,position,printsupport,renderplugins,sceneparsers,sensors,sqldrivers,texttospeech,webview}
for component in Bluetooth Concurrent Designer Help Location NetworkAuth Nfc Positioning PositioningQuick PrintSupport Qml Quick Sensors SerialPort Sql Test Web Xml ; do

    rm -rf "$PYDIR"/site-packages/PyQt5/Qt/lib/libQt5${component}*
    rm -rf "$PYDIR"/site-packages/PyQt5/Qt${component}*
done
rm -rf "$PYDIR"/site-packages/PyQt5/Qt.so

# these are deleted as they were not deterministic; and are not needed anyway
find "$APPDIR" -path '*/__pycache__*' -delete
rm -rf "$PYDIR"/site-packages/*.dist-info/
rm -rf "$PYDIR"/site-packages/*.egg-info/


find -exec touch -h -d '2000-11-11T11:11:11+00:00' {} +


info "Creating the AppImage"
(
    cd "$BUILDDIR"
    chmod +x "$CACHEDIR/appimagetool"
    "$CACHEDIR/appimagetool" --appimage-extract
    # We build a small wrapper for mksquashfs that removes the -mkfs-fixed-time option
    # that mksquashfs from squashfskit does not support. It is not needed for squashfskit.
    cat > ./squashfs-root/usr/lib/appimagekit/mksquashfs << EOF
#!/bin/sh
args=\$(echo "\$@" | sed -e 's/-mkfs-fixed-time 0//')
"$MKSQUASHFS" \$args
EOF
    env VERSION="$VERSION" ARCH=x86_64 SOURCE_DATE_EPOCH=1530212462 \
                ./squashfs-root/AppRun --no-appstream --verbose "$APPDIR" "$APPIMAGE" \
                || fail "AppRun failed"
) || fail "Could not create the AppImage"


info "Done"
ls -la "$DISTDIR"
sha256sum "$DISTDIR"/*
