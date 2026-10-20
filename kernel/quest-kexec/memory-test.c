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
#include <linux/sizes.h>
#include <linux/string.h>
#include <linux/utsname.h>

#define PREFIX "REFRAMED_QUEST_MEMORY_TEST "
#include "ram.h"
#define GH_CALL(function) ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, \
	ARM_SMCCC_SMC_32, ARM_SMCCC_OWNER_VENDOR_HYP, function)

static bool execute;
module_param(execute, bool, 0400);
static bool fixture;
module_param(fixture, bool, 0400);
static struct reframed_ram ram;
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
	phys_addr_t base;
	unsigned int index;
	int rc = reframed_ram_allocate(&ram);

	if (rc)
		return rc;
	base = page_to_phys(ram.image[0]);
	pr_info(PREFIX "image start=%pa bytes=%u adjacent_owned_blocks=%u\n",
		&base, REFRAMED_RAM_IMAGE_BYTES, REFRAMED_RAM_IMAGE_BANKS);
	for (index = 0; index < ARRAY_SIZE(ram.image); ++index) {
		rc = check_owned(ram.image[index], 1UL << REFRAMED_RAM_ORDER);
		if (rc)
			goto out;
	}
	for (index = 0; index < ARRAY_SIZE(ram.heap); ++index) {
		rc = check_owned(ram.heap[index], 1UL << REFRAMED_RAM_ORDER);
		if (rc)
			goto out;
	}
	pr_info(PREFIX "validated image_bytes=%u heap_bytes=%u dma_bytes=%u\n",
		REFRAMED_RAM_IMAGE_BYTES,
		REFRAMED_RAM_HEAP_BANKS * REFRAMED_RAM_BANK_BYTES,
		2 * REFRAMED_RAM_BANK_BYTES);
out:
	reframed_ram_release(&ram);
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
