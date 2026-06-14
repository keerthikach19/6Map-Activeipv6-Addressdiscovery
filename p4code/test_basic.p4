#include <core.p4>
#include <v1model.p4>

header ethernet_t {
    bit<48> dstAddr;
    bit<48> srcAddr;
    bit<16> etherType;
}

struct metadata { }
struct headers { ethernet_t ethernet; }

parser MyParser(packet_in pkt, out headers hdr,
                inout metadata meta, inout standard_metadata_t std_meta) {
    state start { pkt.extract(hdr.ethernet); transition accept; }
}

control MyIngress(inout headers hdr, inout metadata meta,
                  inout standard_metadata_t std_meta) {
    apply { }
}

control MyEgress(inout headers hdr, inout metadata meta,
                 inout standard_metadata_t std_meta) {
    apply { }
}

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
    apply { }
}

control MyDeparser(packet_out pkt, in headers hdr) {
    apply { pkt.emit(hdr.ethernet); }
}

V1Switch(MyParser(), MyVerifyChecksum(), MyIngress(), MyEgress(),
         MyComputeChecksum(), MyDeparser()) main;
