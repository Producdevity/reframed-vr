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
#include <linux/stop_machine.h>
#include <linux/string.h>
#include <linux/utsname.h>

#include <asm/memory.h>
#include <asm/cpufeature.h>
#include <asm/pgtable-hwdef.h>
#include <asm/sysreg.h>

#define PREFIX "REFRAMED_QUEST_MMU_TEST "
#define GH_CALL(function) ARM_SMCCC_CALL_VAL(ARM_SMCCC_FAST_CALL, \
	ARM_SMCCC_SMC_32, ARM_SMCCC_OWNER_VENDOR_HYP, function)

struct physical_result {
	u64 pc;
	u64 flags;
};

extern void reframed_clean_poc(void *address, size_t size, u64 line_size);
extern struct physical_result reframed_mmu_roundtrip(u64 root, u64 entry);
extern char reframed_phys_probe[], reframed_phys_pc[], reframed_phys_probe_end[];

static bool execute;
module_param(execute, bool, 0400);
static bool fixture;
module_param(fixture, bool, 0400);
static unsigned long control, tables[3];
static struct physical_result result;
static bool context_restored;
static bool entered;
static struct hrtimer deadline;
static atomic_t expired = ATOMIC_INIT(0);

static int watchdog_times(u16 bark, u16 bite)
{
	struct arm_smccc_res response;

	arm_smccc_1_1_smc(GH_CALL(8), bark, bite, &response);
	if (response.a0)
		return -EIO;
	arm_smccc_1_1_smc(GH_CALL(7), 0, &response);
	return response.a0 ? -EIO : 0;
}

static enum hrtimer_restart test_timeout(struct hrtimer *timer)
{
	atomic_set(&expired, 1);
	if (watchdog_times(1, 1))
		emergency_restart();
	return HRTIMER_NORESTART;
}

static int roundtrip(void *unused)
{
	u64 tcr = read_sysreg(tcr_el1), ttbr = read_sysreg(ttbr0_el1);
	u64 sctlr = read_sysreg(sctlr_el1), daif = read_sysreg(daif);
	u64 scs_before, scs_after;

	asm volatile("mov %0, x18" : "=r" (scs_before));
	entered = true;
	result = reframed_mmu_roundtrip(virt_to_phys((void *)tables[0]),
					virt_to_phys((void *)control));
	asm volatile("mov %0, x18" : "=r" (scs_after));
	context_restored = tcr == read_sysreg(tcr_el1) &&
		ttbr == read_sysreg(ttbr0_el1) && sctlr == read_sysreg(sctlr_el1) &&
		daif == read_sysreg(daif) && scs_before == scs_after;
	return context_restored ? 0 : -EIO;
}

static int prepare_pages(void)
{
	u64 *root, *middle, *leaf;
	phys_addr_t address;
	unsigned int index;
	u64 line_size = 4ULL << ((read_sanitised_ftr_reg(SYS_CTR_EL0) >> 16) & 15);
	size_t bytes = (unsigned long)reframed_phys_probe_end -
		       (unsigned long)reframed_phys_probe;

	if (!bytes || bytes > PAGE_SIZE || line_size > PAGE_SIZE)
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
	if (address >= (1ULL << 39))
		return -ERANGE;
	root = (u64 *)tables[0];
	middle = (u64 *)tables[1];
	leaf = (u64 *)tables[2];
	root[(address >> 30) & 511] = virt_to_phys(middle) | PUD_TYPE_TABLE;
	middle[(address >> 21) & 511] = virt_to_phys(leaf) | PMD_TYPE_TABLE;
	leaf[(address >> 12) & 511] = address | PTE_TYPE_PAGE | PTE_AF |
		PTE_SHARED | PTE_RDONLY | PTE_UXN | PTE_ATTRINDX(MT_NORMAL);
	memcpy((void *)control, reframed_phys_probe, bytes);
	reframed_clean_poc((void *)control, PAGE_SIZE, line_size);
	for (index = 0; index < ARRAY_SIZE(tables); ++index)
		reframed_clean_poc((void *)tables[index], PAGE_SIZE, line_size);
	return 0;
}

static void release_pages(void)
{
	unsigned int index;

	for (index = 0; index < ARRAY_SIZE(tables); ++index)
		if (tables[index])
			free_page(tables[index]);
	if (control)
		free_page(control);
}

static int __init mmu_test_init(void)
{
	struct device_node *watchdog;
	struct arm_smccc_res response;
	u64 expected, started;
	int rc;

	if (strcmp(utsname()->release, "5.10.246-gd7102a837402") ||
	    !of_machine_is_compatible("oculus,eureka") ||
	    !of_machine_is_compatible("qcom,anorak"))
		return -ENODEV;
	if (!uid_eq(current_uid(), GLOBAL_ROOT_UID))
		return -EPERM;
	if (PAGE_SIZE != SZ_4K || efi_enabled(EFI_RUNTIME_SERVICES) ||
	    read_sysreg(CurrentEL) != 4 || !cpu_online(0))
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
	rc = prepare_pages();
	if (rc)
		goto out;
	if (!fixture) {
		arm_smccc_1_1_smc(GH_CALL(6), 0, &response);
		if (response.a0 || !(response.a1 & 1)) {
			rc = -EIO;
			goto out;
		}
		rc = watchdog_times(44000, 45000);
		if (rc) {
			watchdog_times(11000, 14000);
			goto out;
		}
		hrtimer_init(&deadline, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
		deadline.function = test_timeout;
		hrtimer_start(&deadline, ms_to_ktime(20000), HRTIMER_MODE_REL);
	}
	started = ktime_get_ns();
	rc = stop_machine(roundtrip, NULL, cpumask_of(0));
	if (!fixture) {
		hrtimer_cancel(&deadline);
		if (atomic_read(&expired) || (entered && !context_restored) ||
		    watchdog_times(11000, 14000)) {
			emergency_restart();
			rc = -EIO;
			goto out;
		}
	}
	expected = virt_to_phys((void *)control) +
		(unsigned long)reframed_phys_pc - (unsigned long)reframed_phys_probe;
	if (!rc && (result.pc != expected || result.flags))
		rc = -EIO;
	pr_info(PREFIX "complete rc=%d physical_pc=%#llx expected=%#llx flags=%#llx context_restored=%d elapsed_ns=%llu\n",
		rc, result.pc, expected, result.flags, context_restored,
		ktime_get_ns() - started);
out:
	release_pages();
	return rc ? rc : -ECANCELED;
}

module_init(mmu_test_init);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Eureka owned-page returning MMU transition test; no kernel jump");
