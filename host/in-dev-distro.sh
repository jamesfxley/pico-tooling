#!/bin/sh
# SPDX-License-Identifier: MIT
# AR-15: runs as root inside the distro, from setup-dev-distro.ps1.
#   setup <user> <docker-version>: packages, Docker Engine, user, wsl.conf
#   verify: print the distro service/configuration diagnostics
set -eu
case "${1:-}" in
setup)
    [ "$#" -eq 3 ] || { echo "setup needs a user and Docker version" >&2; exit 2; }
    user="$2"
    version="$3"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl dbus git iproute2 systemd systemd-sysv wget
    # Docker's documented apt repository (docs.docker.com/engine/install/ubuntu).
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    cat > /etc/apt/sources.list.d/docker.sources <<SOURCES
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
SOURCES
    apt-get update
    pinned=$(apt list --all-versions docker-ce 2>/dev/null |
        awk '{print $2}' | grep "^5:${version}-" | head -n 1 || true)
    if [ -z "$pinned" ]; then
        echo "docker-ce $version is not in Docker's repository:" >&2
        apt list --all-versions docker-ce >&2
        exit 3
    fi
    apt-get install -y "docker-ce=$pinned" "docker-ce-cli=$pinned" \
        containerd.io docker-buildx-plugin docker-compose-plugin
    id "$user" >/dev/null 2>&1 || useradd -m -s /bin/bash "$user"
    usermod -aG docker "$user"
    cat > /etc/wsl.conf <<CONF
[boot]
systemd=true

[automount]
enabled=false
mountFsTab=false

[interop]
enabled=false
appendWindowsPath=false

[user]
default=$user
CONF
    ;;
verify)
    echo "## os"; . /etc/os-release; echo "$PRETTY_NAME"
    echo "## systemd"; systemctl is-system-running || true
    echo "## failed units"; systemctl --failed --no-pager || true
    echo "## docker service"; systemctl is-active docker || true
    echo "## docker version"; docker version --format 'client {{.Client.Version}} server {{.Server.Version}}' || true
    echo "## wsl.conf"; cat /etc/wsl.conf
    echo "## mounts under /mnt"; ls -A /mnt 2>/dev/null || true
    echo "## drvfs mounts"; grep -c drvfs /proc/mounts || true
    echo "## binfmt_misc"; ls /proc/sys/fs/binfmt_misc 2>/dev/null || true
    echo "## PATH"; echo "$PATH"
    echo "## ip -4 addr"; ip -4 addr
    echo "## ip route"; ip route
    ;;
*)
    echo "usage: in-dev-distro.sh setup <user> <docker-version> | verify" >&2
    exit 2
    ;;
esac
