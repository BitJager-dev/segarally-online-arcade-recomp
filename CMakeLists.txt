cmake_minimum_required(VERSION 3.20)
project(segarally_online_arcade
    VERSION 0.1.0
    LANGUAGES C CXX
    DESCRIPTION "SEGA Rally Online Arcade (PS3) recompiled with ps3recomp"
)

# ---------------------------------------------------------------------------
# Standards
# ---------------------------------------------------------------------------
set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Prefer Ninja if available
if(NOT CMAKE_GENERATOR MATCHES "Ninja" AND NOT DEFINED ENV{CMAKE_GENERATOR})
    message(STATUS "Tip: use -G Ninja for faster builds")
endif()

# ---------------------------------------------------------------------------
# The two directories this project is built from
# ---------------------------------------------------------------------------
# PS3RECOMP_DIR is the toolkit checkout: include/, runtime/, libs/, tools/.
# RECOMP_DIR is where the lifter's output for THIS game lives. They are
# separate on purpose -- a port keeps its generated code in its own tree and
# points at whatever toolkit checkout it is building against:
#
#   cmake -B build -G Ninja \
#         -DPS3RECOMP_DIR=/path/to/ps3recomp \
#         -DRECOMP_DIR=/path/to/my_game/recompiled
#
if(NOT DEFINED PS3RECOMP_DIR)
    # Default: the toolkit checkout next to this repo (../deps/ps3recomp)
    get_filename_component(PS3RECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../deps/ps3recomp" ABSOLUTE)
endif()
get_filename_component(PS3RECOMP_DIR "${PS3RECOMP_DIR}" ABSOLUTE)

set(RECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/generated" CACHE PATH
    "Directory holding the lifter's output: ppu_recomp.h and the lifted sources")
get_filename_component(RECOMP_DIR "${RECOMP_DIR}" ABSOLUTE)

message(STATUS "ps3recomp SDK:   ${PS3RECOMP_DIR}")
message(STATUS "Lifted output:   ${RECOMP_DIR}")

if(NOT EXISTS "${RECOMP_DIR}/ppu_recomp.h")
    message(FATAL_ERROR
        "No ppu_recomp.h in ${RECOMP_DIR}.\n"
        "That header and the lifted sources beside it are what "
        "tools/ppu_lifter.py writes. Run the lifter, drop its output there, "
        "or point -DRECOMP_DIR= at wherever it already is.")
endif()

# The lifted translation units. A game's lift is hundreds of generated files,
# so they are globbed rather than listed; re-run CMake after a fresh lift.
file(GLOB RECOMP_SOURCES CONFIGURE_DEPENDS
    "${RECOMP_DIR}/*.c"
    "${RECOMP_DIR}/*.cpp"
)
if(NOT RECOMP_SOURCES)
    message(FATAL_ERROR
        "${RECOMP_DIR} has a ppu_recomp.h but no .c or .cpp beside it. The "
        "lifted functions and the function table live in those; without them "
        "there is nothing to run.")
endif()
list(LENGTH RECOMP_SOURCES RECOMP_SOURCE_COUNT)
message(STATUS "Lifted sources:  ${RECOMP_SOURCE_COUNT} file(s)")

# ---------------------------------------------------------------------------
# ps3recomp runtime library
# ---------------------------------------------------------------------------
# Built from source as a subdirectory rather than imported as a prebuilt
# archive. A static library carries none of its own link requirements, so an
# imported one arrives without SDL2, pthreads, the Metal frameworks or the
# Winsock/XInput imports -- the link then fails on every platform for a
# different reason. add_subdirectory hands all of that over with the target.
add_subdirectory("${PS3RECOMP_DIR}" "${CMAKE_BINARY_DIR}/ps3recomp_sdk"
                 EXCLUDE_FROM_ALL)

# ---------------------------------------------------------------------------
# The HLE NID table
# ---------------------------------------------------------------------------
# Maps each firmware import NID onto the handler in the runtime that answers
# it. A port may keep a hand-curated one beside its lift; otherwise generate
# the canonical every-module table, which is what the toolkit's own boot
# harness uses.
if(EXISTS "${RECOMP_DIR}/ppu_hle_nids.cpp")
    set(HLE_NID_TABLE "${RECOMP_DIR}/ppu_hle_nids.cpp")
    message(STATUS "HLE NID table:   ${HLE_NID_TABLE}")
else()
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    set(HLE_NID_TABLE "${CMAKE_CURRENT_BINARY_DIR}/ppu_hle_nids.cpp")
    # The generator discovers handlers from library definitions. Rebuild when
    # an existing module changes, and reconfigure when a new module is added.
    file(GLOB_RECURSE HLE_NID_SOURCES CONFIGURE_DEPENDS
        "${PS3RECOMP_DIR}/libs/*.c")
    # A removed input cannot make the output older than a remaining dependency.
    # Track the list itself so deletions also remove stale handler references.
    set(HLE_NID_SOURCE_LIST "${CMAKE_CURRENT_BINARY_DIR}/hle_nid_sources.txt")
    file(GENERATE OUTPUT "${HLE_NID_SOURCE_LIST}" CONTENT "${HLE_NID_SOURCES}\n")
    add_custom_command(
        OUTPUT "${HLE_NID_TABLE}"
        COMMAND "${Python3_EXECUTABLE}"
                "${PS3RECOMP_DIR}/tools/gen_hle_nids.py"
                --out "${HLE_NID_TABLE}" --all
        DEPENDS "${PS3RECOMP_DIR}/tools/gen_hle_nids.py"
                "${PS3RECOMP_DIR}/tools/nid_database.py"
                ${HLE_NID_SOURCES} "${HLE_NID_SOURCE_LIST}"
        COMMENT "Generating the HLE NID -> handler table")
    message(STATUS "HLE NID table:   generated (every module)")
endif()

# ---------------------------------------------------------------------------
# The game executable
# ---------------------------------------------------------------------------
# The PPU boot scaffold is compiled here rather than taken from the runtime
# library: every one of these files #includes the lifter's per-game
# ppu_recomp.h, so they can only be built against a particular lift.
set(PS3RECOMP_SCAFFOLD
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_loader.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_hle.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_fs.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_sysprx.cpp"
)

# ---------------------------------------------------------------------------
# Lifted SPU images (optional)
# ---------------------------------------------------------------------------
# A title that runs SPU work gets its images lifted into <SPU_DIR>/<image>/ by
# tools/spu_lifter.py, with a registration TU generated by
# tools/build_spu_workloads.py. cellSpurs dispatches them by content
# fingerprint, so the generated table is keyed to the images THIS build ships:
# a table generated from another release registers signatures that can never
# match, which is worse than shipping none. Both the table and the job-module
# registry self-register from constructors and are therefore optional -- a tree
# that has not lifted its SPU images yet configures and links without them.
set(SPU_DIR "${CMAKE_CURRENT_SOURCE_DIR}/spu" CACHE PATH
    "Directory holding the lifted SPU images (<SPU_DIR>/<image>/spu_recomp.c)")
option(PORT_ENABLE_SPU "Compile and register the title's lifted SPU images" ON)

set(PORT_SPU_INPUTS "" CACHE STRING
    "Input files to scan for all embedded SPU ELF programs (semicolon-separated decrypted ELF/PRX/data paths)")
set(SPU_SOURCES "")
if(PORT_ENABLE_SPU AND PORT_SPU_INPUTS)
    # ps3recomp_generate_spu() (cmake/PS3RecompSPU.cmake) with --allow-partial: one of this
    # game's six SPU images has string/float data inside what the function finder takes for
    # code, so it lifts with ".word" placeholders and the strict helper then registers none of
    # the six. Partial registration keeps the five clean images.
    set(_spu_out "${CMAKE_CURRENT_BINARY_DIR}/generated_spu")
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    set(_spu_cmd "${Python3_EXECUTABLE}" "${PS3RECOMP_DIR}/tools/build_spu_workloads.py"
        --lifted "${_spu_out}" --out "${_spu_out}/spu_workloads.c" --constructor --allow-partial)
    # The MultiStream audio program (the 69 KB image): its code range holds data, and it
    # calls into flashATRAC.pic, which it loads from /dev_flash at run time. Lift it anyway:
    # the data words stay traps that never run, and calls out of the image are dispatched at
    # run time (interpreted until that code is lifted too).
    set(PORT_SPU_RUNTIME_CODE "spu_4671d2e3de50519b2a162e089634d3a05973ff53ebe68df393a5d03b03db6f13"
        CACHE STRING "SPU programs (content names) lifted with --runtime-code")
    foreach(name IN LISTS PORT_SPU_RUNTIME_CODE)
        list(APPEND _spu_cmd --runtime-code "${name}")
    endforeach()
    foreach(input IN LISTS PORT_SPU_INPUTS)
        get_filename_component(input "${input}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        list(APPEND _spu_cmd --input "${input}")
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${input}")
    endforeach()
    foreach(tool IN ITEMS build_spu_workloads.py spu_program_pipeline.py spu_lifter.py find_spu_functions.py)
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${PS3RECOMP_DIR}/tools/${tool}")
    endforeach()
    execute_process(COMMAND ${_spu_cmd} RESULT_VARIABLE _spu_rc OUTPUT_VARIABLE _spu_log ERROR_VARIABLE _spu_err)
    message(STATUS "SPU: ${_spu_log}")
    if(NOT _spu_rc EQUAL 0 OR NOT EXISTS "${_spu_out}/sources.cmake")
        message(FATAL_ERROR "SPU generation failed. Inspect ${_spu_out}/inventory.json.\n${_spu_log}\n${_spu_err}")
    endif()
    include("${_spu_out}/sources.cmake")
    list(APPEND SPU_SOURCES ${SPU_GENERATED_SOURCES}
         "${PS3RECOMP_DIR}/runtime/spu/spu_dispatch_mt.c")

    # The code MultiStream loads at run time: flashATRAC.pic from your firmware's /dev_flash
    # and two of the game's own SPU images, lifted at the local-store addresses they run at
    # (tools/lift_spu_overlays.py). Without the firmware they are interpreted (slowly: the
    # sound then breaks up).
    set(PORT_FLASH_ATRAC_PIC "${CMAKE_CURRENT_SOURCE_DIR}/../deps/ps3fw/root/dev_flash/sys/external/flashATRAC.pic"
        CACHE FILEPATH "flashATRAC.pic from the firmware's /dev_flash")
    set(PORT_SPU_IMAGES_DIR "${CMAKE_CURRENT_SOURCE_DIR}/analysis/spu_programs"
        CACHE PATH "The extracted SPU images (tools/build_linux.sh writes them)")
    if(EXISTS "${PORT_FLASH_ATRAC_PIC}" AND EXISTS "${PORT_SPU_IMAGES_DIR}")
        set(_ovl_out "${CMAKE_CURRENT_BINARY_DIR}/generated_spu_ovl")
        execute_process(COMMAND "${Python3_EXECUTABLE}" -I "${CMAKE_CURRENT_SOURCE_DIR}/tools/lift_spu_overlays.py"
                                --pic "${PORT_FLASH_ATRAC_PIC}" --spu-dir "${PORT_SPU_IMAGES_DIR}"
                                --out "${_ovl_out}" --tools "${PS3RECOMP_DIR}/tools"
                        RESULT_VARIABLE _ovl_rc OUTPUT_VARIABLE _ovl_log ERROR_VARIABLE _ovl_err)
        if(NOT _ovl_rc EQUAL 0)
            message(FATAL_ERROR "SPU overlay lifting failed:\n${_ovl_log}\n${_ovl_err}")
        endif()
        message(STATUS "SPU overlays: ${_ovl_log}")
        include("${_ovl_out}/sources.cmake")
        list(APPEND SPU_SOURCES ${SPU_OVERLAY_SOURCES})
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
                     "${PORT_FLASH_ATRAC_PIC}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/lift_spu_overlays.py")
    else()
        message(STATUS "SPU overlays: no ${PORT_FLASH_ATRAC_PIC} -- MultiStream's run-time code is interpreted")
    endif()
elseif(PORT_ENABLE_SPU)
    file(GLOB SPU_LIFTED CONFIGURE_DEPENDS "${SPU_DIR}/*/spu_recomp.c")
    if(SPU_LIFTED)
        list(LENGTH SPU_LIFTED SPU_IMAGE_COUNT)
        message(STATUS "Lifted SPU:      ${SPU_IMAGE_COUNT} image(s)")
        # The musttail indirect-branch fast path. Excluded from the runtime
        # library on purpose (see the SDK root CMakeLists): it must be built
        # here, by clang, or the tail call degrades to a plain call and a guest
        # loop that branches indirectly walks the thread stack off its guard
        # page a few thousand iterations in.
        list(APPEND SPU_SOURCES ${SPU_LIFTED}
             "${PS3RECOMP_DIR}/runtime/spu/spu_dispatch_mt.c")
        # Generated beside the lift; each is present only once its generator
        # has been run, so each is included only if it is actually here.
        foreach(gen IN ITEMS spu_workloads.c jobmods_register.c taskset_policy_bytes.c)
            if(EXISTS "${SPU_DIR}/${gen}")
                list(APPEND SPU_SOURCES "${SPU_DIR}/${gen}")
            else()
                message(STATUS "  (no ${gen} -- not registered)")
            endif()
        endforeach()
    else()
        message(STATUS "Lifted SPU:      none found in ${SPU_DIR}")
    endif()
endif()

add_executable(${PROJECT_NAME}
    main.cpp
    stubs.cpp
    ${PS3RECOMP_SCAFFOLD}
    ${HLE_NID_TABLE}
    ${RECOMP_SOURCES}
    ${SPU_SOURCES}
)

# The lifted SPU sources use bare #include "spu_context.h". Scope that include
# directory (and their flags) to those TUs alone: adding it to the whole target
# changes the compile command of every lifted PPU TU, and those are large enough
# that the needless rebuild is measured in tens of minutes.
#   SPU_USE_DISPATCH_MT -- route SPU_IB_DISPATCH through the musttail path.
#   -O2                 -- the target-wide -O1 exists for the huge PPU TUs; the
#                          SPU sources are small and decode-hot, so they get
#                          full optimization. The last -O on the line wins.
if(SPU_SOURCES)
    set_source_files_properties(${SPU_SOURCES} PROPERTIES
        INCLUDE_DIRECTORIES "${PS3RECOMP_DIR}/runtime/spu"
        COMPILE_DEFINITIONS SPU_USE_DISPATCH_MT)
    # PORT_SPU_X86_LEVEL: the x86-64 level the SPU code is built for. The SPU helpers have
    # SSE4.1 paths (shufb and the integer ops) and AVX2 paths (the float ops, exact to the
    # SPU's rounding); below them they fall back to per-byte/per-lane C, several times
    # slower. The audio mixer (MultiStream) needs the AVX2 paths to keep up in real time.
    set(PORT_SPU_X86_LEVEL "x86-64-v3" CACHE STRING
        "-march level for the lifted SPU code (x86-64-v3 = AVX2, Haswell/Zen and later; x86-64-v2 = SSE4.2)")
    if(NOT MSVC OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64|amd64" AND PORT_SPU_X86_LEVEL)
            set_source_files_properties(${SPU_SOURCES} PROPERTIES COMPILE_OPTIONS "-O2;-march=${PORT_SPU_X86_LEVEL}")
        else()
            set_source_files_properties(${SPU_SOURCES} PROPERTIES COMPILE_OPTIONS "-O2")
        endif()
    endif()
    # PORT_SPU_AUDIO_FAST_FLOAT: the audio program (MultiStream, image spu_4671d2e3...) and the
    # code it loads at run time use the host's float add/multiply/FMA instead of the exact SPU
    # rounding (SPU_FLOAT_FAST in spu_helpers.h): its ATRAC decoder is all float butterflies,
    # and with the exact ops a Ryzen 7840HS decoded ~80% of real time (the sound broke up). The
    # difference is the last bit of a sample. Every other SPU program keeps the exact ops.
    option(PORT_SPU_AUDIO_FAST_FLOAT "Native float ops for the audio SPU code" ON)
    if(PORT_SPU_AUDIO_FAST_FLOAT)
        set(_audio_spu ${SPU_SOURCES})
        list(FILTER _audio_spu INCLUDE REGEX "spu_4671d2e3|generated_spu_ovl/")
        set_property(SOURCE ${_audio_spu} APPEND PROPERTY COMPILE_DEFINITIONS SPU_FLOAT_FAST)
    endif()
endif()

# app.rc carries the icon, the version block and the manifest, and needs a
# resource compiler. Listing it as a source on a host that has none is not a
# link error, it is a "no rule to make" for a file nothing can consume.
if(WIN32 AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/app.rc")
    target_sources(${PROJECT_NAME} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/app.rc")
endif()

target_include_directories(${PROJECT_NAME} PRIVATE
    "${RECOMP_DIR}"                            # the generated ppu_recomp.h
    "${PS3RECOMP_DIR}/include"
    "${PS3RECOMP_DIR}/runtime/ppu"
    "${PS3RECOMP_DIR}/runtime/spu"
    "${PS3RECOMP_DIR}/runtime/memory"
    "${PS3RECOMP_DIR}/runtime/syscalls"
    "${PS3RECOMP_DIR}/runtime/platform"        # win32_compat.h and friends
    "${PS3RECOMP_DIR}/libs/video"
    "${CMAKE_CURRENT_SOURCE_DIR}"
)

# The whole program at the SPU code's x86-64 level (AVX2 + FMA, PORT_SPU_X86_LEVEL). The lifted PPU
# code's AltiVec helpers use fmaf per lane, which at the default x86-64 level is a libm call in
# software: vmaddfp alone was a third of SEGA Rally's main thread.
if(NOT MSVC AND CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64|amd64" AND PORT_SPU_X86_LEVEL)
    target_compile_options(${PROJECT_NAME} PRIVATE -march=${PORT_SPU_X86_LEVEL})
    target_compile_options(ps3recomp_runtime PRIVATE -march=${PORT_SPU_X86_LEVEL})
endif()

# PORT_ASAN=ON: AddressSanitizer for the runtime, the SPU code and the runner -- not the
# lifted PPU code (huge, and guest memory is not the host heap). A diagnostic build, in
# its own build directory.
option(PORT_ASAN "AddressSanitizer on the runtime and SPU code (diagnostic builds)" OFF)
if(PORT_ASAN AND NOT MSVC)
    target_compile_options(ps3recomp_runtime PRIVATE -fsanitize=address -fno-omit-frame-pointer)
    set_property(SOURCE ${SPU_SOURCES} main.cpp stubs.cpp APPEND PROPERTY COMPILE_OPTIONS
                 -fsanitize=address -fno-omit-frame-pointer)
    target_link_options(${PROJECT_NAME} PRIVATE -fsanitize=address)
endif()

# PORT_RUNTIME_DEBUGINFO=ON: line tables for the runtime only (profiling: a gdb sample then
# names the line in the draw engine, not just the function). The optimisation stays.
option(PORT_RUNTIME_DEBUGINFO "Debug line info for the runtime (profiling)" OFF)
if(PORT_RUNTIME_DEBUGINFO AND NOT MSVC)
    target_compile_options(ps3recomp_runtime PRIVATE -g)
endif()

target_link_libraries(${PROJECT_NAME} PRIVATE
    ps3recomp_runtime
)

# The runtime is C++, and on Apple also Objective-C. Letting CMake infer the
# link language from the generated C would leave the C++ standard library out.
set_target_properties(${PROJECT_NAME} PROPERTIES LINKER_LANGUAGE CXX)

# Windows system import libraries. dbghelp symbolizes crash-handler addresses
# against the PDB, user32 and gdi32 are what the backend's window and its GDI
# present are made of, and winmm is timeBeginPeriod. None of the four names
# anything a POSIX linker can find; the D3D12 backend's own imports come in
# through the #pragma comment(lib) in libs/video/rsx_d3d12_backend.c.
if(WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE
        dbghelp
        user32
        gdi32
        winmm
    )
endif()

# ---------------------------------------------------------------------------
# Compiler-specific flags
# ---------------------------------------------------------------------------
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(${PROJECT_NAME} PRIVATE
        -Wall -Wextra -Wno-unused-parameter
        -fno-strict-aliasing
        # The lift spells PPC arithmetic as signed C arithmetic, which must wrap;
        # without this, clang exploits overflow UB (e.g. folds "x*x < 0" to false).
        -fwrapv
        # The target-wide -O1 the SPU note above relies on, for a build whose
        # configuration sets no optimisation level (no CMAKE_BUILD_TYPE, or one
        # CMake has no defaults for). Without it every lifted PPU TU compiled at
        # -O0: each static inline helper (ppc_rlw64, vmx_w, vm_read32_inl) is a
        # real call that spills to the stack, and those calls were most of the
        # PPU thread's profile. -O1 keeps the huge TUs' build time sane. Debug
        # and the optimised configurations keep their own levels.
        $<$<NOT:$<CONFIG:Debug,Release,RelWithDebInfo,MinSizeRel>>:-O1>
    )
elseif(MSVC)
    target_compile_options(${PROJECT_NAME} PRIVATE
        /W3 /wd4100 /wd4244 /wd4267
        /Zc:__cplusplus         # report correct __cplusplus value
        # ppu_recomp.h defines PPU_FENCE, the lowering of the guest's
        # sync/lwsync/eieio/isync, and in C that is <stdatomic.h>. The lifter
        # writes C++ by default, but --single-file writes ppu_recomp.c, and a
        # port that took it would not compile without this. The runtime's own
        # build already carries the same flag for the same reason.
        /experimental:c11atomics
    )
    target_compile_definitions(${PROJECT_NAME} PRIVATE
        _CRT_SECURE_NO_WARNINGS
    )
endif()

# The lifted translation units are machine-generated and can run to hundreds of
# thousands of lines each, so they get their own flags:
#
#   - warnings off. They are about generated code and nobody will act on them,
#     and at this volume they bury the diagnostics that matter.
#   - no floating-point contraction. arm64 fuses a multiply and an add by
#     default; a PPC fmadd is spelt as one where the lifter means one.
#   - /bigobj on MSVC. A single lifted file routinely passes the 65,536-section
#     limit of the default object format.
if(MSVC)
    set_source_files_properties(${RECOMP_SOURCES} PROPERTIES
        COMPILE_OPTIONS "/w;/bigobj")
else()
    set_source_files_properties(${RECOMP_SOURCES} PROPERTIES
        COMPILE_OPTIONS "-w;-ffp-contract=off")
endif()

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
install(TARGETS ${PROJECT_NAME} RUNTIME DESTINATION bin)

# ---------------------------------------------------------------------------
# The window launcher (macOS)
# ---------------------------------------------------------------------------
# A title that replaces its executable (sys_game_process_exitspawn, done by a
# port as an exec) loses its window with the old process image. The launcher
# holds the window for the whole session instead: it runs the port with
# PS3RECOMP_HOST_SURFACES set, the Metal backend renders into IOSurfaces it
# shares (libs/video/rsx_host_surface.h), and the image an exec brings up
# attaches to the same window again. One Objective-C file and no runtime
# library, so it builds in seconds:
#
#   ./MyGameRecomp_window [--title T] [--size WxH] -- ./MyGameRecomp <args>
if(APPLE)
    enable_language(OBJC)
    add_executable(${PROJECT_NAME}_window "${PS3RECOMP_DIR}/tools/host_window/host_window.m")
    target_include_directories(${PROJECT_NAME}_window PRIVATE "${PS3RECOMP_DIR}/libs/video")
    target_compile_definitions(${PROJECT_NAME}_window PRIVATE HOST_WINDOW_TITLE="${PROJECT_NAME}")
    target_compile_options(${PROJECT_NAME}_window PRIVATE -fobjc-arc -Wall -Wextra -Wno-unused-parameter)
    target_link_libraries(${PROJECT_NAME}_window PRIVATE
        "-framework AppKit" "-framework Metal" "-framework QuartzCore" "-framework IOSurface")
    install(TARGETS ${PROJECT_NAME}_window RUNTIME DESTINATION bin)
endif()
