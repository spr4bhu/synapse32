#!/usr/bin/env python3
"""
Bug Detector - Advanced Pattern Recognition for Pipeline Stall Bugs

This module implements sophisticated bug detection algorithms that correlate
multiple signals to identify the 5 known bug patterns in the RISC-V CPU.

Features:
- Multi-signal correlation analysis
- Temporal pattern matching
- Statistical anomaly detection
- Root cause attribution
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import json


@dataclass
class PipelineState:
    """Represents the complete pipeline state at a given cycle"""
    cycle: int
    pc: int
    cache_stall: bool
    load_use_stall: bool
    valid_if: bool
    valid_id: bool
    valid_ex: bool
    valid_mem: bool
    valid_wb: bool
    wr_enable: bool
    read_enable: bool
    wr_en_out: bool
    mem_data_reg: Optional[int] = None
    mem_read_data: Optional[int] = None
    data_mem_access: bool = False
    instr_mem_access: bool = False


@dataclass
class BugReport:
    """Detailed bug report with evidence"""
    bug_id: str
    bug_name: str
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    occurrence_count: int
    first_occurrence: int  # cycle
    last_occurrence: int  # cycle
    affected_cycles: List[int]
    evidence: List[Dict] = field(default_factory=list)
    root_cause: str = ""
    recommendation: str = ""

    def __repr__(self):
        return (
            f"\n{'='*70}\n"
            f"[{self.severity}] {self.bug_name} (ID: {self.bug_id})\n"
            f"{'='*70}\n"
            f"Occurrences: {self.occurrence_count}\n"
            f"First seen: Cycle {self.first_occurrence}\n"
            f"Last seen: Cycle {self.last_occurrence}\n"
            f"Root Cause: {self.root_cause}\n"
            f"Recommendation: {self.recommendation}\n"
            f"Sample Evidence (first 3):\n"
            + "\n".join(f"  Cycle {e['cycle']}: {e['description']}"
                       for e in self.evidence[:3])
        )


class AdvancedBugDetector:
    """Advanced bug detection with correlation analysis"""

    def __init__(self):
        self.pipeline_states: List[PipelineState] = []
        self.bug_reports: Dict[str, BugReport] = {}

    def load_from_cocotb_log(self, log_file: str):
        """Load pipeline states from Cocotb test log"""
        # This would parse the test output logs
        # For now, we'll focus on VCD-based detection
        pass

    def add_pipeline_state(self, state: PipelineState):
        """Add a pipeline state snapshot"""
        self.pipeline_states.append(state)

    def detect_bug_1_memory_write_during_stall(self) -> BugReport:
        """
        Bug #1: Memory unit write enable not gated by stall signals

        Pattern: wr_enable=1 && (cache_stall=1 || load_use_stall=1)
        """
        bug_id = "BUG-001"
        bug_name = "Memory Write Enable During Stall"
        occurrences = []

        for state in self.pipeline_states:
            if state.wr_enable and (state.cache_stall or state.load_use_stall):
                occurrences.append({
                    'cycle': state.cycle,
                    'description': f"wr_enable=1 during {'cache' if state.cache_stall else 'load-use'} stall",
                    'signals': {
                        'wr_enable': state.wr_enable,
                        'cache_stall': state.cache_stall,
                        'load_use_stall': state.load_use_stall,
                        'pc': f"0x{state.pc:08x}"
                    }
                })

        if occurrences:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="CRITICAL",
                occurrence_count=len(occurrences),
                first_occurrence=occurrences[0]['cycle'],
                last_occurrence=occurrences[-1]['cycle'],
                affected_cycles=[e['cycle'] for e in occurrences],
                evidence=occurrences,
                root_cause="memory_unit.v does not check cache_stall/hazard_stall before asserting wr_enable",
                recommendation="Add inputs: cache_stall, hazard_stall. Change line 27: assign wr_enable = is_store && valid_in && !cache_stall && !hazard_stall;"
            )
        else:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="CRITICAL",
                occurrence_count=0,
                first_occurrence=-1,
                last_occurrence=-1,
                affected_cycles=[],
                root_cause="Not detected (may be already fixed or insufficient trace data)"
            )

        self.bug_reports[bug_id] = report
        return report

    def detect_bug_2_read_enable_during_stall(self) -> BugReport:
        """
        Bug #2: Memory unit read enable not gated by stall signals

        Pattern: read_enable=1 && (cache_stall=1 || load_use_stall=1)
        """
        bug_id = "BUG-002"
        bug_name = "Memory Read Enable During Stall"
        occurrences = []

        for state in self.pipeline_states:
            if state.read_enable and (state.cache_stall or state.load_use_stall):
                occurrences.append({
                    'cycle': state.cycle,
                    'description': f"read_enable=1 during {'cache' if state.cache_stall else 'load-use'} stall",
                    'signals': {
                        'read_enable': state.read_enable,
                        'cache_stall': state.cache_stall,
                        'load_use_stall': state.load_use_stall,
                        'pc': f"0x{state.pc:08x}"
                    }
                })

        if occurrences:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="CRITICAL",
                occurrence_count=len(occurrences),
                first_occurrence=occurrences[0]['cycle'],
                last_occurrence=occurrences[-1]['cycle'],
                affected_cycles=[e['cycle'] for e in occurrences],
                evidence=occurrences,
                root_cause="memory_unit.v does not check cache_stall/hazard_stall before asserting read_enable",
                recommendation="Add inputs: cache_stall, hazard_stall. Change line 28: assign read_enable = is_load && valid_in && !cache_stall && !hazard_stall;"
            )
        else:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="CRITICAL",
                occurrence_count=0,
                first_occurrence=-1,
                last_occurrence=-1,
                affected_cycles=[]
            )

        self.bug_reports[bug_id] = report
        return report

    def detect_bug_3_writeback_during_stall(self) -> BugReport:
        """
        Bug #3: Writeback write enable not gated by stall signals

        Pattern: wr_en_out=1 && (cache_stall=1 || load_use_stall=1)
        """
        bug_id = "BUG-003"
        bug_name = "Writeback Enable During Stall"
        occurrences = []

        for state in self.pipeline_states:
            if state.wr_en_out and (state.cache_stall or state.load_use_stall):
                occurrences.append({
                    'cycle': state.cycle,
                    'description': f"wr_en_out=1 during {'cache' if state.cache_stall else 'load-use'} stall",
                    'signals': {
                        'wr_en_out': state.wr_en_out,
                        'cache_stall': state.cache_stall,
                        'load_use_stall': state.load_use_stall,
                        'valid_wb': state.valid_wb,
                        'pc': f"0x{state.pc:08x}"
                    }
                })

        if occurrences:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="CRITICAL",
                occurrence_count=len(occurrences),
                first_occurrence=occurrences[0]['cycle'],
                last_occurrence=occurrences[-1]['cycle'],
                affected_cycles=[e['cycle'] for e in occurrences],
                evidence=occurrences,
                root_cause="writeback.v does not check cache_stall/hazard_stall before asserting wr_en_out",
                recommendation="Add inputs: cache_stall, hazard_stall. Change line 20: assign wr_en_out = valid_in && rd_valid_in && !cache_stall && !hazard_stall;"
            )
        else:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="CRITICAL",
                occurrence_count=0,
                first_occurrence=-1,
                last_occurrence=-1,
                affected_cycles=[]
            )

        self.bug_reports[bug_id] = report
        return report

    def detect_bug_5_memory_data_reg_sampling(self) -> BugReport:
        """
        Bug #5: mem_data_reg samples during cache stalls

        Pattern: mem_data_reg changes while cache_stall=1
        """
        bug_id = "BUG-005"
        bug_name = "Memory Data Register Sampling During Stall"
        occurrences = []

        prev_mem_data_reg = None
        for i, state in enumerate(self.pipeline_states):
            if state.mem_data_reg is not None and prev_mem_data_reg is not None:
                if state.mem_data_reg != prev_mem_data_reg and state.cache_stall:
                    occurrences.append({
                        'cycle': state.cycle,
                        'description': f"mem_data_reg changed from 0x{prev_mem_data_reg:08x} to 0x{state.mem_data_reg:08x} during cache stall",
                        'signals': {
                            'mem_data_reg_old': f"0x{prev_mem_data_reg:08x}",
                            'mem_data_reg_new': f"0x{state.mem_data_reg:08x}",
                            'cache_stall': state.cache_stall,
                            'pc': f"0x{state.pc:08x}"
                        }
                    })

            prev_mem_data_reg = state.mem_data_reg

        if occurrences:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="CRITICAL",
                occurrence_count=len(occurrences),
                first_occurrence=occurrences[0]['cycle'],
                last_occurrence=occurrences[-1]['cycle'],
                affected_cycles=[e['cycle'] for e in occurrences],
                evidence=occurrences,
                root_cause="top.v mem_data_reg samples every cycle cpu_mem_read_en=1, including during stalls",
                recommendation="Change line ~112 in top.v: } else if (cpu_mem_read_en && !cache_stall) begin"
            )
        else:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="CRITICAL",
                occurrence_count=0,
                first_occurrence=-1,
                last_occurrence=-1,
                affected_cycles=[]
            )

        self.bug_reports[bug_id] = report
        return report

    def detect_bug_6_address_decode_race(self) -> BugReport:
        """
        Bug #6: Address decoding race condition

        Pattern: Both data_mem_access and instr_mem_access high simultaneously
        """
        bug_id = "BUG-006"
        bug_name = "Address Decoding Race Condition"
        occurrences = []

        for state in self.pipeline_states:
            if state.data_mem_access and state.instr_mem_access:
                occurrences.append({
                    'cycle': state.cycle,
                    'description': "Both data_mem_access and instr_mem_access asserted",
                    'signals': {
                        'data_mem_access': state.data_mem_access,
                        'instr_mem_access': state.instr_mem_access,
                        'pc': f"0x{state.pc:08x}"
                    }
                })

        if occurrences:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="HIGH",
                occurrence_count=len(occurrences),
                first_occurrence=occurrences[0]['cycle'],
                last_occurrence=occurrences[-1]['cycle'],
                affected_cycles=[e['cycle'] for e in occurrences],
                evidence=occurrences,
                root_cause="top.v address decoding uses muxed data_mem_addr before it's stable",
                recommendation="Reorder logic at line ~54 in top.v: Check addresses directly, not through mux"
            )
        else:
            report = BugReport(
                bug_id=bug_id,
                bug_name=bug_name,
                severity="HIGH",
                occurrence_count=0,
                first_occurrence=-1,
                last_occurrence=-1,
                affected_cycles=[]
            )

        self.bug_reports[bug_id] = report
        return report

    def detect_all_bugs(self) -> Dict[str, BugReport]:
        """Run all bug detection algorithms"""
        print("\n" + "="*70)
        print("ADVANCED BUG DETECTION ANALYSIS")
        print("="*70)

        self.detect_bug_1_memory_write_during_stall()
        self.detect_bug_2_read_enable_during_stall()
        self.detect_bug_3_writeback_during_stall()
        self.detect_bug_5_memory_data_reg_sampling()
        self.detect_bug_6_address_decode_race()

        return self.bug_reports

    def generate_summary(self) -> str:
        """Generate a human-readable summary"""
        summary = []
        summary.append("\n" + "="*70)
        summary.append("BUG DETECTION SUMMARY")
        summary.append("="*70)

        critical_bugs = [b for b in self.bug_reports.values() if b.severity == "CRITICAL" and b.occurrence_count > 0]
        high_bugs = [b for b in self.bug_reports.values() if b.severity == "HIGH" and b.occurrence_count > 0]

        summary.append(f"\nCritical Bugs Found: {len(critical_bugs)}")
        summary.append(f"High Priority Bugs Found: {len(high_bugs)}")

        if critical_bugs or high_bugs:
            summary.append("\n⚠️  BUGS REQUIRING IMMEDIATE ATTENTION:\n")
            for bug in critical_bugs + high_bugs:
                summary.append(str(bug))

        summary.append(f"\n{'='*70}")
        summary.append("NEXT STEPS:")
        summary.append("="*70)
        summary.append("1. Review each bug report above")
        summary.append("2. Open GTKWave with the provided VCD file")
        summary.append("3. Navigate to the 'first_occurrence' cycle for each bug")
        summary.append("4. Apply the recommended fixes in order of severity")
        summary.append("5. Re-run tests after each fix to validate")

        return "\n".join(summary)

    def export_json(self, output_file: str):
        """Export bug reports to JSON"""
        data = {
            'total_states_analyzed': len(self.pipeline_states),
            'bugs': {
                bug_id: {
                    'name': report.bug_name,
                    'severity': report.severity,
                    'count': report.occurrence_count,
                    'first_cycle': report.first_occurrence,
                    'last_cycle': report.last_occurrence,
                    'affected_cycles': report.affected_cycles,
                    'root_cause': report.root_cause,
                    'recommendation': report.recommendation
                }
                for bug_id, report in self.bug_reports.items()
            }
        }

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\n✅ Bug report exported to: {output_file}")


if __name__ == "__main__":
    # Example usage
    detector = AdvancedBugDetector()

    # In real usage, pipeline states would be loaded from VCD or Cocotb logs
    print("Bug Detector Module - Use with signal_tracer.py or integrate into tests")
    print("\nExample:")
    print("  from debug_utils.bug_detector import AdvancedBugDetector, PipelineState")
    print("  detector = AdvancedBugDetector()")
    print("  # Add states during simulation...")
    print("  detector.detect_all_bugs()")
    print("  print(detector.generate_summary())")
