# Debug Utilities for RISC-V CPU Pipeline Debugging

This directory contains comprehensive debugging tools for analyzing pipeline stall bugs in the Synapse-32 RISC-V CPU.

## 📋 Overview

These tools help diagnose and visualize the 5 known bug patterns in the cache integration:

1. **Bug #1**: Memory write enable not gated during stalls
2. **Bug #2**: Memory read enable not gated during stalls
3. **Bug #3**: Writeback write enable during stalls
4. **Bug #5**: Memory data register sampling during stalls
5. **Bug #6**: Address decoding race conditions

## 🛠️ Tools

### 1. signal_tracer.py
VCD file parser that extracts critical signals and detects bug patterns.

**Usage:**
```bash
python signal_tracer.py <vcd_file>
```

**Features:**
- Parses VCD waveforms from Verilator/Icarus
- Extracts write enables, stall signals, valid bits
- Automatically detects bug patterns
- Outputs detailed bug occurrence reports

### 2. bug_detector.py
Advanced bug pattern recognition with multi-signal correlation.

**Usage:**
```python
from debug_utils.bug_detector import AdvancedBugDetector, PipelineState

detector = AdvancedBugDetector()
# Add pipeline states during simulation
detector.add_pipeline_state(state)
# Run detection
bug_reports = detector.detect_all_bugs()
print(detector.generate_summary())
```

**Features:**
- Correlates multiple signals to identify bugs
- Provides root cause analysis
- Generates fix recommendations
- Exports JSON reports

### 3. pipeline_trace.py
ASCII pipeline visualization showing instruction flow cycle-by-cycle.

**Usage:**
```python
from debug_utils.pipeline_trace import PipelineVisualizer

visualizer = PipelineVisualizer(use_color=True)
# Add cycle states
visualizer.add_cycle(cycle_state)
# Render trace
print(visualizer.render_full_trace())
```

**Features:**
- Color-coded pipeline stage display
- Highlights bugs in red
- Shows stall signals and write enables
- Exports to text file

### 4. enhanced_test_runner.py
Test wrapper that integrates all debugging tools with combined_stall_test.

**Usage:**
```bash
cd tests
python debug_utils/enhanced_test_runner.py run
```

**Features:**
- Runs combined_stall_test with full instrumentation
- Real-time bug detection
- Automatic report generation
- Exports bug reports and pipeline traces

## 📊 Quick Start

### Step 1: Run Enhanced Test

```bash
cd tests
python debug_utils/enhanced_test_runner.py run
```

This will:
- Run the combined stall test
- Detect bugs in real-time
- Generate bug reports
- Create pipeline visualizations
- Export results to `debug_output/`

### Step 2: Analyze VCD Waveforms

If you have VCD files from previous runs:

```bash
python debug_utils/signal_tracer.py path/to/waveform.vcd
```

### Step 3: View Results

Check the `debug_output/` directory for:
- `bug_report.json` - Detailed bug analysis in JSON format
- `pipeline_trace.txt` - ASCII pipeline visualization
- Console output with bug summaries

## 🔍 Understanding the Output

### Bug Report Format

```
======================================================================
[CRITICAL] Memory Write Enable During Stall (ID: BUG-001)
======================================================================
Occurrences: 15
First seen: Cycle 45
Last seen: Cycle 150
Root Cause: memory_unit.v does not check cache_stall before asserting wr_enable
Recommendation: Add inputs: cache_stall, hazard_stall. Change line 27: ...
Sample Evidence (first 3):
  Cycle 45: wr_enable=1 during cache stall
  Cycle 67: wr_enable=1 during cache stall
  Cycle 89: wr_enable=1 during cache stall
```

### Pipeline Trace Format

```
Cycle  | IF         | ID         | EX         | MEM        | WB         | Stalls          | Writes
-------------------------------------------------------------------------------------------------------
45     | lw x7,12   | sw x6,8    | addi x6    | BUBBLE     | lui x4     | C-STALL         | MEM_WR ← BUG#1
46     | lw x7,12   | sw x6,8    | BUBBLE     | BUBBLE     | lui x4     | C-STALL         | none
```

## 📈 Integration with Tests

To add debugging to your own tests:

```python
from debug_utils import AdvancedBugDetector, PipelineState, PipelineVisualizer

# During your test
detector = AdvancedBugDetector()

for cycle in range(num_cycles):
    await RisingEdge(dut.clk)

    # Extract signals
    state = PipelineState(
        cycle=cycle,
        pc=int(dut.pc_debug.value),
        cache_stall=bool(int(dut.cache_stall_debug.value)),
        # ... other signals
    )

    detector.add_pipeline_state(state)

# After test
bug_reports = detector.detect_all_bugs()
print(detector.generate_summary())
```

## 🎯 Expected Workflow

1. **Run enhanced test** to collect data
2. **Review bug reports** to understand failure patterns
3. **Open GTKWave** to examine waveforms at reported cycles
4. **Apply fixes** based on recommendations
5. **Re-run tests** to validate fixes

## 📝 Output Files

All debug output is saved to `tests/debug_output/`:

- `bug_report.json` - Machine-readable bug data
- `pipeline_trace.txt` - Human-readable pipeline trace
- Console logs with detailed analysis

## 🔧 Customization

### Adding New Bug Patterns

Edit `bug_detector.py` and add a new detection method:

```python
def detect_bug_X_new_pattern(self) -> BugReport:
    """Detect new bug pattern"""
    occurrences = []
    for state in self.pipeline_states:
        if <your_condition>:
            occurrences.append(...)
    # Create report
    return report
```

### Customizing Visualizations

Edit `pipeline_trace.py` to change colors, formatting, or add new columns.

## 📚 References

- See `problem.md` for detailed bug descriptions
- See `solutions.md` for comprehensive fix plans
- See research PDF for academic context

## ⚡ Performance Notes

- VCD parsing can be slow for large files (>100MB)
- Pipeline visualization is limited to ~1000 cycles for readability
- JSON export is fast and recommended for programmatic analysis
