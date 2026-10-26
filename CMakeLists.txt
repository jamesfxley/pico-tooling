cmake_minimum_required(VERSION 3.26)
project(pico_tooling LANGUAGES CXX)

# The C++ half of this repository is host-only: padcheck's line protocol and the
# refusal probes that prove its dropped-status diagnostics. Nothing here is a
# library a consumer links, and no SDK is involved.
include(house/cxx/cmake/house.cmake)
house_cxx_common_settings(OFF)
house_cxx_add_strict_target(pico_tooling_strict LANGUAGES CXX)

house_cxx_enable_sanitizers(PICO_TOOLING)
house_cxx_declare_tests_option(PICO_TOOLING)

if(PICO_TOOLING_ENABLE_TESTS)
    house_cxx_enable_gtest()
    add_subdirectory(tools/testing)
endif()
