"""Svadu: hardware sets the accessed and dirty bits when menvcfg.ADUE is 1 (privileged spec 4.3.1).

The mirror of test_svade.py: the same page table, with A and D deliberately clear in places, is
walked with ADUE = 1. Nothing faults; the walker writes the updated PTE back before the access
proceeds, and the access completes with the value the page really holds.

Four cases: S-mode accesses that each need A or D from hardware, except a write to a page with no W
bit, which still faults with the PTE untouched; the same accesses in M-mode under MPRV; ADUE cleared
mid-run, so the next access to a page with D clear faults again, Svade behaviour; and menvcfg/menvcfgh
read-back, where ADUE is the only writable bit.

Checks are on committed state: the trap log, the PTE words in memory as hardware left them, and the
data the accesses returned.
"""

import os
import shutil
import struct
import subprocess
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb_test.simulator import run

INSTR_MEM_BASE = 0x8000_0000
INSTR_MEM_SIZE = 0x0400_0000
DATA_MEM_BASE = 0x1000_0000

CONFIG = 0x1000_0000
LOG = 0x1000_0300
LOG_SLOTS = 12
LOG_COUNT = 0x1000_03FC
DONE_ADDR = 0x1000_0400
DONE_VALUE = 0x444F_4E45
M_SCRATCH = 0x1000_0800
PAGE_TABLE = 0x1001_0000
L0_TABLE = 0x1001_1000
SATP_SV32 = 0x8000_0000 | (PAGE_TABLE >> 12)

BODY_PA = 0x8000_2000
BODY_VA = 0x6000_0000
SUPER_VA = 0x4000_0000
STORE_VALUE = 0x1234
MSTATUS_MXR = 1 << 19
MENVCFGH = 0x31A
MENVCFG = 0x30A
ADUE_BIT = 1 << 29

V, R, W, X, A, D = 0x01, 0x02, 0x04, 0x08, 0x40, 0x80

# L1 megapages: VA -> (PA, flags). The SUPER_VA one starts with A and D clear.
MEGAPAGES = {
    INSTR_MEM_BASE: (INSTR_MEM_BASE, V | R | W | X | A | D),
    DATA_MEM_BASE: (DATA_MEM_BASE, V | R | W | A | D),
    SUPER_VA: (DATA_MEM_BASE, V | R | W),
}
# L0 pages under VA 0x60000000: index -> (PA, flags, preloaded word)
PAGES = {
    0: (BODY_PA, V | R | X, None),                     # fetch sets A
    1: (0x1000_1000, V | R | W, 0xA1A1_A1A1),          # load sets A, later store sets D
    2: (0x1000_2000, V | R | W | A, 0xB2B2_B2B2),      # store sets D
    3: (0x1000_3000, V | R | W | A | D, 0xC3C3_C3C3),  # nothing to update
    4: (0x1000_4000, V | X, 0xD4D4_D4D4),              # MXR load sets A
    5: (0x1000_5000, V | R | W, 0x0000_1000),          # AMO sets A and D
    6: (0x1000_6000, V | R | W | A, 0x0000_2000),      # SC sets D
    7: (0x1000_7000, V | R, 0xE7E7_E7E7),              # store faults: no W, and nothing is updated
}
SUPER_OFFSET = 0x10
SUPER_VALUE = 0xE5E5_E5E5
RESULTS = 0x1000_3000 + 16


def _va(index: int, offset: int = 0) -> int:
    return BODY_VA + (index << 12) + offset


def _pte(pa: int, flags: int) -> int:
    return ((pa >> 12) << 10) | flags


PROGRAM = f"""
        .section .text.init, "ax"
        .option norelax
        .global _start
_start:
        li      t0, {M_SCRATCH:#x}
        csrw    mscratch, t0
        la      t0, m_trap
        csrw    mtvec, t0
        csrw    medeleg, zero
        li      t0, {SATP_SV32:#x}
        csrw    satp, t0
        li      t0, 0x1800
        csrc    mstatus, t0
        li      t0, 0x0800
        csrs    mstatus, t0
        # Svadu on: menvcfg.ADUE is bit 61, so menvcfgh bit 29.
        li      t0, {ADUE_BIT:#x}
        csrs    {MENVCFGH:#x}, t0
        li      t0, {CONFIG:#x}
        lw      t1, 0(t0)
        li      t2, 1
        beq     t1, t2, body_mprv
        li      t2, 2
        beq     t1, t2, body_clear_adue
        li      t2, 3
        beq     t1, t2, body_warl
        li      t0, {BODY_VA:#x}
        csrw    mepc, t0
        mret

# ---- M-mode body with MPRV = 1, MPP = S
body_mprv:
        li      t0, 0x20000
        csrs    mstatus, t0
        li      a1, {_va(1):#x}
        li      a2, {_va(2):#x}
        li      t1, {STORE_VALUE:#x}
mprv_load_a:
        lw      t2, 0(a1)
mprv_store_d:
        sw      t1, 0(a2)
        li      t0, 0x20000
        csrc    mstatus, t0
        li      t3, {RESULTS:#x}
        sw      t2, 0(t3)
        j       finish

# ---- ADUE cleared mid-run: the next A/D shortfall must fault again (M-mode, through MPRV).
body_clear_adue:
        li      t0, 0x20000
        csrs    mstatus, t0
        li      a1, {_va(1):#x}
        li      t1, {STORE_VALUE:#x}
clear_load_a:
        lw      t2, 0(a1)
        li      t0, {ADUE_BIT:#x}
        csrc    {MENVCFGH:#x}, t0
        sfence.vma
clear_store_d:
        sw      t1, 4(a1)
        li      t0, 0x20000
        csrc    mstatus, t0
        li      t3, {RESULTS:#x}
        sw      t2, 0(t3)
        j       finish

# ---- menvcfg / menvcfgh read-back
body_warl:
        li      t3, {RESULTS:#x}
        li      t0, -1
        csrw    {MENVCFGH:#x}, t0
        csrr    t1, {MENVCFGH:#x}
        sw      t1, 0(t3)
        li      t0, -1
        csrw    {MENVCFG:#x}, t0
        csrr    t1, {MENVCFG:#x}
        sw      t1, 4(t3)
        csrw    {MENVCFGH:#x}, zero
        csrr    t1, {MENVCFGH:#x}
        sw      t1, 8(t3)
        j       finish

finish:
        li      t0, {DONE_ADDR:#x}
        li      t1, {DONE_VALUE:#x}
        sw      t1, 0(t0)
spin:
        j       spin

# ---- M-mode handler (bare): logs cause, tval, epc and the leaf PTE, then skips.
        .align  2
m_trap:
        csrrw   sp, mscratch, sp
        sw      t0, 0(sp)
        sw      t1, 4(sp)
        sw      t2, 8(sp)
        sw      t3, 12(sp)
        csrr    t0, mtval
        srli    t1, t0, 22
        slli    t1, t1, 2
        li      t2, {PAGE_TABLE:#x}
        add     t1, t1, t2
        lw      t2, 0(t1)
        andi    t3, t2, 0xE
        bnez    t3, 1f
        srli    t2, t2, 10
        slli    t2, t2, 12
        srli    t3, t0, 12
        andi    t3, t3, 0x3FF
        slli    t3, t3, 2
        add     t1, t2, t3
1:
        li      t3, {LOG_COUNT:#x}
        lw      t2, 0(t3)
        addi    t0, t2, 1
        sw      t0, 0(t3)
        slli    t2, t2, 4
        li      t3, {LOG:#x}
        add     t2, t2, t3
        csrr    t0, mcause
        sw      t0, 0(t2)
        csrr    t3, mtval
        sw      t3, 4(t2)
        csrr    t3, mepc
        sw      t3, 8(t2)
        lw      t3, 0(t1)
        sw      t3, 12(t2)
        csrr    t2, mepc
        addi    t2, t2, 4
        csrw    mepc, t2
        lw      t3, 12(sp)
        lw      t2, 8(sp)
        lw      t1, 4(sp)
        lw      t0, 0(sp)
        csrrw   sp, mscratch, sp
        mret

# ---- S-mode body, linked at PA {BODY_PA:#x} and run at VA {BODY_VA:#x}
        .section .text.body, "ax"
body_s:
        li      a1, {_va(1):#x}
        li      a2, {_va(2):#x}
        li      a3, {_va(3):#x}
        li      a4, {_va(4):#x}
        li      a5, {_va(5):#x}
        li      a6, {_va(6):#x}
        li      a7, {SUPER_VA + SUPER_OFFSET:#x}
        li      s2, {_va(7):#x}
        li      t1, {STORE_VALUE:#x}
s_load_a:
        lw      t2, 0(a1)
s_store_d:
        sw      t1, 4(a1)
s_store_a_set_d_clear:
        sw      t1, 0(a2)
        lw      t3, 0(a3)
        sw      t1, 4(a3)
s_amo:
        amoadd.w t4, t1, (a5)
        lr.w    t5, (a6)
s_sc:
        sc.w    t5, t1, (a6)
        li      t0, {MSTATUS_MXR:#x}
        csrs    sstatus, t0
s_mxr_load:
        lw      t6, 0(a4)
        csrc    sstatus, t0
s_super_load:
        lw      s1, 0(a7)
s_store_ro:
        sw      t1, 0(s2)
        sw      t2, 16(a3)
        sw      t3, 20(a3)
        sw      t4, 24(a3)
        sw      t5, 28(a3)
        sw      t6, 32(a3)
        sw      s1, 36(a3)
        lui     t0, %hi(finish)
        addi    t0, t0, %lo(finish)
        jr      t0
"""

LINKER_SCRIPT = f"""
OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {{
    . = {INSTR_MEM_BASE:#x};
    .text : {{ *(.text.init) *(.text) }}
    . = {BODY_PA:#x};
    .body : {{ *(.text.body) }}
}}
"""


def _find_repo_root() -> Path:
    cur = Path.cwd()
    while not (cur / "rtl").exists():
        if cur.parent == cur:
            raise FileNotFoundError("Could not locate repo root (no rtl/ directory found)")
        cur = cur.parent
    return cur


def _build_dir() -> Path:
    return Path(os.environ.get("SVADU_BUILD", Path.cwd() / "build" / "svadu"))


def assemble(build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    src = build_dir / "svadu.S"
    lds = build_dir / "svadu.ld"
    elf = build_dir / "svadu.elf"
    src.write_text(PROGRAM)
    lds.write_text(LINKER_SCRIPT)
    subprocess.run(
        [
            "riscv64-unknown-elf-gcc", "-march=rv32ima_zicsr", "-mabi=ilp32",
            "-nostdlib", "-ffreestanding", "-Wl,--no-relax", "-Wl,-m,elf32lriscv",
            "-T", str(lds), str(src), "-o", str(elf),
        ],
        check=True,
    )
    subprocess.run(
        ["riscv64-unknown-elf-objcopy", "-O", "binary", str(elf), str(build_dir / "image.bin")],
        check=True,
    )
    symbols = _elf32_symbols(elf.read_bytes())
    (build_dir / "symbols.txt").write_text(
        "".join(f"{value:08x} {name}\n" for name, value in sorted(symbols.items()))
    )
    (build_dir / "nop.hex").write_text("@00000000\n" + "00000013 00000013 00000013 00000013\n" * 128)


def _elf32_symbols(elf: bytes) -> dict:
    assert elf[:4] == b"\x7fELF" and elf[4] == 1 and elf[5] == 1, "expected a little-endian ELF32 file"
    e_shoff, = struct.unpack_from("<I", elf, 32)
    e_shentsize, e_shnum = struct.unpack_from("<HH", elf, 46)
    sections = [struct.unpack_from("<IIIIIIIIII", elf, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    table = {}
    for _, sh_type, _, _, offset, size, link, _, _, entsize in sections:
        if sh_type != 2:  # SHT_SYMTAB
            continue
        strtab_offset = sections[link][4]
        for pos in range(offset, offset + size, entsize):
            st_name, st_value = struct.unpack_from("<II", elf, pos)
            if st_name:
                end = elf.index(b"\x00", strtab_offset + st_name)
                table[elf[strtab_offset + st_name:end].decode()] = st_value
    return table


def _load_symbols(build_dir: Path) -> dict:
    table = {}
    for line in (build_dir / "symbols.txt").read_text().splitlines():
        value, name = line.split()
        table[name] = int(value, 16)
    return table


def _phys_word_index(addr: int) -> int:
    if INSTR_MEM_BASE <= addr < INSTR_MEM_BASE + INSTR_MEM_SIZE:
        return (addr - INSTR_MEM_BASE) // 4
    if addr >= DATA_MEM_BASE:
        return (INSTR_MEM_SIZE + (addr - DATA_MEM_BASE)) // 4
    raise AssertionError(f"Unsupported physical address 0x{addr:08x}")


def _poke(dut, addr: int, value: int) -> None:
    dut.unified_mem_inst.instr_ram[_phys_word_index(addr)].value = value & 0xFFFF_FFFF


def _peek(dut, addr: int) -> int:
    return int(dut.unified_mem_inst.instr_ram[_phys_word_index(addr)].value) & 0xFFFF_FFFF


def _load(dut, image: bytes) -> None:
    for offset in range(0, len(image), 4):
        _poke(dut, INSTR_MEM_BASE + offset, int.from_bytes(image[offset:offset + 4], "little"))


def _pte_addr(index: int) -> int:
    return L0_TABLE + 4 * index


async def run_case(dut, config, limit=20000):
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    dut.uart_rx.value = 1
    _poke(dut, CONFIG, config)
    for va, (pa, flags) in MEGAPAGES.items():
        _poke(dut, PAGE_TABLE + 4 * (va >> 22), _pte(pa, flags))
    _poke(dut, PAGE_TABLE + 4 * (BODY_VA >> 22), _pte(L0_TABLE, V))
    for index, (pa, flags, value) in PAGES.items():
        _poke(dut, _pte_addr(index), _pte(pa, flags))
        if value is not None:
            for offset in range(0, 64, 4):
                _poke(dut, pa + offset, 0)
            _poke(dut, pa, value)
    _poke(dut, DATA_MEM_BASE + SUPER_OFFSET, SUPER_VALUE)
    for offset in range(0, 16 * LOG_SLOTS, 4):
        _poke(dut, LOG + offset, 0)
    _poke(dut, LOG_COUNT, 0)
    _poke(dut, DONE_ADDR, 0)
    await ClockCycles(dut.clk, 2)
    dut.rst.value = 0

    done = False
    pte_writes = 0
    for _ in range(limit):
        await RisingEdge(dut.clk)
        await ReadOnly()
        # A write the walker owns is a hardware A/D update, not a store the core committed.
        if int(dut.data_write_fire.value) and int(dut.data_bus_walk_owns.value):
            pte_writes += 1
        if (int(dut.cpu_mem_write_en.value) and int(dut.cpu_mem_write_addr.value) == DONE_ADDR
                and int(dut.cpu_mem_write_data.value) == DONE_VALUE):
            done = True
            break
    await RisingEdge(dut.clk)
    count = _peek(dut, LOG_COUNT)
    log = [tuple(_peek(dut, LOG + 16 * i + 4 * k) for k in range(4)) for i in range(min(count, LOG_SLOTS))]
    return done, count, log, pte_writes


def _fmt(log):
    return [f"(cause {c}, tval {t:#010x}, epc {e:#010x}, pte {p:#010x})" for c, t, e, p in log]


async def _start(dut):
    build_dir = _build_dir()
    symbols = _load_symbols(build_dir)
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    image = (build_dir / "image.bin").read_bytes()
    image += b"\x00" * (-len(image) % 4)
    _load(dut, image)
    return symbols


@cocotb.test()
async def test_hardware_sets_accessed_and_dirty_in_s_mode(dut):
    symbols = await _start(dut)

    def body_va(label):
        return BODY_VA + (symbols[label] - BODY_PA)

    done, count, log, pte_writes = await run_case(dut, 0)
    problems = []
    if not done:
        problems.append("did not finish")

    # The only trap is the store to the page with no W bit: permission decides before A/D.
    expected = [(15, _va(7), body_va("s_store_ro"), _pte(PAGES[7][0], PAGES[7][1]))]
    if count != len(expected) or log != expected:
        problems.append(f"trap log {_fmt(log)} (count {count}), expected {_fmt(expected)}")

    # What hardware must have written back, page by page.
    expected_ptes = {
        0: PAGES[0][1] | A,          # fetch sets A
        1: PAGES[1][1] | A | D,      # load set A, the later store set D
        2: PAGES[2][1] | D,          # store set D
        3: PAGES[3][1],              # already A and D: untouched
        4: PAGES[4][1] | A,          # MXR load sets A
        5: PAGES[5][1] | A | D,      # AMO sets both
        6: PAGES[6][1] | D,          # SC sets D
        7: PAGES[7][1],              # faulted on permission: must be untouched
    }
    for index, flags in expected_ptes.items():
        want = _pte(PAGES[index][0], flags)
        got = _peek(dut, _pte_addr(index))
        if got != want:
            problems.append(f"page {index} PTE is {got:#010x}, expected {want:#010x}")
    super_pte = _peek(dut, PAGE_TABLE + 4 * (SUPER_VA >> 22))
    want_super = _pte(MEGAPAGES[SUPER_VA][0], MEGAPAGES[SUPER_VA][1] | A)
    if super_pte != want_super:
        problems.append(f"megapage PTE is {super_pte:#010x}, expected {want_super:#010x} (A set by the load)")

    # The accesses themselves must have completed against the real data.
    checks = {
        "load from page 1": (_peek(dut, RESULTS), PAGES[1][2]),
        "store to page 1": (_peek(dut, PAGES[1][0] + 4), STORE_VALUE),
        "store to page 2": (_peek(dut, PAGES[2][0]), STORE_VALUE),
        "load from page 3": (_peek(dut, RESULTS + 4), PAGES[3][2]),
        "store to page 3": (_peek(dut, PAGES[3][0] + 4), STORE_VALUE),
        "AMO rd": (_peek(dut, RESULTS + 8), PAGES[5][2]),
        "AMO memory": (_peek(dut, PAGES[5][0]), PAGES[5][2] + STORE_VALUE),
        "SC succeeded": (_peek(dut, RESULTS + 12), 0),
        "SC memory": (_peek(dut, PAGES[6][0]), STORE_VALUE),
        "MXR load": (_peek(dut, RESULTS + 16), PAGES[4][2]),
        "megapage load": (_peek(dut, RESULTS + 20), SUPER_VALUE),
        "read-only page unwritten": (_peek(dut, PAGES[7][0]), PAGES[7][2]),
    }
    for name, (got, want) in checks.items():
        if got != want:
            problems.append(f"{name}: {got:#010x}, expected {want:#010x}")

    dut._log.info(f"S-mode: {count} traps, {pte_writes} PTE writes by the walker")
    if pte_writes == 0:
        problems.append("the walker never wrote a PTE, so nothing was updated by hardware")
    for line in problems:
        dut._log.error(line)
    assert not problems, "; ".join(problems)


@cocotb.test()
async def test_hardware_update_under_mprv(dut):
    await _start(dut)
    done, count, log, pte_writes = await run_case(dut, 1)
    problems = []
    if not done:
        problems.append("did not finish")
    if count:
        problems.append(f"expected no traps with ADUE = 1, got {_fmt(log)}")
    for index, flags in ((1, PAGES[1][1] | A), (2, PAGES[2][1] | D)):
        want = _pte(PAGES[index][0], flags)
        got = _peek(dut, _pte_addr(index))
        if got != want:
            problems.append(f"page {index} PTE is {got:#010x}, expected {want:#010x}")
    if _peek(dut, RESULTS) != PAGES[1][2]:
        problems.append(f"MPRV load returned {_peek(dut, RESULTS):#010x}, expected {PAGES[1][2]:#010x}")
    if _peek(dut, PAGES[2][0]) != STORE_VALUE:
        problems.append("MPRV store did not land")
    dut._log.info(f"MPRV: {count} traps, {pte_writes} PTE writes by the walker")
    for line in problems:
        dut._log.error(line)
    assert not problems, "; ".join(problems)


@cocotb.test()
async def test_clearing_adue_restores_faulting(dut):
    symbols = await _start(dut)
    done, count, log, _ = await run_case(dut, 2)
    problems = []
    if not done:
        problems.append("did not finish")
    # The load took the hardware update; the store after ADUE was cleared faults, as Svade does.
    # This body runs in M-mode, so epc is its own physical address.
    expected = [(15, _va(1, 4), symbols["clear_store_d"], _pte(PAGES[1][0], PAGES[1][1] | A))]
    if count != len(expected) or log != expected:
        problems.append(f"trap log {_fmt(log)} (count {count}), expected {_fmt(expected)}")
    if _peek(dut, RESULTS) != PAGES[1][2]:
        problems.append("the load before ADUE was cleared did not return the page's data")
    for line in problems:
        dut._log.error(line)
    assert not problems, "; ".join(problems)


@cocotb.test()
async def test_menvcfg_is_warl_with_only_adue_writable(dut):
    await _start(dut)
    done, count, log, _ = await run_case(dut, 3)
    problems = []
    if not done:
        problems.append("did not finish")
    if count:
        problems.append(f"unexpected traps: {_fmt(log)}")
    checks = {
        "menvcfgh after writing all ones": (_peek(dut, RESULTS), ADUE_BIT),
        "menvcfg after writing all ones": (_peek(dut, RESULTS + 4), 0),
        "menvcfgh after writing zero": (_peek(dut, RESULTS + 8), 0),
    }
    for name, (got, want) in checks.items():
        if got != want:
            problems.append(f"{name}: {got:#010x}, expected {want:#010x}")
    for line in problems:
        dut._log.error(line)
    assert not problems, "; ".join(problems)


def runCocotbTests():
    repo_root = _find_repo_root()
    rtl_dir = repo_root / "rtl"
    sources = [str(p) for p in sorted(rtl_dir.rglob("*.v"))]
    build_dir = _build_dir()
    assemble(build_dir)

    sim_build = Path.cwd() / "sim_build" / "sim_build_svadu"
    if sim_build.exists():
        shutil.rmtree(sim_build)

    run(
        verilog_sources=sources,
        toplevel="top",
        module="test_svadu",
        includes=[str(rtl_dir / "include")],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f'INSTR_HEX_FILE="{build_dir / "nop.hex"}"'],
        sim_build=str(sim_build),
        force_compile=True,
        extra_env={
            "TOPLEVEL": "top",
            "MODULE": "test_svadu",
            "COCOTB_TOPLEVEL": "top",
            "COCOTB_TEST_MODULES": "test_svadu",
            "SVADU_BUILD": str(build_dir.resolve()),
        },
    )


if __name__ == "__main__":
    runCocotbTests()
