# Orientation

Start at the root instructions. Edit `pico_tooling/`, `cmake/` and `guides/`;
House and standard changes belong in their own repositories. Run checks against
the final indexed state.

Generated library output is owned here and checked in each library. A change to
a renderer changes every library's expected files, so prepare one reviewed
adoption batch rather than editing generated files by hand.
