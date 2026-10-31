# SEGA Rally Online Arcade Recompiled (PS3)

Work in progress: static recompilation of **SEGA Rally Online Arcade** (PlayStation 3 PSN, SEGA 2011; NPUB30375,
content ID `UP0177-NPUB30375_00-SEGARALLYARCADE1`, update 1.01) to native PC, using
[ps3recomp](https://github.com/sp00nznet/ps3recomp).

This is the PS3 release, not the Xbox 360 XBLA one, so it does not use the ReXGlue SDK like the After Burner
Climax and OutRun recomps. ps3recomp is much younger than ReXGlue: so far it boots titles to gameplay on
Windows only (Linux/macOS compile the per-game boot code but have not run a title from the upstream tree).

**No game data is included.** You need your own PSN package (`.pkg`) and license (`.RAP`).

## Status
| Step | State |
|---|---|
| Extract the PKG (base + 1.01 update) | done: `tools/ps3_pkg_extract.py` |
| Decrypt `EBOOT.BIN` (retail NPDRM SELF, key rev 0x10 in 1.01) | done: `tools/ps3_unself.py` -> `game/EBOOT.elf` (PPC64, entry 0x5D26F0) |
| Analysis, function finding, PPU lift (`tools/recomp_pipeline.sh`) | done: 25,339 functions, 1,215 HLE handlers |
| Game project (CMake from ps3recomp's template), Linux build + test boot | builds (container); boots past the intro (skipped) through the menus into a race that renders correctly past one minute (Vulkan, game shaders) |
| SPU programs | 5 of 6 lifted and registered; the 69 KB one has data inside its code |
| Audio: the Multistream SPU program (the 69 KB image) calls into `flashATRAC.pic`, firmware SPU code it loads at run time, so that code has to be lifted at its load address too. Until then `SPU_MB_ACK` answers its commands (no sound) and the intro movie is skipped | next |

## Building (Linux)
`tools/build_linux.sh` configures and builds `out/linux/segarally_online_arcade`, stages the game data as
`run/dev_hdd0/game/NPUB30375` (base + 1.01; `PS3_HDD0_ROOT`), and boots it for 60 s into `logs/boot.log`.
Needs clang, ninja, SDL2; install `vulkan-headers` for the Vulkan renderer (otherwise the headless null
renderer). `JOBS=` sets parallel compiles (default 6: each lifted file is ~600k lines).

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
(same RPCS3 key source as the EBOOT); `build_linux.sh` uses it when present.

`USRDIR/KEY.EDAT` is NPDRM-encrypted data the game reads at runtime; the port's `cellFs`/EDAT layer has to
decrypt it with the same license.

## Layout
| Path | What |
|---|---|
| `tools/ps3_pkg_extract.py` | Retail PS3 PKG extractor (AES-128-CTR; the package key is read from RPCS3's `key_vault.h`; system `cryptography` module) |
| `tools/ps3_unself.py` | NPDRM SELF -> ELF with the title's RAP (port of RPCS3's `unself.cpp`; keys loaded from RPCS3's source at run time) |
| `tools/ps3_pup_devflash.py` | `/dev_flash` from an official `PS3UPDAT.PUP` (port of RPCS3's firmware installer) |
| `tools/setup_ps3.sh` | One-shot setup: decrypt, Python environment, pipeline |
| `tools/recomp_pipeline.sh` | ps3recomp phases 3-5: ELF/imports, functions, SPU images, PPU lift, HLE table |
| `patches/` | ps3recomp runtime fixes for this title, applied by `build_linux.sh`: blocked event waits deliver GCM callbacks (Linux), SPU group thread slots, answers for a stopped audio SPU, Vulkan 3D textures, ZPASS pixel counts (occlusion queries), a flip-time ring wrap that no longer overwrites commands the GPU has not read, cellVoice notify queues (its thread blocks instead of spinning) |
| `tools/docker_build.sh`, `docker/Dockerfile` | Container build environment |
| `game/` | Your decrypted `EBOOT.elf` (not in git) |
| `analysis/`, `generated/` | Pipeline output (not in git) |

Expected next to this folder: `../deps/ps3recomp` (toolkit checkout), `../deps/ps3-venv` (its Python deps),
`../deps/segarally_ps3/{pkg,game,update}` (your package and its extracted files).

## Disclaimer
Unofficial fan project, not affiliated with or endorsed by SEGA or Sony. Contains no game data.
