"""uart_rx reaches the receiver through two flip-flops, and a byte is received at any phase."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from cocotb_test.simulator import run
from memory_view import read_word

INSTR_MEM_BASE = 0x8000_0000
INSTR_MEM_SIZE = 0x0400_0000
DATA_MEM_BASE = 0x1000_0000
UART_BASE = 0x2000_0000

BUFFER = 0x1000_0200
READY = 0x1000_02F0
DONE_ADDR = 0x1000_0300
DONE_VALUE = 0x444F_4E45
TRAP_CAUSE = 0x1000_0304
TRAP_EPC = 0x1000_030C

LATENCIES = [0]
DIVISOR = 3
BIT = 16 * DIVISOR
BYTES = [(37 * k + 11) & 0xFF for k in range(BIT)]
GAP = 2 * BIT + 1  # each byte starts one cycle later in the bit period than the one before
POLL = 4000
LIMIT = 40000
FLOPS = ("$dff", "$adff")

PROGRAM = f"""
        .section .text.init, "ax"
        .option norelax
        .global _start
_start:
        la      t0, m_trap
        csrw    mtvec, t0
        li      s0, {UART_BASE:#x}
        li      t0, 0x83
        sw      t0, 12(s0)              # LCR: DLAB, 8N1
        li      t0, {DIVISOR}
        sw      t0, 0(s0)               # DLL
        sw      zero, 4(s0)             # DLM
        li      t0, 0x03
        sw      t0, 12(s0)              # LCR: 8N1
        li      t0, 0x07
        sw      t0, 8(s0)               # FCR: enable and clear FIFOs
        li      t0, {READY:#x}
        li      t1, 1
        sw      t1, 0(t0)
        li      s1, {len(BYTES)}
        li      s2, {BUFFER:#x}
next:
        li      t2, {POLL}
1:
        lw      t0, 20(s0)
        andi    t0, t0, 1
        bnez    t0, 2f
        addi    t2, t2, -1
        bnez    t2, 1b
        j       done
2:
        lw      t0, 0(s0)
        sb      t0, 0(s2)
        addi    s2, s2, 1
        addi    s1, s1, -1
        bnez    s1, next
done:
        li      t0, {DONE_ADDR:#x}
        li      t1, {DONE_VALUE:#x}
        sw      t1, 0(t0)
1:
        j       1b

        .align  2
m_trap:
        li      t1, {TRAP_CAUSE:#x}
        csrr    t0, mcause
        sw      t0, 0(t1)
        csrr    t0, mepc
        sw      t0, 8(t1)
        li      t0, {DONE_ADDR:#x}
        li      t1, {DONE_VALUE:#x}
        sw      t1, 0(t0)
1:
        j       1b
"""

LINKER_SCRIPT = f"""
OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {{
    . = {INSTR_MEM_BASE:#x};
    .text : {{ *(.text.init) *(.text*) }}
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
    return Path(os.environ.get("RX_SYNC_BUILD", Path.cwd() / "build" / "uart_rx_sync"))


def assemble(build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    src = build_dir / "rx.S"
    lds = build_dir / "rx.ld"
    elf = build_dir / "rx.elf"
    src.write_text(PROGRAM)
    lds.write_text(LINKER_SCRIPT)
    subprocess.run(
        [
            "riscv64-unknown-elf-gcc", "-march=rv32ima_zicsr_zifencei", "-mabi=ilp32",
            "-nostdlib", "-ffreestanding", "-Wl,--no-relax", "-Wl,-m,elf32lriscv",
            "-T", str(lds), str(src), "-o", str(elf),
        ],
        check=True,
    )
    subprocess.run(["riscv64-unknown-elf-objcopy", "-O", "binary", str(elf), str(build_dir / "rx.bin")],
                   check=True)
    (build_dir / "nop.hex").write_text("@00000000\n" + "00000013 00000013 00000013 00000013\n" * 128)


def _phys_word_index(addr: int) -> int:
    if INSTR_MEM_BASE <= addr < INSTR_MEM_BASE + INSTR_MEM_SIZE:
        return (addr - INSTR_MEM_BASE) // 4
    if addr >= DATA_MEM_BASE:
        return (INSTR_MEM_SIZE + (addr - DATA_MEM_BASE)) // 4
    raise AssertionError(f"Unsupported physical address 0x{addr:08x}")


def _poke(dut, addr: int, value: int) -> None:
    dut.unified_mem_inst.instr_ram[_phys_word_index(addr)].value = value & 0xFFFF_FFFF


def _peek(dut, addr: int) -> int:
    """What the program sees at addr."""
    return read_word(dut, _phys_word_index(addr))


def _uart_netlist() -> dict:
    rtl_dir = Path(os.environ["RX_SYNC_RTL"])
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "uart.json"
        subprocess.run(
            ["yosys", "-q", "-p", f"read_verilog -I{rtl_dir / 'include'} {rtl_dir / 'core_modules' / 'uart.v'}; "
             f"hierarchy -check -top uart; proc; flatten; opt_clean; write_json {out}"],
            check=True, capture_output=True, text=True,
        )
        return json.loads(out.read_text())["modules"]["uart"]


def _readers(module: dict, bits) -> list:
    """(cell type, input port, Q bits) of every cell that reads one of bits."""
    readers = []
    for cell in module["cells"].values():
        for port, connected in cell["connections"].items():
            if cell["port_directions"][port] == "input" and set(connected) & set(bits):
                readers.append((cell["type"], port, cell["connections"].get("Q")))
    return readers


@cocotb.test()
async def test_rx_reaches_the_receiver_through_two_flops(dut):
    module = _uart_netlist()
    first = _readers(module, module["ports"]["rx"]["bits"])
    assert len(first) == 1 and first[0][0] in FLOPS and first[0][1] == "D", (
        f"uart_rx must drive one flop's D input only, it drives {[(t, p) for t, p, _ in first]}")
    second = _readers(module, first[0][2])
    assert len(second) == 1 and second[0][0] in FLOPS and second[0][1] == "D", (
        f"the first synchronizer flop must drive one flop's D input only, it drives {[(t, p) for t, p, _ in second]}")


async def _send_all(dut) -> None:
    await FallingEdge(dut.clk)
    for value in BYTES:
        for bit in [0] + [(value >> i) & 1 for i in range(8)] + [1]:
            dut.uart_rx.value = bit
            await ClockCycles(dut.clk, BIT, rising=False)
        await ClockCycles(dut.clk, GAP, rising=False)


@cocotb.test()
async def test_a_byte_is_received_at_every_phase(dut):
    cocotb.start_soon(Clock(dut.clk, 20, units="ns").start())
    await FallingEdge(dut.clk)
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    dut.uart_rx.value = 1
    data = (_build_dir() / "rx.bin").read_bytes()
    data += b"\x00" * (-len(data) % 4)
    for offset in range(0, len(data), 4):
        _poke(dut, INSTR_MEM_BASE + offset, int.from_bytes(data[offset:offset + 4], "little"))
    for offset in range(0, len(BYTES), 4):
        _poke(dut, BUFFER + offset, 0)
    for addr in (READY, DONE_ADDR, TRAP_CAUSE, TRAP_EPC):
        _poke(dut, addr, 0)
    await ClockCycles(dut.clk, 2)
    dut.rst.value = 0

    started = False
    done = False
    for _ in range(LIMIT):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if not started and _peek(dut, READY) == 1:
            started = True
            cocotb.start_soon(_send_all(dut))
        if _peek(dut, DONE_ADDR) == DONE_VALUE:
            done = True
            break

    cause = _peek(dut, TRAP_CAUSE)
    assert cause == 0, f"unexpected trap, mcause 0x{cause:08x} at 0x{_peek(dut, TRAP_EPC):08x}"
    words = [_peek(dut, BUFFER + offset) for offset in range(0, len(BYTES), 4)]
    got = [(words[i // 4] >> (8 * (i % 4))) & 0xFF for i in range(len(BYTES))]
    wrong = [f"byte {k} (phase {k}): 0x{g:02x}, sent 0x{b:02x}" for k, (g, b) in enumerate(zip(got, BYTES)) if g != b]
    if not done:
        wrong.insert(0, f"the program did not finish in {LIMIT} cycles")
    assert not wrong, f"{len(wrong)} problems; " + "; ".join(wrong[:6])


def runCocotbTests():
    repo_root = _find_repo_root()
    rtl_dir = repo_root / "rtl"
    sources = [str(p) for p in sorted(rtl_dir.rglob("*.v"))]
    build_dir = _build_dir()
    assemble(build_dir)

    for latency in LATENCIES:
        sim_build = Path.cwd() / "sim_build" / f"sim_build_uart_rx_sync_lat{latency}"
        if sim_build.exists():
            shutil.rmtree(sim_build)
        run(
            verilog_sources=sources,
            toplevel="top",
            module="test_uart_rx_sync",
            parameters={"MEM_LATENCY": latency, "FETCH_LATENCY": latency},
            includes=[str(rtl_dir / "include")],
            simulator="verilator",
            timescale="1ns/1ps",
            defines=[f'INSTR_HEX_FILE="{build_dir / "nop.hex"}"'],
            sim_build=str(sim_build),
            force_compile=True,
            extra_env={
                "TOPLEVEL": "top",
                "MODULE": "test_uart_rx_sync",
                "COCOTB_TOPLEVEL": "top",
                "COCOTB_TEST_MODULES": "test_uart_rx_sync",
                "RX_SYNC_BUILD": str(build_dir.resolve()),
                "RX_SYNC_RTL": str(rtl_dir.resolve()),
            },
        )


if __name__ == "__main__":
    runCocotbTests()
