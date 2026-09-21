`default_nettype none
// Sv32 MMU: a TLB in front of a walker that reads PTEs over the data memory interface, one level
// at a time. Fetch and data share the walker, data first since its instruction is older; the
// requesting stage waits until its *_ready is high.
module sv32_mmu (
    input wire clk,
    input wire rst,
    input wire flush_tlb,

    input wire [31:0] satp,
    input wire data_sum,
    input wire data_mxr,
    // Svadu: menvcfg.ADUE. 0 is Svade, where an A/D shortfall is a page fault.
    input wire adue,

    // Instruction side
    input wire instr_translate_enable,
    input wire [31:0] instr_virtual_addr,
    input wire [1:0] instr_priv_mode,
    output wire [31:0] instr_phys_addr,
    output wire instr_ready,
    output wire instr_page_fault,

    // Data side
    input wire data_translate_enable,
    input wire [31:0] data_virtual_addr,
    input wire data_rd_en,
    input wire data_wr_req,
    input wire [1:0] data_priv_mode,
    output wire [31:0] data_phys_addr,
    output wire data_ready,
    output wire data_load_page_fault,
    output wire data_store_page_fault,
    output wire [31:0] data_fault_addr,

    // Walk port on the data memory interface; with Svadu the walker also writes PTEs.
    output wire walk_req,
    output wire [31:0] walk_addr,
    output wire walk_we,
    output wire [31:0] walk_wdata,
    input wire walk_gnt,
    input wire walk_rvalid,
    input wire [31:0] walk_rdata
);

    localparam [1:0] WALK_IDLE = 2'd0;
    localparam [1:0] WALK_LEVEL1 = 2'd1;
    localparam [1:0] WALK_LEVEL0 = 2'd2;
    localparam [1:0] WALK_UPDATE = 2'd3;

    localparam SIDE_DATA = 1'b0;
    localparam SIDE_INSTR = 1'b1;

    wire [31:0] root_pt_base = {satp[19:0], 12'b0};

    // TLB lookup
    wire tlb_instr_hit;
    wire [31:0] tlb_instr_pte;
    wire tlb_instr_megapage;
    wire tlb_data_hit;
    wire [31:0] tlb_data_pte;
    wire tlb_data_megapage;

    reg fill_en;
    reg [31:0] fill_vaddr;
    reg [31:0] fill_pte;
    reg fill_megapage;

    sv32_tlb tlb_inst (
        .clk(clk),
        .rst(rst),
        .flush(flush_tlb),
        .instr_vaddr(instr_virtual_addr),
        .instr_hit(tlb_instr_hit),
        .instr_pte(tlb_instr_pte),
        .instr_megapage(tlb_instr_megapage),
        .data_vaddr(data_virtual_addr),
        .data_hit(tlb_data_hit),
        .data_pte(tlb_data_pte),
        .data_megapage(tlb_data_megapage),
        .fill_en(fill_en),
        .fill_vaddr(fill_vaddr),
        .fill_pte(fill_pte),
        .fill_megapage(fill_megapage)
    );

    // Walk faults are held for the faulting address until its requester moves on, never cached.
    reg instr_fault_valid;
    reg [31:0] instr_fault_vaddr;
    reg data_fault_valid;
    reg [31:0] data_fault_vaddr;

    wire instr_fault_match = instr_fault_valid && (instr_fault_vaddr[31:12] == instr_virtual_addr[31:12]);
    wire data_fault_match = data_fault_valid && (data_fault_vaddr[31:12] == data_virtual_addr[31:12]);

    // Permission checks on the leaf PTE
    wire instr_perm_fault;
    wire instr_needs_accessed;
    sv32_instr_check instr_perm_check (
        .translate_enable(instr_translate_enable && tlb_instr_hit),
        .addr_valid_in(1'b1),
        .privilege_mode(instr_priv_mode),
        .adue(adue),
        .leaf_pte(tlb_instr_pte),
        .page_fault(instr_perm_fault),
        .update_accessed(instr_needs_accessed)
    );

    wire data_perm_load_fault;
    wire data_perm_store_fault;
    wire data_needs_accessed;
    wire data_needs_dirty;
    sv32_data_check data_perm_check (
        .translate_enable(data_translate_enable && tlb_data_hit),
        .addr_valid_in(1'b1),
        .privilege_mode(data_priv_mode),
        .sum(data_sum),
        .mxr(data_mxr),
        .data_rd_en(data_rd_en),
        .data_wr_req(data_wr_req),
        .adue(adue),
        .leaf_pte(tlb_data_pte),
        .load_page_fault(data_perm_load_fault),
        .store_page_fault(data_perm_store_fault),
        .update_accessed(data_needs_accessed),
        .update_dirty(data_needs_dirty)
    );

    // With Svadu, a hit whose PTE lacks A (or D for a write) is a miss, so the walker sets them.
    wire instr_ad_update = instr_translate_enable && tlb_instr_hit && instr_needs_accessed;
    wire data_ad_update = data_translate_enable && tlb_data_hit &&
                          (data_needs_accessed || data_needs_dirty);

    // Address translation outputs
    function [31:0] translated_addr;
        input [31:0] pte;
        input megapage;
        input [31:0] vaddr;
        begin
            translated_addr = megapage ? {pte[29:20], vaddr[21:12], vaddr[11:0]}
                                       : {pte[29:10], vaddr[11:0]};
        end
    endfunction

    assign instr_phys_addr = !instr_translate_enable ? instr_virtual_addr :
                             translated_addr(tlb_instr_pte, tlb_instr_megapage, instr_virtual_addr);
    assign data_phys_addr = !data_translate_enable ? data_virtual_addr :
                            translated_addr(tlb_data_pte, tlb_data_megapage, data_virtual_addr);
    assign data_fault_addr = data_virtual_addr;

    assign instr_ready = !instr_translate_enable ||
                         (tlb_instr_hit && !instr_ad_update) || instr_fault_match;
    assign data_ready = !data_translate_enable ||
                        (tlb_data_hit && !data_ad_update) || data_fault_match;

    assign instr_page_fault = instr_translate_enable && (instr_perm_fault || instr_fault_match);
    // A write reports only the store/AMO fault, including an AMO's read half.
    assign data_load_page_fault = data_translate_enable &&
                                  (data_perm_load_fault ||
                                   (data_fault_match && data_rd_en && !data_wr_req));
    assign data_store_page_fault = data_translate_enable &&
                                   (data_perm_store_fault || (data_fault_match && data_wr_req));

    // Walker. While a fill is being written the lookups still miss, so no new walk starts.
    wire data_walk_needed = data_translate_enable && (data_rd_en || data_wr_req) &&
                            (!tlb_data_hit || data_ad_update) && !data_fault_match && !fill_en;
    wire instr_walk_needed = instr_translate_enable &&
                             (!tlb_instr_hit || instr_ad_update) && !instr_fault_match && !fill_en;

    reg [1:0] walk_state;
    // A flush mid-walk may leave the entry it would fill stale, so the walk is abandoned.
    reg walk_aborted;
    reg walk_side;
    reg [31:0] walk_vaddr;
    reg [31:0] walk_level0_base;
    reg walk_accepted;
    // The walk's access context, captured at its start; the requester is held while it runs.
    reg walk_is_write;
    reg walk_is_read;
    reg [1:0] walk_priv;
    // Svadu: the leaf PTE's address and the value to write back with A/D set.
    reg [31:0] walk_pte_addr;
    reg [31:0] walk_pte_wdata;

    assign walk_req = (walk_state != WALK_IDLE) && !walk_accepted;
    assign walk_addr = (walk_state == WALK_UPDATE) ? walk_pte_addr :
                       (walk_state == WALK_LEVEL1)
                       ? (root_pt_base + {20'b0, walk_vaddr[31:22], 2'b00})
                       : (walk_level0_base + {20'b0, walk_vaddr[21:12], 2'b00});
    assign walk_we = (walk_state == WALK_UPDATE);
    assign walk_wdata = walk_pte_wdata;

    // The same checks on the freshly walked PTE, deciding whether A/D must be set first.
    wire walk_instr_fault;
    wire walk_instr_needs_accessed;
    sv32_instr_check walk_instr_check (
        .translate_enable(walk_side == SIDE_INSTR),
        .addr_valid_in(1'b1),
        .privilege_mode(walk_priv),
        .adue(adue),
        .leaf_pte(walk_rdata),
        .page_fault(walk_instr_fault),
        .update_accessed(walk_instr_needs_accessed)
    );

    wire walk_data_load_fault;
    wire walk_data_store_fault;
    wire walk_data_needs_accessed;
    wire walk_data_needs_dirty;
    sv32_data_check walk_data_check (
        .translate_enable(walk_side == SIDE_DATA),
        .addr_valid_in(1'b1),
        .privilege_mode(walk_priv),
        .sum(data_sum),
        .mxr(data_mxr),
        .data_rd_en(walk_is_read),
        .data_wr_req(walk_is_write),
        .adue(adue),
        .leaf_pte(walk_rdata),
        .load_page_fault(walk_data_load_fault),
        .store_page_fault(walk_data_store_fault),
        .update_accessed(walk_data_needs_accessed),
        .update_dirty(walk_data_needs_dirty)
    );

    // Only when the access is otherwise permitted, which the checks above already require.
    wire walk_needs_update = (walk_side == SIDE_INSTR)
                             ? walk_instr_needs_accessed
                             : (walk_data_needs_accessed || walk_data_needs_dirty);
    wire [31:0] walk_updated_pte =
        walk_rdata | 32'h40 |
        (((walk_side == SIDE_DATA) && walk_data_needs_dirty) ? 32'h80 : 32'h00);

    // Usable PTE: V set, not W without R, and a PPN that fits 32-bit physical space.
    function pte_usable;
        input [31:0] pte;
        begin
            pte_usable = pte[0] && (pte[31:30] == 2'b00) && !(!pte[1] && pte[2]);
        end
    endfunction

    function pte_is_leaf;
        input [31:0] pte;
        begin
            pte_is_leaf = pte[1] || pte[3];
        end
    endfunction

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            walk_state <= WALK_IDLE;
            walk_side <= SIDE_DATA;
            walk_vaddr <= 32'b0;
            walk_level0_base <= 32'b0;
            walk_accepted <= 1'b0;
            walk_aborted <= 1'b0;
            walk_is_write <= 1'b0;
            walk_is_read <= 1'b0;
            walk_priv <= 2'b00;
            walk_pte_addr <= 32'b0;
            walk_pte_wdata <= 32'b0;
            fill_en <= 1'b0;
            fill_vaddr <= 32'b0;
            fill_pte <= 32'b0;
            fill_megapage <= 1'b0;
            instr_fault_valid <= 1'b0;
            instr_fault_vaddr <= 32'b0;
            data_fault_valid <= 1'b0;
            data_fault_vaddr <= 32'b0;
        end else begin
            fill_en <= 1'b0;
            if (flush_tlb && (walk_state != WALK_IDLE)) begin
                walk_aborted <= 1'b1;
            end

            // A held fault is dropped when its requester moves to another page or software fences.
            if (flush_tlb || !instr_translate_enable ||
                (instr_fault_valid && instr_fault_vaddr[31:12] != instr_virtual_addr[31:12])) begin
                instr_fault_valid <= 1'b0;
            end
            if (flush_tlb || !data_translate_enable ||
                (data_fault_valid && data_fault_vaddr[31:12] != data_virtual_addr[31:12])) begin
                data_fault_valid <= 1'b0;
            end

            case (walk_state)
                WALK_IDLE: begin
                    walk_accepted <= 1'b0;
                    walk_aborted <= 1'b0;
                    if (data_walk_needed) begin
                        walk_side <= SIDE_DATA;
                        walk_vaddr <= data_virtual_addr;
                        walk_is_read <= data_rd_en;
                        walk_is_write <= data_wr_req;
                        walk_priv <= data_priv_mode;
                        walk_state <= WALK_LEVEL1;
                    end else if (instr_walk_needed) begin
                        walk_side <= SIDE_INSTR;
                        walk_vaddr <= instr_virtual_addr;
                        walk_is_read <= 1'b0;
                        walk_is_write <= 1'b0;
                        walk_priv <= instr_priv_mode;
                        walk_state <= WALK_LEVEL1;
                    end
                end
                WALK_LEVEL1, WALK_LEVEL0: begin
                    if (walk_gnt) begin
                        walk_accepted <= 1'b1;
                    end
                    if (walk_rvalid) begin
                        walk_accepted <= 1'b0;
                        if (walk_aborted || flush_tlb) begin
                            // Software fenced while this walk was in flight: drop the result.
                            walk_state <= WALK_IDLE;
                        end else if (!pte_usable(walk_rdata) ||
                            (pte_is_leaf(walk_rdata) && (walk_state == WALK_LEVEL1) &&
                             (walk_rdata[19:10] != 10'b0)) ||
                            (!pte_is_leaf(walk_rdata) && (walk_state == WALK_LEVEL0))) begin
                            // Invalid entry, misaligned megapage, or a pointer at the last level.
                            if (walk_side == SIDE_INSTR) begin
                                instr_fault_valid <= 1'b1;
                                instr_fault_vaddr <= walk_vaddr;
                            end else begin
                                data_fault_valid <= 1'b1;
                                data_fault_vaddr <= walk_vaddr;
                            end
                            walk_state <= WALK_IDLE;
                        end else if (pte_is_leaf(walk_rdata)) begin
                            fill_megapage <= (walk_state == WALK_LEVEL1);
                            if (walk_needs_update) begin
                                // Svadu: write A (and D) back before the access uses this translation.
                                walk_pte_addr <= walk_addr;
                                walk_pte_wdata <= walk_updated_pte;
                                walk_state <= WALK_UPDATE;
                            end else begin
                                fill_en <= 1'b1;
                                fill_vaddr <= walk_vaddr;
                                fill_pte <= walk_rdata;
                                walk_state <= WALK_IDLE;
                            end
                        end else begin
                            walk_level0_base <= {walk_rdata[29:10], 12'b0};
                            walk_state <= WALK_LEVEL0;
                        end
                    end
                end
                WALK_UPDATE: begin
                    if (walk_gnt) begin
                        walk_accepted <= 1'b1;
                    end
                    // Wait for the write response, so the PTE lands before the entry is used.
                    if (walk_rvalid) begin
                        walk_accepted <= 1'b0;
                        walk_state <= WALK_IDLE;
                        if (!walk_aborted && !flush_tlb) begin
                            fill_en <= 1'b1;
                            fill_vaddr <= walk_vaddr;
                            fill_pte <= walk_pte_wdata;
                        end
                    end
                end
                default: walk_state <= WALK_IDLE;
            endcase
        end
    end

endmodule
