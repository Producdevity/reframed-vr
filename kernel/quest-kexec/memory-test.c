// SPDX-License-Identifier: GPL-2.0-only
#include <linux/arm-smccc.h>
#include <linux/cred.h>
#include <linux/efi.h>
#include <linux/hrtimer.h>
#include <linux/init.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/reboot.h>
#include <linux/sched/mm.h>
#include <linux/sizes.h>
#include <linux/string.h>
#include <linux/utsname.h>

#define PREFIX "REFRAMED_QUEST_MEMORY_TEST "
#define IMAGE_BYTES (16 * SZ_1M)
#define HEAP_BANKS 24
#define HEAP_ORDER 10
#define MAX_BANKS 64
#define IMAGE_BANKS 4
#define GH_CALL(function) ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, \
	ARM_SMCCC_SMC_32, ARM_SMCCC_OWNER_VENDOR_HYP, function)

static bool execute;
module_param(execute, bool, 0400);
static bool fixture;
module_param(fixture, bool, 0400);
static struct page *banks[MAX_BANKS];
static struct page *dma_banks[2];
static struct hrtimer deadline;
static atomic_t expired = ATOMIC_INIT(0);

static int watchdog_times(u16 bark, u16 bite)
{
	struct arm_smccc_res result;

	arm_smccc_1_1_smc(GH_CALL(8), bark, bite, &result);
	if (result.a0)
		return -EIO;
	arm_smccc_1_1_smc(GH_CALL(7), 0, &result);
	return result.a0 ? -EIO : 0;
}

static enum hrtimer_restart allocation_timeout(struct hrtimer *timer)
{
	pr_emerg(PREFIX "allocation deadline expired; requesting stock reset\n");
	atomic_set(&expired, 1);
	if (watchdog_times(1, 1))
		emergency_restart();
	return HRTIMER_NORESTART;
}

static int check_owned(struct page *pages, unsigned long count)
{
	unsigned long index;
	phys_addr_t base = page_to_phys(pages);

	if (page_count(pages) != 1)
		return -EINVAL;
	for (index = 0; index < count; ++index) {
		struct page *page = pages + index;
		u64 *words = page_address(page);
		u64 pattern = 0x524652414d454452ULL ^ (base + index * PAGE_SIZE);

		if (PageReserved(page))
			return -EINVAL;
		WRITE_ONCE(words[0], pattern);
		WRITE_ONCE(words[PAGE_SIZE / sizeof(*words) - 1], ~pattern);
		if (READ_ONCE(words[0]) != pattern ||
		    READ_ONCE(words[PAGE_SIZE / sizeof(*words) - 1]) != ~pattern)
			return -EIO;
	}
	pr_info(PREFIX "owned start=%pa bytes=%lu allocator=buddy pattern=pass\n",
		&base, count * PAGE_SIZE);
	return 0;
}

static int allocate_and_release(void)
{
	unsigned long noio;
	phys_addr_t base;
	unsigned int index, other, count = 0, image = MAX_BANKS, kept = 0;
	bool selected[MAX_BANKS] = { false };
	int rc = -ENOMEM;

	noio = memalloc_noio_save();
	for (index = 0; index < ARRAY_SIZE(dma_banks); ++index) {
		dma_banks[index] = alloc_pages(GFP_KERNEL | GFP_DMA32 |
				__GFP_NORETRY | __GFP_NOWARN, HEAP_ORDER);
		if (!dma_banks[index])
			goto out;
		if (page_to_phys(dma_banks[index]) +
		    (PAGE_SIZE << HEAP_ORDER) > (1ULL << 32)) {
			rc = -ERANGE;
			goto out;
		}
	}
	for (count = 0; count < MAX_BANKS; ++count) {
		banks[count] = alloc_pages(GFP_KERNEL | __GFP_NORETRY |
					  __GFP_NOWARN, HEAP_ORDER);
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
	pr_info(PREFIX "acquired_banks=%u bank_bytes=%lu\n",
		count, PAGE_SIZE << HEAP_ORDER);
	if (count < IMAGE_BANKS + HEAP_BANKS - ARRAY_SIZE(dma_banks))
		goto out;
	for (index = 0; index + IMAGE_BANKS <= count; ++index) {
		base = page_to_phys(banks[index]);
		for (other = 1; other < IMAGE_BANKS; ++other)
			if (page_to_phys(banks[index + other]) !=
			    base + other * (PAGE_SIZE << HEAP_ORDER))
				break;
		if (other == IMAGE_BANKS) {
			image = index;
			break;
		}
	}
	if (image == MAX_BANKS)
		goto out;
	for (index = image; index < image + IMAGE_BANKS; ++index)
		selected[index] = true;
	for (index = 0; index < count; ++index) {
		if (!selected[index] && kept < HEAP_BANKS - ARRAY_SIZE(dma_banks)) {
			selected[index] = true;
			++kept;
		}
		if (!selected[index]) {
			__free_pages(banks[index], HEAP_ORDER);
			banks[index] = NULL;
		}
	}
	base = page_to_phys(banks[image]);
	pr_info(PREFIX "image start=%pa bytes=%u adjacent_owned_blocks=%u\n",
		&base, IMAGE_BYTES, IMAGE_BANKS);
	for (index = 0; index < count; ++index) {
		if (!banks[index])
			continue;
		rc = check_owned(banks[index], 1UL << HEAP_ORDER);
		if (rc)
			goto out;
	}
	for (index = 0; index < ARRAY_SIZE(dma_banks); ++index) {
		rc = check_owned(dma_banks[index], 1UL << HEAP_ORDER);
		if (rc)
			goto out;
	}
	pr_info(PREFIX "validated image_bytes=%u heap_bytes=%lu dma_bytes=%lu\n",
		IMAGE_BYTES, HEAP_BANKS * (PAGE_SIZE << HEAP_ORDER),
		ARRAY_SIZE(dma_banks) * (PAGE_SIZE << HEAP_ORDER));
out:
	for (index = 0; index < MAX_BANKS; ++index) {
		if (banks[index]) {
			__free_pages(banks[index], HEAP_ORDER);
			banks[index] = NULL;
		}
	}
	for (index = 0; index < ARRAY_SIZE(dma_banks); ++index) {
		if (dma_banks[index]) {
			__free_pages(dma_banks[index], HEAP_ORDER);
			dma_banks[index] = NULL;
		}
	}
	memalloc_noio_restore(noio);
	pr_info(PREFIX "released rc=%d\n", rc);
	return rc;
}

static int __init memory_test_init(void)
{
	struct device_node *watchdog;
	struct arm_smccc_res result;
	u64 started;
	int rc, restore;

	if (strcmp(utsname()->release, "5.10.246-gd7102a837402") ||
	    !of_machine_is_compatible("oculus,eureka") ||
	    !of_machine_is_compatible("qcom,anorak"))
		return -ENODEV;
	if (!uid_eq(current_uid(), GLOBAL_ROOT_UID))
		return -EPERM;
	if (PAGE_SIZE != SZ_4K || MAX_ORDER != 11 || efi_enabled(EFI_RUNTIME_SERVICES))
		return -EOPNOTSUPP;
	watchdog = of_find_compatible_node(NULL, NULL, "qcom,gh-watchdog");
	if (fixture && (watchdog || !of_machine_is_compatible("linux,dummy-virt"))) {
		of_node_put(watchdog);
		return -EPERM;
	}
	if (!fixture && !watchdog)
		return -ENODEV;
	of_node_put(watchdog);
	pr_info(PREFIX "validated execute=%d fixture=%d\n", execute, fixture);
	if (!execute)
		return -ECANCELED;
	if (!fixture) {
		arm_smccc_1_1_smc(GH_CALL(6), 0, &result);
		if (result.a0 || !(result.a1 & 1))
			return -EIO;
		rc = watchdog_times(44000, 45000);
		if (rc) {
			watchdog_times(11000, 14000);
			return rc;
		}
		hrtimer_init(&deadline, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
		deadline.function = allocation_timeout;
		hrtimer_start(&deadline, ms_to_ktime(20000), HRTIMER_MODE_REL);
	}
	started = ktime_get_ns();
	rc = allocate_and_release();
	if (!fixture) {
		hrtimer_cancel(&deadline);
		if (atomic_read(&expired)) {
			emergency_restart();
			return -ETIMEDOUT;
		}
		restore = watchdog_times(11000, 14000);
		if (restore)
			rc = restore;
	}
	pr_info(PREFIX "complete rc=%d elapsed_ns=%llu\n", rc, ktime_get_ns() - started);
	return rc ? rc : -ECANCELED;
}

module_init(memory_test_init);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Eureka owned buddy RAM allocation and release test; no jump");
