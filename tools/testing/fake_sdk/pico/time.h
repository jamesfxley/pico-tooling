// SPDX-License-Identifier: MIT
// The one time call pico_family/device_test.hpp makes, declared as the Pico SDK
// declares it (pico_time/include/pico/time.h), for the host compile of
// pico_family/device_test.hpp.
#pragma once

#include <cstdint>

void sleep_ms(std::uint32_t ms);
