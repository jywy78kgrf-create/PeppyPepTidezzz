#!/usr/bin/env bash
# One-time Docker install on a fresh Ubuntu 24.04 server (run as root).
#
#   ssh root@<SERVER_IP>
#   bash setup-server.sh
#
# Skip this entirely if you created the server from Hetzner's "Docker CE"
# app image — Docker is already installed there.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git rsync

# Docker's official apt repo (works on both amd64 and arm64 / CAX servers)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

echo
echo "Docker ready: $(docker --version)"
echo "Compose ready: $(docker compose version)"
