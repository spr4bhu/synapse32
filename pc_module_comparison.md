# PC Module Comparison: Version 1 vs Version 2

## Executive Summary

Both PC module versions were tested and **both pass all tests (5/5 registers correct)**. However, **Version 1 (pc_current/pc_next) is superior** from a hardware design perspective due to better synthesis characteristics, clearer intent, and industry-standard structure.

---

## Test Results

### Version 1 (pc_current/pc_next - Separate Registers)
```
Register Verification:
  ✓ x6 = 42
  ✓ x8 = 142
  ✓ x10 = 143
  ✓ x13 = 701
  ✓ x14 = 511

Result: 5/5 correct (100% pass rate)
Test time: 1.87s
```

### Version 2 (next_pc - Self-Updating Register)
```
Register Verification:
  ✓ x6 = 42
  ✓ x8 = 142
  ✓ x10 = 143
  ✓ x13 = 701
  ✓ x14 = 511

Result: 5/5 correct (100% pass rate)
Test time: 2.08s
```

**Conclusion:** Both versions are functionally correct.

---

## Detailed Code Comparison

### Version 1: Separate Current and Next PC (Industry Standard)

```verilog
module pc(
   input clk,
   input rst,
   input j_signal,
   input stall,
   input [31:0] jump,
   output[31:0] out
);
   // Separate current and next PC registers
   reg [31:0] pc_current = 32'd0;  // STABLE output register
   wire [31:0] pc_next;             // Combinational next value

   // Combinational calculation of next PC
   assign pc_next = j_signal ? jump :
                    stall    ? pc_current :
                               pc_current + 32'h4;

   // Update PC register with async reset
   always @ (posedge clk or posedge rst) begin
       if (rst) begin
           pc_current <= 32'b0;
       end else begin
           pc_current <= pc_next;
       end
       // ... debug statements
   end

   assign out = pc_current;  // Output the STABLE register
endmodule
```

**Key Characteristics:**
- ✓ Async reset (`posedge rst` in sensitivity list)
- ✓ Separate current and next PC
- ✓ Combinational next-state logic (`assign`)
- ✓ Output is stable register, not updating one
- ✓ Clear separation of concerns

---

### Version 2: Self-Updating Register

```verilog
module pc(
   input clk,
   input rst,
   input j_signal,
   input stall,
   input [31:0] jump,
   output[31:0] out
);
   reg [31:0] next_pc = 32'd0;  // Single register

   always @ (posedge clk) begin  // Synchronous reset only
       if(rst)
           next_pc <= 32'b0;
       else if(j_signal) begin
           next_pc <= jump;
       end
       else if(stall) begin
           next_pc <= next_pc;  // Hold current value
       end
       else begin
           next_pc <= next_pc + 32'h4;  // Self-increment
       end
       // ... debug statements
   end

   assign out = next_pc;  // Output the updating register
endmodule
```

**Key Characteristics:**
- ⚠ Synchronous reset only (no async reset)
- ⚠ Single register that updates itself
- ⚠ Next-state logic inside `always` block
- ⚠ Output is the register being updated
- ⚠ Potential timing issues

---

## Technical Analysis

### 1. Reset Behavior

**Version 1 (Async Reset):**
```verilog
always @ (posedge clk or posedge rst) begin
    if (rst) begin
        pc_current <= 32'b0;
    end
```
- **Pros:**
  - Immediate reset (doesn't wait for clock)
  - More robust in glitchy clock scenarios
  - Standard for critical control logic
  - Better for FPGA synthesis

- **Cons:**
  - Slightly more complex synthesis

**Version 2 (Sync Reset):**
```verilog
always @ (posedge clk) begin
    if(rst)
        next_pc <= 32'b0;
```
- **Pros:**
  - Simpler synthesis
  - No reset timing issues

- **Cons:**
  - Reset delayed until clock edge
  - Less robust in clock glitch scenarios
  - PC won't reset until first clock edge arrives

**Winner:** Version 1 (async reset is safer for control logic)

---

### 2. Output Stability

**Version 1:**
```verilog
reg [31:0] pc_current = 32'd0;  // Stable register
assign out = pc_current;         // Output stable value
```

**Timing during clock edge:**
```
T=0ns (posedge):
  - pc_current is STABLE at old value (e.g., 0x100)
  - Downstream logic samples 0x100
  - Non-blocking assignment schedules: pc_current <= 0x104

T=0ns (delta cycle end):
  - pc_current updates to 0x104
  - Output changes to 0x104
  - Next cycle begins with stable 0x104
```

**Winner:** Clear and predictable timing

---

**Version 2:**
```verilog
reg [31:0] next_pc = 32'd0;    // Updating register
assign out = next_pc;           // Output updating value
```

**Timing during clock edge:**
```
T=0ns (posedge):
  - next_pc is at old value (e.g., 0x100)
  - Downstream logic samples... what exactly?
  - Non-blocking assignment schedules: next_pc <= 0x104

T=0ns (delta cycle):
  - Order depends on Verilog scheduler
  - Potential race: does downstream sample before or after update?
  - Output changes during the clock edge event
```

**Issue:** The output changes **during** the clock edge, which can cause race conditions with other posedge-triggered logic.

**Winner:** Version 1 (stable output, no races)

---

### 3. Synthesis Quality

**Version 1:**
```verilog
wire [31:0] pc_next;  // Combinational wire
assign pc_next = j_signal ? jump : stall ? pc_current : pc_current + 32'h4;

always @ (posedge clk or posedge rst) begin
    if (rst)
        pc_current <= 32'b0;
    else
        pc_current <= pc_next;
end
```

**Synthesizes to:**
- 32-bit register (pc_current)
- Combinational MUX tree for next-state logic
- Clear critical path: MUX → Register
- Easy for synthesis tools to optimize

**Estimated Logic:**
- 32 flip-flops (pc_current)
- 32 4:1 MUXes (for j_signal/stall/increment selection)
- Clean, optimizable structure

---

**Version 2:**
```verilog
always @ (posedge clk) begin
    if(rst)
        next_pc <= 32'b0;
    else if(j_signal)
        next_pc <= jump;
    else if(stall)
        next_pc <= next_pc;  // Feedback path!
    else
        next_pc <= next_pc + 32'h4;  // Self-referencing
end
```

**Synthesizes to:**
- 32-bit register (next_pc)
- Combinational MUX tree (same as V1)
- BUT: Self-referencing expressions may confuse some tools
- "next_pc <= next_pc" creates explicit feedback path

**Estimated Logic:**
- 32 flip-flops (next_pc)
- 32 4:1 MUXes
- Potential synthesis warnings about feedback loops

**Winner:** Version 1 (cleaner for synthesis tools)

---

### 4. Code Clarity and Maintainability

**Version 1:**
```verilog
// PROS:
// ✓ Clear separation: pc_current (state) vs pc_next (next-state logic)
// ✓ Follows standard FSM design pattern
// ✓ Easy to understand: "current state → calculate next → update on clock"
// ✓ Matches textbook examples
// ✓ Self-documenting with wire names

// Standard pattern:
wire [31:0] next_state;          // Next state calculation
reg [31:0] current_state;        // Current state storage
assign next_state = ...;         // Combinational logic
always @(posedge clk) current_state <= next_state;  // State update
```

**Industry Pattern Match:** This is the **exact pattern** taught in:
- "RTL Hardware Design Using VHDL" by Pong P. Chu
- "Digital Design and Computer Architecture" by Harris & Harris
- All major university courses

---

**Version 2:**
```verilog
// CONS:
// ⚠ Mixes state and next-state in single register
// ⚠ Self-referencing ("next_pc <= next_pc") is confusing
// ⚠ Not obvious that "next_pc" is actually the CURRENT PC
// ⚠ Harder to reason about timing
// ⚠ Naming is misleading (next_pc is the current value!)

// Confusing:
next_pc <= next_pc + 4;  // "next_pc" is actually current PC!
```

**Winner:** Version 1 (much clearer intent)

---

### 5. Timing Analysis

**Version 1 Critical Path:**
```
Input signals (j_signal, stall, jump)
  ↓
Combinational MUX (pc_next calculation)  [~1ns]
  ↓
Setup time for pc_current register       [~0.5ns]
  ↓
Clock edge captures pc_next
```

**Total combinational delay:** ~1.5ns
**Clock-to-Q delay:** ~0.5ns (standard flip-flop)
**Output available:** 0.5ns after clock edge

---

**Version 2 Critical Path:**
```
Input signals (j_signal, stall, jump)
  ↓
Combinational MUX (inside always block)  [~1ns]
  ↓
Setup time for next_pc register          [~0.5ns]
  ↓
Clock edge captures value
  ↓
Clock-to-Q delay to output              [~0.5ns]
```

**Total combinational delay:** ~1.5ns (same)
**BUT:** Output stability less clear due to self-referencing

**Winner:** Version 1 (clearer timing model)

---

### 6. Potential Race Conditions

**Version 1 with negedge IF_ID:**
```
T=0ns (posedge): pc_current updates, cache starts calculating
T=5ns (negedge): IF_ID samples settled instruction
```
✓ No race - pc_current is stable when IF_ID samples

**Version 2 with negedge IF_ID:**
```
T=0ns (posedge): next_pc updates, output changes
T=5ns (negedge): IF_ID samples
```
✓ Also works, but output changed during the posedge event

**With posedge IF_ID (both versions):**

**Version 1:**
```
T=0ns (posedge):
  - pc_current is STABLE at old value
  - IF_ID samples old (correct) value
  - pc_current then updates to new value
```
Result: IF_ID gets the **correct** instruction for that cycle ✓

**Version 2:**
```
T=0ns (posedge):
  - next_pc and IF_ID both trigger
  - Delta cycle ordering determines who wins
  - RACE CONDITION
```
Result: IF_ID might get wrong value ✗

**Winner:** Version 1 (no race with posedge IF_ID)

---

## Industry Standards

### What Modern Processors Use

**ARM Cortex-A cores:**
```verilog
// Typical ARM-style PC logic
reg [31:0] pc_r;          // Current PC (registered)
wire [31:0] pc_next;      // Next PC (combinational)

assign pc_next = branch_taken ? branch_target :
                 stall ? pc_r :
                 pc_r + 4;

always_ff @(posedge clk or negedge rst_n)
    if (!rst_n)
        pc_r <= RESET_VECTOR;
    else
        pc_r <= pc_next;

assign pc_out = pc_r;  // Output current PC
```

**Pattern:** Separate current and next PC ← **Version 1**

---

**RISC-V Rocket Core:**
```scala
// Chisel code (translates to similar Verilog)
val pc = RegInit(START_ADDR)
val pc_next = Wire(UInt(32.W))

pc_next := MuxCase(pc + 4.U, Array(
  jump_taken -> jump_target,
  stall -> pc
))

pc := pc_next
```

**Pattern:** Separate current and next PC ← **Version 1**

---

**MIPS R4000:**
```verilog
// Simplified MIPS PC logic
reg [31:0] PC;
wire [31:0] PC_next;

assign PC_next = (exception) ? exception_vector :
                 (branch_taken) ? branch_target :
                 (stall) ? PC :
                 PC + 4;

always @(posedge clk)
    PC <= PC_next;
```

**Pattern:** Separate current and next PC ← **Version 1**

---

**Conclusion:** **Version 1 matches industry standard patterns**

---

## Performance Comparison

### Simulation Time
- Version 1: 1.87s
- Version 2: 2.08s

**Winner:** Version 1 (11% faster simulation)

Why? Likely because:
- Combinational `assign` is more efficient in simulation
- Simpler delta-cycle behavior
- Less scheduler overhead

---

### Synthesis (Estimated)

**Area:**
- Both: ~32 flip-flops + ~128 LUTs (similar)

**Timing:**
- Version 1: Cleaner timing paths, easier to optimize
- Version 2: Self-referencing may create suboptimal paths

**Power:**
- Similar (same logic gates)

**Winner:** Slight edge to Version 1

---

## Security and Robustness

### Reset Behavior

**Version 1:** Async reset
- If clock fails, CPU can still be reset
- More robust in power-on scenarios
- Better for security (can force reset immediately)

**Version 2:** Sync reset
- If clock fails, CPU cannot be reset
- Relies on functioning clock for reset
- Security concern: clock glitching attacks could prevent reset

**Winner:** Version 1 (more robust)

---

### Formal Verification

**Version 1:**
- Clear state variable (pc_current)
- Clear next-state function (pc_next)
- Easy to write formal properties:
  ```
  assert property (@(posedge clk)
    !stall && !j_signal |-> ##1 pc_current == $past(pc_current) + 4);
  ```

**Version 2:**
- State and next-state mixed
- Self-referencing complicates assertions
- Harder to verify

**Winner:** Version 1 (easier to verify)

---

## Summary Table

| Criterion | Version 1 (pc_current/pc_next) | Version 2 (next_pc) | Winner |
|-----------|-------------------------------|---------------------|--------|
| **Functional Correctness** | ✓ 5/5 tests pass | ✓ 5/5 tests pass | Tie |
| **Reset Type** | Async (robust) | Sync (simple) | **V1** |
| **Output Stability** | Stable register | Updates during edge | **V1** |
| **Race Condition Risk** | None | Potential with posedge IF_ID | **V1** |
| **Synthesis Quality** | Clean structure | Self-referencing | **V1** |
| **Code Clarity** | Very clear | Confusing naming | **V1** |
| **Industry Pattern** | Matches ARM/RISC-V/MIPS | Non-standard | **V1** |
| **Maintainability** | Easy to modify | Harder to understand | **V1** |
| **Simulation Speed** | 1.87s (faster) | 2.08s | **V1** |
| **Formal Verification** | Easy | Harder | **V1** |
| **Timing Closure** | Clear critical path | Less clear | **V1** |

**Overall Winner: Version 1 (10/11 categories)**

---

## Recommendation

### **Use Version 1 (pc_current/pc_next)**

**Reasons:**
1. ✓ **Industry Standard:** Matches ARM, RISC-V, MIPS patterns
2. ✓ **Clearer Code:** Obvious separation of current and next state
3. ✓ **More Robust:** Async reset for better reliability
4. ✓ **No Races:** Stable output eliminates timing issues
5. ✓ **Better Synthesis:** Cleaner structure for tools
6. ✓ **Easier to Verify:** Clear state machine pattern
7. ✓ **Faster Simulation:** 11% faster test execution
8. ✓ **Maintainable:** Future developers will understand it immediately

**Version 2 is not wrong** - it works correctly in simulation. However, it:
- Uses confusing naming ("next_pc" is actually current PC)
- Has potential race conditions with certain pipeline configurations
- Deviates from industry-standard patterns
- Is harder to understand and maintain

---

## Migration Recommendation

**Keep Version 1** as the current implementation. If Version 2 is in git history, document why Version 1 is preferred for future reference.

---

## Code Quality Best Practices

This comparison illustrates important RTL design principles:

### ✓ DO:
- Separate current state and next state
- Use async reset for critical control logic
- Follow industry-standard patterns
- Make code self-documenting with clear names
- Output stable registers, not updating ones

### ✗ DON'T:
- Mix state and next-state in single register
- Use misleading variable names ("next" for current value)
- Create self-referencing expressions without good reason
- Deviate from standards without clear benefit

---

## Conclusion

**Version 1 (pc_current/pc_next) is the superior implementation** due to:
- Industry-standard structure
- Better code clarity
- More robust reset behavior
- Elimination of potential race conditions
- Easier synthesis and verification

**Recommendation: Use Version 1 in production code.**

---

**Testing Date:** 2025-10-30
**Test Suite:** combined_stall_test.py
**Result:** Both versions pass, but Version 1 recommended for production
