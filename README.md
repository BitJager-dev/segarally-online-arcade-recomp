# SEGA Rally Online Arcade Recompiled (PS3)

Work in progress: static recompilation of **SEGA Rally Online Arcade** (PlayStation 3 PSN, SEGA 2011; NPUB30375,
content ID `UP0177-NPUB30375_00-SEGARALLYARCADE1`, update 1.01) to native PC, using
[ps3recomp](https://github.com/sp00nznet/ps3recomp).

This is the PS3 release, not the Xbox 360 XBLA one, so it does not use the ReXGlue SDK like the After Burner
Climax and OutRun recomps. ps3recomp is much younger than ReXGlue: so far it boots titles to gameplay on
Windows only (Linux/macOS compile the per-game boot code but have not run a title from the upstream tree).

**No game data is included.** You need your own PSN package (`.pkg`) and license (`.RAP`).

Progress and known problems are tracked in the [issues](https://github.com/BitJager-dev/segarally-online-arcade-recomp/issues).

## Status
| Step | State |
|---|---|
| Extract the PKG (base + 1.01 update) | done: `tools/ps3_pkg_extract.py` |
| Decrypt `EBOOT.BIN` (retail NPDRM SELF, key rev 0x10 in 1.01) | done: `tools/ps3_unself.py` -> `game/EBOOT.elf` (PPC64, entry 0x5D26F0) |
| Analysis, function finding, PPU lift (`tools/recomp_pipeline.sh`) | done: 25,339 functions, 1,215 HLE handlers |
| Game project (CMake from ps3recomp's template), Linux build + test boot | builds (container); plays the intro movie, the menus and a full race with its replay (Vulkan, game shaders) |
| SPU programs | 6 of 6 lifted, plus the code the audio program loads at run time (below) |
| Audio | plays: the MultiStream SPU program, the ATRAC decoder it loads from `/dev_flash` (`flashATRAC.pic`) and three of the game's SPU images it swaps in are lifted at the addresses they run at (`tools/lift_spu_overlays.py`) |

## Building (Linux)
`tools/build_linux.sh` configures and builds `out/linux/segarally_online_arcade`, stages the game data as
`run/dev_hdd0/game/NPUB30375` (base + 1.01; `PS3_HDD0_ROOT`), and boots it for 60 s into `logs/boot.log`.
Needs clang, ninja, SDL2; install `vulkan-headers` for the Vulkan renderer (otherwise the headless null
renderer). `JOBS=` sets parallel compiles (default 6: each lifted file is ~600k lines).

Requirements to run: an x86-64 CPU with AVX2 (Intel Haswell / AMD Zen or later; the SPU code is built for
x86-64-v3, `PORT_SPU_X86_LEVEL`: with SSE4.2 only the audio mixer cannot keep up and the sound breaks up), a
Vulkan GPU, and your firmware's `/dev_flash` (below) for sound.

## Building in a container
`tools/docker_build.sh` builds in `docker/Dockerfile` (Arch, the same clang, glslang, SPIRV-Tools and SDL2 as the
CachyOS host) into `out/linux-docker`, then runs the test boot on the host, which has the GPU, display and controller.
The `xbla` folder is mounted at its own path and the container runs as you. `--no-run` builds only; `--shell` opens a
shell in the build environment. The image is rebuilt when the Dockerfile or ps3recomp's Python requirements change.

## Getting the ELF
`tools/setup_ps3.sh` does everything: it decrypts the 1.01 `EBOOT.BIN` with your `.RAP` (no RPCS3 needed; the
keys are read from RPCS3's open-source `key_vault.cpp`/`.h`, downloaded to `../deps/rpcs3src`, never stored here),
sets up ps3recomp's Python environment and runs `tools/recomp_pipeline.sh`. Log: `setup_ps3.log`.

Firmware: `tools/ps3_pup_devflash.py PS3UPDAT.PUP ../deps/ps3fw/root --keys ../deps/rpcs3src` installs `/dev_flash`
(same RPCS3 key source as the EBOOT); `build_linux.sh` uses it when present, and the build lifts the audio
decoder from it (without it there is no sound).

`USRDIR/KEY.EDAT` is NPDRM-encrypted data the game reads at runtime; the port's `cellFs`/EDAT layer has to
decrypt it with the same license.

## Layout
| Path | What |
|---|---|
| `tools/ps3_pkg_extract.py` | Retail PS3 PKG extractor (AES-128-CTR; the package key is read from RPCS3's `key_vault.h`; system `cryptography` module) |
| `tools/ps3_unself.py` | NPDRM SELF -> ELF with the title's RAP (port of RPCS3's `unself.cpp`; keys loaded from RPCS3's source at run time) |
| `tools/ps3_pup_devflash.py` | `/dev_flash` from an official `PS3UPDAT.PUP` (port of RPCS3's firmware installer) |
| `tools/setup_ps3.sh` | One-shot setup: decrypt, Python environment, pipeline |
| `tools/recomp_pipeline.sh` | ps3recomp phases 3-5: ELF/imports, functions, SPU images, PPU lift |
| `tools/lift_spu_overlays.py` | Lifts the code the MultiStream audio program loads at run time, at the addresses it runs at (run by CMake) |
| `patches/` | ps3recomp fixes for this title (against ps3recomp `4e8f3ca`), applied by `build_linux.sh`: lifting SPU programs with data in their code and calls into run-time code (`--runtime-code`, `spu_lifter --external-calls`), lifted run-time overlays checked against local store (`spu_overlay_register_static`), real-time audio mixing on Linux (one block every 5.33 ms on the clock, a few ms of patience for a late writer, `PS3_AUDIO_BUF_MS`), native float ops for the audio SPU program's ATRAC decoder (`PORT_SPU_AUDIO_FAST_FLOAT`, twice as fast; the exact SPU rounding left a Ryzen 7840HS decoding ~80% of real time), a present that no longer waits for the GPU (the walker records the next frame meanwhile; `VK_PRESENT_SYNC=1` for the old wait), a converted-vertex cache (`ENG_VTX_CACHE`), blocked event waits deliver GCM callbacks (Linux), SPU group thread slots, answers for a stopped audio SPU, Vulkan 3D textures, ZPASS pixel counts (occlusion queries), a window swapchain on Wayland drivers that list over 64 surface formats (RADV), a flip-time ring wrap that no longer overwrites commands the GPU has not read, flips that complete one at a time after the GPU has run past them (the main loop no longer needs `EVT_RECV_KICK`), cellVoice notify queues (its thread blocks instead of spinning), SPU job workers that back off while they poll an unchanged line (`SPU_POLL_SPIN`), `sys_mempool_*`, `cellUsbdRegisterExtraLdd2`, `UTF8stoUCS2s` and the sceNp custom-menu calls (registered in `stubs.cpp`, since the NID generator only picks up cell*/sce*/sys* names) |
| `tools/docker_build.sh`, `docker/Dockerfile` | Container build environment |
| `game/` | Your decrypted `EBOOT.elf` (not in git) |
| `analysis/`, `generated/` | Pipeline output (not in git). The HLE NID table is generated by CMake in the build tree, so new handlers in ps3recomp are picked up on the next build |

Expected next to this folder: `../deps/ps3recomp` (toolkit checkout), `../deps/ps3-venv` (its Python deps),
`../deps/segarally_ps3/{pkg,game,update}` (your package and its extracted files).

## Disclaimer
Unofficial fan project, not affiliated with or endorsed by SEGA or Sony. Contains no game data.
