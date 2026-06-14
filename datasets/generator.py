##creating, or generating new addresses 

with open("/home/keerthika/6Map-proj/datasets/ipv6-sample.txt","w") as f:
    for i in range(1,51):
        f.write(f"2001:db8:1::{i}\n")
    for i in range(1,51):
        f.write(f"2001:db8:2::{i}\n")
    
