#!/usr/bin/env python3
"""
Pipeline Trace Visualizer - ASCII Pipeline State Display

This module creates human-readable ASCII visualizations of the 5-stage pipeline
state cycle-by-cycle, making it easy to spot bugs in pipeline control.

Features:
- Cycle-by-cycle pipeline stage visualization
- Instruction flow tracking
- Valid bit and stall signal display
- Write enable and register update tracking
- Color-coded anomaly highlighting (when terminal supports it)
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class InstructionType(Enum):
    """Instruction types for visualization"""
    NOP = "nop"
    BUBBLE = "BUBBLE"
    LOAD = "lw"
    STORE = "sw"
    ALU = "alu"
    BRANCH = "br"
    JUMP = "jmp"
    CSR = "csr"
    UNKNOWN = "???"


@dataclass
class PipelineStageState:
    """State of a single pipeline stage"""
    instruction: str
    instr_type: InstructionType
    valid: bool
    pc: Optional[int] = None
    rd: Optional[int] = None
    rd_value: Optional[int] = None

    def __repr__(self):
        if not self.valid:
            return "-----"
        return f"{self.instruction:8s}"


@dataclass
class CycleState:
    """Complete CPU state for one cycle"""
    cycle: int
    if_stage: PipelineStageState
    id_stage: PipelineStageState
    ex_stage: PipelineStageState
    mem_stage: PipelineStageState
    wb_stage: PipelineStageState
    cache_stall: bool
    load_use_stall: bool
    wr_enable: bool
    read_enable: bool
    wr_en_out: bool
    reg_write: Optional[Tuple[int, int]] = None  # (reg_addr, value)


class PipelineVisualizer:
    """Visualizes pipeline execution cycle-by-cycle"""

    def __init__(self, use_color: bool = True):
        self.cycles: List[CycleState] = []
        self.use_color = use_color

        # ANSI color codes
        self.RED = '\033[91m' if use_color else ''
        self.GREEN = '\033[92m' if use_color else ''
        self.YELLOW = '\033[93m' if use_color else ''
        self.BLUE = '\033[94m' if use_color else ''
        self.MAGENTA = '\033[95m' if use_color else ''
        self.CYAN = '\033[96m' if use_color else ''
        self.RESET = '\033[0m' if use_color else ''
        self.BOLD = '\033[1m' if use_color else ''

    def add_cycle(self, cycle_state: CycleState):
        """Add a cycle state to the trace"""
        self.cycles.append(cycle_state)

    def render_header(self) -> str:
        """Render the table header"""
        header = f"{self.BOLD}"
        header += f"{'Cycle':<6} | {'IF':<10} | {'ID':<10} | {'EX':<10} | {'MEM':<10} | {'WB':<10} | "
        header += f"{'Stalls':<16} | {'Writes':<20}"
        header += self.RESET
        return header

    def render_separator(self) -> str:
        """Render a separator line"""
        return "-" * 110

    def render_cycle(self, cycle_state: CycleState, prev_state: Optional[CycleState] = None) -> str:
        """Render a single cycle state"""

        # Determine if this cycle has anomalies
        has_bug = False
        bug_markers = []

        # Check for Bug #1: write_enable during stall
        if cycle_state.wr_enable and (cycle_state.cache_stall or cycle_state.load_use_stall):
            has_bug = True
            bug_markers.append("BUG#1")

        # Check for Bug #3: wr_en_out during stall
        if cycle_state.wr_en_out and (cycle_state.cache_stall or cycle_state.load_use_stall):
            has_bug = True
            bug_markers.append("BUG#3")

        # Color code based on anomalies
        line_color = self.RED if has_bug else ""

        line = f"{line_color}"
        line += f"{cycle_state.cycle:<6} | "

        # Pipeline stages
        line += f"{self._format_stage(cycle_state.if_stage):<10} | "
        line += f"{self._format_stage(cycle_state.id_stage):<10} | "
        line += f"{self._format_stage(cycle_state.ex_stage):<10} | "
        line += f"{self._format_stage(cycle_state.mem_stage):<10} | "
        line += f"{self._format_stage(cycle_state.wb_stage):<10} | "

        # Stalls
        stalls = []
        if cycle_state.cache_stall:
            stalls.append(f"{self.YELLOW}C-STALL{self.RESET}{line_color}")
        if cycle_state.load_use_stall:
            stalls.append(f"{self.CYAN}LU-STALL{self.RESET}{line_color}")
        stall_str = " ".join(stalls) if stalls else "none"
        # Calculate actual display length for padding
        stall_display_len = len("C-STALL" if cycle_state.cache_stall else "") + \
                           (1 if cycle_state.cache_stall and cycle_state.load_use_stall else 0) + \
                           len("LU-STALL" if cycle_state.load_use_stall else "") + \
                           (0 if stalls else 4)
        stall_padding = max(0, 16 - stall_display_len)
        line += f"{stall_str}{' ' * stall_padding} | "

        # Writes
        writes = []
        if cycle_state.wr_enable:
            writes.append(f"{self.RED}MEM_WR{self.RESET}{line_color}")
        if cycle_state.read_enable:
            writes.append("MEM_RD")
        if cycle_state.reg_write:
            reg, val = cycle_state.reg_write
            writes.append(f"{self.GREEN}x{reg}←{val}{self.RESET}{line_color}")
        write_str = " ".join(writes) if writes else "none"
        line += f"{write_str:<20}"

        # Add bug markers
        if bug_markers:
            line += f" {self.BOLD}{self.RED}← {','.join(bug_markers)}{self.RESET}"

        line += self.RESET

        return line

    def _format_stage(self, stage: PipelineStageState) -> str:
        """Format a pipeline stage for display"""
        if not stage.valid:
            return f"{self.BLUE}BUBBLE{self.RESET}"

        # Color code by instruction type
        if stage.instr_type == InstructionType.LOAD:
            return f"{self.CYAN}{stage.instruction}{self.RESET}"
        elif stage.instr_type == InstructionType.STORE:
            return f"{self.MAGENTA}{stage.instruction}{self.RESET}"
        elif stage.instr_type == InstructionType.BUBBLE:
            return f"{self.BLUE}BUBBLE{self.RESET}"
        else:
            return stage.instruction

    def render_full_trace(self, start_cycle: int = 0, end_cycle: Optional[int] = None,
                         highlight_bugs_only: bool = False) -> str:
        """Render the complete trace"""

        if end_cycle is None:
            end_cycle = len(self.cycles)

        output = []
        output.append("\n" + "="*110)
        output.append(f"{self.BOLD}PIPELINE EXECUTION TRACE{self.RESET}")
        output.append("="*110)
        output.append(self.render_header())
        output.append(self.render_separator())

        prev_state = None
        bug_count = 0

        for i, cycle_state in enumerate(self.cycles[start_cycle:end_cycle]):
            # Check if this cycle has bugs
            has_bug = (
                (cycle_state.wr_enable and (cycle_state.cache_stall or cycle_state.load_use_stall)) or
                (cycle_state.wr_en_out and (cycle_state.cache_stall or cycle_state.load_use_stall))
            )

            if has_bug:
                bug_count += 1

            # Skip if we're only highlighting bugs and this cycle doesn't have any
            if highlight_bugs_only and not has_bug:
                prev_state = cycle_state
                continue

            output.append(self.render_cycle(cycle_state, prev_state))
            prev_state = cycle_state

        output.append(self.render_separator())
        output.append(f"\n{self.BOLD}LEGEND:{self.RESET}")
        output.append(f"  {self.CYAN}lw/sw{self.RESET} = Load/Store instructions")
        output.append(f"  {self.BLUE}BUBBLE{self.RESET} = Invalid instruction (pipeline bubble)")
        output.append(f"  {self.YELLOW}C-STALL{self.RESET} = Cache stall")
        output.append(f"  {self.CYAN}LU-STALL{self.RESET} = Load-use hazard stall")
        output.append(f"  {self.RED}MEM_WR{self.RESET} = Memory write enable")
        output.append(f"  {self.GREEN}x#←val{self.RESET} = Register write")
        output.append(f"  {self.RED}BUG#X{self.RESET} = Bug pattern detected!")

        output.append(f"\n{self.BOLD}STATISTICS:{self.RESET}")
        output.append(f"  Total cycles: {len(self.cycles[start_cycle:end_cycle])}")
        output.append(f"  Cycles with bugs: {bug_count}")

        return "\n".join(output)

    def export_to_file(self, filename: str, start_cycle: int = 0, end_cycle: Optional[int] = None):
        """Export trace to file"""
        trace = self.render_full_trace(start_cycle, end_cycle, highlight_bugs_only=False)

        # Remove ANSI codes for file export
        import re
        trace_no_color = re.sub(r'\033\[[0-9;]+m', '', trace)

        with open(filename, 'w') as f:
            f.write(trace_no_color)

        print(f"✅ Pipeline trace exported to: {filename}")

    def find_bug_cycles(self) -> List[int]:
        """Find all cycles with detected bugs"""
        bug_cycles = []

        for cycle_state in self.cycles:
            has_bug = (
                (cycle_state.wr_enable and (cycle_state.cache_stall or cycle_state.load_use_stall)) or
                (cycle_state.wr_en_out and (cycle_state.cache_stall or cycle_state.load_use_stall))
            )

            if has_bug:
                bug_cycles.append(cycle_state.cycle)

        return bug_cycles


def create_example_trace():
    """Create an example trace for demonstration"""
    visualizer = PipelineVisualizer(use_color=True)

    # Simulate a few cycles with a cache stall
    for cycle in range(1, 30):
        # Simulate cache stall at cycle 10-28
        cache_stall = 10 <= cycle <= 28

        # Create stage states
        if_state = PipelineStageState(
            instruction="lw x7,12",
            instr_type=InstructionType.LOAD,
            valid=not cache_stall,
            pc=0x100
        )

        id_state = PipelineStageState(
            instruction="sw x6,8",
            instr_type=InstructionType.STORE,
            valid=cycle > 2,
            pc=0x0FC
        )

        ex_state = PipelineStageState(
            instruction="addi x6",
            instr_type=InstructionType.ALU,
            valid=cycle > 3 and not (cache_stall and cycle > 12),
            pc=0x0F8
        )

        mem_state = PipelineStageState(
            instruction="lw x5,0",
            instr_type=InstructionType.LOAD,
            valid=cycle > 4 and not (cache_stall and cycle > 13),
            pc=0x0F4
        )

        wb_state = PipelineStageState(
            instruction="lui x4",
            instr_type=InstructionType.ALU,
            valid=cycle > 5,
            pc=0x0F0
        )

        # Bug: write enable during stall
        wr_enable = cache_stall and cycle == 15  # Bug occurs at cycle 15
        wr_en_out = cache_stall and cycle == 20  # Bug occurs at cycle 20

        cycle_state = CycleState(
            cycle=cycle,
            if_stage=if_state,
            id_stage=id_state,
            ex_stage=ex_state,
            mem_stage=mem_state,
            wb_stage=wb_state,
            cache_stall=cache_stall,
            load_use_stall=False,
            wr_enable=wr_enable,
            read_enable=False,
            wr_en_out=wr_en_out,
            reg_write=(7, 42) if cycle == 29 else None
        )

        visualizer.add_cycle(cycle_state)

    return visualizer


if __name__ == "__main__":
    print("Pipeline Trace Visualizer")
    print("Creating example trace with bugs...\n")

    visualizer = create_example_trace()
    print(visualizer.render_full_trace())

    bug_cycles = visualizer.find_bug_cycles()
    print(f"\n{len(bug_cycles)} bug occurrences found at cycles: {bug_cycles}")
