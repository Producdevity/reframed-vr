// SPDX-License-Identifier: GPL-2.0-only
#include <linux/cred.h>
#include <linux/efi.h>
#include <linux/init.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/string.h>
#include <linux/utsname.h>
#include <linux/version.h>

#include <asm/sysreg.h>

#if LINUX_VERSION_CODE != KERNEL_VERSION(5, 10, 246)
#error "Build the probe against the captured Quest 3 kernel source"
#endif

#define PROBE_PREFIX "REFRAMED_QUEST_PROBE "

static int report_regions(struct device_node *node)
{
	const __be32 *reg;
	int bytes, index, cells;

	reg = of_get_property(node, "reg", &bytes);
	if (!reg)
		return 0;
	if (of_n_addr_cells(node) != 2 || of_n_size_cells(node) != 2 ||
	    bytes < 0 || bytes % (4 * sizeof(*reg)))
		return -EINVAL;
	cells = bytes / sizeof(*reg);
	if (cells > 128)
		return -E2BIG;
	for (index = 0; index < cells; index += 4) {
		u64 start = of_read_number(reg + index, 2);
		u64 size = of_read_number(reg + index + 2, 2);

		if (size && start > U64_MAX - size)
			return -EOVERFLOW;
		pr_info(PROBE_PREFIX "region node=%pOF start=%#llx size=%#llx\n",
			node, start, size);
	}
	return 0;
}

static int report_device(struct device *dev, void *data)
{
	static const char * const compatibles[] = {
		"qcom,dwc3", "qcom,dwc-usb3-msm", "snps,dwc3", "qcom,aoss-qmp",
		"qcom,qmp-aop", "qcom,msm-smmu-v2",
	};
	unsigned int *count = data;
	struct resource *resource;
	size_t index;

	for (index = 0; index < ARRAY_SIZE(compatibles); ++index) {
		if (of_device_is_compatible(dev->of_node, compatibles[index]))
			break;
	}
	if (index == ARRAY_SIZE(compatibles))
		return 0;
	device_lock(dev);
	resource = platform_get_resource(to_platform_device(dev), IORESOURCE_MEM, 0);
	pr_info(PROBE_PREFIX "device name=%s compatible=%s driver=%s resource=%pR\n",
		dev_name(dev), compatibles[index],
		dev->driver ? dev->driver->name : "unbound", resource);
	device_unlock(dev);
	++*count;
	return 0;
}

static int __init probe_init(void)
{
	struct device_node *node = NULL;
	struct sysinfo memory;
	unsigned int nodes = 0, devices = 0;
	int rc;

	if (strcmp(utsname()->release, "5.10.246-gd7102a837402") ||
	    !of_machine_is_compatible("oculus,eureka") ||
	    !of_machine_is_compatible("qcom,anorak"))
		return -ENODEV;
	if (!uid_eq(current_uid(), GLOBAL_ROOT_UID))
		return -EPERM;

	si_meminfo(&memory);
	pr_info(PROBE_PREFIX "efi_flags=%#lx efi_runtime=%d\n",
		efi.flags, efi_enabled(EFI_RUNTIME_SERVICES));
	pr_info(PROBE_PREFIX "begin release=%s uid=%u el=%llu sctlr=%#llx tcr=%#llx total_pages=%lu free_pages=%lu page_size=%lu\n",
		utsname()->release, __kuid_val(current_uid()),
		read_sysreg(CurrentEL) >> 2, read_sysreg(sctlr_el1),
		read_sysreg(tcr_el1), memory.totalram, memory.freeram, PAGE_SIZE);
	for (node = of_find_all_nodes(NULL); node; node = of_find_all_nodes(node)) {
		if (++nodes > 8192) {
			of_node_put(node);
			return -E2BIG;
		}
		if (!of_node_is_type(node, "memory") &&
		    (!node->parent || !of_node_name_eq(node->parent, "reserved-memory")))
			continue;
		rc = report_regions(node);
		if (rc) {
			of_node_put(node);
			return rc;
		}
	}
	rc = bus_for_each_dev(&platform_bus_type, NULL, &devices, report_device);
	if (rc)
		return rc;
	/* A deliberate init failure leaves no resident module or unload callback. */
	pr_info(PROBE_PREFIX "complete nodes=%u devices=%u rc=%d\n",
		nodes, devices, -ECANCELED);
	return -ECANCELED;
}

module_init(probe_init);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Read-only Eureka kernel interface and device-tree probe");
