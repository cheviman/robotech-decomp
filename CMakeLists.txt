# Name:        CMakeLists.txt
# Description: build of Robotech: Battlecry recompiled with xboxrecomp (the game's executable and the
#              toolkit's runtime libraries)
# Version:     0.1.0
# Created:     25-10-2026
# Modified:    26-10-2026
# Author:      Sebastian Toyos
#
# Started from xboxrecomp's templates/new-game/CMakeLists.txt (MIT, see licenses/xboxrecomp.txt). The
# toolkit is expected next to this repo (../xboxrecomp); override XBOXRECOMP_DIR otherwise.
cmake_minimum_required(VERSION 3.20)

project(robotech_battlecry C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Common definitions
add_compile_definitions(
    WIN32_LEAN_AND_MEAN
    NOMINMAX
)

# Record every indirect-call target the game reaches, and dump them on exit or
# on a crash: tools/pipeline.py feeds them back to the disassembler as function
# starts it could not find on its own (xboxrecomp's icall feedback). Set before
# the toolkit is added, because its kernel library records them too.
option(ROBOTECH_ICALL_FEEDBACK "Record the game's indirect-call targets" ON)
if(ROBOTECH_ICALL_FEEDBACK)
    add_compile_definitions(
        RECOMP_ICALL_FEEDBACK
        RECOMP_ICALL_FEEDBACK_PATH="analysis/icall_targets.dump"
    )
endif()

# ── xboxrecomp toolkit ──────────────────────────────────────────
#
# Option A: xboxrecomp as a subdirectory (simplest)
#   Place xboxrecomp/ next to your game project and use a relative path.
#
# Option B: find_package (if you install xboxrecomp system-wide)
#   find_package(xboxrecomp REQUIRED)
#
# Adjust this path to point to your xboxrecomp clone:
set(XBOXRECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../xboxrecomp" CACHE PATH
    "Path to the xboxrecomp toolkit root directory")

# Add xboxrecomp as a subdirectory -- this builds all 6 runtime libraries
# and provides the 'xboxrecomp' umbrella target to link against.
add_subdirectory(${XBOXRECOMP_DIR} ${CMAKE_BINARY_DIR}/xboxrecomp)

# ── Recompiled game executable ──────────────────────────────────

# Collect generated recompiled code.
# The recomp pipeline outputs files into src/recomp/gen/, laid out by subject in
# folders (tools/organize_gen.py: engine/vcTexture.c, xdk/d3d8.c...), hence
# GLOB_RECURSE.
# CONFIGURE_DEPENDS so re-running the recompiler picks up added/removed files
# without a manual re-configure. A plain GLOB is evaluated once at configure
# time, so a newly generated file (an extra chunk, recomp_stubs_unresolved.c)
# is silently left out of the build and shows up as unresolved externals.
file(GLOB_RECURSE RECOMP_GEN_SOURCES CONFIGURE_DEPENDS "src/recomp/gen/*.c")

# The game's functions written by hand (src/game/, by subject), each in its
# recompiled version's place
file(GLOB_RECURSE GAME_HAND_SOURCES CONFIGURE_DEPENDS "src/game/*.c")

# Core game sources
set(GAME_SOURCES
    ${GAME_HAND_SOURCES}
    src/main.c
    src/recomp_manual.c
    src/d3d11_bridge.c
    src/input_bridge.c
    src/dsound_bridge.c
    src/sound_mixer.c
    src/clock_bridge.c
    # Add game-specific sources here, e.g.:
    # src/asset_loader.c
    # src/custom_renderer.c
)

# The recomp pipeline also generates a dispatch header and function declarations.
# These are included by the generated .c files:
#   src/recomp/gen/recomp_funcs.h    - extern declarations for all recompiled functions
#   src/recomp/recomp_dispatch.h     - binary search dispatch table
#   src/recomp/recomp_types.h        - register model, ICALL macros, MEM helpers

add_executable(${PROJECT_NAME} WIN32
    ${GAME_SOURCES}
    ${RECOMP_GEN_SOURCES}
)

# Link against the xboxrecomp umbrella target (all 6 runtime libraries)
target_link_libraries(${PROJECT_NAME} PRIVATE xboxrecomp)

# Include paths for generated recomp headers
target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/src/recomp
    # recomp_funcs.h, for the generated files laid out in folders below it
    ${CMAKE_CURRENT_SOURCE_DIR}/src/recomp/gen
    # decomp.h, for the C written by hand
    ${CMAKE_CURRENT_SOURCE_DIR}/src/game
    ${XBOXRECOMP_DIR}/include
)

# Windows SDK libraries needed at link time
target_link_libraries(${PROJECT_NAME} PRIVATE
    d3d11
    dxgi
    dxguid
    $<IF:$<BOOL:${MINGW}>,xinput1_4,xinput>   # see src/input/CMakeLists.txt
    winmm
    # Lets the fault handler resolve the host RIP back to the generated
    # function's symbol, i.e. to the guest function that faulted.
    dbghelp
)

# MSVC-specific: large address aware, increase section limit for big generated files
if(MSVC)
    target_link_options(${PROJECT_NAME} PRIVATE
        /LARGEADDRESSAWARE
    )
    # The generated code files can be very large. Increase object file section limit.
    # /MP6: the generated chunks are one project, so MSBuild would compile them
    # one at a time; six at once is half of the 12-thread dev machine.
    target_compile_options(${PROJECT_NAME} PRIVATE /bigobj /MP6)
    # C4113 as an error: CALL(name, ...) handed a function written by hand, which takes its arguments
    # in C, would run it with none; a function becomes written by hand and its calls must change.
    target_compile_options(${PROJECT_NAME} PRIVATE /we4113)
endif()

# ── Game-specific additions ─────────────────────────────────────
#
# Add any game-specific libraries, loaders, or custom renderers below.
# Examples:
#
# # Custom texture loader for your game's format
# target_sources(${PROJECT_NAME} PRIVATE src/texture_loader.c)
#
# # If your game uses RenderWare, you may need a RW bridge layer
# target_sources(${PROJECT_NAME} PRIVATE src/rw_bridge.c)
#
# # Additional compile definitions for debugging
# target_compile_definitions(${PROJECT_NAME} PRIVATE
#     ENABLE_ICALL_TRACE=1
#     VERBOSE_KERNEL_LOG=1
# )
