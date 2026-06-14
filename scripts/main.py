import os

from dataset_loader import load_addresses
from dataset_loader import split_dataset

from clustering import cluster_addresses
from clustering import generate_patterns

from evaluator import compute_coverage

DATASET = "datasets/ipv6_50k.txt"

addresses = load_addresses(DATASET)

seed_set, validation_set = split_dataset(addresses)

clusters = cluster_addresses(seed_set)

patterns = generate_patterns(clusters)

cluster_keys = set(clusters.keys())

coverage = compute_coverage(
    cluster_keys,
    validation_set
)

print()
print("Total addresses:", len(addresses))
print("Seed addresses:", len(seed_set))
print("Validation addresses:", len(validation_set))
print("Clusters:", len(clusters))
print("Patterns:", len(patterns))
print("Coverage:", round(coverage * 100, 2), "%")

os.makedirs("outputs", exist_ok=True)

with open("outputs/patterns.txt", "w") as f:

    for p in patterns:
        f.write(p + "\n")

with open("outputs/coverage_report.txt", "w") as f:

    f.write(f"Total addresses: {len(addresses)}\n")
    f.write(f"Seed addresses: {len(seed_set)}\n")
    f.write(f"Validation addresses: {len(validation_set)}\n")
    f.write(f"Clusters: {len(clusters)}\n")
    f.write(f"Patterns: {len(patterns)}\n")
    f.write(f"Coverage: {coverage*100:.2f}%\n")
    
cluster_sizes = [len(v) for v in clusters.values()]

print("Largest cluster:", max(cluster_sizes))
print("Average cluster size:", sum(cluster_sizes)/len(cluster_sizes))    
    
    
