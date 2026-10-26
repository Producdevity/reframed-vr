// SPDX-License-Identifier: GPL-2.0-only
#include <linux/arm-smccc.h>
#include <linux/cred.h>
#include <linux/cpu.h>
#include <linux/efi.h>
#include <linux/init.h>
#include <linux/irqflags.h>
#include <linux/limits.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/reboot.h>
#include <linux/string.h>
#include <linux/utsname.h>

#define TEST_COMMAND "reframed-kexec-reset-test"
#define TEST_PREFIX "REFRAMED_QUEST_RESET_TEST "
#define GH_CALL(function) ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, \
	ARM_SMCCC_SMC_32, ARM_SMCCC_OWNER_VENDOR_HYP, function)

static bool execute;
module_param(execute, bool, 0400);
MODULE_PARM_DESC(execute, "Explicitly run the bounded no-jump restart test");

static bool armed;

static int watchdog_deadline(void)
{
	struct arm_smccc_res result;

	/* The stock GH driver uses milliseconds and reserves 0xffff as unchanged. */
	arm_smccc_1_1_smc(GH_CALL(0x0008), 44000, 45000, &result);
	if (result.a0)
		return -EIO;
	arm_smccc_1_1_smc(GH_CALL(0x0007), 0, &result);
	return result.a0 ? -EIO : 0;
}

static int reset_handler(struct notifier_block *notifier, unsigned long mode,
			 void *command)
{
	int rc;

	if (!armed || !command || strcmp(command, TEST_COMMAND))
		return NOTIFY_DONE;
	rc = watchdog_deadline();
	pr_emerg(TEST_PREFIX "late_entry watchdog_rc=%d online=%u irq_disabled=%d\n",
		rc, num_online_cpus(), irqs_disabled());
	if (rc)
		return NOTIFY_DONE;
	/* No kernel jump: this deliberately lets the measured GH deadline expire. */
	for (;;)
		cpu_relax();
}

static struct notifier_block restart_notifier = {
	.notifier_call = reset_handler,
	.priority = INT_MAX,
};

static int __init reset_test_init(void)
{
	struct device_node *watchdog;
	struct arm_smccc_res result;
	int rc;

	if (strcmp(utsname()->release, "5.10.246-gd7102a837402") ||
	    !of_machine_is_compatible("oculus,eureka") ||
	    !of_machine_is_compatible("qcom,anorak"))
		return -ENODEV;
	if (!uid_eq(current_uid(), GLOBAL_ROOT_UID))
		return -EPERM;
	if (efi_enabled(EFI_RUNTIME_SERVICES))
		return -EOPNOTSUPP;
	pr_info(TEST_PREFIX "validated execute=%d efi_runtime=0\n", execute);
	if (!execute)
		return -ECANCELED;
	watchdog = of_find_compatible_node(NULL, NULL, "qcom,gh-watchdog");
	if (!watchdog)
		return -ENODEV;
	of_node_put(watchdog);
	arm_smccc_1_1_smc(GH_CALL(0x0006), 0, &result);
	if (result.a0 || !(result.a1 & 1))
		return -EIO;
	rc = register_restart_handler(&restart_notifier);
	if (rc)
		return rc;
	rc = watchdog_deadline();
	if (rc) {
		unregister_restart_handler(&restart_notifier);
		return rc;
	}
	armed = true;
	pr_emerg(TEST_PREFIX "armed; entering normal kernel restart\n");
	kernel_restart(TEST_COMMAND);
	return -EIO;
}

module_init(reset_test_init);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Eureka no-jump restart-handler and GH deadline rehearsal");
