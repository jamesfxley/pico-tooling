# Building family libraries

A library pins infra; House reads `family = "infra"` in house.toml and imports
the gates and firmware profile from family.toml. Read [usage-guide.md](usage-guide.md)
for CMake helper signatures. Include cmake/pico_family_bootstrap.cmake before
project(), call pico_family_bootstrap, then initialize the SDK after project().
Libraries declare product pins directly with pico_family_dependency in
CMakeLists.txt, before pico_family_make_available populates them.

Run `python3 dev.py build` to configure, clean-build and test enabled trees.
Firmware uses PICO_SDK_PATH and the board axis; sanitize is House's built-in
tree selected by house_cxx_enable_sanitizers and HOUSE_MATRIX_SANITIZE=ON.
Per-tree build and lint names include build:firmware and lint:sanitize.
Each CI group runs independently: lint prepares with dev.py build; firmware
prepares with dev.py build and dev.py gate build-warnings.

`python3 dev.py sync` renders House's fixed-path copies, devcontainer and workflow.
`python3 -m infra.pico_tooling sync` writes only the generated CMake bootstrap.
family-files compares that bootstrap; family-freshness checks the infra release
online. A stale or unreleased pin passes with an adoption message;
GITHUB_ACTIONS=true adds a column-zero workflow warning annotation. Missing or
unreadable release tags are CANNOT_RUN, because evidence is unavailable. Footprint and symbols use the
library's declared budgets after firmware builds. Neither plain CMake nor House
performs product dependency selection policing.

A library takes a new infra patch release with its next change, when it needs a
fix the release carries, or when it moves a product pin to a revision whose infra
pin is newer than its own; `cmake/pico_family.cmake` refuses a build whose infra
is older than a dependency's pin. A release is taken at once only where it fixes
a gate defect that fails that library's CI, or a security defect. While the major
version is 0, a build refuses infra pins of different minor versions, so a minor
release is taken by every library, dependencies before their consumers. An open
pull request takes a new `main` only to merge.

See [installed SDK links](usage-guide.md#installed-sdk-links) for exporting
SDK-linked targets and restoring their links in installed consumers.

Profile-dependent footprint budgets use an optional `when` table on the row;
see [the pico.toml reference](usage-guide.md#embedded-gates). House's declared
matrix axes supply the matching `HOUSE_MATRIX_<AXIS>` environment variables.
Unmet rows are informational and are not measured.
