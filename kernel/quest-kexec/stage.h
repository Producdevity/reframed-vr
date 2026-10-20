/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef REFRAMED_QUEST_STAGE_H
#define REFRAMED_QUEST_STAGE_H

#include <linux/kobject.h>
#include <linux/mutex.h>
#include "ram.h"

struct reframed_stage {
	struct reframed_ram ram;
	struct kobject *object;
	struct mutex lock;
	bool sealed;
	bool fixture;
};

extern struct reframed_stage reframed_stage;
int reframed_stage_init(void);
void reframed_stage_exit(void);

#endif
