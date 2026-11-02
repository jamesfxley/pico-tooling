// SPDX-License-Identifier: MIT
// The one time call run.hpp makes, declared as the Pico SDK declares it
// (pico_time/include/pico/time.h), for the host compile of run.hpp.
#pragma once

#include <cstdint>

void sleep_ms(std::uint32_t ms);
