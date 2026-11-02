// SPDX-License-Identifier: MIT
// The one stdio call run.hpp makes, declared as the Pico SDK declares it
// (pico_stdio/include/pico/stdio.h), so run.hpp compiles on the host (AR-17).
#pragma once

int stdio_put_string(const char* text, int len, bool newline,
                     bool cr_translation);
