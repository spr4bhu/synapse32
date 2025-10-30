#!/usr/bin/env python3
"""
Setup Test - Verify Debug Infrastructure

This script tests that all debug utilities are properly installed
and can be imported without errors.

Usage:
    python test_setup.py
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_imports():
    """Test that all debug modules can be imported"""
    print("Testing debug utility imports...")

    try:
        from debug_utils import (
            AdvancedBugDetector,
            PipelineState,
            BugReport,
            PipelineVisualizer,
            CycleState,
            PipelineStageState,
            InstructionType
        )
        print("  ✅ All imports successful")
        return True
    except ImportError as e:
        print(f"  ❌ Import failed: {e}")
        return False


def test_bug_detector():
    """Test bug detector functionality"""
    print("\nTesting bug detector...")

    try:
        from debug_utils import AdvancedBugDetector, PipelineState

        detector = AdvancedBugDetector()

        # Add a sample state
        state = PipelineState(
            cycle=10,
            pc=0x100,
            cache_stall=False,
            load_use_stall=False,
            valid_if=True,
            valid_id=True,
            valid_ex=True,
            valid_mem=True,
            valid_wb=True,
            wr_enable=False,
            read_enable=False,
            wr_en_out=False
        )

        detector.add_pipeline_state(state)
        reports = detector.detect_all_bugs()

        print(f"  ✅ Bug detector working ({len(reports)} bug types checked)")
        return True
    except Exception as e:
        print(f"  ❌ Bug detector failed: {e}")
        return False


def test_pipeline_visualizer():
    """Test pipeline visualizer functionality"""
    print("\nTesting pipeline visualizer...")

    try:
        from debug_utils import (
            PipelineVisualizer,
            CycleState,
            PipelineStageState,
            InstructionType
        )

        viz = PipelineVisualizer(use_color=False)  # No color for testing

        # Create a sample cycle
        if_stage = PipelineStageState("fetch", InstructionType.UNKNOWN, True, 0x100)
        id_stage = PipelineStageState("decode", InstructionType.UNKNOWN, True)
        ex_stage = PipelineStageState("execute", InstructionType.UNKNOWN, True)
        mem_stage = PipelineStageState("memory", InstructionType.UNKNOWN, True)
        wb_stage = PipelineStageState("writebk", InstructionType.UNKNOWN, True)

        cycle = CycleState(
            cycle=1,
            if_stage=if_stage,
            id_stage=id_stage,
            ex_stage=ex_stage,
            mem_stage=mem_stage,
            wb_stage=wb_stage,
            cache_stall=False,
            load_use_stall=False,
            wr_enable=False,
            read_enable=False,
            wr_en_out=False
        )

        viz.add_cycle(cycle)
        trace = viz.render_full_trace()

        print(f"  ✅ Pipeline visualizer working ({len(viz.cycles)} cycle added)")
        return True
    except Exception as e:
        print(f"  ❌ Pipeline visualizer failed: {e}")
        return False


def test_file_structure():
    """Test that all required files exist"""
    print("\nChecking file structure...")

    required_files = [
        "debug_utils/__init__.py",
        "debug_utils/signal_tracer.py",
        "debug_utils/bug_detector.py",
        "debug_utils/pipeline_trace.py",
        "debug_utils/enhanced_test_runner.py",
        "debug_utils/gtkwave_generator.py",
        "debug_utils/README.md",
        "debug_utils/DEBUGGING_GUIDE.md",
    ]

    all_exist = True
    base_dir = Path(__file__).parent.parent

    for file_path in required_files:
        full_path = base_dir / file_path
        if full_path.exists():
            print(f"  ✅ {file_path}")
        else:
            print(f"  ❌ {file_path} - NOT FOUND")
            all_exist = False

    return all_exist


def test_example_run():
    """Test creating example visualizations"""
    print("\nTesting example visualization generation...")

    try:
        from debug_utils.pipeline_trace import create_example_trace

        viz = create_example_trace()
        bug_cycles = viz.find_bug_cycles()

        print(f"  ✅ Example trace created with {len(viz.cycles)} cycles")
        print(f"     Found {len(bug_cycles)} bug cycles in example")
        return True
    except Exception as e:
        print(f"  ❌ Example generation failed: {e}")
        return False


def main():
    """Run all tests"""
    print("="*70)
    print("DEBUG UTILITIES SETUP TEST")
    print("="*70)

    results = {
        "File Structure": test_file_structure(),
        "Module Imports": test_imports(),
        "Bug Detector": test_bug_detector(),
        "Pipeline Visualizer": test_pipeline_visualizer(),
        "Example Generation": test_example_run(),
    }

    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name:.<30} {status}")

    all_passed = all(results.values())

    print("="*70)
    if all_passed:
        print("🎉 All tests passed! Debug infrastructure is ready.")
        print("\nNext steps:")
        print("  1. cd /home/shashvat/synapse32/tests")
        print("  2. source .venv/bin/activate")
        print("  3. python debug_utils/enhanced_test_runner.py run")
        return 0
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
