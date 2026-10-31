/*
 * ps3recomp game project -- game-specific hooks and overrides.
 *
 * main.cpp is the runner and is game-agnostic. This file is where a port puts
 * everything that is not: the PRX loading hook it must answer, overrides for
 * firmware functions the HLE library gets wrong for this title, and patches
 * over recompiled code.
 *
 * It starts out as the empty version of all of that, which is what a game with
 * no lifted PRX and no overrides needs.
 */

#include <cstdio>
#include <cstring>
#include <cstdint>

#include "ps3emu/ps3types.h"
#include "ps3emu/error_codes.h"

/* ---------------------------------------------------------------------------
 * PRX loading
 *
 * main.cpp calls this once, after the lifted function table is registered and
 * vm_base is live, before the game runs. A title that lifts a real system PRX
 * -- libsre, which is cellSpurs and cellSync -- loads its image into guest RAM
 * here and registers its exports. Most ports never need to: the HLE library
 * answers those modules instead.
 * -----------------------------------------------------------------------*/

extern "C" void ps3_hle_register(uint32_t nid, const char* name, void* handler);
extern "C" uint8_t* vm_base;   /* host pointer = vm_base + guest address */

static void guest_write32(uint32_t addr, uint32_t v)   /* guest memory is big-endian */
{
    uint8_t* p = vm_base + addr;
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;
}

/* cellSpursGetSpuThreadId (NID 0x6C960F6D) has no handler in the HLE library. The game
 * calls it right after cellSpursInitialize, for its spu_printf server to attach to the
 * SPURS SPU threads. HLE SPURS runs no real SPU threads, so report none: *nThreads = 0. */
static int32_t sr_cellSpursGetSpuThreadId(uint32_t spurs, uint32_t thread, uint32_t nThreads)
{
    (void)thread;
    if (!spurs || !nThreads)
        return (int32_t)0x80410711;   /* CELL_SPURS_CORE_ERROR_NULL_POINTER */
    guest_write32(nThreads, 0);
    return CELL_OK;
}

/* cellL10n's UTF8stoUCS2s (NID 0xFDBF6AC5) is implemented in libs/font/cellL10n.c, but
 * gen_hle_nids.py only registers functions named cell*, sce* or sys*, so the cellL10n
 * converters never reach the table. Register this one by hand. */
extern "C" s32 UTF8stoUCS2s(u32 src_ea, u32 src_len_ea, u32 dst_ea, u32 dst_len_ea);

/* Runs before ppu_hle_init(); the generated table has no entry for these NIDs, so
 * registering them first does not collide with anything. */
extern "C" void ps3_load_prx_modules(void)
{
    ps3_hle_register(0x6C960F6Du, "cellSpursGetSpuThreadId", (void*)sr_cellSpursGetSpuThreadId);
    ps3_hle_register(0xFDBF6AC5u, "UTF8stoUCS2s", (void*)UTF8stoUCS2s);
}

/* ---------------------------------------------------------------------------
 * Example: Override a specific NID
 *
 * The module system resolves function imports by NID.  To replace a default
 * HLE stub with custom logic, register your function at init time.
 * -----------------------------------------------------------------------*/

/*
 * Example: override cellGcmSetFlipMode (NID 0xA53D12AE) to force vsync.
 *
 *   static void my_cellGcmSetFlipMode(u32 mode)
 *   {
 *       printf("[hook] cellGcmSetFlipMode: forcing VSYNC (was %u)\n", mode);
 *       // Force vsync regardless of what the game requested
 *       cellGcmSetFlipMode(CELL_GCM_DISPLAY_VSYNC);
 *   }
 *
 * Then in your init code:
 *
 *   ps3::modules::override_nid(0xA53D12AE,
 *       reinterpret_cast<void*>(my_cellGcmSetFlipMode));
 */

/* ---------------------------------------------------------------------------
 * Example: Hook into module loading
 *
 * You can intercept cellSysmoduleLoadModule to perform custom actions
 * when a particular module is loaded.
 * -----------------------------------------------------------------------*/

/*
 *   static s32 my_loadmodule_hook(u16 id)
 *   {
 *       printf("[hook] Module 0x%04X loaded\n", id);
 *
 *       if (id == CELL_SYSMODULE_AUDIO) {
 *           // Perform custom audio backend initialization
 *           init_my_audio_backend();
 *       }
 *
 *       // Call the original implementation
 *       return cellSysmoduleLoadModule(id);
 *   }
 */

/* ---------------------------------------------------------------------------
 * Game-specific patches
 *
 * Sometimes you need to patch recompiled code at specific addresses.
 * Use the patch system to modify behavior without editing generated code.
 * -----------------------------------------------------------------------*/

/*
 *   // Skip an integrity check at guest address 0x00812FA0
 *   ps3::patches::nop_range(0x00812FA0, 0x00812FB0);
 *
 *   // Replace a function call with a direct return
 *   ps3::patches::force_return(0x009A1000, 0);  // return 0
 */
