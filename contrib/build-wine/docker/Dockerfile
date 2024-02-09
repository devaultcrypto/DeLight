FROM ubuntu:18.04@sha256:2aeed98f2fa91c365730dc5d70d18e95e8d53ad4f1bbf4269c3bb625060383f0

ARG UBUNTU_MIRROR=http://archive.ubuntu.com/ubuntu/

ENV LC_ALL=C.UTF-8 LANG=C.UTF-8

# Official WineHQ signing key
# See https://wiki.winehq.org/Ubuntu
# From https://dl.winehq.org/wine-builds/winehq.key
COPY winehq.key /tmp

RUN echo deb ${UBUNTU_MIRROR} bionic main restricted universe multiverse > /etc/apt/sources.list && \
    echo deb ${UBUNTU_MIRROR} bionic-updates main restricted universe multiverse >> /etc/apt/sources.list && \
    echo deb ${UBUNTU_MIRROR} bionic-backports main restricted universe multiverse >> /etc/apt/sources.list && \
    echo deb ${UBUNTU_MIRROR} bionic-security main restricted universe multiverse >> /etc/apt/sources.list && \
    dpkg --add-architecture i386 && \
    apt-get update -q && \
    apt-get install -qy \
        gnupg2 \
        software-properties-common=0.96.24.32.14 \
        python3-software-properties=0.96.24.32.14 && \
    echo "78b185fabdb323971d13bd329fefc8038e08559aa51c4996de18db0639a51df6 /tmp/winehq.key" | sha256sum -c - && \
    apt-key add /tmp/winehq.key && \
    apt-add-repository https://dl.winehq.org/wine-builds/ubuntu/ && \
    apt-get update -q && \
    apt-get install -qy \
        wget=1.19.4-1ubuntu2.2 \
        git \
        p7zip-full=16.02+dfsg-6 \
        make=4.1-9.1ubuntu1 \
        autotools-dev=20180224.1 \
        autoconf=2.69-11 \
        libtool=2.4.6-2 \
        gettext=0.19.8.1-6ubuntu0.3 \
        autopoint=0.19.8.1-6ubuntu0.3 \
        mingw-w64=5.0.3-1 \
        mingw-w64-tools=5.0.3-1 \
        win-iconv-mingw-w64-dev=0.0.8-2 \
        wine-stable-amd64:amd64 \
        wine-stable-i386:i386 \
        wine-stable:amd64 \
        winehq-stable:amd64 && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get autoremove -y && \
    apt-get clean
