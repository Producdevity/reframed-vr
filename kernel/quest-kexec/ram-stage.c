// SPDX-License-Identifier: GPL-2.0-only
#include <linux/arm-smccc.h>
#include <linux/cred.h>
#include <linux/efi.h>
#include <linux/hrtimer.h>
#include <linux/init.h>
#include <linux/kobject.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/reboot.h>
#include <linux/string.h>
#include <linux/sysfs.h>
#include <linux/utsname.h>

#include <asm/sysreg.h>

#include "ram.h"

#define PREFIX "REFRAMED_QUEST_RAM_STAGE "
#define GH_CALL(function) ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, \
	ARM_SMCCC_SMC_32, ARM_SMCCC_OWNER_VENDOR_HYP, function)

static bool stage;
module_param(stage, bool, 0400);
static bool fixture;
module_param(fixture, bool, 0400);
static struct reframed_ram ram;
static struct kobject *object;
static DEFINE_MUTEX(payload_lock);
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
	atomic_set(&expired, 1);
	if (watchdog_times(1, 1))
		emergency_restart();
	return HRTIMER_NORESTART;
}

static ssize_t info_show(struct kobject *kobj, struct kobj_attribute *attribute,
			 char *buffer)
{
	phys_addr_t base = page_to_phys(ram.image[0]);
	unsigned int index;
	int size;

	size = scnprintf(buffer, PAGE_SIZE,
		"{\"image_start\":\"%pa\",\"image_bytes\":%u,\"heap\":[",
		&base, REFRAMED_RAM_IMAGE_BYTES);
	for (index = 0; index < ARRAY_SIZE(ram.heap); ++index) {
		base = page_to_phys(ram.heap[index]);
		size += scnprintf(buffer + size, PAGE_SIZE - size,
			"%s{\"start\":\"%pa\",\"bytes\":%u}", index ? "," : "",
			&base, REFRAMED_RAM_BANK_BYTES);
	}
	return size + scnprintf(buffer + size, PAGE_SIZE - size, "]}\n");
}

static struct kobj_attribute info_attribute = __ATTR(info, 0400, info_show, NULL);

static ssize_t payload_read(struct file *file, struct kobject *kobj,
			    struct bin_attribute *attribute, char *buffer,
			    loff_t offset, size_t count)
{
	if (offset < 0)
		return -EINVAL;
	if (offset >= REFRAMED_RAM_IMAGE_BYTES)
		return 0;
	count = min_t(size_t, count, REFRAMED_RAM_IMAGE_BYTES - offset);
	mutex_lock(&payload_lock);
	memcpy(buffer, (char *)page_address(ram.image[0]) + offset, count);
	mutex_unlock(&payload_lock);
	return count;
}

static ssize_t payload_write(struct file *file, struct kobject *kobj,
			     struct bin_attribute *attribute, char *buffer,
			     loff_t offset, size_t count)
{
	if (offset < 0 || offset > REFRAMED_RAM_IMAGE_BYTES ||
	    count > REFRAMED_RAM_IMAGE_BYTES - offset)
		return -EFBIG;
	mutex_lock(&payload_lock);
	memcpy((char *)page_address(ram.image[0]) + offset, buffer, count);
	mutex_unlock(&payload_lock);
	return count;
}

static BIN_ATTR(payload, 0600, payload_read, payload_write, REFRAMED_RAM_IMAGE_BYTES);

static int __init ram_stage_init(void)
{
	struct device_node *watchdog;
	struct arm_smccc_res result;
	unsigned int index;
	int rc;

	if (strcmp(utsname()->release, "5.10.246-gd7102a837402") ||
	    !of_machine_is_compatible("oculus,eureka") ||
	    !of_machine_is_compatible("qcom,anorak"))
		return -ENODEV;
	if (!uid_eq(current_uid(), GLOBAL_ROOT_UID))
		return -EPERM;
	if (PAGE_SIZE != SZ_4K || MAX_ORDER != 11 || read_sysreg(CurrentEL) != 4 ||
	    efi_enabled(EFI_RUNTIME_SERVICES))
		return -EOPNOTSUPP;
	watchdog = of_find_compatible_node(NULL, NULL, "qcom,gh-watchdog");
	if (fixture && (watchdog || !of_machine_is_compatible("linux,dummy-virt"))) {
		of_node_put(watchdog);
		return -EPERM;
	}
	if (!fixture && !watchdog)
		return -ENODEV;
	of_node_put(watchdog);
	pr_info(PREFIX "validated stage=%d fixture=%d\n", stage, fixture);
	if (!stage)
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
	rc = reframed_ram_allocate(&ram);
	if (!rc) {
		memset(page_address(ram.image[0]), 0, REFRAMED_RAM_IMAGE_BYTES);
		for (index = 0; index < ARRAY_SIZE(ram.heap); ++index)
			memset(page_address(ram.heap[index]), 0, REFRAMED_RAM_BANK_BYTES);
	}
	if (!fixture) {
		hrtimer_cancel(&deadline);
		if (atomic_read(&expired) || watchdog_times(11000, 14000)) {
			emergency_restart();
			rc = -EIO;
		}
	}
	if (rc)
		goto out;
	object = kobject_create_and_add("reframed_quest_ram", kernel_kobj);
	if (!object) {
		rc = -ENOMEM;
		goto out;
	}
	rc = sysfs_create_file(object, &info_attribute.attr);
	if (rc)
		goto put;
	rc = sysfs_create_bin_file(object, &bin_attr_payload);
	if (rc) {
		sysfs_remove_file(object, &info_attribute.attr);
		goto put;
	}
	pr_info(PREFIX "ready image_bytes=%u heap_bytes=%u; no jump path\n",
		REFRAMED_RAM_IMAGE_BYTES, REFRAMED_RAM_HEAP_BANKS * REFRAMED_RAM_BANK_BYTES);
	return 0;
put:
	kobject_put(object);
out:
	reframed_ram_release(&ram);
	return rc;
}

static void __exit ram_stage_exit(void)
{
	sysfs_remove_bin_file(object, &bin_attr_payload);
	sysfs_remove_file(object, &info_attribute.attr);
	kobject_put(object);
	reframed_ram_release(&ram);
	pr_info(PREFIX "released\n");
}

module_init(ram_stage_init);
module_exit(ram_stage_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Eureka root-only owned RAM payload staging; no kernel jump");
