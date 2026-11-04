cmake_minimum_required(VERSION 3.26)
project(pico_tooling LANGUAGES CXX)

# C++ builds test padcheck's line protocol and its discarded-result
# diagnostics on the host. They need no SDK and install no library.
include(house/cxx/cmake/house.cmake)
house_cxx_common_settings(OFF)
house_cxx_add_strict_target(pico_tooling_strict LANGUAGES CXX)

house_cxx_enable_sanitizers(PICO_TOOLING)
house_cxx_declare_tests_option(PICO_TOOLING)

if(PICO_TOOLING_ENABLE_TESTS)
    house_cxx_enable_gtest()
    add_subdirectory(tools/testing)
endif()
