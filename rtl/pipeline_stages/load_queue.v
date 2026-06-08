`default_nettype none

//=============================================================================
// Load Queue - RISC-V Memory Subsystem Component
//=============================================================================
// Implements a circular buffer that decouples load execution from memory
// latency, allowing out-of-order memory responses while maintaining
// program-order completion (in-order writeback).
//
// Key Features:
// - Configurable depth (default 8 entries)
// - Out-of-order memory response handling
// - Program-order dequeue to writeback
// - Support for all RV32I load types (LB, LH, LW, LBU, LHU)
// - Full/empty status for pipeline stall control
//
// RISC-V Compliance:
// - Maintains program order for load completion
// - Proper sign/zero extension per load type specification
// - Supports precise exceptions (via program-order retirement)
//=============================================================================

module load_queue #(
    parameter ENTRIES = 8,
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter INDEX_WIDTH = $clog2(ENTRIES)
)(
    input wire clk,
    input wire rst,

    //-------------------------------------------------------------------------
    // Enqueue Interface (from EX stage)
    //-------------------------------------------------------------------------
    input wire enq_valid,                       // Load instruction in EX stage
    input wire [ADDR_WIDTH-1:0] enq_addr,       // Memory address to load from
    input wire [4:0] enq_rd,                    // Destination register (x0-x31)
    input wire [2:0] enq_load_type,             // func3: LB/LH/LW/LBU/LHU
    output wire enq_ready,                      // Queue has space (not full)
    output wire [INDEX_WIDTH-1:0] enq_lq_id,    // Assigned LQ entry ID

    //-------------------------------------------------------------------------
    // Memory Request Interface
    //-------------------------------------------------------------------------
    output wire mem_req_valid,                  // Request to memory
    output wire [ADDR_WIDTH-1:0] mem_req_addr,  // Request address
    output wire [INDEX_WIDTH-1:0] mem_req_lq_id, // LQ entry for this request
    input wire mem_req_ready,                   // Memory can accept request

    //-------------------------------------------------------------------------
    // Memory Response Interface (out-of-order capable)
    //-------------------------------------------------------------------------
    input wire mem_resp_valid,                  // Memory response ready
    input wire [DATA_WIDTH-1:0] mem_resp_data,  // Data from memory
    input wire [INDEX_WIDTH-1:0] mem_resp_lq_id, // Which LQ entry this is for

    //-------------------------------------------------------------------------
    // Dequeue Interface (to WB stage - program order)
    //-------------------------------------------------------------------------
    output wire deq_valid,                      // Load ready to retire
    output wire [4:0] deq_rd,                   // Destination register
    output wire [DATA_WIDTH-1:0] deq_data,      // Load data (sign/zero extended)
    input wire deq_ready,                       // WB stage can accept

    //-------------------------------------------------------------------------
    // Status Signals
    //-------------------------------------------------------------------------
    output wire full,                           // Queue full (stall pipeline)
    output wire empty                           // Queue empty (no pending loads)
);

    //=========================================================================
    // Load Queue Entry Structure
    //=========================================================================
    // Each entry contains:
    // - valid: Entry is occupied
    // - addr: Memory address
    // - rd: Destination register
    // - load_type: LB/LH/LW/LBU/LHU (func3 encoding)
    // - data_ready: Memory has responded
    // - data: Data from memory (raw, before extension)
    // - req_sent: Memory request has been issued
    //=========================================================================

    reg valid [0:ENTRIES-1];
    reg [ADDR_WIDTH-1:0] addr [0:ENTRIES-1];
    reg [4:0] rd [0:ENTRIES-1];
    reg [2:0] load_type [0:ENTRIES-1];
    reg data_ready [0:ENTRIES-1];
    reg [DATA_WIDTH-1:0] data [0:ENTRIES-1];
    reg req_sent [0:ENTRIES-1];

    //=========================================================================
    // Queue Pointers (Circular Buffer)
    //=========================================================================
    reg [INDEX_WIDTH-1:0] head;  // Oldest entry (dequeue here - program order)
    reg [INDEX_WIDTH-1:0] tail;  // Next free slot (enqueue here)
    reg [INDEX_WIDTH:0] count;   // Number of valid entries (need extra bit for full detection)

    //=========================================================================
    // Enqueue Logic
    //=========================================================================
    // Allocate new entry when load instruction reaches EX stage
    // Assign sequential LQ IDs based on tail pointer
    //=========================================================================

    assign enq_ready = (count < ENTRIES);
    assign enq_lq_id = tail;
    assign full = (count == ENTRIES);
    assign empty = (count == 0);

    integer i;

    always @(posedge clk) begin
        if (rst) begin
            tail <= 0;
            count <= 0;
            for (i = 0; i < ENTRIES; i = i + 1) begin
                valid[i] <= 0;
                data_ready[i] <= 0;
                req_sent[i] <= 0;
            end
        end else begin
            // Enqueue and dequeue can happen simultaneously
            if (enq_valid && enq_ready && deq_valid && deq_ready) begin
                // Both enqueue and dequeue - count stays same
                // Enqueue
                valid[tail] <= 1;
                addr[tail] <= enq_addr;
                rd[tail] <= enq_rd;
                load_type[tail] <= enq_load_type;
                data_ready[tail] <= 0;
                req_sent[tail] <= 0;
                if (tail == INDEX_WIDTH'(ENTRIES - 1))
                    tail <= {INDEX_WIDTH{1'b0}};
                else
                    tail <= tail + 1'b1;

                // Dequeue (handled below)
            end else if (enq_valid && enq_ready) begin
                // Only enqueue
                valid[tail] <= 1;
                addr[tail] <= enq_addr;
                rd[tail] <= enq_rd;
                load_type[tail] <= enq_load_type;
                data_ready[tail] <= 0;
                req_sent[tail] <= 0;
                if (tail == INDEX_WIDTH'(ENTRIES - 1))
                    tail <= {INDEX_WIDTH{1'b0}};
                else
                    tail <= tail + 1'b1;
                count <= count + 1;
            end else if (deq_valid && deq_ready) begin
                // Only dequeue
                count <= count - 1;
            end
        end
    end

    //=========================================================================
    // Memory Request Arbiter
    //=========================================================================
    // Find oldest entry that needs memory request (hasn't sent request yet)
    // This ensures requests are issued in program order
    //=========================================================================

    reg [INDEX_WIDTH-1:0] req_entry;
    reg found_req;

    always @(*) begin
        reg [INDEX_WIDTH-1:0] check_idx;
        found_req = 0;
        req_entry = 0;

        // Search from head forward (program order)
        check_idx = head;
        for (i = 0; i < ENTRIES; i = i + 1) begin
            if (valid[check_idx] && !req_sent[check_idx] && !data_ready[check_idx] && !found_req) begin
                req_entry = check_idx;
                found_req = 1;
            end
            // Increment check_idx with wraparound
            if (check_idx == INDEX_WIDTH'(ENTRIES - 1))
                check_idx = {INDEX_WIDTH{1'b0}};
            else
                check_idx = check_idx + 1'b1;
        end
    end

    assign mem_req_valid = found_req;
    assign mem_req_addr = addr[req_entry];
    assign mem_req_lq_id = req_entry;

    // Mark request as sent when accepted
    always @(posedge clk) begin
        if (mem_req_valid && mem_req_ready) begin
            req_sent[req_entry] <= 1;
        end
    end

    //=========================================================================
    // Memory Response Handler (Out-of-Order)
    //=========================================================================
    // Memory can respond to any pending entry, not necessarily in order
    // Store data directly into the addressed entry
    //=========================================================================

    always @(posedge clk) begin
        if (mem_resp_valid) begin
            data[mem_resp_lq_id] <= mem_resp_data;
            data_ready[mem_resp_lq_id] <= 1;
        end
    end

    //=========================================================================
    // Dequeue Logic (Program Order)
    //=========================================================================
    // Only dequeue from head (oldest entry) to maintain program order
    // Apply sign/zero extension based on load type per RISC-V spec
    //=========================================================================

    reg [DATA_WIDTH-1:0] extended_data;

    // Load type encoding (RISC-V func3):
    // 000 - LB  (load byte, sign-extend)
    // 001 - LH  (load halfword, sign-extend)
    // 010 - LW  (load word)
    // 100 - LBU (load byte, zero-extend)
    // 101 - LHU (load halfword, zero-extend)

    always @(*) begin
        case (load_type[head])
            3'b000: // LB - sign extend byte
                extended_data = {{24{data[head][7]}}, data[head][7:0]};
            3'b001: // LH - sign extend halfword
                extended_data = {{16{data[head][15]}}, data[head][15:0]};
            3'b010: // LW - full word
                extended_data = data[head];
            3'b100: // LBU - zero extend byte
                extended_data = {24'b0, data[head][7:0]};
            3'b101: // LHU - zero extend halfword
                extended_data = {16'b0, data[head][15:0]};
            default:
                extended_data = data[head];
        endcase
    end

    // Dequeue when head entry is valid and data ready
    assign deq_valid = valid[head] && data_ready[head];
    assign deq_rd = rd[head];
    assign deq_data = extended_data;

    always @(posedge clk) begin
        if (rst) begin
            head <= 0;
        end else if (deq_valid && deq_ready) begin
            valid[head] <= 0;
            if (head == INDEX_WIDTH'(ENTRIES - 1))
                head <= {INDEX_WIDTH{1'b0}};
            else
                head <= head + 1'b1;
        end
    end

endmodule

`default_nettype wire
