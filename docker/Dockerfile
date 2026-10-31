# Build environment for the Linux port (tools/docker_build.sh drives it).
#
# Arch, like the CachyOS host the binary runs on, so the libraries it links against
# (SDL2, glslang, SPIRV-Tools) are the same ones it loads there. No game data, keys or
# sources go into the image: the xbla folder is mounted at run time.
FROM archlinux:latest

RUN pacman -Syu --noconfirm --needed \
        base-devel clang ninja cmake git python \
        sdl2-compat glslang spirv-tools vulkan-headers \
        libx11 libxi libxext \
    && pacman -Scc --noconfirm

# ps3recomp's Python tools (SPU lift at configure time). Pinned list from its checkout.
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/ps3-venv && /opt/ps3-venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

ENV CC=clang CXX=clang++ PS3_PYTHON=/opt/ps3-venv/bin/python
