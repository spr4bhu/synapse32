`default_nettype none

//=============================================================================
// Store Queue - RISC-V Memory Subsystem Component
//=============================================================================
// Implements a circular buffer that decouples store execution from memory
// write bandwidth, allowing out-of-order store issue while maintaining
// program-order memory commitment.
//
// Key Features:
// - Configurable depth (default 8 entries)
// - Store-to-load forwarding via CAM lookup
// - Program-order store retirement to memory
// - Support for all RV32I store types (SB, SH, SW)
// - Full/empty status for pipeline stall control
//
// RISC-V Compliance:
// - Maintains program order for store commitment to memory
// - Proper byte masking for SB/SH stores
// - Supports memory consistency model (stores visible in program order)
//=============================================================================

module store_queue #(
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
    input wire enq_valid,                       // Store instruction in EX stage
    input wire [ADDR_WIDTH-1:0] enq_addr,       // Memory address to store to
    input wire [DATA_WIDTH-1:0] enq_data,       // Data to store (rs2 value)
    input wire [2:0] enq_store_type,            // func3: SB/SH/SW
    output wire enq_ready,                      // Queue has space (not full)
    output wire [INDEX_WIDTH-1:0] enq_sq_id,    // Assigned SQ entry ID

    //-------------------------------------------------------------------------
    // Memory Write Interface (program order from head)
    //-------------------------------------------------------------------------
    output wire mem_write_valid,                // Ready to commit store
    output wire [ADDR_WIDTH-1:0] mem_write_addr, // Store address
    output wire [DATA_WIDTH-1:0] mem_write_data, // Store data
    output wire [3:0] mem_write_byte_en,        // Byte enable (for SB/SH)
    input wire mem_write_ready,                 // Memory can accept write

    //-------------------------------------------------------------------------
    // Store-to-Load Forwarding Interface (CAM lookup)
    //-------------------------------------------------------------------------
    input wire lookup_valid,                    // Load wants to check for forwarding
    input wire [ADDR_WIDTH-1:0] lookup_addr,    // Load address
    input wire [2:0] lookup_load_type,          // LB/LH/LW/LBU/LHU
    output wire forward_match,                  // Found matching store
    output wire [DATA_WIDTH-1:0] forward_data,  // Forwarded data (sign/zero extended)

    //-------------------------------------------------------------------------
    // Status Signals
    //-------------------------------------------------------------------------
    output wire full,                           // Queue full (stall pipeline)
    output wire empty                           // Queue empty (no pending stores)
);

    //=========================================================================
    // Store Queue Entry Structure
    //=========================================================================
    // Each entry contains:
    // - valid: Entry is occupied
    // - addr: Memory address
    // - data: Data to store
    // - store_type: SB/SH/SW (func3 encoding)
    // - retired: Entry has been committed to memory
    //=========================================================================

    reg valid [0:ENTRIES-1];
    reg [ADDR_WIDTH-1:0] addr [0:ENTRIES-1];
    reg [DATA_WIDTH-1:0] data [0:ENTRIES-1];
    reg [2:0] store_type [0:ENTRIES-1];
    reg retired [0:ENTRIES-1];

    //=========================================================================
    // Queue Pointers (Circular Buffer)
    //=========================================================================
    reg [INDEX_WIDTH-1:0] head;  // Oldest entry (dequeue/retire here - program order)
    reg [INDEX_WIDTH-1:0] tail;  // Next free slot (enqueue here)
    reg [INDEX_WIDTH:0] count;   // Number of valid entries (need extra bit for full detection)

    //=========================================================================
    // Enqueue Logic
    //=========================================================================
    // Allocate new entry when store instruction reaches EX stage
    // Assign sequential SQ IDs based on tail pointer
    //=========================================================================

    assign enq_ready = (count < ENTRIES);
    assign enq_sq_id = tail;
    assign full = (count == ENTRIES);
    assign empty = (count == 0);

    integer i;

    always @(posedge clk) begin
        if (rst) begin
            tail <= 0;
            count <= 0;
            for (i = 0; i < ENTRIES; i = i + 1) begin
                valid[i] <= 0;
                retired[i] <= 0;
            end
        end else begin
            // Enqueue and retire can happen simultaneously
            if (enq_valid && enq_ready && mem_write_valid && mem_write_ready) begin
                // Both enqueue and retire - count stays same
                // Enqueue
                valid[tail] <= 1;
                addr[tail] <= enq_addr;
                data[tail] <= enq_data;
                store_type[tail] <= enq_store_type;
                retired[tail] <= 0;
                if (tail == INDEX_WIDTH'(ENTRIES - 1))
                    tail <= {INDEX_WIDTH{1'b0}};
                else
                    tail <= tail + 1'b1;

                // Retire (handled below)
            end else if (enq_valid && enq_ready) begin
                // Only enqueue
                valid[tail] <= 1;
                addr[tail] <= enq_addr;
                data[tail] <= enq_data;
                store_type[tail] <= enq_store_type;
                retired[tail] <= 0;
                if (tail == INDEX_WIDTH'(ENTRIES - 1))
                    tail <= {INDEX_WIDTH{1'b0}};
                else
                    tail <= tail + 1'b1;
                count <= count + 1;
            end else if (mem_write_valid && mem_write_ready) begin
                // Only retire
                count <= count - 1;
            end
        end
    end

    //=========================================================================
    // Memory Write Logic (Program Order)
    //=========================================================================
    // Only commit stores from head (oldest entry) to maintain program order
    // Generate byte enable based on store type
    //=========================================================================

    // Store type encoding (RISC-V func3):
    // 000 - SB  (store byte)
    // 001 - SH  (store halfword)
    // 010 - SW  (store word)

    reg [3:0] byte_enable;
    reg [DATA_WIDTH-1:0] write_data;

    always @(*) begin
        case (store_type[head])
            3'b000: begin // SB - store byte
                byte_enable = 4'b0001;
                write_data = {24'b0, data[head][7:0]};
            end
            3'b001: begin // SH - store halfword
                byte_enable = 4'b0011;
                write_data = {16'b0, data[head][15:0]};
            end
            3'b010: begin // SW - store word
                byte_enable = 4'b1111;
                write_data = data[head];
            end
            default: begin
                byte_enable = 4'b0000;
                write_data = 32'b0;
            end
        endcase
    end

    // Commit when head entry is valid and not yet retired
    assign mem_write_valid = valid[head] && !retired[head];
    assign mem_write_addr = addr[head];
    assign mem_write_data = write_data;
    assign mem_write_byte_en = byte_enable;

    always @(posedge clk) begin
        if (rst) begin
            head <= 0;
        end else if (mem_write_valid && mem_write_ready) begin
            valid[head] <= 0;
            retired[head] <= 0;
            if (head == INDEX_WIDTH'(ENTRIES - 1))
                head <= {INDEX_WIDTH{1'b0}};
            else
                head <= head + 1'b1;
        end
    end

    //=========================================================================
    // Store-to-Load Forwarding Logic (CAM Lookup)
    //=========================================================================
    // Search all valid entries from newest (tail-1) to oldest (head)
    // Find youngest store that matches address and size
    // Apply sign/zero extension based on load type
    //=========================================================================

    reg [INDEX_WIDTH-1:0] match_entry;
    reg match_found;
    reg [DATA_WIDTH-1:0] raw_forward_data;

    // Load type encoding (RISC-V func3):
    // 000 - LB  (load byte, sign-extend)
    // 001 - LH  (load halfword, sign-extend)
    // 010 - LW  (load word)
    // 100 - LBU (load byte, zero-extend)
    // 101 - LHU (load halfword, zero-extend)

    always @(*) begin
        reg [INDEX_WIDTH-1:0] check_idx;
        reg addr_match;
        reg size_match;
        match_found = 0;
        match_entry = 0;
        raw_forward_data = 32'b0;

        if (lookup_valid) begin
            // Search from newest to oldest (tail-1 down to head)
            check_idx = (tail == 0) ? INDEX_WIDTH'(ENTRIES - 1) : (tail - 1'b1);

            for (i = 0; i < ENTRIES; i = i + 1) begin
                if (valid[check_idx] && !match_found) begin
                    addr_match = (addr[check_idx] == lookup_addr);

                    // Check if store and load sizes are compatible
                    size_match = 0;
                    case (store_type[check_idx])
                        3'b000: // SB - can forward to LB/LBU
                            size_match = (lookup_load_type == 3'b000) || (lookup_load_type == 3'b100);
                        3'b001: // SH - can forward to LH/LHU
                            size_match = (lookup_load_type == 3'b001) || (lookup_load_type == 3'b101);
                        3'b010: // SW - can forward to LW
                            size_match = (lookup_load_type == 3'b010);
                        default:
                            size_match = 0;
                    endcase

                    if (addr_match && size_match) begin
                        match_found = 1;
                        match_entry = check_idx;
                        raw_forward_data = data[check_idx];
                    end
                end

                // Decrement check_idx with wraparound
                if (check_idx == 0)
                    check_idx = INDEX_WIDTH'(ENTRIES - 1);
                else
                    check_idx = check_idx - 1'b1;
            end
        end
    end

    // Apply sign/zero extension based on load type
    reg [DATA_WIDTH-1:0] extended_forward_data;

    always @(*) begin
        case (lookup_load_type)
            3'b000: // LB - sign extend byte
                extended_forward_data = {{24{raw_forward_data[7]}}, raw_forward_data[7:0]};
            3'b001: // LH - sign extend halfword
                extended_forward_data = {{16{raw_forward_data[15]}}, raw_forward_data[15:0]};
            3'b010: // LW - full word
                extended_forward_data = raw_forward_data;
            3'b100: // LBU - zero extend byte
                extended_forward_data = {24'b0, raw_forward_data[7:0]};
            3'b101: // LHU - zero extend halfword
                extended_forward_data = {16'b0, raw_forward_data[15:0]};
            default:
                extended_forward_data = 32'b0;
        endcase
    end

    assign forward_match = match_found;
    assign forward_data = extended_forward_data;

endmodule

`default_nettype wire
