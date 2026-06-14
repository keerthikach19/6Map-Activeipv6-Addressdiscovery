from dataset_loader import (
    load_addresses,
    sample_addresses,
    split_dataset
)

from clustering import (
    cluster_addresses,
    generate_patterns
)

from evaluator import compute_coverage


addresses = load_addresses(
    "datasets/mininet_ipv6.txt"
)
print(addresses[:10])

seed_set, validation_set = split_dataset(addresses)

clusters = cluster_addresses(seed_set)

patterns = generate_patterns(clusters)

coverage = compute_coverage(
    patterns, validation_set
)

print()

print("MININET PHASE A")
print("-" * 40)

print("Addresses:", len(addresses))
print("Seeds:", len(seed_set))
print("Validation:", len(validation_set))
print("Clusters:", len(clusters))
print("Patterns:", len(patterns))

print(f"Coverage: {coverage:.2f}%")

largest_cluster = max(
    len(cluster)
    for cluster in clusters.values()
)

avg_cluster = (
    sum(len(c) for c in clusters.values())
    / len(clusters)
)

print("Largest cluster:", largest_cluster)
print("Average cluster size:", avg_cluster)
