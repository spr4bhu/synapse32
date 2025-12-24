`default_nettype none
`include "instr_defines.vh"

// Store-load hazard detector - forwards store data to immediately following loads at same address
module store_load_detector (
    // Current load instruction (in MEM stage)
    input  wire [5:0] load_instr_id,
    input  wire [31:0] load_addr,

    // Previous store instruction (in WB stage)
    input  wire [5:0] prev_store_instr_id,
    input  wire [31:0] prev_store_addr,
    input  wire [31:0] rs2_value, // Source data of the store (rs2)

    // Output signals
    output wire store_load_hazard,
    output wire [31:0] forwarded_data
);

    // Detect if current instruction is a load
    wire is_load = (load_instr_id == INSTR_LB)  ||
                   (load_instr_id == INSTR_LH)  ||
                   (load_instr_id == INSTR_LW)  ||
                   (load_instr_id == INSTR_LBU) ||
                   (load_instr_id == INSTR_LHU);

    // Detect if previous instruction was a store
    wire is_store = (prev_store_instr_id == INSTR_SB) ||
                    (prev_store_instr_id == INSTR_SH) ||
                    (prev_store_instr_id == INSTR_SW);

    wire addr_match = (load_addr == prev_store_addr);

    // Width-compatible type matching
    wire byte_match =
        ((load_instr_id == INSTR_LB)  ||
         (load_instr_id == INSTR_LBU)) &&
        (prev_store_instr_id == INSTR_SB);

    wire halfword_match =
        ((load_instr_id == INSTR_LH)  ||
         (load_instr_id == INSTR_LHU)) &&
        (prev_store_instr_id == INSTR_SH);

    wire word_match =
        (load_instr_id == INSTR_LW) &&
        (prev_store_instr_id == INSTR_SW);

    wire type_match = byte_match   ||
                     halfword_match ||
                     word_match;

    assign store_load_hazard = is_load && is_store && addr_match && type_match;

    wire [7:0]  byte_data     = rs2_value[7:0];
    wire [15:0] halfword_data = rs2_value[15:0];

    assign forwarded_data = store_load_hazard ? (
        (load_instr_id == INSTR_LB)  ? {{24{byte_data[7]}},     byte_data}      :
        (load_instr_id == INSTR_LBU) ? {24'h0,                 byte_data}      :
        (load_instr_id == INSTR_LH)  ? {{16{halfword_data[15]}}, halfword_data} :
        (load_instr_id == INSTR_LHU) ? {16'h0,                 halfword_data}  :
        (load_instr_id == INSTR_LW)  ? rs2_value                                   :
                                     32'h0
    ) : 32'h0;

endmodule
