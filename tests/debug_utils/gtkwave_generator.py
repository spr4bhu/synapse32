#!/usr/bin/env python3
"""
GTKWave Save File Generator

Creates .gtkw files (GTKWave save files) that pre-configure signal views
for debugging specific bugs. This makes it easy to visualize bugs in GTKWave
by opening the generated save files.

Usage:
    python gtkwave_generator.py <vcd_file> [bug_id]
"""

import sys
from pathlib import Path
from typing import List, Dict


class GTKWaveSaveFileGenerator:
    """Generates GTKWave save files for bug visualization"""

    def __init__(self, vcd_file: str):
        self.vcd_file = Path(vcd_file).absolute()
        self.save_files: Dict[str, str] = {}

    def generate_bug1_view(self) -> str:
        """
        Bug #1: Memory Write Enable During Stall

        Shows:
        - cache_stall
        - load_use_stall
        - wr_enable (should be 0 when stalls are 1)
        - valid bits through pipeline
        - PC
        """
        content = f"""[*]
[*] GTKWave Analyzer v3.3.104 (w)1999-2020 BSI
[*] {self.vcd_file}
[*]
[timestart] 0
[size] 1920 1080
[pos] -1 -1
*-18.000000 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1
[treeopen] top.
[treeopen] top.cpu_inst.
[sst_width] 245
[signals_width] 250
[sst_expanded] 1
[sst_vpaned_height] 500

@28
#{self.BOLD}Bug #1: Memory Write Enable During Stall{self.RESET}
@200
-Clock & Reset
@28
top.clk
top.rst
@200
-
-{self.BOLD}STALL SIGNALS (Should prevent writes){self.RESET}
@28
#{self.RED}top.cache_stall_debug{self.RESET}
#{self.CYAN}top.cpu_inst.load_use_stall{self.RESET}
@200
-
-{self.BOLD}MEMORY UNIT - Write Enable{self.RESET}
@28
#{self.RED}top.cpu_mem_write_en{self.RESET}
@200
-⚠️  WHEN cache_stall=1 OR load_use_stall=1, cpu_mem_write_en MUST be 0!
-
-Memory Addresses & Data
@22
top.cpu_mem_write_addr[31:0]
top.cpu_mem_write_data[31:0]
@28
top.cpu_mem_write_byte_enable[3:0]
@200
-
-Pipeline Valid Bits
@28
top.cpu_inst.if_id_valid_out
top.cpu_inst.id_ex_valid_out
top.cpu_inst.ex_mem_valid_out
top.cpu_inst.mem_wb_valid_out
@200
-
-Program Counter
@22
top.pc_debug[31:0]
@200
-
-{self.BOLD}HOW TO FIND BUG:{self.RESET}
-1. Look for cycles where cache_stall_debug=1 or load_use_stall=1
-2. Check if cpu_mem_write_en=1 at the same time
-3. That's the bug! Write enable should be gated by stall signals.
"""

        return content

    def generate_bug3_view(self) -> str:
        """
        Bug #3: Writeback Enable During Stall

        Shows:
        - Stall signals
        - Writeback write enable
        - Register file writes
        """
        content = f"""[*]
[*] GTKWave Analyzer v3.3.104 (w)1999-2020 BSI
[*] {self.vcd_file}
[*]
[timestart] 0
[size] 1920 1080
[pos] -1 -1
*-18.000000 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1
[treeopen] top.
[treeopen] top.cpu_inst.
[sst_width] 245
[signals_width] 250
[sst_expanded] 1
[sst_vpaned_height] 500

@28
#{self.BOLD}Bug #3: Writeback Enable During Stall{self.RESET}
@200
-Clock & Reset
@28
top.clk
top.rst
@200
-
-{self.BOLD}STALL SIGNALS{self.RESET}
@28
#{self.RED}top.cache_stall_debug{self.RESET}
#{self.CYAN}top.cpu_inst.load_use_stall{self.RESET}
@200
-
-{self.BOLD}WRITEBACK - Write Enable{self.RESET}
@28
#{self.RED}top.cpu_inst.wb_inst0_wr_en_out{self.RESET}
@200
-⚠️  WHEN cache_stall=1 OR load_use_stall=1, wr_en_out MUST be 0!
-
-Register File Writes
@28
top.cpu_inst.rf_inst0_wr_en
@22
top.cpu_inst.rf_inst0_rd_in[4:0]
top.cpu_inst.rf_inst0_rd_value_in[31:0]
@200
-
-MEM/WB Pipeline Register
@28
top.cpu_inst.mem_wb_valid_out
top.cpu_inst.mem_wb_inst0_rd_valid_out
@22
top.cpu_inst.mem_wb_inst0_rd_addr_out[4:0]
top.cpu_inst.mem_wb_inst0_exec_output_out[31:0]
@200
-
-Program Counter
@22
top.pc_debug[31:0]
@200
-
-{self.BOLD}HOW TO FIND BUG:{self.RESET}
-1. Find cycles where cache_stall=1 or load_use_stall=1
-2. Check if wb_inst0_wr_en_out=1 at same time
-3. Check if rf_inst0_wr_en=1 (register actually being written)
-4. That's the bug! Writeback should be gated by stalls.
"""

        return content

    def generate_bug5_view(self) -> str:
        """
        Bug #5: Memory Data Register Sampling During Stall

        Shows:
        - cache_stall
        - mem_data_reg changes
        - cpu_mem_read_en
        """
        content = f"""[*]
[*] GTKWave Analyzer v3.3.104 (w)1999-2020 BSI
[*] {self.vcd_file}
[*]
[timestart] 0
[size] 1920 1080
[pos] -1 -1
*-18.000000 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1
[treeopen] top.
[sst_width] 245
[signals_width] 250
[sst_expanded] 1
[sst_vpaned_height] 500

@28
#{self.BOLD}Bug #5: Memory Data Register Sampling During Stall{self.RESET}
@200
-Clock & Reset
@28
top.clk
top.rst
@200
-
-{self.BOLD}CACHE STALL{self.RESET}
@28
#{self.RED}top.cache_stall_debug{self.RESET}
top.cache_miss_debug
@200
-
-{self.BOLD}MEMORY DATA REGISTER{self.RESET}
@28
top.cpu_mem_read_en
@22
#{self.RED}top.mem_data_reg[31:0]{self.RESET}
top.mem_read_data[31:0]
@200
-⚠️  mem_data_reg should NOT change when cache_stall=1!
-
-Memory Read Signals
@22
top.cpu_mem_read_addr[31:0]
@28
top.data_mem_access
top.instr_mem_access
@200
-
-Data Memory
@22
top.data_mem_read_data[31:0]
@200
-
-Pipeline Memory Stage
@28
top.cpu_inst.ex_mem_valid_out
@22
top.cpu_inst.ex_mem_inst0_instr_id_out[5:0]
@200
-
-{self.BOLD}HOW TO FIND BUG:{self.RESET}
-1. Find a cache miss (cache_miss_debug=1)
-2. Observe cache_stall=1 for 19 cycles
-3. Watch mem_data_reg during these 19 cycles
-4. If it changes while cache_stall=1, that's the bug!
-5. It should only sample when cache_stall=0
"""

        return content

    def generate_bug6_view(self) -> str:
        """
        Bug #6: Address Decoding Race Condition

        Shows:
        - Address decoding logic
        - data_mem_access and instr_mem_access
        - Read addresses
        """
        content = f"""[*]
[*] GTKWave Analyzer v3.3.104 (w)1999-2020 BSI
[*] {self.vcd_file}
[*]
[timestart] 0
[size] 1920 1080
[pos] -1 -1
*-18.000000 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1
[treeopen] top.
[sst_width] 245
[signals_width] 250
[sst_expanded] 1
[sst_vpaned_height] 500

@28
#{self.BOLD}Bug #6: Address Decoding Race Condition{self.RESET}
@200
-Clock & Reset
@28
top.clk
@200
-
-{self.BOLD}ADDRESS DECODING{self.RESET}
@28
#{self.RED}top.data_mem_access{self.RESET}
#{self.RED}top.instr_mem_access{self.RESET}
@200
-⚠️  Both should NEVER be 1 at the same time!
-
-Memory Access Signals
@28
top.cpu_mem_read_en
top.cpu_mem_write_en
@22
top.cpu_mem_read_addr[31:0]
top.cpu_mem_write_addr[31:0]
top.data_mem_addr[31:0]
@200
-
-Memory Data
@22
top.mem_read_data[31:0]
top.data_mem_read_data[31:0]
top.instr_read_data[31:0]
@200
-
-Register File (Check for wrong data)
@28
top.cpu_inst.rf_inst0_wr_en
@22
top.cpu_inst.rf_inst0_rd_in[4:0]
top.cpu_inst.rf_inst0_rd_value_in[31:0]
@200
-
-{self.BOLD}HOW TO FIND BUG:{self.RESET}
-1. Look for data memory loads (cpu_mem_read_en=1, addr=0x1000xxxx)
-2. Check data_mem_access and instr_mem_access signals
-3. If both are 1 simultaneously, that's the race!
-4. Check mem_read_data - might get instruction data instead
"""

        return content

    def generate_overview(self) -> str:
        """Generate overview with all critical signals"""
        content = f"""[*]
[*] GTKWave Analyzer v3.3.104 (w)1999-2020 BSI
[*] {self.vcd_file}
[*]
[timestart] 0
[size] 1920 1080
[pos] -1 -1
*-18.000000 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1
[treeopen] top.
[treeopen] top.cpu_inst.
[sst_width] 245
[signals_width] 300
[sst_expanded] 1
[sst_vpaned_height] 500

@28
#{self.BOLD}OVERVIEW - All Critical Signals{self.RESET}
@200
-Clock
@28
top.clk
@200
-
-{self.BOLD}STALL SIGNALS{self.RESET}
@28
#{self.YELLOW}top.cache_stall_debug{self.RESET}
#{self.CYAN}top.cpu_inst.load_use_stall{self.RESET}
top.cache_miss_debug
@200
-
-{self.BOLD}WRITE ENABLES (Should be 0 during stalls){self.RESET}
@28
#{self.RED}top.cpu_mem_write_en{self.RESET}
top.cpu_mem_read_en
#{self.RED}top.cpu_inst.wb_inst0_wr_en_out{self.RESET}
top.cpu_inst.rf_inst0_wr_en
@200
-
-{self.BOLD}PIPELINE VALID BITS{self.RESET}
@28
top.cpu_inst.if_id_valid_out
top.cpu_inst.id_ex_valid_out
top.cpu_inst.ex_mem_valid_out
top.cpu_inst.mem_wb_valid_out
@200
-
-{self.BOLD}MEMORY INTERFACE{self.RESET}
@28
top.data_mem_access
top.instr_mem_access
@22
top.cpu_mem_read_addr[31:0]
top.cpu_mem_write_addr[31:0]
top.mem_data_reg[31:0]
top.mem_read_data[31:0]
@200
-
-{self.BOLD}REGISTER FILE{self.RESET}
@22
top.cpu_inst.rf_inst0_rd_in[4:0]
top.cpu_inst.rf_inst0_rd_value_in[31:0]
@200
-
-{self.BOLD}PROGRAM COUNTER{self.RESET}
@22
top.pc_debug[31:0]
"""

        return content

    @property
    def BOLD(self):
        return ""

    @property
    def RESET(self):
        return ""

    @property
    def RED(self):
        return "⚠️ "

    @property
    def YELLOW(self):
        return "⏸ "

    @property
    def CYAN(self):
        return "⏸ "

    def generate_all(self, output_dir: str = "."):
        """Generate all GTKWave save files"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        views = {
            "overview.gtkw": self.generate_overview(),
            "bug1_memory_write_stall.gtkw": self.generate_bug1_view(),
            "bug3_writeback_stall.gtkw": self.generate_bug3_view(),
            "bug5_mem_data_reg_sample.gtkw": self.generate_bug5_view(),
            "bug6_address_decode_race.gtkw": self.generate_bug6_view(),
        }

        for filename, content in views.items():
            filepath = output_path / filename
            with open(filepath, 'w') as f:
                f.write(content)
            print(f"✅ Generated: {filepath}")

        print(f"\n{'='*70}")
        print("GTKWave Save Files Generated!")
        print("="*70)
        print(f"\nTo use in GTKWave:")
        print(f"  gtkwave {self.vcd_file} {output_path}/overview.gtkw")
        print(f"\nOr open GTKWave and use File → Read Save File")


def main():
    if len(sys.argv) < 2:
        print("Usage: python gtkwave_generator.py <vcd_file> [output_dir]")
        sys.exit(1)

    vcd_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "gtkwave_views"

    if not Path(vcd_file).exists():
        print(f"Error: VCD file not found: {vcd_file}")
        sys.exit(1)

    generator = GTKWaveSaveFileGenerator(vcd_file)
    generator.generate_all(output_dir)


if __name__ == "__main__":
    main()
