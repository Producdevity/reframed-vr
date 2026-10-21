// SPDX-License-Identifier: GPL-2.0-only
#include <linux/sched/mm.h>
#include <linux/string.h>

#include "ram.h"

#define MAX_BANKS 64

void reframed_ram_release(struct reframed_ram *ram)
{
	unsigned int index;

	for (index = 0; index < ARRAY_SIZE(ram->image); ++index) {
		if (ram->image[index]) {
			__free_pages(ram->image[index], REFRAMED_RAM_ORDER);
			ram->image[index] = NULL;
		}
	}
	for (index = 0; index < ARRAY_SIZE(ram->heap); ++index) {
		if (ram->heap[index]) {
			__free_pages(ram->heap[index], REFRAMED_RAM_ORDER);
			ram->heap[index] = NULL;
		}
	}
}

int reframed_ram_allocate(struct reframed_ram *ram)
{
	struct page *banks[MAX_BANKS] = { NULL };
	unsigned long noio;
	phys_addr_t base;
	unsigned int index, other, count, image = MAX_BANKS, heap = 2;
	int rc = -ENOMEM;

	memset(ram, 0, sizeof(*ram));
	noio = memalloc_noio_save();
	for (index = 0; index < 2; ++index) {
		ram->heap[index] = alloc_pages(GFP_KERNEL | GFP_DMA32 |
				__GFP_NORETRY | __GFP_NOWARN, REFRAMED_RAM_ORDER);
		if (!ram->heap[index])
			goto out;
		if (page_to_phys(ram->heap[index]) + REFRAMED_RAM_BANK_BYTES > (1ULL << 32)) {
			rc = -ERANGE;
			goto out;
		}
	}
	for (count = 0; count < MAX_BANKS; ++count) {
		banks[count] = alloc_pages(GFP_KERNEL | __GFP_NORETRY | __GFP_NOWARN,
					  REFRAMED_RAM_ORDER);
		if (!banks[count])
			break;
	}
	for (index = 1; index < count; ++index) {
		struct page *page = banks[index];

		other = index;
		while (other && page_to_phys(banks[other - 1]) > page_to_phys(page)) {
			banks[other] = banks[other - 1];
			--other;
		}
		banks[other] = page;
	}
	pr_info("REFRAMED_QUEST_RAM acquired_banks=%u\n", count);
	if (count < REFRAMED_RAM_IMAGE_BANKS + REFRAMED_RAM_HEAP_BANKS - 2)
		goto out;
	for (index = 0; index + REFRAMED_RAM_IMAGE_BANKS <= count; ++index) {
		base = page_to_phys(banks[index]);
		for (other = 1; other < REFRAMED_RAM_IMAGE_BANKS; ++other)
			if (page_to_phys(banks[index + other]) !=
			    base + other * REFRAMED_RAM_BANK_BYTES)
				break;
		if (other == REFRAMED_RAM_IMAGE_BANKS) {
			image = index;
			break;
		}
	}
	if (image == MAX_BANKS)
		goto out;
	for (index = 0; index < REFRAMED_RAM_IMAGE_BANKS; ++index) {
		ram->image[index] = banks[image + index];
		banks[image + index] = NULL;
	}
	for (index = 0; index < count && heap < REFRAMED_RAM_HEAP_BANKS; ++index) {
		if (banks[index]) {
			ram->heap[heap++] = banks[index];
			banks[index] = NULL;
		}
	}
	rc = 0;
out:
	for (index = 0; index < MAX_BANKS; ++index)
		if (banks[index])
			__free_pages(banks[index], REFRAMED_RAM_ORDER);
	if (rc)
		reframed_ram_release(ram);
	memalloc_noio_restore(noio);
	return rc;
}
