# 🎓 **RESEARCH ANALYSIS + COMPREHENSIVE FIX PLAN**

After reading this research paper and comparing it to our current CPU state, I've identified **MULTIPLE CRITICAL BUGS** that perfectly match the patterns described.

---

## 🔍 **KEY FINDINGS FROM RESEARCH**

### **Bug Pattern Match:**
The paper describes **EXACTLY** our symptoms:

> "Bug 1: Write enables not gated during stalls. Symptoms: Garbage writes to 0x00000000 or random addresses during cache misses."

> "Your specific bug: The write to 0x00000000 during cycle 19 suggests your MEM stage write enable isn't being gated by the valid bit or stall signal."

**This is US!** We have garbage writes and wrong load data.

---

## 🚨 **CRITICAL BUGS IDENTIFIED IN OUR CPU**

### **BUG #1: Memory Write Enable Not Gated** ⭐⭐⭐⭐⭐

**Location:** `rtl/memory_unit.v` line 27-29

**Current Code:**
```verilog
// WRONG: Just checks instruction type and valid_in
assign wr_enable = is_store && valid_in;
assign read_enable = is_load && valid_in;
```

**Problem:** Doesn't check for stalls! During cache stalls, `valid_in` might still be 1 for stale instructions in EX/MEM.

**Research Says:**
> "mem_write_enable = instruction_MemWrite && stage_valid && !stall_signal"

**Our Fix:**
```verilog
// CORRECT: Gate with stall signal
assign wr_enable = is_store && valid_in && !cache_stall;
assign read_enable = is_load && valid_in && !cache_stall;
```

But wait... `memory_unit` doesn't have `cache_stall` input! **This is the root cause!**

---

### **BUG #2: Memory Unit Missing Stall Signal** ⭐⭐⭐⭐⭐

**Location:** `rtl/memory_unit.v` module declaration

**Current Code:**
```verilog
module memory_unit (
    input wire clk,
    input wire rst,
    input wire valid_in,
    // NO STALL SIGNAL!
    ...
);
```

**Problem:** Can't gate writes during stalls because it doesn't know about stalls!

**Fix:** Add stall input:
```verilog
module memory_unit (
    input wire clk,
    input wire rst,
    input wire valid_in,
    input wire cache_stall,    // ADD THIS
    input wire hazard_stall,   // ADD THIS
    ...
);
```

---

### **BUG #3: Writeback Not Gating With Stalls** ⭐⭐⭐⭐

**Location:** `rtl/writeback.v` line 20

**Current Code:**
```verilog
assign wr_en_out = valid_in && rd_valid_in;
```

**Research Says:**
> "assign actual_reg_write_enable = WB_RegWrite && WB_valid && !pipeline_stalled;"

**Fix:**
```verilog
assign wr_en_out = valid_in && rd_valid_in && !cache_stall && !hazard_stall;
```

But again, `writeback` doesn't have stall inputs!

---

### **BUG #4: Forwarding Not Checking rd_valid** ⭐⭐⭐⭐

**Location:** `rtl/pipeline_stages/forwarding_unit.v` lines 28-45

**Current Code:**
```verilog
if (rd_valid_mem && (rd_addr_mem != 5'b0) && (rd_addr_mem == rs1_addr_ex)) begin
    forward_a = FORWARD_FROM_MEM;
end
```

**Problem:** Only checks `rd_valid_mem`, not if the instruction is actually writing!

**Research Says:**
> "Forward = (RegWrite == 1) AND (Rd != 0) AND (Rd == Rs). Notice RegWrite is checked first — this is the validity check."

**In our case:** We check `rd_valid_mem` but during bubbles, this might still be 1 from a previous instruction!

**Research Pattern:**
```verilog
wire forward_from_mem = EX_MEM_RegWrite && (EX_MEM_Rd != 0) && (EX_MEM_Rd == ID_EX_Rs1);
```

**Our Pattern:** We use `rd_valid` as "RegWrite" but we should ALSO check valid bit from pipeline register!

---

### **BUG #5: mem_data_reg Timing Issue** ⭐⭐⭐⭐⭐

**Location:** `rtl/top.v` lines 109-116

**Current Code:**
```verilog
always @(posedge clk) begin
    if (rst) begin
        mem_data_reg <= 32'b0;
    end else if (cpu_mem_read_en) begin
        mem_data_reg <= mem_read_data;  // Samples every read
    end
end
```

**Problem:** This samples data EVERY time `cpu_mem_read_en` is high, including during stalls!

**Research Says:**
> "Valid bit must be set only after the entire cache line fill completes, not when it starts."

**During cache stall:**
- Cycle 1: Load starts, `cpu_mem_read_en=1`, samples garbage
- Cycles 2-19: Still stalled, but `mem_data_reg` already has wrong data
- Cycle 20: Stall ends, wrong data goes to CPU

**Fix:** Only sample when NOT stalled:
```verilog
always @(posedge clk) begin
    if (rst) begin
        mem_data_reg <= 32'b0;
    end else if (cpu_mem_read_en && !cache_stall) begin
        mem_data_reg <= mem_read_data;
    end
end
```

---

### **BUG #6: Address Decoding Race Condition** ⭐⭐⭐

**Location:** `rtl/top.v` line 54-57

**Current Code:**
```verilog
assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;

assign data_mem_access = `IS_DATA_MEM(data_mem_addr) || 
                        (`IS_DATA_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                        (`IS_DATA_MEM(cpu_mem_write_addr) && cpu_mem_write_en);
```

**Problem:** Combinational logic race! The check uses `data_mem_addr` which depends on write_en, but also checks read/write addresses directly. During transitions, wrong memory selected!

**This explains x13 = 0x10000237 (instruction value)!**

**Research Says:**
> "Bug 2: Race condition between cache miss and stall assertion."

**Fix:** Use only the addresses, not the mux output:
```verilog
assign data_mem_access = (`IS_DATA_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                        (`IS_DATA_MEM(cpu_mem_write_addr) && cpu_mem_write_en);
                        
assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;
```

---

## 🎯 **COMPREHENSIVE FIX PLAN**

### **Phase 1: Fix Memory Unit Stall Gating** (CRITICAL)

**File:** `rtl/memory_unit.v`

**Changes:**
1. Add stall inputs to module
2. Gate write/read enables with stall signals
3. Update instantiation in riscv_cpu.v

**New Code:**
```verilog
module memory_unit (
    input wire clk,
    input wire rst,
    input wire valid_in,
    input wire cache_stall,        // NEW
    input wire hazard_stall,       // NEW
    input wire [5:0] instr_id,
    input wire [31:0] rs2_value,
    input wire [31:0] mem_addr,
    output wire wr_enable,
    output wire read_enable,
    output wire [31:0] wr_data,
    output wire [31:0] read_addr,
    output wire [31:0] wr_addr,
    output wire [3:0] write_byte_enable,
    output wire [2:0] load_type
);

    wire is_store;
    wire is_load;
    
    assign is_store = (instr_id == INSTR_SB) || 
                      (instr_id == INSTR_SH) || 
                      (instr_id == INSTR_SW);
                      
    assign is_load = (instr_id == INSTR_LB) || 
                     (instr_id == INSTR_LH) || 
                     (instr_id == INSTR_LW) ||
                     (instr_id == INSTR_LBU) || 
                     (instr_id == INSTR_LHU);
    
    // CRITICAL FIX: Gate with stall signals
    assign wr_enable = is_store && valid_in && !cache_stall && !hazard_stall;
    assign read_enable = is_load && valid_in && !cache_stall && !hazard_stall;
    
    // Rest remains the same...
```

**Update in riscv_cpu.v:**
```verilog
memory_unit mem_unit_inst0 (
    .clk(clk),
    .rst(rst),
    .valid_in(ex_mem_valid_out),
    .cache_stall(cache_stall),      // ADD THIS
    .hazard_stall(load_use_stall),  // ADD THIS
    .instr_id(ex_mem_inst0_instr_id_out),
    // ... rest
);
```

---

### **Phase 2: Fix Writeback Stall Gating** (CRITICAL)

**File:** `rtl/writeback.v`

**Changes:**
```verilog
module writeback (
    input wire valid_in,
    input wire rd_valid_in,
    input wire [4:0] rd_addr_in,
    input wire [31:0] rd_value_in,
    input wire [31:0] mem_data_in,
    input wire [5:0] instr_id_in,
    input wire cache_stall,        // ADD
    input wire hazard_stall,       // ADD
    output wire [4:0] rd_addr_out,
    output wire [31:0] rd_value_out,
    output wire wr_en_out
);
    wire is_load_instr;
    assign is_load_instr = (instr_id_in == INSTR_LB) || 
                           (instr_id_in == INSTR_LH) || 
                           (instr_id_in == INSTR_LW) || 
                           (instr_id_in == INSTR_LBU) || 
                           (instr_id_in == INSTR_LHU);
    
    assign rd_addr_out = rd_addr_in;
    assign rd_value_out = is_load_instr ? mem_data_in : rd_value_in;
    
    // CRITICAL FIX: Gate with stall signals
    assign wr_en_out = valid_in && rd_valid_in && !cache_stall && !hazard_stall;
    
endmodule
```

**Update in riscv_cpu.v:**
```verilog
writeback wb_inst0 (
    .valid_in(mem_wb_valid_out),
    .rd_valid_in(mem_wb_inst0_rd_valid_out),
    .rd_addr_in(mem_wb_inst0_rd_addr_out),
    .rd_value_in(mem_wb_inst0_exec_output_out),
    .mem_data_in(mem_wb_inst0_mem_data_out),
    .instr_id_in(mem_wb_inst0_instr_id_out),
    .cache_stall(cache_stall),      // ADD
    .hazard_stall(load_use_stall),  // ADD
    .rd_addr_out(wb_inst0_rd_addr_out),
    .rd_value_out(wb_inst0_rd_value_out),
    .wr_en_out(wb_inst0_wr_en_out)
);
```

---

### **Phase 3: Fix mem_data_reg Sampling** (CRITICAL)

**File:** `rtl/top.v`

**Change lines 109-116:**
```verilog
always @(posedge clk) begin
    if (rst) begin
        mem_data_reg <= 32'b0;
    end else if (cpu_mem_read_en && !cache_stall) begin  // ADD: && !cache_stall
        mem_data_reg <= mem_read_data;
    end
    // CRITICAL: Hold value during stalls
end
```

---

### **Phase 4: Fix Address Decoding Race** (HIGH PRIORITY)

**File:** `rtl/top.v`

**Change lines 54-58:**
```verilog
// FIXED: Check addresses directly, not through mux
assign data_mem_access = (`IS_DATA_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                        (`IS_DATA_MEM(cpu_mem_write_addr) && cpu_mem_write_en);

assign timer_access = (`IS_TIMER_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                     (`IS_TIMER_MEM(cpu_mem_write_addr) && cpu_mem_write_en);

assign uart_access = (`IS_UART_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                    (`IS_UART_MEM(cpu_mem_write_addr) && cpu_mem_write_en);

assign instr_mem_access = (`IS_INSTR_MEM(cpu_mem_read_addr) && cpu_mem_read_en);

// Select address AFTER checks
assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;
```

---

### **Phase 5: Improve Forwarding** (OPTIONAL)

**File:** `rtl/pipeline_stages/forwarding_unit.v`

**Current code is actually OK** - we check `rd_valid_mem` which acts as RegWrite. But we can add paranoid check:

```verilog
// Forward to RS1
if (rs1_valid_ex && (rs1_addr_ex != 5'b0)) begin
    // Check MEM stage forwarding first
    if (rd_valid_mem && (rd_addr_mem != 5'b0) && (rd_addr_mem == rs1_addr_ex)) begin
        forward_a = FORWARD_FROM_MEM;
    end
    // Check WB stage forwarding (lower priority)
    else if (rd_valid_wb && wr_en_wb && (rd_addr_wb != 5'b0) && (rd_addr_wb == rs1_addr_ex)) begin
        forward_a = FORWARD_FROM_WB;
    end
end
```

---

## 📊 **EXECUTION ORDER**

### **Step 1:** Fix memory_unit.v (Phase 1)
- Add stall inputs
- Gate write/read enables
- Update riscv_cpu.v instantiation

### **Step 2:** Fix writeback.v (Phase 2)
- Add stall inputs
- Gate wr_en_out
- Update riscv_cpu.v instantiation

### **Step 3:** Fix top.v mem_data_reg (Phase 3)
- Add `!cache_stall` condition

### **Step 4:** Fix top.v address decoding (Phase 4)
- Reorder logic to check addresses first

### **Step 5:** Run comprehensive_load_test.py
- Should now pass!

### **Step 6:** Run combined_stall_test.py
- Should get x8=142, x13=701

---

## 🎯 **PREDICTED OUTCOME**

After these fixes:
- ✅ No more garbage writes during stalls
- ✅ Loads return correct data
- ✅ x7 = 42 (not 0)
- ✅ x8 = 142 (not 100)
- ✅ x13 = 701 (not 0x10000237)
- ✅ All tests pass

**Confidence Level:** 95% - These are the EXACT bugs described in the research!

**Shall I create the complete fixed files?** 🚀