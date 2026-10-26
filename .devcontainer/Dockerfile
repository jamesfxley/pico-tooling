# The pico family's dev container image. The build context is the pico-tooling
# checkout, whose pinned House
# submodule supplies the clang release.
#
# The base is pinned by content: the multi-platform index digest of
# ubuntu:26.04, which resolves to the linux/amd64 manifest recorded in
# .devcontainer/README.md. Only linux/amd64 is built and qualified. Every other
# downloaded artefact is pinned by a content digest: the PyPI wheels by SHA-256
# in tools.txt, and the Pico SDK and picotool sources by the Git commit their
# release tag must resolve to (a moved tag fails the build). The apt packages
# come from Canonical's dated snapshot of the archive (APT_SNAPSHOT below), so
# the same timestamp serves the same package set; the qualification report lists
# every installed package and version.
FROM ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944

# The Pico SDK release and the picotool release it requires
# (tools/CMakeLists.txt, picotool_VERSION_REQUIRED). An installed picotool of
# that release stops every firmware configure from fetching and building one.
ARG PICO_SDK_VERSION=2.3.0
ARG PICO_SDK_COMMIT=98a542c1a62fb549ffb5d66a3e5892b06276b670
ARG PICOTOOL_VERSION=2.3.0
ARG PICOTOOL_COMMIT=6f6458d792b93685a11423b244a585eaa99eafcf
# The archive state apt installs from, as YYYYMMDDTHHMMSSZ (UTC).
ARG APT_SNAPSHOT=20261020T163000Z

USER root
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
# The archive service answers intermittently with 502, 503 and timeouts. apt
# retries each failed download (Acquire::Retries, apt.conf(5)) and waits at most
# the timeout on a connection or transfer (Acquire::http::Timeout, and
# Acquire::https::Timeout which defaults to it; apt-transport-http(1) and
# apt-transport-https(1)). Every update-and-install step below also runs in a
# bounded loop of five attempts, 30 s apart, and every `apt-get update` fails on
# any index error (--error-on=any, apt-get(8)): by default apt treats a failed
# index as a warning and the install then fails with a misleading message.
RUN printf '%s\n' 'Acquire::Retries "10";' 'Acquire::http::Timeout "30";' \
      'Acquire::https::Timeout "30";' > /etc/apt/apt.conf.d/80-retries

# Point both archive sources at the dated snapshot. The base image carries no CA
# bundle, so the first fetch cannot verify TLS; apt still verifies every index
# against the archive keyring named by Signed-By, which is what authenticates
# the packages. ca-certificates comes first, and every later fetch verifies TLS.
RUN [[ "${APT_SNAPSHOT}" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] \
 && sed -i -E "s#^URIs: http://(archive|security)\.ubuntu\.com/ubuntu/?\$#URIs: https://snapshot.ubuntu.com/ubuntu/${APT_SNAPSHOT}#" \
      /etc/apt/sources.list.d/ubuntu.sources \
 && [[ "$(grep -c "^URIs: https://snapshot.ubuntu.com/ubuntu/${APT_SNAPSHOT}\$" \
      /etc/apt/sources.list.d/ubuntu.sources)" == 2 ]] \
 && for attempt in 1 2 3 4 5; do \
      if apt-get -o Acquire::https::Verify-Peer=false --error-on=any update \
         && apt-get -o Acquire::https::Verify-Peer=false install -y \
              --no-install-recommends ca-certificates; then break; \
      else status=$?; fi; \
      if [[ "${attempt}" == 5 ]]; then echo "apt failed after 5 attempts" >&2; exit "${status}"; fi; \
      echo "apt attempt ${attempt} failed; retrying in 30 s" >&2; sleep 30; \
    done \
 && rm -rf /var/lib/apt/lists/*

COPY house/config/.clang-version /tmp/pins/

# Read as House reads it: .clang-version's first word, comments dropped.
RUN clang="$(sed 's/#.*//' /tmp/pins/.clang-version | tr ',' ' ' | awk 'NF {print $1; exit}')" \
 && [[ "${clang}" =~ ^[0-9]+$ ]] \
 && for attempt in 1 2 3 4 5; do \
      if apt-get --error-on=any update \
         && apt-get upgrade -y \
         && apt-get install -y --no-install-recommends \
              bash ca-certificates curl git sudo less openssh-client socat \
              python3 python3-venv \
              cmake ninja-build ccache g++ make pkg-config libusb-1.0-0-dev \
              "clang-${clang}" "clang-tidy-${clang}" "clang-format-${clang}" \
              "clangd-${clang}" "libclang-rt-${clang}-dev" \
              gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib \
              xz-utils doxygen gh; then break; \
      else status=$?; fi; \
      if [[ "${attempt}" == 5 ]]; then echo "apt failed after 5 attempts" >&2; exit "${status}"; fi; \
      echo "apt attempt ${attempt} failed; retrying in 30 s" >&2; sleep 30; \
    done \
 && ln -sf "/usr/bin/clangd-${clang}" /usr/local/bin/clangd \
 && rm -rf /var/lib/apt/lists/*

# uv and ruff, hash-checked, in a venv of their own. ruff's release is the one
# house/config/ruff.toml requires.
COPY .devcontainer/tools.txt /tmp/tools.txt
RUN python3 -m venv /opt/tools \
 && /opt/tools/bin/pip install --quiet --no-cache-dir --require-hashes \
      --only-binary :all: --requirement /tmp/tools.txt \
 && ln -sf /opt/tools/bin/uv /opt/tools/bin/uvx /opt/tools/bin/ruff /usr/local/bin/ \
 && rm -rf /tmp/tools.txt /tmp/pins

# Both sources are cloned by release tag and must be at the pinned commit.
RUN git clone --quiet --depth 1 --branch "${PICO_SDK_VERSION}" \
      https://github.com/raspberrypi/pico-sdk.git /opt/pico-sdk \
 && [[ "$(git -C /opt/pico-sdk rev-parse HEAD)" == "${PICO_SDK_COMMIT}" ]] \
 && git -C /opt/pico-sdk submodule update --quiet --init --recursive --depth 1 \
 && git clone --quiet --depth 1 --branch "${PICOTOOL_VERSION}" \
      https://github.com/raspberrypi/picotool.git /tmp/picotool \
 && [[ "$(git -C /tmp/picotool rev-parse HEAD)" == "${PICOTOOL_COMMIT}" ]] \
 && cmake -S /tmp/picotool -B /tmp/picotool/build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release -DPICO_SDK_PATH=/opt/pico-sdk \
      -DCMAKE_INSTALL_PREFIX=/usr/local \
 && cmake --build /tmp/picotool/build \
 && cmake --install /tmp/picotool/build \
 && rm -rf /tmp/picotool

ENV PICO_SDK_PATH=/opt/pico-sdk

# The user the dev container runs as: agent, UID 1000, home /home/agent.
# ubuntu:26.04 has `ubuntu` at UID 1000, which gives way. A dev container on
# Linux remaps the UID to the host user's.
RUN if ! id agent >/dev/null 2>&1; then \
      if id ubuntu >/dev/null 2>&1; then userdel --remove ubuntu; fi; \
      useradd --create-home --uid 1000 --shell /bin/bash agent; \
      echo 'agent ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agent; \
      chmod 0440 /etc/sudoers.d/agent; \
    fi \
 && [[ "$(id -u agent)" == 1000 && "$(getent passwd agent | cut -d: -f6)" == /home/agent ]]

# A mounted workspace is owned by the host user, which in CI and under Docker
# Desktop is not the container's: git would refuse every repository as
# dubiously owned. The container is the trust boundary here, not the directory.
RUN git config --system --add safe.directory '*'

# Image identity is its digest, recorded by qualification with the checkout commit.
LABEL org.opencontainers.image.title="pico family development image" \
      org.opencontainers.image.description="The pico family's toolchain, Pico SDK and gates" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="" \
      org.opencontainers.image.created="" \
      devcontainer.metadata='[{"remoteUser":"agent","containerUser":"agent","updateRemoteUserUID":true}]'

USER agent
