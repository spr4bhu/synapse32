"""
Debug Utilities for RISC-V CPU Pipeline Debugging

This package provides comprehensive debugging tools for analyzing
pipeline stall bugs in the Synapse-32 RISC-V CPU.

Modules:
- signal_tracer: VCD file parser and signal extraction
- bug_detector: Automated bug pattern detection
- pipeline_trace: ASCII pipeline visualization
- enhanced_test_runner: Test wrapper with integrated debugging
"""

from .bug_detector import AdvancedBugDetector, PipelineState, BugReport
from .pipeline_trace import PipelineVisualizer, CycleState, PipelineStageState, InstructionType

__all__ = [
    'AdvancedBugDetector',
    'PipelineState',
    'BugReport',
    'PipelineVisualizer',
    'CycleState',
    'PipelineStageState',
    'InstructionType',
]
