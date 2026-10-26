// SPDX-License-Identifier: GPL-2.0-only
#include <crypto/sha.h>
#include <linux/arm-smccc.h>
#include <linux/cpu.h>
#include <linux/hrtimer.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/limits.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/reboot.h>
#include <linux/string.h>
#include <linux/sysfs.h>

#include <asm/cpufeature.h>
#include <asm/memory.h>
#include <asm/pgtable-hwdef.h>
#include <asm/unaligned.h>

#include "stage.h"

#define PREFIX "REFRAMED_QUEST_BOOT "
#define COMMAND "reframed-ram-usb"
#define GH_CALL(function) ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, \
	ARM_SMCCC_SMC_32, ARM_SMCCC_OWNER_VENDOR_HYP, function)

extern void reframed_clean_poc(void *address, size_t size, u64 line_size);
extern void reframed_enter(u64 root, u64 code, u64 image, u64 dtb);
extern char reframed_phys_enter[], reframed_phys_enter_end[];

static struct device *parent, *child;
static bool parent_pm, child_pm, armed;
static void __iomem *registers;
static unsigned long control, tables[3];
static u64 dtb_address, cache_line;
static struct hrtimer deadline;

static int watchdog_times(u16 bark, u16 bite)
{
	struct arm_smccc_res result;

	arm_smccc_1_1_smc(GH_CALL(8), bark, bite, &result);
	if (result.a0)
		return -EIO;
	arm_smccc_1_1_smc(GH_CALL(7), 0, &result);
	return result.a0 ? -EIO : 0;
}

static enum hrtimer_restart shutdown_timeout(struct hrtimer *timer)
{
	if (watchdog_times(1, 1))
		emergency_restart();
	return HRTIMER_NORESTART;
}

static bool usb_halted(void)
{
	u32 gctl, dctl, devten, dsts;

	if (reframed_stage.fixture)
		return true;
	if (!registers)
		return false;
	gctl = readl(registers + 0x10);
	dctl = readl(registers + 0x604);
	devten = readl(registers + 0x608);
	dsts = readl(registers + 0x60c);
	return ((gctl >> 12) & 3) == 2 && !(dctl & BIT(31)) &&
		!devten && (dsts & BIT(22));
}

static int restart_handler(struct notifier_block *notifier, unsigned long mode,
			   void *command)
{
	unsigned int index;
	void *image = page_address(reframed_stage.ram.image[0]);

	if (!armed || !command || strcmp(command, COMMAND))
		return NOTIFY_DONE;
	if (num_online_cpus() != 1 || smp_processor_id() != 0 ||
	    !irqs_disabled() || !usb_halted()) {
		pr_emerg(PREFIX "late gate refused; returning to stock reset handlers\n");
		return NOTIFY_DONE;
	}
	if (!reframed_stage.fixture && watchdog_times(44000, 45000))
		return NOTIFY_DONE;
	pr_emerg(PREFIX "late_gate=pass; entering owned RAM Image\n");
	reframed_clean_poc(image, REFRAMED_RAM_IMAGE_BYTES, cache_line);
	for (index = 0; index < ARRAY_SIZE(reframed_stage.ram.heap); ++index)
		reframed_clean_poc(page_address(reframed_stage.ram.heap[index]),
			REFRAMED_RAM_BANK_BYTES, cache_line);
	reframed_clean_poc((void *)control, PAGE_SIZE, cache_line);
	for (index = 0; index < ARRAY_SIZE(tables); ++index)
		reframed_clean_poc((void *)tables[index], PAGE_SIZE, cache_line);
	reframed_enter(virt_to_phys((void *)tables[0]),
		virt_to_phys((void *)control), virt_to_phys(image), dtb_address);
	return NOTIFY_DONE;
}

static struct notifier_block restart_notifier = {
	.notifier_call = restart_handler,
	.priority = INT_MAX,
};

static int prepare_control(void)
{
	u64 *root, *middle, *leaf;
	phys_addr_t address;
	unsigned int index;
	size_t bytes = (unsigned long)reframed_phys_enter_end -
		       (unsigned long)reframed_phys_enter;

	cache_line = 4ULL << ((read_sanitised_ftr_reg(SYS_CTR_EL0) >> 16) & 15);
	if (!bytes || bytes > PAGE_SIZE || cache_line > PAGE_SIZE)
		return -E2BIG;
	control = get_zeroed_page(GFP_KERNEL | __GFP_NORETRY);
	if (!control)
		return -ENOMEM;
	for (index = 0; index < ARRAY_SIZE(tables); ++index) {
		tables[index] = get_zeroed_page(GFP_KERNEL | __GFP_NORETRY);
		if (!tables[index])
			return -ENOMEM;
	}
	address = virt_to_phys((void *)control);
	if (address >= 1ULL << 39)
		return -ERANGE;
	root = (u64 *)tables[0];
	middle = (u64 *)tables[1];
	leaf = (u64 *)tables[2];
	root[(address >> 30) & 511] = virt_to_phys(middle) | PUD_TYPE_TABLE;
	middle[(address >> 21) & 511] = virt_to_phys(leaf) | PMD_TYPE_TABLE;
	leaf[(address >> 12) & 511] = address | PTE_TYPE_PAGE | PTE_AF |
		PTE_SHARED | PTE_RDONLY | PTE_UXN | PTE_ATTRINDX(MT_NORMAL);
	memcpy((void *)control, reframed_phys_enter, bytes);
	return 0;
}

static int prepare_usb(void)
{
	struct resource *resource;
	int rc;

	if (reframed_stage.fixture)
		return 0;
	parent = bus_find_device_by_name(&platform_bus_type, NULL, "a600000.ssusb");
	child = bus_find_device_by_name(&platform_bus_type, NULL, "a600000.dwc3");
	if (!parent || !child || child->parent != parent)
		return -ENODEV;
	device_lock(parent);
	rc = parent->driver && !strcmp(parent->driver->name, "msm-dwc3") ? 0 : -ENODEV;
	device_unlock(parent);
	if (rc)
		return rc;
	device_lock(child);
	rc = child->driver && !strcmp(child->driver->name, "dwc3") ? 0 : -ENODEV;
	device_unlock(child);
	if (rc)
		return rc;
	resource = platform_get_resource(to_platform_device(child), IORESOURCE_MEM, 0);
	if (!resource || resource->start != 0xa600000 || resource_size(resource) < 0xc710)
		return -ERANGE;
	rc = pm_runtime_get_sync(parent);
	if (rc < 0) {
		pm_runtime_put_noidle(parent);
		return rc;
	}
	parent_pm = true;
	rc = pm_runtime_get_sync(child);
	if (rc < 0) {
		pm_runtime_put_noidle(child);
		return rc;
	}
	child_pm = true;
	registers = ioremap(resource->start + 0xc100, 0x610);
	return registers ? 0 : -ENOMEM;
}

static void release_control(void)
{
	unsigned int index;

	if (registers)
		iounmap(registers);
	if (child_pm)
		pm_runtime_put_sync(child);
	if (parent_pm)
		pm_runtime_put_sync(parent);
	if (child)
		put_device(child);
	if (parent)
		put_device(parent);
	for (index = 0; index < ARRAY_SIZE(tables); ++index)
		if (tables[index])
			free_page(tables[index]);
	if (control)
		free_page(control);
}

static ssize_t status_show(struct kobject *object, struct kobj_attribute *attribute,
			   char *buffer)
{
	return scnprintf(buffer, PAGE_SIZE, "fixture=%d usb_halted=%d sealed=%d armed=%d\n",
		reframed_stage.fixture, usb_halted(), reframed_stage.sealed, armed);
}

static ssize_t launch_store(struct kobject *object, struct kobj_attribute *attribute,
			    const char *buffer, size_t count)
{
	char hexadecimal[65], extra;
	u8 expected[SHA256_DIGEST_SIZE], actual[SHA256_DIGEST_SIZE];
	u8 *image = page_address(reframed_stage.ram.image[0]);
	unsigned long offset;
	u64 extent;
	u32 dtb_bytes;
	int rc;

	if (sscanf(buffer, "%lx %64s %c", &offset, hexadecimal, &extra) != 2 ||
	    strlen(hexadecimal) != 64 || hex2bin(expected, hexadecimal, sizeof(expected)))
		return -EINVAL;
	if (!cpu_online(0) || offset % PAGE_SIZE || offset > REFRAMED_RAM_IMAGE_BYTES - 40)
		return -ERANGE;
	mutex_lock(&reframed_stage.lock);
	rc = -EBUSY;
	if (reframed_stage.sealed || !usb_halted())
		goto out;
	extent = get_unaligned_le64(image + 16);
	dtb_bytes = get_unaligned_be32(image + offset + 4);
	rc = -EINVAL;
	if (memcmp(image + 56, "ARM\x64", 4) || get_unaligned_le64(image + 8) ||
	    get_unaligned_le64(image + 24) != 0xa || extent < 64 || extent > offset ||
	    get_unaligned_be32(image + offset) != 0xd00dfeed || dtb_bytes < 40 ||
	    dtb_bytes > SZ_2M || dtb_bytes > REFRAMED_RAM_IMAGE_BYTES - offset)
		goto out;
	sha256(image, REFRAMED_RAM_IMAGE_BYTES, actual);
	rc = -EBADMSG;
	if (memcmp(actual, expected, sizeof(actual)))
		goto out;
	dtb_address = page_to_phys(reframed_stage.ram.image[0]) + offset;
	if (!reframed_stage.fixture) {
		rc = watchdog_times(44000, 45000);
		if (rc) {
			watchdog_times(11000, 14000);
			goto out;
		}
		hrtimer_init(&deadline, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
		deadline.function = shutdown_timeout;
		hrtimer_start(&deadline, ms_to_ktime(20000), HRTIMER_MODE_REL);
	}
	reframed_stage.sealed = true;
	__module_get(THIS_MODULE);
	armed = true;
	pr_emerg(PREFIX "payload hash verified; entering normal restart\n");
	kernel_restart(COMMAND);
	for (;;)
		cpu_relax();
out:
	mutex_unlock(&reframed_stage.lock);
	return rc;
}

static struct kobj_attribute status_attribute = __ATTR(status, 0400, status_show, NULL);
static struct kobj_attribute launch_attribute = __ATTR(launch, 0200, NULL, launch_store);

static int __init boot_init(void)
{
	int rc = reframed_stage_init();

	if (rc)
		return rc;
	rc = prepare_control();
	if (rc)
		goto release;
	rc = prepare_usb();
	if (rc)
		goto release;
	rc = register_restart_handler(&restart_notifier);
	if (rc)
		goto release;
	rc = sysfs_create_file(reframed_stage.object, &status_attribute.attr);
	if (rc)
		goto unregister;
	rc = sysfs_create_file(reframed_stage.object, &launch_attribute.attr);
	if (!rc)
		return 0;
	sysfs_remove_file(reframed_stage.object, &status_attribute.attr);
unregister:
	unregister_restart_handler(&restart_notifier);
release:
	release_control();
	reframed_stage_exit();
	return rc;
}

static void __exit boot_exit(void)
{
	sysfs_remove_file(reframed_stage.object, &launch_attribute.attr);
	sysfs_remove_file(reframed_stage.object, &status_attribute.attr);
	unregister_restart_handler(&restart_notifier);
	release_control();
	reframed_stage_exit();
}

module_init(boot_init);
module_exit(boot_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Eureka owned RAM Image handoff with bounded stock return");
