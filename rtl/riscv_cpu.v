`default_nettype none
`include "instr_defines.vh"
`include "memory_map.vh"

module riscv_cpu (
    input wire clk,
    input wire rst,
    input wire [31:0] module_instr_in,
    input wire [31:0] module_read_data_in,
    output wire [31:0] module_pc_out,
    output wire [31:0] module_wr_data_out,
    output wire module_mem_wr_en,
    output wire module_mem_rd_en,
    output wire [31:0] module_read_addr,
    output wire [31:0] module_write_addr,
    output wire [3:0] module_write_byte_enable,  // Write byte enables
    output wire [2:0] module_load_type,          // Load type

    // Interrupt inputs
    input wire timer_interrupt,
    input wire software_interrupt,
    input wire external_interrupt,
    
    // Instruction cache interface
    input wire icache_stall,                     // Instruction cache miss stall
    output wire fence_i_signal                   // FENCE.I invalidation signal
);

    // Startup NOP injection: inject NOPs after reset to sync pipeline registers before first instruction reaches writeback
    reg [2:0] startup_nop_counter;
    wire startup_sequence;
    assign startup_sequence = (startup_nop_counter < 3'd4);

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            startup_nop_counter <= 3'b000;
        end else if (startup_sequence) begin
            startup_nop_counter <= startup_nop_counter + 3'd1;
        end
    end

    // Instantiate PC
    wire [31:0] pc_inst0_out;
    wire pc_inst0_j_signal;
    wire [31:0] pc_inst0_jump;
    wire stall_pipeline; // For load-use hazards
    
    // Stalls: pipeline (hazards, cache), PC (pipeline + startup)
    wire pipeline_stall;
    wire pc_stall;
    assign pipeline_stall = stall_pipeline || icache_stall;
    assign pc_stall = pipeline_stall || startup_sequence;
    
    // FENCE.I detection - invalidate instruction cache
    assign fence_i_signal = (id_ex_inst0_instr_id_out == INSTR_FENCE_I);
    
    // Branch handling: use EX stage jump signal/address
    assign pc_inst0_j_signal = ex_inst0_jump_signal_out;
    assign pc_inst0_jump = ex_inst0_jump_addr_out;
    pc pc_inst0 (
        .clk(clk),
        .rst(rst),
        .j_signal(pc_inst0_j_signal),
        .jump(pc_inst0_jump),
        .stall(pc_stall), // Stall on load-use hazard, cache miss, or startup NOP sequence
        .out(pc_inst0_out)
    );

    // Send out the PC value
    assign module_pc_out = pc_inst0_out;


    // Instantiate IF_ID pipeline register
    wire [31:0] if_id_pc_out;
    wire [31:0] if_id_instr_out;
    wire branch_flush;
    assign branch_flush = ex_inst0_jump_signal_out;
    wire if_id_stall;
    // Do NOT stall IF/ID during startup sequence; we want NOPs to flow through the pipeline.
    assign if_id_stall = pipeline_stall && !branch_flush;
    
    // Inject NOPs (ADDI x0, x0, 0 = 0x00000013) during startup or branch flush
    wire [31:0] instruction_to_if_id;
    assign instruction_to_if_id = (branch_flush || startup_sequence) ? 32'h00000013 : module_instr_in;
    
    IF_ID if_id_inst0 (
        .clk(clk),
        .rst(rst),
        .pc_in(pc_inst0_out),
        .instruction_in(instruction_to_if_id),
        .stall(if_id_stall),
        .pc_out(if_id_pc_out),
        .instruction_out(if_id_instr_out)
    );

    // Instantiate Decoder
    wire [4:0] decoder_inst0_rs1_out;
    wire [4:0] decoder_inst0_rs2_out;
    wire [4:0] decoder_inst0_rd_out;
    wire [31:0] decoder_inst0_imm_out;
    wire decoder_inst0_rs1_valid_out;
    wire decoder_inst0_rs2_valid_out;
    wire decoder_inst0_rd_valid_out;
    wire [6:0] decoder_inst0_opcode_out;
    wire [5:0] decoder_inst0_instr_id_out;

    decoder decoder_inst0 (
        .instr(if_id_instr_out),
        .rs2(decoder_inst0_rs2_out),
        .rs1(decoder_inst0_rs1_out),
        .imm(decoder_inst0_imm_out),
        .rd(decoder_inst0_rd_out),
        .rs1_valid(decoder_inst0_rs1_valid_out),
        .rs2_valid(decoder_inst0_rs2_valid_out),
        .rd_valid(decoder_inst0_rd_valid_out),
        .opcode(decoder_inst0_opcode_out),
        .instr_id(decoder_inst0_instr_id_out)
    );
    
    // Instantiate Load-Use Hazard Detector
    load_use_detector load_use_detector_inst0 (
        .rs1_id(decoder_inst0_rs1_out),
        .rs2_id(decoder_inst0_rs2_out),
        .rs1_valid_id(decoder_inst0_rs1_valid_out),
        .rs2_valid_id(decoder_inst0_rs2_valid_out),
        .instr_id_ex(id_ex_inst0_instr_id_out),
        .rd_ex(id_ex_inst0_rd_addr_out),
        .rd_valid_ex(id_ex_inst0_rd_valid_out),
        .stall_pipeline(stall_pipeline)
    );

    // Instantiate Register File
    wire [31:0] rf_inst0_rs1_value_out;
    wire [31:0] rf_inst0_rs2_value_out;
    // RD control signals will be later handled by WB stage
    wire [4:0] rf_inst0_rd_in;
    wire rf_inst0_wr_en;
    wire [31:0] rf_inst0_rd_value_in;


    registerfile rf_inst0 (
        .clk(clk),
        .rst(rst),
        .rs1(decoder_inst0_rs1_out),
        .rs2(decoder_inst0_rs2_out),
        .rs1_valid(decoder_inst0_rs1_valid_out),
        .rs2_valid(decoder_inst0_rs2_valid_out),
        .rd(rf_inst0_rd_in),
        .wr_en(rf_inst0_wr_en),
        .rd_value(rf_inst0_rd_value_in),
        .rs1_value(rf_inst0_rs1_value_out),
        .rs2_value(rf_inst0_rs2_value_out)
    );

    // Instantiate ID_EX pipeline register
    wire id_ex_inst0_rs1_valid_out;
    wire id_ex_inst0_rs2_valid_out;
    wire id_ex_inst0_rd_valid_out;
    wire [31:0] id_ex_inst0_imm_out;
    wire [4:0] id_ex_inst0_rs1_addr_out;
    wire [4:0] id_ex_inst0_rs2_addr_out;
    wire [4:0] id_ex_inst0_rd_addr_out;
    wire [6:0] id_ex_inst0_opcode_out;
    wire [5:0] id_ex_inst0_instr_id_out;
    wire [31:0] id_ex_inst0_pc_out;
    wire [31:0] id_ex_inst0_rs1_value_out;
    wire [31:0] id_ex_inst0_rs2_value_out;

    // Pipeline flush signals
    wire execution_flush;
    wire pipeline_flush;
    
    // Combine branch flush and execution unit flush
    assign pipeline_flush = branch_flush || execution_flush;

    ID_EX id_ex_inst0 (
        .clk(clk),
        .rst(rst),
        .rs1_valid_in(decoder_inst0_rs1_valid_out),
        .rs2_valid_in(decoder_inst0_rs2_valid_out),
        .rd_valid_in(decoder_inst0_rd_valid_out),
        .imm_in(decoder_inst0_imm_out),
        .rs1_addr_in(decoder_inst0_rs1_out),
        .rs2_addr_in(decoder_inst0_rs2_out),
        .rd_addr_in(decoder_inst0_rd_out),
        .opcode_in(decoder_inst0_opcode_out),
        .instr_id_in(decoder_inst0_instr_id_out),
        .pc_in(if_id_pc_out),
        .rs1_value_in(rf_inst0_rs1_value_out),
        .rs2_value_in(rf_inst0_rs2_value_out),
        // Stall on hazards/cache/flush only, not startup (allow NOPs to propagate)
        .stall(pipeline_flush || pipeline_stall),
        .rs1_valid_out(id_ex_inst0_rs1_valid_out),
        .rs2_valid_out(id_ex_inst0_rs2_valid_out),
        .rd_valid_out(id_ex_inst0_rd_valid_out),
        .imm_out(id_ex_inst0_imm_out),
        .rs1_addr_out(id_ex_inst0_rs1_addr_out),
        .rs2_addr_out(id_ex_inst0_rs2_addr_out),
        .rd_addr_out(id_ex_inst0_rd_addr_out),
        .opcode_out(id_ex_inst0_opcode_out),
        .instr_id_out(id_ex_inst0_instr_id_out),
        .pc_out(id_ex_inst0_pc_out),
        .rs1_value_out(id_ex_inst0_rs1_value_out),
        .rs2_value_out(id_ex_inst0_rs2_value_out)
    );

    // Instantiate Execution Unit
    wire [31:0] ex_inst0_exec_output_out;
    wire ex_inst0_jump_signal_out;
    wire [31:0] ex_inst0_jump_addr_out;
    wire [31:0] ex_inst0_mem_addr_out;
    wire [31:0] ex_inst0_rs1_value_out;
    wire [31:0] ex_inst0_rs2_value_out;
    
    // Forwarding unit signals
    wire [1:0] forward_a;
    wire [1:0] forward_b;

    // Actual WB stage values (including store-queue and load-queue forwarding)
    // These are computed later in the file after writeback arbitration
    wire actual_wb_wr_en;
    wire [4:0] actual_wb_rd_addr;
    wire actual_wb_rd_valid;

    // Instantiate forwarding unit
    forwarding_unit forwarding_unit_inst0 (
        .rs1_addr_ex(id_ex_inst0_rs1_addr_out),
        .rs2_addr_ex(id_ex_inst0_rs2_addr_out),
        .rs1_valid_ex(id_ex_inst0_rs1_valid_out),
        .rs2_valid_ex(id_ex_inst0_rs2_valid_out),
        .rd_addr_mem(ex_mem_inst0_rd_addr_out),
        .rd_valid_mem(ex_mem_inst0_rd_valid_out),
        .instr_id_mem(ex_mem_inst0_instr_id_out),
        .rd_addr_wb(actual_wb_rd_addr),
        .rd_valid_wb(actual_wb_rd_valid),
        .wr_en_wb(actual_wb_wr_en),
        .forward_a(forward_a),
        .forward_b(forward_b)
    );

    // CSR file signals
    wire [11:0] csr_addr;
    wire [31:0] csr_read_data;
    wire [31:0] csr_write_data;
    wire csr_write_enable;
    wire csr_read_enable;
    wire csr_valid;

    // Interrupt controller signals
    wire interrupt_pending;
    wire [31:0] interrupt_cause;
    wire [31:0] interrupt_pc;
    wire interrupt_taken;
    wire mret_instruction;
    wire ecall_exception;
    wire ebreak_exception;

    // Instantiate interrupt controller
    interrupt_controller int_ctrl_inst (
        .clk(clk),
        .rst(rst),
        .timer_interrupt(timer_interrupt),
        .software_interrupt(software_interrupt),
        .external_interrupt(external_interrupt),
        .mstatus(csr_file_inst.mstatus),
        .mie(csr_file_inst.mie),
        .mip(csr_file_inst.mip),
        .interrupt_pending(interrupt_pending),
        .interrupt_cause(interrupt_cause),
        .interrupt_taken(interrupt_taken),
        .current_pc(pc_inst0_out),
        .interrupt_pc(interrupt_pc)
    );

    // Instantiate CSR file at CPU level
    csr_file csr_file_inst (
        .clk(clk),
        .rst(rst),
        .csr_addr(csr_addr),
        .write_data(csr_write_data),
        .write_enable(csr_write_enable),
        .read_enable(csr_read_enable),
        .read_data(csr_read_data),
        .csr_valid(csr_valid),
        .interrupt_pending(interrupt_pending),
        .interrupt_cause_in(interrupt_cause),
        .interrupt_pc_in(interrupt_pc),
        .interrupt_taken(interrupt_taken),
        .mret_instruction(mret_instruction),
        .ecall_exception(ecall_exception),
        .ebreak_exception(ebreak_exception),
        .timer_interrupt(timer_interrupt),
        .software_interrupt(software_interrupt),
        .external_interrupt(external_interrupt)
    );

    //=========================================================================
    // Load Queue and Store Queue Integration
    //=========================================================================

    // Load Queue signals
    wire lq_enq_valid;
    wire lq_enq_ready;
    wire [2:0] lq_enq_lq_id;
    wire lq_mem_req_valid;
    wire [31:0] lq_mem_req_addr;
    wire [2:0] lq_mem_req_lq_id;
    wire lq_mem_req_ready;
    wire lq_mem_resp_valid;
    wire [31:0] lq_mem_resp_data;
    wire [2:0] lq_mem_resp_lq_id;
    wire lq_deq_valid;
    wire [4:0] lq_deq_rd;
    wire [31:0] lq_deq_data;
    wire lq_deq_ready;
    wire lq_full;
    wire lq_empty;

    // Store Queue signals
    wire sq_enq_valid;
    wire sq_enq_ready;
    wire [2:0] sq_enq_sq_id;
    wire sq_mem_write_valid;
    wire [31:0] sq_mem_write_addr;
    wire [31:0] sq_mem_write_data;
    wire [3:0] sq_mem_write_byte_en;
    wire sq_mem_write_ready;
    wire sq_lookup_valid;
    wire [31:0] sq_lookup_addr;
    wire [2:0] sq_lookup_load_type;
    wire sq_forward_match;
    wire [31:0] sq_forward_data;
    wire sq_full;
    wire sq_empty;

    // Determine if current EX instruction is a load
    wire ex_is_load;
    assign ex_is_load = (id_ex_inst0_instr_id_out == INSTR_LB) ||
                        (id_ex_inst0_instr_id_out == INSTR_LH) ||
                        (id_ex_inst0_instr_id_out == INSTR_LW) ||
                        (id_ex_inst0_instr_id_out == INSTR_LBU) ||
                        (id_ex_inst0_instr_id_out == INSTR_LHU);

    // Determine if current EX instruction is a store
    wire ex_is_store;
    assign ex_is_store = (id_ex_inst0_instr_id_out == INSTR_SB) ||
                         (id_ex_inst0_instr_id_out == INSTR_SH) ||
                         (id_ex_inst0_instr_id_out == INSTR_SW);

    // Extract load type from instruction ID (func3 encoding)
    wire [2:0] ex_load_type;
    assign ex_load_type =
        (id_ex_inst0_instr_id_out == INSTR_LB)  ? 3'b000 :
        (id_ex_inst0_instr_id_out == INSTR_LH)  ? 3'b001 :
        (id_ex_inst0_instr_id_out == INSTR_LW)  ? 3'b010 :
        (id_ex_inst0_instr_id_out == INSTR_LBU) ? 3'b100 :
        (id_ex_inst0_instr_id_out == INSTR_LHU) ? 3'b101 :
        3'b111;

    // Extract store type from instruction ID (func3 encoding)
    wire [2:0] ex_store_type;
    assign ex_store_type =
        (id_ex_inst0_instr_id_out == INSTR_SB) ? 3'b000 :
        (id_ex_inst0_instr_id_out == INSTR_SH) ? 3'b001 :
        (id_ex_inst0_instr_id_out == INSTR_SW) ? 3'b010 :
        3'b111;

    // Store-to-load forwarding from store queue to loads in EX stage
    // Check if load can be forwarded from store queue before enqueueing to load queue
    assign sq_lookup_valid = ex_is_load && !branch_flush && !execution_flush;
    assign sq_lookup_addr = ex_inst0_mem_addr_out;
    assign sq_lookup_load_type = ex_load_type;

    // Enqueue loads from EX stage (only if not forwarded from store queue)
    assign lq_enq_valid = ex_is_load && !branch_flush && !execution_flush && !sq_forward_match;

    // Enqueue stores from EX stage
    assign sq_enq_valid = ex_is_store && !branch_flush && !execution_flush;

    // Instantiate Load Queue
    load_queue #(
        .ENTRIES(8),
        .ADDR_WIDTH(32),
        .DATA_WIDTH(32)
    ) load_queue_inst (
        .clk(clk),
        .rst(rst),
        .enq_valid(lq_enq_valid),
        .enq_addr(ex_inst0_mem_addr_out),
        .enq_rd(id_ex_inst0_rd_addr_out),
        .enq_load_type(ex_load_type),
        .enq_ready(lq_enq_ready),
        .enq_lq_id(lq_enq_lq_id),
        .mem_req_valid(lq_mem_req_valid),
        .mem_req_addr(lq_mem_req_addr),
        .mem_req_lq_id(lq_mem_req_lq_id),
        .mem_req_ready(lq_mem_req_ready),
        .mem_resp_valid(lq_mem_resp_valid),
        .mem_resp_data(lq_mem_resp_data),
        .mem_resp_lq_id(lq_mem_resp_lq_id),
        .deq_valid(lq_deq_valid),
        .deq_rd(lq_deq_rd),
        .deq_data(lq_deq_data),
        .deq_ready(lq_deq_ready),
        .full(lq_full),
        .empty(lq_empty)
    );

    // Instantiate Store Queue
    store_queue #(
        .ENTRIES(8),
        .ADDR_WIDTH(32),
        .DATA_WIDTH(32)
    ) store_queue_inst (
        .clk(clk),
        .rst(rst),
        .enq_valid(sq_enq_valid),
        .enq_addr(ex_inst0_mem_addr_out),
        .enq_data(ex_inst0_rs2_value_out),
        .enq_store_type(ex_store_type),
        .enq_ready(sq_enq_ready),
        .enq_sq_id(sq_enq_sq_id),
        .mem_write_valid(sq_mem_write_valid),
        .mem_write_addr(sq_mem_write_addr),
        .mem_write_data(sq_mem_write_data),
        .mem_write_byte_en(sq_mem_write_byte_en),
        .mem_write_ready(sq_mem_write_ready),
        .lookup_valid(sq_lookup_valid),
        .lookup_addr(sq_lookup_addr),
        .lookup_load_type(sq_lookup_load_type),
        .forward_match(sq_forward_match),
        .forward_data(sq_forward_data),
        .full(sq_full),
        .empty(sq_empty)
    );

    execution_unit ex_unit_inst0 (
        .rs1(id_ex_inst0_rs1_value_out),
        .rs2(id_ex_inst0_rs2_value_out),
        .imm(id_ex_inst0_imm_out),
        .rs1_addr(id_ex_inst0_rs1_addr_out),
        .rs2_addr(id_ex_inst0_rs2_addr_out),
        .opcode(id_ex_inst0_opcode_out),
        .instr_id(id_ex_inst0_instr_id_out),
        .rs1_valid(id_ex_inst0_rs1_valid_out),
        .rs2_valid(id_ex_inst0_rs2_valid_out),
        .pc_input(id_ex_inst0_pc_out),
        .forward_a(forward_a),
        .forward_b(forward_b),
        .ex_mem_result(ex_mem_inst0_exec_output_out),
        .mem_wb_result(wb_inst0_rd_value_out),
        
        // CSR interface connections
        .csr_read_data(csr_read_data),
        .csr_valid(csr_valid),
        .csr_addr(csr_addr),
        .csr_read_enable(csr_read_enable),
        .csr_write_data(csr_write_data),
        .csr_write_enable(csr_write_enable),
        
        .exec_output(ex_inst0_exec_output_out),
        .jump_signal(ex_inst0_jump_signal_out),
        .jump_addr(ex_inst0_jump_addr_out),
        .mem_addr(ex_inst0_mem_addr_out),
        .rs1_value_out(ex_inst0_rs1_value_out),
        .rs2_value_out(ex_inst0_rs2_value_out),
        .flush_pipeline(execution_flush),

        // Interrupt connections
        .interrupt_pending(interrupt_pending),
        .interrupt_cause(interrupt_cause),
        .mtvec(csr_file_inst.mtvec),
        .mepc(csr_file_inst.mepc),
        .interrupt_taken(interrupt_taken),
        .mret_instruction(mret_instruction),
        .ecall_exception(ecall_exception),
        .ebreak_exception(ebreak_exception)
    );

    // Memory Stage

    // Instantiate EX_MEM pipeline register
    wire [4:0] ex_mem_inst0_rs1_addr_out;
    wire [4:0] ex_mem_inst0_rs2_addr_out;
    wire [4:0] ex_mem_inst0_rd_addr_out;
    wire [31:0] ex_mem_inst0_rs1_value_out;
    wire [31:0] ex_mem_inst0_rs2_value_out;
    wire [31:0] ex_mem_inst0_pc_out;
    wire [31:0] ex_mem_inst0_mem_addr_out;
    wire [31:0] ex_mem_inst0_exec_output_out;
    wire ex_mem_inst0_jump_signal_out;
    wire [31:0] ex_mem_inst0_jump_addr_out;
    wire [5:0] ex_mem_inst0_instr_id_out;
    wire ex_mem_inst0_rd_valid_out;

    // Invalidate rd_valid if load was forwarded from store queue
    // Forwarded loads write back directly, shouldn't write back from pipeline
    wire ex_mem_rd_valid_in;
    assign ex_mem_rd_valid_in = sq_forward_match ? 1'b0 : id_ex_inst0_rd_valid_out;

    EX_MEM ex_mem_inst0 (
        .clk(clk),
        .rst(rst),
        .rs1_addr_in(id_ex_inst0_rs1_addr_out),
        .rs2_addr_in(id_ex_inst0_rs2_addr_out),
        .rd_addr_in(id_ex_inst0_rd_addr_out),
        .rs1_value_in(ex_inst0_rs1_value_out),
        .rs2_value_in(ex_inst0_rs2_value_out),
        .pc_in(id_ex_inst0_pc_out),
        .mem_addr_in(ex_inst0_mem_addr_out),
        .exec_output_in(ex_inst0_exec_output_out),
        .jump_signal_in(ex_inst0_jump_signal_out),
        .jump_addr_in(ex_inst0_jump_addr_out),
        .instr_id_in(id_ex_inst0_instr_id_out),
        .rd_valid_in(ex_mem_rd_valid_in),
        .rs1_addr_out(ex_mem_inst0_rs1_addr_out),
        .rs2_addr_out(ex_mem_inst0_rs2_addr_out),
        .rd_addr_out(ex_mem_inst0_rd_addr_out),
        .rs1_value_out(ex_mem_inst0_rs1_value_out),
        .rs2_value_out(ex_mem_inst0_rs2_value_out),
        .pc_out(ex_mem_inst0_pc_out),
        .mem_addr_out(ex_mem_inst0_mem_addr_out),
        .exec_output_out(ex_mem_inst0_exec_output_out),
        .jump_signal_out(ex_mem_inst0_jump_signal_out),
        .jump_addr_out(ex_mem_inst0_jump_addr_out),
        .instr_id_out(ex_mem_inst0_instr_id_out),
        .rd_valid_out(ex_mem_inst0_rd_valid_out)
    );

    // Instantiate Memory Unit
    wire mem_unit_inst0_wr_enable_out;
    wire mem_unit_inst0_read_enable_out;
    wire [31:0] mem_unit_inst0_wr_data_out;
    wire [31:0] mem_unit_inst0_read_addr_out;
    wire [31:0] mem_unit_inst0_wr_addr_out;
    wire [3:0] mem_unit_inst0_write_byte_enable_out;  // Write byte enables
    wire [2:0] mem_unit_inst0_load_type_out;          // Load type

    //=========================================================================
    // Memory Arbitration: Priority-based (Industry Standard)
    //=========================================================================
    // Dynamic priority based on queue occupancy to prevent starvation
    // Priority levels:
    //   1. Store queue >75% full → prioritize stores (prevent deadlock)
    //   2. Load queue >75% full → prioritize loads (unblock pipeline)
    //   3. Otherwise → loads get priority (critical path)

    localparam SQ_ALMOST_FULL_THRESHOLD = 6;  // 75% of 8 entries
    localparam LQ_ALMOST_FULL_THRESHOLD = 6;  // 75% of 8 entries

    wire sq_almost_full;
    wire lq_almost_full;
    wire grant_load;
    wire grant_store;

    assign sq_almost_full = !sq_empty && (sq_full || !sq_enq_ready);
    assign lq_almost_full = !lq_empty && (lq_full || !lq_enq_ready);

    // Priority arbitration logic
    assign grant_store = sq_mem_write_valid && (
        !lq_mem_req_valid ||           // No competing load
        sq_almost_full ||               // SQ almost full - prioritize draining
        (!lq_almost_full)               // Neither full, stores get chance
    );
    assign grant_load = lq_mem_req_valid && !grant_store;

    // Grant signals to queues
    assign lq_mem_req_ready = grant_load;
    assign sq_mem_write_ready = grant_store;

    // Route memory signals through load/store queues
    assign module_mem_rd_en = grant_load;
    assign module_mem_wr_en = grant_store;
    assign module_read_addr = lq_mem_req_addr;
    assign module_write_addr = sq_mem_write_addr;
    assign module_wr_data_out = sq_mem_write_data;
    assign module_write_byte_enable = sq_mem_write_byte_en;
    assign module_load_type = 3'b010;  // Unused - load queue handles extension

    //=========================================================================
    // Memory Response Handling
    //=========================================================================
    // Register memory read for 1 cycle to match load queue timing
    reg mem_read_valid_reg;
    reg [31:0] mem_read_data_reg;
    reg [2:0] mem_read_lq_id_reg;

    always @(posedge clk) begin
        if (rst) begin
            mem_read_valid_reg <= 0;
            mem_read_data_reg <= 0;
            mem_read_lq_id_reg <= 0;
        end else begin
            mem_read_valid_reg <= module_mem_rd_en;
            mem_read_data_reg <= module_read_data_in;
            mem_read_lq_id_reg <= lq_mem_req_lq_id;
        end
    end

    assign lq_mem_resp_valid = mem_read_valid_reg;
    assign lq_mem_resp_data = mem_read_data_reg;
    assign lq_mem_resp_lq_id = mem_read_lq_id_reg;

    memory_unit mem_unit_inst0 (
        .instr_id(ex_mem_inst0_instr_id_out),
        .rs2_value(ex_mem_inst0_rs2_value_out),
        .mem_addr(ex_mem_inst0_mem_addr_out),
        .wr_enable(mem_unit_inst0_wr_enable_out),
        .read_enable(mem_unit_inst0_read_enable_out),
        .wr_data(mem_unit_inst0_wr_data_out),
        .read_addr(mem_unit_inst0_read_addr_out),
        .wr_addr(mem_unit_inst0_wr_addr_out),
        .write_byte_enable(mem_unit_inst0_write_byte_enable_out),
        .load_type(mem_unit_inst0_load_type_out)
    );

    // Instantiate MEM_WB pipeline register
    wire [4:0] mem_wb_inst0_rs1_addr_out;
    wire [4:0] mem_wb_inst0_rs2_addr_out;
    wire [4:0] mem_wb_inst0_rd_addr_out;
    wire [31:0] mem_wb_inst0_rs1_value_out;
    wire [31:0] mem_wb_inst0_rs2_value_out;
    wire [31:0] mem_wb_inst0_pc_out;
    wire [31:0] mem_wb_inst0_mem_addr_out;
    wire [31:0] mem_wb_inst0_exec_output_out;
    wire mem_wb_inst0_jump_signal_out;
    wire [31:0] mem_wb_inst0_jump_addr_out;
    wire [5:0] mem_wb_inst0_instr_id_out;
    wire mem_wb_inst0_rd_valid_out;
    wire [31:0] mem_wb_inst0_mem_data_out;

    // Store-to-load forwarding now handled by Store Queue (EX stage)
    // Load Queue handles asynchronous load completion
    // Old store_load_detector removed (redundant with queue-based forwarding)

    MEM_WB mem_wb_inst0 (
        .clk(clk),
        .rst(rst),
        .rs1_addr_in(ex_mem_inst0_rs1_addr_out),
        .rs2_addr_in(ex_mem_inst0_rs2_addr_out),
        .rd_addr_in(ex_mem_inst0_rd_addr_out),
        .rs1_value_in(ex_mem_inst0_rs1_value_out),
        .rs2_value_in(ex_mem_inst0_rs2_value_out),
        .pc_in(ex_mem_inst0_pc_out),
        .mem_addr_in(ex_mem_inst0_mem_addr_out),
        .exec_output_in(ex_mem_inst0_exec_output_out),
        .jump_signal_in(ex_mem_inst0_jump_signal_out),
        .jump_addr_in(ex_mem_inst0_jump_addr_out),
        .instr_id_in(ex_mem_inst0_instr_id_out),
        .rd_valid_in(ex_mem_inst0_rd_valid_out),
        .mem_data_in(module_read_data_in),  // Direct memory read (queues handle forwarding)

        // Outputs
        .rs1_addr_out(mem_wb_inst0_rs1_addr_out),
        .rs2_addr_out(mem_wb_inst0_rs2_addr_out),
        .rd_addr_out(mem_wb_inst0_rd_addr_out),
        .rs1_value_out(mem_wb_inst0_rs1_value_out),
        .rs2_value_out(mem_wb_inst0_rs2_value_out),
        .pc_out(mem_wb_inst0_pc_out),
        .mem_addr_out(mem_wb_inst0_mem_addr_out),
        .exec_output_out(mem_wb_inst0_exec_output_out),
        .jump_signal_out(mem_wb_inst0_jump_signal_out),
        .jump_addr_out(mem_wb_inst0_jump_addr_out),
        .instr_id_out(mem_wb_inst0_instr_id_out),
        .rd_valid_out(mem_wb_inst0_rd_valid_out),
        .mem_data_out(mem_wb_inst0_mem_data_out)  // Output to WB stage
    );

    // Instantiate Write Back Stage
    wire wb_inst0_wr_en_out;
    wire [4:0] wb_inst0_rd_addr_out;
    wire [31:0] wb_inst0_rd_value_out;

    //=========================================================================
    // Writeback Arbitration with Load/Store Queues
    //=========================================================================
    // Store-to-load forwarding: Register for 1 cycle (match load queue timing)
    // Both store queue forwarding and load queue retirement happen at WB stage
    reg sq_forwarded_valid;
    reg [4:0] sq_forwarded_rd;
    reg [31:0] sq_forwarded_data;

    always @(posedge clk) begin
        if (rst) begin
            sq_forwarded_valid <= 0;
            sq_forwarded_rd <= 0;
            sq_forwarded_data <= 0;
        end else begin
            sq_forwarded_valid <= sq_forward_match;
            sq_forwarded_rd <= id_ex_inst0_rd_addr_out;
            sq_forwarded_data <= sq_forward_data;
        end
    end

    // Load queue always ready to dequeue
    assign lq_deq_ready = 1'b1;

    // Writeback arbitration: Priority to store queue forwarding > load queue > pipeline
    // All three sources can write to register file
    assign rf_inst0_wr_en = sq_forwarded_valid ? 1'b1 :
                            (lq_deq_valid ? 1'b1 : wb_inst0_wr_en_out);
    assign rf_inst0_rd_in = sq_forwarded_valid ? sq_forwarded_rd :
                            (lq_deq_valid ? lq_deq_rd : wb_inst0_rd_addr_out);
    assign rf_inst0_rd_value_in = sq_forwarded_valid ? sq_forwarded_data :
                                  (lq_deq_valid ? lq_deq_data : wb_inst0_rd_value_out);

    // Expose actual WB values for forwarding unit (includes all writeback sources)
    assign actual_wb_wr_en = rf_inst0_wr_en;
    assign actual_wb_rd_addr = rf_inst0_rd_in;
    assign actual_wb_rd_valid = rf_inst0_wr_en;  // If writing, then rd is valid

    writeback wb_inst0 (
        .rd_valid_in(mem_wb_inst0_rd_valid_out),
        .rd_addr_in(mem_wb_inst0_rd_addr_out),
        .rd_value_in(mem_wb_inst0_exec_output_out),
        .mem_data_in(mem_wb_inst0_mem_data_out),  // Use pipelined data
        .instr_id_in(mem_wb_inst0_instr_id_out),
        .rd_addr_out(wb_inst0_rd_addr_out),
        .rd_value_out(wb_inst0_rd_value_out),
        .wr_en_out(wb_inst0_wr_en_out)
    );

endmodule
