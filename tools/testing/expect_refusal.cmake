# Builds one compile-fail probe and passes only if the build fails with the
# expected diagnostic. Failure for another reason does not pass the test.
# Both the diagnostic and call are matched as literal text.
#
#   cmake -DBUILD_DIR=<dir> -DTARGET=<target> -DEXPECT_DIAGNOSTIC=<text>
#         -DEXPECT_CALL=<text> -P expect_refusal.cmake
# A compiler quotes by locale (curly quotes in a UTF-8 one), so the expected
# text is only exact in the C locale.
set(ENV{LC_ALL} C)
set(ENV{LANGUAGE} C)
execute_process(
    COMMAND "${CMAKE_COMMAND}" --build "${BUILD_DIR}" --target "${TARGET}"
    OUTPUT_VARIABLE OUT
    ERROR_VARIABLE OUT
    RESULT_VARIABLE STATUS)
if(STATUS EQUAL 0)
    message(FATAL_ERROR "${TARGET} compiled; it was expected to be refused")
endif()
foreach(EXPECTED IN ITEMS "${EXPECT_DIAGNOSTIC}" "${EXPECT_CALL}")
    string(FIND "${OUT}" "${EXPECTED}" FOUND)
    if(FOUND EQUAL -1)
        message(FATAL_ERROR
            "${TARGET} failed, but without '${EXPECTED}':\n${OUT}")
    endif()
endforeach()
