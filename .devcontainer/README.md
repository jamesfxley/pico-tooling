# Family image

`Dockerfile` builds the image for `linux/amd64`; `devcontainer.json` builds the
same file for a dev container. The build context is the repository root, and
`Dockerfile.dockerignore` lets only the two files the build copies into it.
`python3 -m pico_tooling.qualify` proves a built image from inside it.

## Pins

| Input | Pin | Why it can be trusted |
|---|---|---|
| Base | `ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944` | The multi-platform index digest. For `linux/amd64` it resolves to the manifest `sha256:42527649dbc4f9197a6073f426f488cbff0e9cc9f2afce32d91c383e4875634a`. |
| Pico SDK | 2.3.0, commit `98a542c1a62fb549ffb5d66a3e5892b06276b670` | The build fails if the tag resolves elsewhere. Its submodules follow from that commit. |
| picotool | 2.3.0, commit `6f6458d792b93685a11423b244a585eaa99eafcf` | The same check. |
| `uv`, `ruff` | `tools.txt` | PyPI wheel SHA-256 digests, installed with `--require-hashes`. |
| clang | `house/config/.clang-version` | The file House's gates read. |
| apt packages | `snapshot.ubuntu.com/ubuntu/20261020T163000Z` (`APT_SNAPSHOT`) | Canonical's dated snapshot of the archive: one timestamp, one package set. The qualification report lists every installed package and version. |

The snapshot service answers intermittently with 502, 503 and timeouts. Every
`apt-get update` in the Dockerfile runs with `--error-on=any`, so a failed
index fails the step instead of surfacing later as a missing package. Each
update-and-install step runs in a loop of at most five attempts, 30 s apart,
and apt itself retries each download ten times with a 30 s timeout. Before a
build, request the snapshot's `InRelease`; it answers 200 when the service is
usable.

## Labels

The image sets its title, description and license. Qualification records the
built image digest and the checkout commit separately. The base's version and
created labels are empty and no source label is set.

## The syscall filter

`seccomp.json` is the default filter of Docker Engine 29.8.2
(`vendor/github.com/moby/profiles/seccomp/default.json` at tag `docker-v29.8.2`,
commit `8af9fe3a36bab3e039862a2ab1cef1880c9b4d03`) with one rule added, after
the existing `personality` rules, allowing `personality` when its first argument
is `ADDR_NO_RANDOMIZE` (262144, 0x40000). An unmodified copy of the upstream file
is `tests/data/moby-docker-v29.8.2-seccomp-default.json`, and
`tests/test_image.py` proves that the one rule is the only difference. The
SHA-256 of `seccomp.json` is pinned in `pico_tooling/qualify.py` and in
`tests/test_image.py`. A later engine's default may differ; taking a newer one
means regenerating the file with the one rule, replacing the upstream copy and
recording both digests in the same change.
