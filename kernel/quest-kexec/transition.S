/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Returning path adapted from YusufOzmen01/quest-kexec and Mac898/quest-kexec,
 * revision 057cb9ecf76a14d940f808a5b6d0094050a5c05a, module/transition.S.
 * PoC maintenance follows Linux arch/arm64/mm/cache.S.
 */
#include <linux/linkage.h>
#include <asm/assembler.h>
#include <asm/sysreg.h>

.text
SYM_FUNC_START(reframed_clean_poc)
	add x1, x0, x1
	sub x3, x2, #1
	bic x0, x0, x3
1:
	dc civac, x0
	add x0, x0, x2
	cmp x0, x1
	b.lo 1b
	dsb sy
	ret
SYM_FUNC_END(reframed_clean_poc)

/* x0: private 39-bit TTBR0 root; x1: owned physical code page. */
SYM_FUNC_START(reframed_mmu_roundtrip)
	stp x19, x20, [sp, #-96]!
	stp x21, x22, [sp, #16]
	stp x23, x24, [sp, #32]
	stp x25, x26, [sp, #48]
	stp x27, x28, [sp, #64]
	str x30, [sp, #80]
	str x18, [sp, #88]
	mrs x24, tcr_el1
	mrs x25, ttbr0_el1
	mrs x26, sctlr_el1
	mrs x28, daif
	msr daifset, #0xf
	adr x27, .Lreturn_high
	orr x9, x24, #(1 << 7)
	msr tcr_el1, x9
	isb
	dsb ishst
	tlbi vmalle1
	dsb ish
	isb
	msr ttbr0_el1, x0
	bic x9, x9, #0x3f
	mov x10, #25
	orr x9, x9, x10
	bic x9, x9, #(3 << 14)
	bic x9, x9, #(1 << 37)
	bic x9, x9, #(1 << 7)
	msr tcr_el1, x9
	isb
	ic iallu
	dsb sy
	isb
	br x1
.Lreturn_high:
	hint #38
	mrs x9, tcr_el1
	orr x9, x9, #(1 << 7)
	msr tcr_el1, x9
	isb
	msr ttbr0_el1, x25
	dsb ishst
	tlbi vmalle1
	dsb ish
	isb
	msr tcr_el1, x24
	isb
	mov x9, x28
	ldr x18, [sp, #88]
	ldr x30, [sp, #80]
	ldp x27, x28, [sp, #64]
	ldp x25, x26, [sp, #48]
	ldp x23, x24, [sp, #32]
	ldp x21, x22, [sp, #16]
	ldp x19, x20, [sp], #96
	msr daif, x9
	ret
SYM_FUNC_END(reframed_mmu_roundtrip)

/* The copied body contains no stack access or reference outside its page. */
SYM_FUNC_START(reframed_phys_probe)
	mov_q x12, INIT_SCTLR_EL1_MMU_OFF
	pre_disable_mmu_workaround
	msr sctlr_el1, x12
	isb
.global reframed_phys_pc
reframed_phys_pc:
	adr x18, reframed_phys_pc
	mov x0, x18
	mrs x1, sctlr_el1
	mov x10, #(SCTLR_ELx_M | SCTLR_ELx_C | SCTLR_ELx_I)
	and x1, x1, x10
	msr sctlr_el1, x26
	isb
	br x27
.global reframed_phys_probe_end
reframed_phys_probe_end:
SYM_FUNC_END(reframed_phys_probe)

/* x0: TTBR0 root; x1: owned code page; x2: Image; x3: DTB. */
SYM_FUNC_START(reframed_enter)
	msr daifset, #0xf
	mov x19, x2
	mov x20, x3
	mrs x9, tcr_el1
	orr x9, x9, #(1 << 7)
	msr tcr_el1, x9
	isb
	dsb ishst
	tlbi vmalle1
	dsb ish
	isb
	msr ttbr0_el1, x0
	bic x9, x9, #0x3f
	mov x10, #25
	orr x9, x9, x10
	bic x9, x9, #(3 << 14)
	bic x9, x9, #(1 << 37)
	bic x9, x9, #(1 << 7)
	msr tcr_el1, x9
	isb
	ic iallu
	dsb sy
	isb
	br x1
SYM_FUNC_END(reframed_enter)

SYM_FUNC_START(reframed_phys_enter)
	mov_q x12, INIT_SCTLR_EL1_MMU_OFF
	pre_disable_mmu_workaround
	msr sctlr_el1, x12
	isb
	mov x0, x20
	mov x1, xzr
	mov x2, xzr
	mov x3, xzr
	br x19
.global reframed_phys_enter_end
reframed_phys_enter_end:
SYM_FUNC_END(reframed_phys_enter)
