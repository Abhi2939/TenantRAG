from app.keys import KEY_TAG,generate_key,hash_key,key_prefix

def test_key_has_tag_and_enough_length():
    k = generate_key()

    assert k.startswith(KEY_TAG)
    assert len(k) >= len(KEY_TAG) + 40

def test_keys_are_unique():
    assert len({generate_key() for _ in range(1000)}) == 1000

def test_hash_is_deterministic_hex_sha256():
    h = hash_key("trag_example")
    assert h == hash_key("trag_example")
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)

def test_different_keys_give_different_hashes():
    assert hash_key("trag_a") != hash_key("trag_b")

def test_hash_does_not_contain_the_key():
    k = generate_key()
    assert k not in hash_key(k)

def test_prefix_is_short_and_part_of_the_key():
    k = generate_key()
    assert len(key_prefix(k)) == 8 and k.startswith(key_prefix(k))



