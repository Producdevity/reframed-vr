/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef REFRAMED_QUEST_RAM_H
#define REFRAMED_QUEST_RAM_H

#include <linux/mm.h>
#include <linux/sizes.h>

#define REFRAMED_RAM_ORDER 10
#define REFRAMED_RAM_IMAGE_BANKS 4
#define REFRAMED_RAM_HEAP_BANKS 24
#define REFRAMED_RAM_IMAGE_BYTES (16 * SZ_1M)
#define REFRAMED_RAM_BANK_BYTES (4 * SZ_1M)

struct reframed_ram {
	struct page *image[REFRAMED_RAM_IMAGE_BANKS];
	struct page *heap[REFRAMED_RAM_HEAP_BANKS];
};

int reframed_ram_allocate(struct reframed_ram *ram);
void reframed_ram_release(struct reframed_ram *ram);

#endif
