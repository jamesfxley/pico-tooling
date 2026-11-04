// SPDX-License-Identifier: MIT
// The one stdio call pico_family/device_test.hpp makes, declared as the Pico
// SDK declares it (pico_stdio/include/pico/stdio.h), so
// pico_family/device_test.hpp compiles on the host (AR-17).
#pragma once

int stdio_put_string(const char* text, int len, bool newline,
                     bool cr_translation);
