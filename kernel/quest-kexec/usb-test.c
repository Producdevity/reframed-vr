// SPDX-License-Identifier: GPL-2.0-only
#include <linux/arm-smccc.h>
#include <linux/cred.h>
#include <linux/efi.h>
#include <linux/hrtimer.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/reboot.h>
#include <linux/string.h>
#include <linux/utsname.h>

#define PREFIX "REFRAMED_QUEST_USB_TEST "
#define GH_CALL(function) ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, \
	ARM_SMCCC_SMC_32, ARM_SMCCC_OWNER_VENDOR_HYP, function)

static bool execute;
module_param(execute, bool, 0400);
static struct device *parent, *child;
static bool parent_pm, child_pm;
static void __iomem *registers;
static struct hrtimer deadline;
static atomic_t expired = ATOMIC_INIT(0);
static bool armed;

static int watchdog_times(u16 bark, u16 bite)
{
	struct arm_smccc_res result;

	arm_smccc_1_1_smc(GH_CALL(8), bark, bite, &result);
	if (result.a0)
		return -EIO;
	arm_smccc_1_1_smc(GH_CALL(7), 0, &result);
	return result.a0 ? -EIO : 0;
}

static enum hrtimer_restart reset_timeout(struct hrtimer *timer)
{
	pr_emerg(PREFIX "test deadline; requesting stock reset\n");
	atomic_set(&expired, 1);
	if (watchdog_times(1, 1))
		emergency_restart();
	return HRTIMER_NORESTART;
}

static int snapshot_get(char *buffer, const struct kernel_param *parameter)
{
	u32 gctl, dctl, devten, dsts;
	bool halted;

	if (!registers)
		return -ENODEV;
	gctl = readl(registers + 0x10);
	dctl = readl(registers + 0x604);
	devten = readl(registers + 0x608);
	dsts = readl(registers + 0x60c);
	halted = ((gctl >> 12) & 3) == 2 && !(dctl & BIT(31)) &&
		 !devten && (dsts & BIT(22));
	return scnprintf(buffer, PAGE_SIZE,
		"gctl=%08x dctl=%08x devten=%08x dsts=%08x halted=%d\n",
		gctl, dctl, devten, dsts, halted);
}

static const struct kernel_param_ops snapshot_ops = {
	.get = snapshot_get,
};
module_param_cb(snapshot, &snapshot_ops, NULL, 0400);

static int finish_set(const char *value, const struct kernel_param *parameter)
{
	u32 gctl, dctl, devten, dsts;

	if (strcmp(value, "1") && strcmp(value, "1\n"))
		return -EINVAL;
	if (!armed || !registers)
		return -EBUSY;
	gctl = readl(registers + 0x10);
	dctl = readl(registers + 0x604);
	devten = readl(registers + 0x608);
	dsts = readl(registers + 0x60c);
	if (((gctl >> 12) & 3) != 2 || !(dctl & BIT(31)) ||
	    !devten || (dsts & BIT(22)))
		return -EBUSY;
	hrtimer_cancel(&deadline);
	if (atomic_read(&expired) || watchdog_times(11000, 14000)) {
		emergency_restart();
		return -EIO;
	}
	armed = false;
	module_put(THIS_MODULE);
	pr_info(PREFIX "gadget running again; deadline disarmed\n");
	return 0;
}

static const struct kernel_param_ops finish_ops = {
	.set = finish_set,
};
module_param_cb(finish, &finish_ops, NULL, 0200);

static void release_devices(void)
{
	if (registers) {
		iounmap(registers);
		registers = NULL;
	}
	if (child_pm)
		pm_runtime_put_sync(child);
	if (parent_pm)
		pm_runtime_put_sync(parent);
	if (child)
		put_device(child);
	if (parent)
		put_device(parent);
}

static int __init usb_test_init(void)
{
	struct resource *resource;
	struct device_node *watchdog;
	struct arm_smccc_res result;
	char snapshot[128];
	int rc;

	if (strcmp(utsname()->release, "5.10.246-gd7102a837402") ||
	    !of_machine_is_compatible("oculus,eureka") ||
	    !of_machine_is_compatible("qcom,anorak"))
		return -ENODEV;
	if (!uid_eq(current_uid(), GLOBAL_ROOT_UID))
		return -EPERM;
	if (efi_enabled(EFI_RUNTIME_SERVICES))
		return -EOPNOTSUPP;
	parent = bus_find_device_by_name(&platform_bus_type, NULL, "a600000.ssusb");
	child = bus_find_device_by_name(&platform_bus_type, NULL, "a600000.dwc3");
	rc = -ENODEV;
	if (!parent || !child || child->parent != parent)
		goto out;
	device_lock(parent);
	if (parent->driver && !strcmp(parent->driver->name, "msm-dwc3"))
		rc = 0;
	device_unlock(parent);
	if (rc)
		goto out;
	device_lock(child);
	if (!child->driver || strcmp(child->driver->name, "dwc3"))
		rc = -ENODEV;
	device_unlock(child);
	if (rc)
		goto out;
	resource = platform_get_resource(to_platform_device(child), IORESOURCE_MEM, 0);
	if (!resource || resource->start != 0xa600000 || resource_size(resource) < 0xc710) {
		rc = -ERANGE;
		goto out;
	}
	pr_info(PREFIX "validated execute=%d parent=msm-dwc3 child=dwc3 resource=%pR\n",
		execute, resource);
	if (!execute) {
		rc = -ECANCELED;
		goto out;
	}
	watchdog = of_find_compatible_node(NULL, NULL, "qcom,gh-watchdog");
	if (!watchdog) {
		rc = -ENODEV;
		goto out;
	}
	of_node_put(watchdog);
	arm_smccc_1_1_smc(GH_CALL(6), 0, &result);
	if (result.a0 || !(result.a1 & 1)) {
		rc = -EIO;
		goto out;
	}
	rc = watchdog_times(44000, 45000);
	if (rc) {
		watchdog_times(11000, 14000);
		goto out;
	}
	hrtimer_init(&deadline, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
	deadline.function = reset_timeout;
	hrtimer_start(&deadline, ms_to_ktime(20000), HRTIMER_MODE_REL);
	rc = pm_runtime_get_sync(parent);
	if (rc < 0) {
		pm_runtime_put_noidle(parent);
		goto cancel;
	}
	parent_pm = true;
	rc = pm_runtime_get_sync(child);
	if (rc < 0) {
		pm_runtime_put_noidle(child);
		goto cancel;
	}
	child_pm = true;
	registers = ioremap(resource->start + 0xc100, 0x610);
	if (!registers) {
		rc = -ENOMEM;
		goto cancel;
	}
	snapshot_get(snapshot, NULL);
	pr_info(PREFIX "armed timeout_ms=20000 %s", snapshot);
	/* Keep PM references until a verified rebind permits normal module removal. */
	__module_get(THIS_MODULE);
	armed = true;
	return 0;
cancel:
	hrtimer_cancel(&deadline);
	if (atomic_read(&expired)) {
		emergency_restart();
		rc = -ETIMEDOUT;
		goto out;
	}
	if (watchdog_times(11000, 14000))
		emergency_restart();
out:
	release_devices();
	return rc;
}

static void __exit usb_test_exit(void)
{
	hrtimer_cancel(&deadline);
	release_devices();
}

module_init(usb_test_init);
module_exit(usb_test_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Eureka bounded USB halt observation with bound platform drivers");
