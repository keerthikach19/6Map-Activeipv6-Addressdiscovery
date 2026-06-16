#include <core.p4>
#include <v1model.p4>

// ============================================================================
// HEADERS
// ============================================================================

typedef bit<48> macAddr_t;
typedef bit<128> ip6Addr_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv6_t {
    bit<4>    version;
    bit<8>    trafficClass;
    bit<20>   flowLabel;
    bit<16>   payloadLen;
    bit<8>    nextHdr;
    bit<8>    hopLimit;
    ip6Addr_t srcAddr;
    ip6Addr_t dstAddr;
}

header icmpv6_t {
    bit<8>  type;
    bit<8>  code;
    bit<16> checksum;
}

struct metadata {
    // Empty for now
}

struct headers {
    ethernet_t ethernet;
    ipv6_t     ipv6;
    icmpv6_t   icmpv6;
}

// ============================================================================
// PARSER
// ============================================================================

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType) {
            0x86dd: parse_ipv6;
            default: accept;
        }
    }

    state parse_ipv6 {
        packet.extract(hdr.ipv6);
        transition select(hdr.ipv6.nextHdr) {
            58: parse_icmpv6; // 58 is ICMPv6
            default: accept;
        }
    }

    state parse_icmpv6 {
        packet.extract(hdr.icmpv6);
        transition accept;
    }
}

// ============================================================================
// CHECKSUM VERIFICATION
// ============================================================================

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

// ============================================================================
// INGRESS
// ============================================================================

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    // ------------------------------------------------------------------------
    // MAC Learning / Forwarding Table
    // Acts as a simple L2 switch so hosts can reach each other.
    // ------------------------------------------------------------------------
    action forward(bit<9> port) {
        standard_metadata.egress_spec = port;
    }

    action drop() {
        mark_to_drop(standard_metadata);
    }

    table mac_forward {
        key = {
            hdr.ethernet.dstAddr: exact;
        }
        actions = {
            forward;
            drop;
            NoAction;
        }
        size = 1024;
        default_action = drop();
    }

    // ------------------------------------------------------------------------
    // Pacing / Rate Limiter (Fuzzy PID Controlled)
    // ------------------------------------------------------------------------
    // We use a meter to rate-limit ICMPv6 Echo Requests (type 128)
    // sent by the prober (assumed to be connected to port 1).
    // The Fuzzy PID control plane updates the rates of this meter dynamically.
    meter(1, MeterType.packets) probe_meter;

    apply {
        if (hdr.ethernet.isValid()) {
            // Rate limit outgoing probes from h1 (port 1)
            if (standard_metadata.ingress_port == 1 &&
                hdr.ipv6.isValid() && 
                hdr.icmpv6.isValid() && 
                hdr.icmpv6.type == 128) {
                
                bit<32> meter_color;
                // Index 0 tracks the overall probe rate limit
                probe_meter.execute_meter(32w0, meter_color);
                
                if (meter_color == 2) { // RED (exceeds limit)
                    drop();
                    return;
                }
            }
            
            // Standard L2 Forwarding (or flood if unknown, handled by control plane)
            mac_forward.apply();
        }
    }
}

// ============================================================================
// EGRESS
// ============================================================================

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply { }
}

// ============================================================================
// CHECKSUM COMPUTATION
// ============================================================================

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

// ============================================================================
// DEPARSER
// ============================================================================

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv6);
        packet.emit(hdr.icmpv6);
    }
}

// ============================================================================
// SWITCH INSTANTIATION
// ============================================================================

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
