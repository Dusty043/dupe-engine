from dupe_engine.hashing import hamming_distance


def test_hamming_distance_hex():
    assert hamming_distance("0", "0") == 0
    assert hamming_distance("0", "f") == 4
    assert hamming_distance("ff", "00") == 8
