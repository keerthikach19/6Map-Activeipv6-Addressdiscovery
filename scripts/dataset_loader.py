import random

def load_addresses(path):
    with open(path, "r") as f:
        addresses = [line.strip() for line in f if line.strip()]
    return addresses


def sample_addresses(addresses, n):
    return random.sample(addresses, min(n, len(addresses)))


def split_dataset(addresses, train_ratio=0.8):

    addresses = addresses.copy()
    random.shuffle(addresses)

    split_index = int(len(addresses) * train_ratio)

    seed_set = addresses[:split_index]
    validation_set = addresses[split_index:]

    return seed_set, validation_set
