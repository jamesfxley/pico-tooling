# SPDX-License-Identifier: MIT
# Pico family CMake entry points (AR-6). Definition-only; a library reaches this
# file through its generated cmake/pico_family_bootstrap.cmake, which selects
# one family context per build before including it.
include_guard(GLOBAL)

file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/../pyproject.toml" _pico_family_version
    REGEX "^version = ")
string(REGEX REPLACE "^version = \"([^\"]+)\"$" "\\1"
    PICO_FAMILY_VERSION "${_pico_family_version}")
unset(_pico_family_version)
# $<BUILD_LOCAL_INTERFACE:> (CMake manual, "versionadded:: 3.26") keeps SDK
# libraries out of both exports, so every library of the family needs 3.26.
set(PICO_FAMILY_MINIMUM_CMAKE "3.26")
set(PICO_FAMILY_SUPPORTED_BOARDS pico_w pico2_w)

# Select one context, recording its actual revision, state and release version.
# A parent may serve children only within a compatible release line and at or
# above every requested version (AR-6).
function(_pico_family_context PICO_FAMILY_ROOT_DIR PICO_FAMILY_REVISION
        PICO_FAMILY_REQUESTED_VERSION)
    get_property(selected GLOBAL PROPERTY PICO_FAMILY_ROOT)
    if(NOT selected)
        _pico_family_describe_override("${PICO_FAMILY_ROOT_DIR}" effective)
        set_property(GLOBAL PROPERTY PICO_FAMILY_ROOT "${PICO_FAMILY_ROOT_DIR}")
        set_property(GLOBAL PROPERTY PICO_FAMILY_REVISION "${effective}")
        set_property(GLOBAL PROPERTY PICO_FAMILY_SELECTED_VERSION "${PICO_FAMILY_VERSION}")
        if(effective STREQUAL PICO_FAMILY_REVISION)
            message(STATUS "pico family: context ${effective} "
                "(version ${PICO_FAMILY_VERSION}) at ${PICO_FAMILY_ROOT_DIR}")
        else()
            message(STATUS "pico family: context override ${effective} "
                "(version ${PICO_FAMILY_VERSION}) at ${PICO_FAMILY_ROOT_DIR}; "
                "${CMAKE_CURRENT_SOURCE_DIR} pins ${PICO_FAMILY_REVISION}")
        endif()
    endif()
    get_property(revision GLOBAL PROPERTY PICO_FAMILY_REVISION)
    get_property(version GLOBAL PROPERTY PICO_FAMILY_SELECTED_VERSION)
    string(REGEX MATCH "^([0-9]+)\\.([0-9]+)\\.[0-9]+$" _ "${version}")
    set(selected_major "${CMAKE_MATCH_1}")
    set(selected_minor "${CMAKE_MATCH_2}")
    string(REGEX MATCH "^([0-9]+)\\.([0-9]+)\\.[0-9]+$" _ "${PICO_FAMILY_REQUESTED_VERSION}")
    if(NOT selected_major EQUAL CMAKE_MATCH_1 OR
            (selected_major EQUAL 0 AND NOT selected_minor EQUAL CMAKE_MATCH_2))
        message(FATAL_ERROR
            "pico family: ${CMAKE_CURRENT_SOURCE_DIR} pins version "
            "${PICO_FAMILY_REQUESTED_VERSION} (${PICO_FAMILY_REVISION}), but this "
            "build selected version ${version} (${revision}). Align the infra "
            "pins or supply a compatible context from the parent.")
    endif()
    if(version VERSION_LESS PICO_FAMILY_REQUESTED_VERSION)
        message(FATAL_ERROR
            "pico family: ${CMAKE_CURRENT_SOURCE_DIR} needs version "
            "${PICO_FAMILY_REQUESTED_VERSION} (${PICO_FAMILY_REVISION}), but "
            "this build selected the older version ${version} (${revision}). "
            "Raise the parent's infra pin to version "
            "${PICO_FAMILY_REQUESTED_VERSION} or later within the compatible line.")
    endif()
    if(selected AND NOT revision STREQUAL PICO_FAMILY_REVISION)
        message(STATUS "pico family: ${CMAKE_CURRENT_SOURCE_DIR} pins "
            "${PICO_FAMILY_REVISION}; reusing selected context ${revision}")
    endif()
endfunction()

# This file is the selected context's copy, so its House pin is the build's.
include("${CMAKE_CURRENT_LIST_DIR}/../house/cxx/cmake/house.cmake")

# Argument checks owned by the family, so this module calls no private House
# helper (EN-00.8).
macro(_pico_family_check_arguments PICO_FAMILY_CA_PREFIX PICO_FAMILY_CA_CALL)
    list(LENGTH ${PICO_FAMILY_CA_PREFIX}_UNPARSED_ARGUMENTS PICO_FAMILY_CA_EXTRA)
    if(PICO_FAMILY_CA_EXTRA GREATER 0)
        message(FATAL_ERROR
            "${PICO_FAMILY_CA_CALL}: unrecognised arguments "
            "'${${PICO_FAMILY_CA_PREFIX}_UNPARSED_ARGUMENTS}'")
    endif()
    list(LENGTH ${PICO_FAMILY_CA_PREFIX}_KEYWORDS_MISSING_VALUES
         PICO_FAMILY_CA_EMPTY)
    if(PICO_FAMILY_CA_EMPTY GREATER 0)
        message(FATAL_ERROR
            "${PICO_FAMILY_CA_CALL}: no value given for "
            "'${${PICO_FAMILY_CA_PREFIX}_KEYWORDS_MISSING_VALUES}'")
    endif()
endmacro()

function(_pico_family_no_extra_arguments PICO_FAMILY_NX_CALL)
    list(LENGTH ARGN PICO_FAMILY_NX_EXTRA)
    if(PICO_FAMILY_NX_EXTRA GREATER 0)
        message(FATAL_ERROR
            "${PICO_FAMILY_NX_CALL}: unrecognised arguments '${ARGN}'")
    endif()
endfunction()

# Before project(). Defines <PREFIX>_BUILD_FIRMWARE from the PICO_SDK_PATH CMake
# variable only, never the environment, so a developer shell cannot silently
# turn a host build into firmware. At top level a firmware build validates the
# SDK and board and imports the SDK once. As a dependency it takes the parent's
# SDK and board (BR-12) and never imports a second SDK.
macro(pico_family_bootstrap PICO_FAMILY_PREFIX)
    if(CMAKE_VERSION VERSION_LESS PICO_FAMILY_MINIMUM_CMAKE)
        message(FATAL_ERROR
            "pico_family_bootstrap: the pico family needs CMake "
            "${PICO_FAMILY_MINIMUM_CMAKE} or later, because "
            "$<BUILD_LOCAL_INTERFACE:> keeps SDK libraries out of an export; "
            "this is CMake ${CMAKE_VERSION}")
    endif()
    cmake_parse_arguments(PICO_FAMILY_BOOT "CYW43" "PLATFORM" "" ${ARGN})
    _pico_family_check_arguments(PICO_FAMILY_BOOT "pico_family_bootstrap")

    set(${PICO_FAMILY_PREFIX}_BUILD_FIRMWARE_DEFAULT OFF)
    if(DEFINED PICO_SDK_PATH AND EXISTS "${PICO_SDK_PATH}/pico_sdk_init.cmake")
        set(${PICO_FAMILY_PREFIX}_BUILD_FIRMWARE_DEFAULT ON)
    endif()
    option(${PICO_FAMILY_PREFIX}_BUILD_FIRMWARE
        "Build Pico SDK dependent firmware components"
        ${${PICO_FAMILY_PREFIX}_BUILD_FIRMWARE_DEFAULT})
    if(${PICO_FAMILY_PREFIX}_BUILD_FIRMWARE
       AND NOT CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
        if(NOT DEFINED PICO_PLATFORM)
            message(FATAL_ERROR
                "${PICO_FAMILY_PREFIX} is a dependency here, so the top-level "
                "project must import the Pico SDK (pico_sdk_import.cmake) before "
                "adding it, or set ${PICO_FAMILY_PREFIX}_BUILD_FIRMWARE OFF")
        endif()
    elseif(${PICO_FAMILY_PREFIX}_BUILD_FIRMWARE)
        _pico_family_import_sdk()
    endif()
    if(${PICO_FAMILY_PREFIX}_BUILD_FIRMWARE)
        if(DEFINED PICO_FAMILY_BOOT_PLATFORM)
            string(FIND "${PICO_PLATFORM}" "${PICO_FAMILY_BOOT_PLATFORM}"
                PICO_FAMILY_BOOT_AT)
            if(NOT PICO_FAMILY_BOOT_AT EQUAL 0)
                message(FATAL_ERROR
                    "${PICO_FAMILY_PREFIX} needs PICO_PLATFORM "
                    "${PICO_FAMILY_BOOT_PLATFORM}, and PICO_BOARD '${PICO_BOARD}' "
                    "is ${PICO_PLATFORM}")
            endif()
        endif()
        if(PICO_FAMILY_BOOT_CYW43 AND NOT PICO_CYW43_SUPPORTED)
            message(FATAL_ERROR
                "${PICO_FAMILY_PREFIX} needs a board with the CYW43 radio, and "
                "PICO_BOARD '${PICO_BOARD}' has none")
        endif()
    endif()
endmacro()

macro(_pico_family_import_sdk)
    get_property(PICO_FAMILY_SDK_IMPORTED GLOBAL PROPERTY PICO_FAMILY_SDK_IMPORTED)
    if(NOT PICO_FAMILY_SDK_IMPORTED)
        if(NOT DEFINED PICO_SDK_PATH AND DEFINED ENV{PICO_SDK_PATH})
            set(PICO_SDK_PATH $ENV{PICO_SDK_PATH})
        endif()
        if(NOT DEFINED PICO_SDK_PATH)
            message(FATAL_ERROR
                "PICO_SDK_PATH must point to a valid Pico SDK checkout when "
                "building firmware targets")
        endif()
        if(NOT EXISTS "${PICO_SDK_PATH}/pico_sdk_init.cmake")
            message(FATAL_ERROR
                "Could not find pico_sdk_init.cmake in '${PICO_SDK_PATH}'")
        endif()
        if(NOT DEFINED PICO_BOARD OR PICO_BOARD STREQUAL "")
            # BR-6: the SDK reads an environment PICO_BOARD when no variable is
            # set, so substituting the default would build for another board.
            if(NOT "$ENV{PICO_BOARD}" STREQUAL ""
               AND NOT "$ENV{PICO_BOARD}" STREQUAL "pico2_w")
                message(FATAL_ERROR
                    "PICO_BOARD is '$ENV{PICO_BOARD}' in the environment and "
                    "unset as a CMake variable, which would select 'pico2_w'. "
                    "Pass -DPICO_BOARD=<board> to choose.")
            endif()
            set(PICO_BOARD "pico2_w" CACHE STRING "Target Pico board" FORCE)
        endif()
        set_property(CACHE PICO_BOARD PROPERTY STRINGS ${PICO_FAMILY_SUPPORTED_BOARDS})
        if(NOT PICO_BOARD IN_LIST PICO_FAMILY_SUPPORTED_BOARDS)
            message(FATAL_ERROR
                "Unsupported PICO_BOARD='${PICO_BOARD}'. Supported boards: "
                "${PICO_FAMILY_SUPPORTED_BOARDS}")
        endif()
        set(PICOTOOL_FETCH_FROM_GIT_PATH "$ENV{HOME}/pico/picotool" CACHE PATH
            "Shared directory to fetch/build picotool into")
        include("${PICO_SDK_PATH}/pico_sdk_init.cmake")
        set_property(GLOBAL PROPERTY PICO_FAMILY_SDK_IMPORTED TRUE)
    endif()
endmacro()

# After project(). The top-level project initializes the SDK exactly once;
# a dependency verifies its parent did. No-op on host.
macro(pico_family_init_sdk PICO_FAMILY_FIRMWARE)
    _pico_family_no_extra_arguments("pico_family_init_sdk" ${ARGN})
    if(${PICO_FAMILY_FIRMWARE})
        get_property(PICO_FAMILY_SDK_INITIALIZED GLOBAL
            PROPERTY PICO_FAMILY_SDK_INITIALIZED)
        if(PROJECT_IS_TOP_LEVEL AND NOT PICO_FAMILY_SDK_INITIALIZED)
            pico_sdk_init()
            set_property(GLOBAL PROPERTY PICO_FAMILY_SDK_INITIALIZED TRUE)
        # _pico_sdk_inclusion_marker is an SDK internal, not documented API: it
        # is the one trace pico_sdk_init() leaves (SDK 2.3.0 CMakeLists.txt,
        # lines 5-6). A later SDK that renames it makes this branch reject a
        # correctly initialised parent, which fails loudly, never silently.
        elseif(NOT PICO_FAMILY_SDK_INITIALIZED
               AND NOT TARGET _pico_sdk_inclusion_marker)
            message(FATAL_ERROR
                "pico_sdk_init() must be called by the top-level project before "
                "enabling ${PROJECT_NAME} firmware components")
        endif()
    endif()
endmacro()

# Declare one pinned product dependency. The library declares every direct pin
# in CMakeLists.txt, then calls pico_family_make_available(), so its
# own pins win over its dependencies' pins. FetchContent's first declaration
# wins; a later different pin is reported, never silently used.
# FETCHCONTENT_SOURCE_DIR_<NAME> is the explicit override; siblings are never
# discovered. Product fetches skip submodules: the build reuses one context.
function(pico_family_dependency PICO_FAMILY_DEP_NAME)
    cmake_parse_arguments(PICO_FAMILY_DEP "" "REPOSITORY;REVISION" "" ${ARGN})
    _pico_family_check_arguments(PICO_FAMILY_DEP
        "pico_family_dependency(${PICO_FAMILY_DEP_NAME})")
    if(NOT PICO_FAMILY_DEP_REPOSITORY OR NOT PICO_FAMILY_DEP_REVISION)
        message(FATAL_ERROR "pico_family_dependency(${PICO_FAMILY_DEP_NAME}): "
            "REPOSITORY and REVISION are required")
    endif()
    # CMake regular expressions have no repetition counts; check the length.
    string(LENGTH "${PICO_FAMILY_DEP_REVISION}" length)
    if(NOT PICO_FAMILY_DEP_REVISION MATCHES "^[0-9a-f]+$"
       OR NOT (length EQUAL 40 OR length EQUAL 64))
        message(FATAL_ERROR "pico_family_dependency(${PICO_FAMILY_DEP_NAME}): "
            "REVISION must be a full commit object ID, got "
            "'${PICO_FAMILY_DEP_REVISION}'")
    endif()
    cmake_policy(GET CMP0097 PICO_FAMILY_SUBMODULE_POLICY)
    if(NOT PICO_FAMILY_SUBMODULE_POLICY STREQUAL "NEW")
        message(FATAL_ERROR "pico_family_dependency requires policy CMP0097 NEW "
            "(cmake_minimum_required 3.16 or later) so GIT_SUBMODULES \"\" "
            "fetches no submodules")
    endif()
    set(key "PICO_FAMILY_DECLARED_${PICO_FAMILY_DEP_NAME}")
    get_property(declared GLOBAL PROPERTY "${key}")
    if(declared)
        list(GET declared 0 revision)
        list(GET declared 1 owner)
        if(NOT revision STREQUAL PICO_FAMILY_DEP_REVISION)
            message(STATUS "pico family: ${PICO_FAMILY_DEP_NAME} selected "
                "${revision} from ${owner}; ${PROJECT_NAME} pins "
                "${PICO_FAMILY_DEP_REVISION}, which is not used")
        endif()

        return()
    endif()
    set_property(GLOBAL PROPERTY "${key}"
        "${PICO_FAMILY_DEP_REVISION};${PROJECT_NAME}")
    string(TOUPPER "${PICO_FAMILY_DEP_NAME}" upper)
    set(override "${FETCHCONTENT_SOURCE_DIR_${upper}}")
    if(override)
        _pico_family_describe_override("${override}" description)
        message(STATUS "pico family: ${PICO_FAMILY_DEP_NAME} override "
            "${override} at ${description}; ${PROJECT_NAME} pins "
            "${PICO_FAMILY_DEP_REVISION}")
    else()
        message(STATUS "pico family: ${PICO_FAMILY_DEP_NAME} pinned "
            "${PICO_FAMILY_DEP_REVISION} by ${PROJECT_NAME}")
    endif()
    include(FetchContent)
    FetchContent_Declare(${PICO_FAMILY_DEP_NAME}
        GIT_REPOSITORY "${PICO_FAMILY_DEP_REPOSITORY}"
        GIT_TAG "${PICO_FAMILY_DEP_REVISION}"
        GIT_SUBMODULES "")
endfunction()

# The revision a directory is at and its state: clean, dirty (uncommitted
# changes) or unversioned (not a Git checkout, so no revision).
function(_pico_family_directory_state PICO_FAMILY_DIR PICO_FAMILY_REV_OUT
        PICO_FAMILY_STATE_OUT)
    execute_process(COMMAND git -C "${PICO_FAMILY_DIR}" rev-parse HEAD
        OUTPUT_VARIABLE revision OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE failed ERROR_QUIET)
    if(failed)
        set(${PICO_FAMILY_REV_OUT} "" PARENT_SCOPE)
        set(${PICO_FAMILY_STATE_OUT} "unversioned" PARENT_SCOPE)
        return()
    endif()
    execute_process(COMMAND git -C "${PICO_FAMILY_DIR}" status --porcelain
        OUTPUT_VARIABLE changes OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    set(${PICO_FAMILY_REV_OUT} "${revision}" PARENT_SCOPE)
    if(changes)
        set(${PICO_FAMILY_STATE_OUT} "dirty" PARENT_SCOPE)
    else()
        set(${PICO_FAMILY_STATE_OUT} "clean" PARENT_SCOPE)
    endif()
endfunction()

function(_pico_family_describe_override PICO_FAMILY_DIR PICO_FAMILY_OUT)
    _pico_family_directory_state("${PICO_FAMILY_DIR}" revision state)
    if(state STREQUAL "unversioned")
        set(${PICO_FAMILY_OUT} "an unversioned directory" PARENT_SCOPE)
    elseif(state STREQUAL "dirty")
        set(${PICO_FAMILY_OUT} "${revision} with uncommitted changes" PARENT_SCOPE)
    else()
        set(${PICO_FAMILY_OUT} "${revision}" PARENT_SCOPE)
    endif()
endfunction()

# Populate the dependencies declared by the library.
macro(pico_family_make_available)
    include(FetchContent)
    FetchContent_MakeAvailable(${ARGN})
endmacro()

# Link SDK libraries to an exported target. The SDK targets exist only after the
# top level runs pico_sdk_init(), so a plain link would put them in the export and
# make install() and export() fail. $<BUILD_INTERFACE:> is not enough: it removes
# the link from the installed interface, but the build-tree export() runs with
# BUILD_INTERFACE active and fails the same way. $<BUILD_LOCAL_INTERFACE:> applies
# only within this build system and is excluded from both exports, which is why
# the family requires CMake 3.26. The recorded links are for the installed package
# config to re-apply after the consumer initializes the SDK.
function(pico_family_sdk_link_libraries PICO_FAMILY_SDK_TARGET)
    cmake_parse_arguments(PICO_FAMILY_SDK "" "" "PUBLIC;PRIVATE" ${ARGN})
    if(PICO_FAMILY_SDK_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR "pico_family_sdk_link_libraries: unrecognised "
            "arguments '${PICO_FAMILY_SDK_UNPARSED_ARGUMENTS}'. Every library "
            "must be under PUBLIC or PRIVATE.")
    endif()
    if(NOT PICO_FAMILY_SDK_PUBLIC AND NOT PICO_FAMILY_SDK_PRIVATE)
        message(FATAL_ERROR "pico_family_sdk_link_libraries: no libraries given "
            "for ${PICO_FAMILY_SDK_TARGET}")
    endif()
    foreach(visibility IN ITEMS PUBLIC PRIVATE)
        foreach(library IN LISTS PICO_FAMILY_SDK_${visibility})
            target_link_libraries(${PICO_FAMILY_SDK_TARGET} ${visibility}
                $<BUILD_LOCAL_INTERFACE:${library}>)
        endforeach()
        if(PICO_FAMILY_SDK_${visibility})
            set_property(TARGET ${PICO_FAMILY_SDK_TARGET} APPEND PROPERTY
                PICO_FAMILY_SDK_LINKS_${visibility} ${PICO_FAMILY_SDK_${visibility}})
        endif()
    endforeach()
endfunction()

# Emit the baseline package SDK block for House's CONFIG_SNIPPET. The package
# and imported namespace are PROJECT_NAME, as in the family libraries.
function(pico_family_sdk_config_snippet PICO_FAMILY_SNIPPET_OUT)
    cmake_parse_arguments(PICO_FAMILY_SNIPPET "" "" "TARGETS" ${ARGN})
    _pico_family_check_arguments(PICO_FAMILY_SNIPPET
        "pico_family_sdk_config_snippet")
    set(PICO_FAMILY_SNIPPET_SDK_BLOCK "")
    set(PICO_FAMILY_SNIPPET_GUARDED "")
    foreach(PICO_FAMILY_SNIPPET_TARGET IN LISTS PICO_FAMILY_SNIPPET_TARGETS)
        string(REGEX REPLACE "^${PROJECT_NAME}_" ""
            PICO_FAMILY_SNIPPET_EXPORT_NAME "${PICO_FAMILY_SNIPPET_TARGET}")
        set(PICO_FAMILY_SNIPPET_IMPORTED
            "${PROJECT_NAME}::${PICO_FAMILY_SNIPPET_EXPORT_NAME}")
        foreach(PICO_FAMILY_SNIPPET_VIS IN ITEMS PUBLIC PRIVATE)
            get_target_property(PICO_FAMILY_SNIPPET_LIBS
                ${PICO_FAMILY_SNIPPET_TARGET} PICO_FAMILY_SDK_LINKS_${PICO_FAMILY_SNIPPET_VIS})
            if(NOT PICO_FAMILY_SNIPPET_LIBS)
                continue()
            endif()
            set(PICO_FAMILY_SNIPPET_ENTRIES "")
            foreach(PICO_FAMILY_SNIPPET_LIB IN LISTS PICO_FAMILY_SNIPPET_LIBS)
                if(NOT PICO_FAMILY_SNIPPET_LIB IN_LIST PICO_FAMILY_SNIPPET_GUARDED)
                    list(APPEND PICO_FAMILY_SNIPPET_GUARDED ${PICO_FAMILY_SNIPPET_LIB})
                    string(APPEND PICO_FAMILY_SNIPPET_SDK_BLOCK
                        "if(NOT TARGET ${PICO_FAMILY_SNIPPET_LIB})\n"
                        "    message(FATAL_ERROR\n"
                        "        \"${PROJECT_NAME}: no target '${PICO_FAMILY_SNIPPET_LIB}'. This package \"\n"
                        "        \"links the Pico SDK, so the SDK must be initialised before \"\n"
                        "        \"find_package(${PROJECT_NAME}): include pico_sdk_import.cmake and \"\n"
                        "        \"call pico_sdk_init() first.\")\n"
                        "endif()\n")
                endif()
                if(PICO_FAMILY_SNIPPET_VIS STREQUAL "PRIVATE")
                    list(APPEND PICO_FAMILY_SNIPPET_ENTRIES
                        "$<LINK_ONLY:${PICO_FAMILY_SNIPPET_LIB}>")
                else()
                    list(APPEND PICO_FAMILY_SNIPPET_ENTRIES "${PICO_FAMILY_SNIPPET_LIB}")
                endif()
            endforeach()
            string(REPLACE ";" " " PICO_FAMILY_SNIPPET_ENTRY_STR "${PICO_FAMILY_SNIPPET_ENTRIES}")
            string(APPEND PICO_FAMILY_SNIPPET_SDK_BLOCK
                "set_property(TARGET ${PICO_FAMILY_SNIPPET_IMPORTED} APPEND PROPERTY\n"
                "    INTERFACE_LINK_LIBRARIES ${PICO_FAMILY_SNIPPET_ENTRY_STR})\n")
        endforeach()
    endforeach()
    if(PICO_FAMILY_SNIPPET_SDK_BLOCK)
        string(PREPEND PICO_FAMILY_SNIPPET_SDK_BLOCK
            "\n# Pico SDK libraries. Not exportable, so re-applied here; see\n"
            "# pico_family_sdk_link_libraries in pico-tooling.\n")
    endif()

    set(PICO_FAMILY_SNIPPET_PATH
        "${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}-sdk-config.cmake")
    file(WRITE "${PICO_FAMILY_SNIPPET_PATH}" "${PICO_FAMILY_SNIPPET_SDK_BLOCK}")
    set(${PICO_FAMILY_SNIPPET_OUT} "${PICO_FAMILY_SNIPPET_PATH}" PARENT_SCOPE)
endfunction()

# One application-owned lwipopts target for the whole image (CXX-10.3).
macro(pico_family_require_lwipopts_target PICO_FAMILY_LIBRARY)
    cmake_parse_arguments(PICO_FAMILY_LWO "" "FALLBACK" "" ${ARGN})
    _pico_family_check_arguments(PICO_FAMILY_LWO
        "pico_family_require_lwipopts_target(${PICO_FAMILY_LIBRARY})")
    set(PICO_LWIPOPTS_TARGET "" CACHE STRING
        "CMake target providing lwipopts.h (required for a firmware build)")
    if(NOT PICO_LWIPOPTS_TARGET)
        set(PICO_FAMILY_LWO_HINT "")
        if(PICO_FAMILY_LWO_FALLBACK)
            set(PICO_FAMILY_LWO_HINT " To build this repository standalone, pass "
                "-DPICO_LWIPOPTS_TARGET=${PICO_FAMILY_LWO_FALLBACK}.")
        endif()
        message(FATAL_ERROR "${PICO_FAMILY_LIBRARY}: PICO_LWIPOPTS_TARGET must "
            "name the target carrying your lwipopts.h. The Pico SDK compiles lwIP "
            "into this library, so a default here would build a second lwIP "
            "against a configuration your application does not use."
            ${PICO_FAMILY_LWO_HINT})
    endif()
endmacro()

# Installing a library installs the dependencies its export names (IR-6).
macro(pico_family_propagate_install PICO_FAMILY_PREFIX)
    set(PICO_FAMILY_PI_DEPS ${ARGN})
    if(NOT PICO_FAMILY_PI_DEPS)
        message(FATAL_ERROR "pico_family_propagate_install(${PICO_FAMILY_PREFIX}): "
            "no dependency prefixes given")
    endif()
    if(${PICO_FAMILY_PREFIX}_ENABLE_INSTALL)
        foreach(PICO_FAMILY_PI_DEP IN LISTS PICO_FAMILY_PI_DEPS)
            set(${PICO_FAMILY_PI_DEP}_ENABLE_INSTALL ON CACHE BOOL
                "Generate install/export rules" FORCE)
        endforeach()
    endif()
endmacro()

# Declare a whole-build sizing profile: a cached string restricted to named
# values, <PREFIX>_<NAME>. A value outside the set is refused, naming the set,
# including an empty value (quoted, so it is not silently skipped). One variable
# has one declaration per build: a second declaration with a different default
# or value set, from another library, is fatal and names both directories, since
# one cache entry cannot serve two meanings; an identical one is a no-op.
function(pico_family_declare_profile PICO_FAMILY_PREFIX)
    cmake_parse_arguments(PICO_FAMILY_PROFILE "" "NAME;DEFAULT;DOC" "VALUES" ${ARGN})
    _pico_family_check_arguments(PICO_FAMILY_PROFILE
        "pico_family_declare_profile(${PICO_FAMILY_PREFIX})")
    if(NOT PICO_FAMILY_PROFILE_NAME OR NOT PICO_FAMILY_PROFILE_DEFAULT
       OR NOT PICO_FAMILY_PROFILE_VALUES)
        message(FATAL_ERROR "pico_family_declare_profile(${PICO_FAMILY_PREFIX}): "
            "NAME, DEFAULT and VALUES are all required")
    endif()
    if(NOT PICO_FAMILY_PROFILE_DEFAULT IN_LIST PICO_FAMILY_PROFILE_VALUES)
        message(FATAL_ERROR "pico_family_declare_profile(${PICO_FAMILY_PREFIX}): "
            "DEFAULT '${PICO_FAMILY_PROFILE_DEFAULT}' is not one of VALUES")
    endif()
    set(variable "${PICO_FAMILY_PREFIX}_${PICO_FAMILY_PROFILE_NAME}")
    string(REPLACE ";" "," values "${PICO_FAMILY_PROFILE_VALUES}")
    set(shape "${PICO_FAMILY_PROFILE_DEFAULT} among ${values}")
    get_property(declared GLOBAL PROPERTY "PICO_FAMILY_PROFILE_${variable}")
    if(declared)
        list(GET declared 0 earlier_shape)
        list(GET declared 1 earlier_directory)
        if(NOT shape STREQUAL earlier_shape)
            message(FATAL_ERROR "pico family: ${variable} is declared twice with "
                "different defaults or values: '${earlier_shape}' by "
                "${earlier_directory} and '${shape}' by "
                "${CMAKE_CURRENT_SOURCE_DIR}. One build has one meaning for it.")
        endif()
        return()
    endif()
    set_property(GLOBAL PROPERTY "PICO_FAMILY_PROFILE_${variable}"
        "${shape};${CMAKE_CURRENT_SOURCE_DIR}")
    if(NOT PICO_FAMILY_PROFILE_DOC)
        set(PICO_FAMILY_PROFILE_DOC "${variable}")
    endif()
    string(REPLACE ";" ", " listed "${PICO_FAMILY_PROFILE_VALUES}")
    set(${variable} "${PICO_FAMILY_PROFILE_DEFAULT}" CACHE STRING
        "${PICO_FAMILY_PROFILE_DOC}: one of ${listed}")
    set_property(CACHE ${variable} PROPERTY STRINGS ${PICO_FAMILY_PROFILE_VALUES})
    if(NOT "${${variable}}" IN_LIST PICO_FAMILY_PROFILE_VALUES)
        message(FATAL_ERROR
            "${variable} must be one of ${listed}; got '${${variable}}'")
    endif()
endfunction()

# Declare <PREFIX>_ENABLE_FIRMWARE_PROBE: the cross-compiled probe image a
# footprint or symbol gate measures. On only for a top-level cross build.
macro(pico_family_declare_probe_option PICO_FAMILY_PREFIX)
    _pico_family_no_extra_arguments("pico_family_declare_probe_option" ${ARGN})
    set(${PICO_FAMILY_PREFIX}_ENABLE_FIRMWARE_PROBE_DEFAULT OFF)
    if(PROJECT_IS_TOP_LEVEL AND CMAKE_CROSSCOMPILING)
        set(${PICO_FAMILY_PREFIX}_ENABLE_FIRMWARE_PROBE_DEFAULT ON)
    endif()
    option(${PICO_FAMILY_PREFIX}_ENABLE_FIRMWARE_PROBE
        "Build the cross-compiled probe image"
        ${${PICO_FAMILY_PREFIX}_ENABLE_FIRMWARE_PROBE_DEFAULT})
endmacro()

# The libnosys stubs that carry a link-time warning. A probe links no SDK
# library, so the C library's syscalls have nothing behind them, and a link that
# warns is a build that warns. Each name is defined as the one stub in
# cross_probe_stub.cpp, by the linker's --defsym, so no C++ source declares a
# name the C library fixes. GNU ld manual, "Command-line Options", --defsym=
# symbol=expression (https://sourceware.org/binutils/docs-2.45/ld/Options.html):
# "Create a global symbol in the output file, containing the absolute address
# given by expression", where the expression may be "the name of an existing
# symbol". The manual states nothing about a symbol that names a function, so
# what a call through one of these names does at run time is UNCONFIRMED; a
# probe is never run. _sbrk and _exit stay with nosys, as the former helper left
# them.
set(_PICO_FAMILY_PROBE_SYSCALLS _chown _close _execve _fork _fstat _getentropy
    _getpid _gettimeofday _isatty _kill _link _lseek _open _read _readlink _stat
    _symlink _times _unlink _wait _write)

# A freestanding cross-compiled image that exists to be measured and to prove the
# headers stand alone. Nothing runs it.
function(pico_family_add_cross_probe PICO_FAMILY_NAME)
    cmake_parse_arguments(PICO_FAMILY_CP "" "PACKAGE;SOURCE" "LIBRARIES" ${ARGN})
    _pico_family_check_arguments(PICO_FAMILY_CP
        "pico_family_add_cross_probe(${PICO_FAMILY_NAME})")
    if(NOT PICO_FAMILY_CP_PACKAGE OR NOT PICO_FAMILY_CP_SOURCE)
        message(FATAL_ERROR "pico_family_add_cross_probe(${PICO_FAMILY_NAME}): "
            "PACKAGE and SOURCE are both required")
    endif()
    get_property(root GLOBAL PROPERTY PICO_FAMILY_ROOT)
    add_executable(${PICO_FAMILY_NAME} ${PICO_FAMILY_CP_SOURCE}
        ${root}/cmake/cross_probe_stub.cpp)
    set_target_properties(${PICO_FAMILY_NAME} PROPERTIES SUFFIX ".elf")
    target_compile_features(${PICO_FAMILY_NAME} PRIVATE cxx_std_20)
    target_link_libraries(${PICO_FAMILY_NAME} PRIVATE
        ${PICO_FAMILY_CP_PACKAGE}_strict ${PICO_FAMILY_CP_LIBRARIES})
    target_compile_options(${PICO_FAMILY_NAME} PRIVATE -fno-exceptions -fno-rtti)
    target_link_options(${PICO_FAMILY_NAME} PRIVATE --specs=nosys.specs)
    foreach(syscall IN LISTS _PICO_FAMILY_PROBE_SYSCALLS)
        target_link_options(${PICO_FAMILY_NAME} PRIVATE
            LINKER:--defsym=${syscall}=pico_family_probe_unsupported)
    endforeach()
endfunction()
