# padcheck's line protocol on the host (AR-14). The header holds no SDK code, so
# the cases run here rather than on a board.

# The protocol as a header-only target, so the tests and the refusal probes
# take one include path rather than reaching into padcheck/ by relative path.
add_library(pico_tooling_line_protocol INTERFACE)
target_include_directories(pico_tooling_line_protocol INTERFACE
    ${PROJECT_SOURCE_DIR}/tools/padcheck)

add_executable(pico_tooling_line_protocol_tests line_protocol_test.cpp)
target_link_libraries(pico_tooling_line_protocol_tests PRIVATE
    pico_tooling_strict
    pico_tooling_line_protocol
    GTest::gtest_main
)
# In every configuration, not only Debug: a subscript past the line buffer
# must abort rather than write past it and pass.
target_compile_definitions(pico_tooling_line_protocol_tests PRIVATE
    _GLIBCXX_ASSERTIONS)
gtest_discover_tests(pico_tooling_line_protocol_tests)

# The cross probe's one syscall stub, compiled for the host so its body is
# linted and covered; the cross build links the same file.
add_executable(pico_tooling_cross_probe_stub_tests cross_probe_stub_test.cpp
    ${PROJECT_SOURCE_DIR}/cmake/cross_probe_stub.cpp)
target_link_libraries(pico_tooling_cross_probe_stub_tests PRIVATE
    pico_tooling_strict GTest::gtest_main)
gtest_discover_tests(pico_tooling_cross_probe_stub_tests)

# A discarded status is a build failure. refusal_probe.cpp compiles as written
# and is part of every build; a PROBE=<n> copy discards one result, is built
# only by its test, and passes only on the diagnostic that refusal names.
add_library(pico_tooling_refusal_probe OBJECT refusal_probe.cpp)
target_link_libraries(pico_tooling_refusal_probe PRIVATE
    pico_tooling_strict pico_tooling_line_protocol)

# One row per discarded result: the PROBE number, the target suffix, the call
# the probe makes, and the signature GCC names in its diagnostic. Clang's
# diagnostic does not name the function, so its row is the call's own text.
set(PICO_TOOLING_PROBE_ROWS
    "1|take_field|padcheck::take_field(text, field)|bool padcheck::take_field(std::string_view&, std::string_view&)"
    "2|take_pin|padcheck::take_pin(text, pin)|padcheck::PinField padcheck::take_pin(std::string_view&, uint32_t&)"
    "3|at_end|padcheck::at_end(text)|bool padcheck::at_end(std::string_view)"
    "4|push|buffer.push(ch)|padcheck::LineBuffer::Ready padcheck::LineBuffer::push(char)"
    "5|take_pin_list|padcheck::take_pin_list(text, list)|padcheck::ListField padcheck::take_pin_list(std::string_view&, PinList&)"
    "6|take_pin_pair|padcheck::take_pin_pair(text, pin, second)|padcheck::PairField padcheck::take_pin_pair(std::string_view&, uint32_t&, uint32_t&)")

foreach(PICO_TOOLING_PROBE_ROW IN LISTS PICO_TOOLING_PROBE_ROWS)
    string(REPLACE "|" ";" PICO_TOOLING_PROBE_FIELDS "${PICO_TOOLING_PROBE_ROW}")
    list(GET PICO_TOOLING_PROBE_FIELDS 0 PICO_TOOLING_PROBE_N)
    list(GET PICO_TOOLING_PROBE_FIELDS 1 PICO_TOOLING_PROBE_WHAT)
    list(GET PICO_TOOLING_PROBE_FIELDS 2 PICO_TOOLING_PROBE_CALL)
    list(GET PICO_TOOLING_PROBE_FIELDS 3 PICO_TOOLING_PROBE_SIGNATURE)
    if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
        set(PICO_TOOLING_PROBE_DIAGNOSTIC
            "error: ignoring return value of '${PICO_TOOLING_PROBE_SIGNATURE}', declared with attribute 'nodiscard' [-Werror=unused-result]")
    elseif(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        set(PICO_TOOLING_PROBE_DIAGNOSTIC
            "error: ignoring return value of function declared with 'nodiscard' attribute [-Werror,-Wunused-result]")
    else()
        message(FATAL_ERROR
            "no exact diagnostic is recorded for ${CMAKE_CXX_COMPILER_ID}; a "
            "probe that cannot name its refusal would pass on any failure")
    endif()
    set(PICO_TOOLING_PROBE_TARGET
        pico_tooling_refuses_discarded_${PICO_TOOLING_PROBE_WHAT})
    add_library(${PICO_TOOLING_PROBE_TARGET} OBJECT EXCLUDE_FROM_ALL
        refusal_probe.cpp)
    target_link_libraries(${PICO_TOOLING_PROBE_TARGET} PRIVATE
        pico_tooling_strict pico_tooling_line_protocol)
    target_compile_definitions(${PICO_TOOLING_PROBE_TARGET} PRIVATE
        PROBE=${PICO_TOOLING_PROBE_N})
    add_test(NAME ${PICO_TOOLING_PROBE_TARGET}
        COMMAND ${CMAKE_COMMAND} -DBUILD_DIR=${CMAKE_BINARY_DIR}
                -DTARGET=${PICO_TOOLING_PROBE_TARGET}
                "-DEXPECT_DIAGNOSTIC=${PICO_TOOLING_PROBE_DIAGNOSTIC}"
                "-DEXPECT_CALL=${PICO_TOOLING_PROBE_CALL}"
                -P ${CMAKE_CURRENT_SOURCE_DIR}/expect_refusal.cmake)
    # Each test drives the one build tree; two at once contend for it.
    set_tests_properties(${PICO_TOOLING_PROBE_TARGET} PROPERTIES
        RESOURCE_LOCK pico_tooling_build_tree)
endforeach()
