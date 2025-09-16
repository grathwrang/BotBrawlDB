DEFAULT_RATING = 1000
DEFAULT_K = 32
KO_WEIGHT = 1.10
def get_expected(r_a, r_b):
    return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))
def get_k_for_robot(matches_count, base_k):
    if matches_count < 20: return base_k
    return max(8, int(base_k * 0.75))
