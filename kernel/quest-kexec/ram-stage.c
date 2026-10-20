// SPDX-License-Identifier: GPL-2.0-only
#include <linux/init.h>
#include <linux/module.h>
#include "stage.h"

static int __init ram_stage_init(void)
{
	return reframed_stage_init();
}

static void __exit ram_stage_exit(void)
{
	reframed_stage_exit();
}

module_init(ram_stage_init);
module_exit(ram_stage_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Eureka root-only owned RAM payload staging; no kernel jump");
