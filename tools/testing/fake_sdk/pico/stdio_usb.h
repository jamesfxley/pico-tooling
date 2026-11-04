// SPDX-License-Identifier: MIT
// The one USB stdio call pico_family/device_test.hpp makes, declared as the
// Pico SDK declares it (pico_stdio_usb/include/pico/stdio_usb.h), for the host
// compile of pico_family/device_test.hpp.
#pragma once

bool stdio_usb_connected();
