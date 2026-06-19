"""
Base62 encoding of the Postgres BIGSERIAL id.

Why this approach over random-string-with-collision-check:
- Zero collision retries -> predictable latency under load.
- Monotonic ids are fine here because short codes aren't meant to be
  unguessable/secret; they're public identifiers (like TinyURL).
- If you DO need non-enumerable codes, XOR/permute the id with a fixed
  secret before encoding (see `obfuscate`) so codes aren't sequential
  in appearance, while still being reversible and collision-free.
"""
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)

# Any odd 64-bit constant works; keep it fixed for the life of the system,
# since changing it invalidates the mapping between ids and existing codes.
XOR_MASK = 0x5DEECE66D


def encode(num: int) -> str:
    if num == 0:
        return ALPHABET[0]
    chars = []
    n = obfuscate(num)
    while n > 0:
        n, rem = divmod(n, BASE)
        chars.append(ALPHABET[rem])
    return "".join(reversed(chars))


def decode(code: str) -> int:
    n = 0
    for ch in code:
        n = n * BASE + ALPHABET.index(ch)
    return obfuscate(n)  # XOR is its own inverse


def obfuscate(num: int) -> int:
    return num ^ XOR_MASK
