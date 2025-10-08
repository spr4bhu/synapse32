`default_nettype none
`include "instr_defines.vh"

module memory_unit (
    input wire clk,
    input wire rst,
    input wire valid_in,               // NEW: valid bit from EX_MEM
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

    // ============================================================================
    // WRITE-ONCE TRACKING
    // Prevents the same store from writing multiple times
    // ============================================================================
    
    reg store_executed;           // Has this store already written?
    reg [31:0] last_mem_addr;     // What address did we last process?
    reg [5:0] last_instr_id;      // What instruction did we last process?
    reg last_valid;               // Was last cycle valid?
    
    // Detect if a NEW instruction has entered the MEM stage
    // An instruction is "new" if:
    // 1. The address changed, OR
    // 2. The instruction ID changed, OR
    // 3. We transitioned from invalid to valid (new instruction entering after bubble)
    wire new_instruction;
    assign new_instruction = (mem_addr != last_mem_addr) || 
                            (instr_id != last_instr_id) ||
                            (!last_valid && valid_in);
    
    // State machine to track store execution
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            store_executed <= 1'b0;
            last_mem_addr <= 32'b0;
            last_instr_id <= 6'b0;
            last_valid <= 1'b0;
        end else begin
            // Update tracking registers every cycle
            last_mem_addr <= mem_addr;
            last_instr_id <= instr_id;
            last_valid <= valid_in;
            
            if (new_instruction) begin
                // New instruction arrived - reset the executed flag
                store_executed <= 1'b0;
            end else if (is_store_internal && valid_in && !store_executed) begin
                // We just executed a store for the first time - mark it
                store_executed <= 1'b1;
            end
            // If same instruction and already executed, keep flag high
        end
    end
    
    // ============================================================================
    // INSTRUCTION DECODING (unchanged from your original)
    // ============================================================================
    
    wire is_store_internal;
    wire is_load_internal;
    
    assign is_store_internal = (instr_id == INSTR_SB) || 
                               (instr_id == INSTR_SH) || 
                               (instr_id == INSTR_SW);
                               
    assign is_load_internal = (instr_id == INSTR_LB) || 
                              (instr_id == INSTR_LH) || 
                              (instr_id == INSTR_LW) ||
                              (instr_id == INSTR_LBU) || 
                              (instr_id == INSTR_LHU);
    
    // ============================================================================
    // CONTROL SIGNALS - WITH WRITE-ONCE PROTECTION
    // ============================================================================
    
    // CRITICAL: Only write if:
    // 1. This is a store instruction, AND
    // 2. The instruction is valid, AND
    // 3. We haven't already executed this store
    assign wr_enable = is_store_internal && valid_in && !store_executed;
    
    // Loads don't need write-once protection (reading multiple times is harmless)
    // But still respect the valid bit
    assign read_enable = is_load_internal && valid_in;
    
    // ============================================================================
    // ADDRESS AND DATA OUTPUTS (unchanged from your original)
    // ============================================================================
    
    assign wr_addr = mem_addr;
    assign read_addr = mem_addr;
    
    // Byte enable logic (unchanged)
    assign write_byte_enable =
        (instr_id == INSTR_SB) ? 4'b0001 :
        (instr_id == INSTR_SH) ? (
            (mem_addr[0] == 1'b0) ? 4'b0011 : 4'b0000
        ) :
        (instr_id == INSTR_SW) ? (
            (mem_addr[1:0] == 2'b00) ? 4'b1111 : 4'b0000
        ) : 4'b0000;
    
    // Load type encoding (unchanged)
    assign load_type =
        (instr_id == INSTR_LB) ? 3'b000 :
        (instr_id == INSTR_LH) ? 3'b001 :
        (instr_id == INSTR_LW) ? 3'b010 :
        (instr_id == INSTR_LBU) ? 3'b100 :
        (instr_id == INSTR_LHU) ? 3'b101 :
        3'b111;
    
    // Write data formatting (unchanged)
    assign wr_data =
        (instr_id == INSTR_SB) ? {24'b0, rs2_value[7:0]} :
        (instr_id == INSTR_SH) ? {16'b0, rs2_value[15:0]} :
        (instr_id == INSTR_SW) ? rs2_value :
        32'b0;

endmodule