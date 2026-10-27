"""Memecoin basket definition.

Each entry is (symbol, network, token_address). We resolve the most liquid
pool for each token at fetch time rather than hard-coding pool addresses, so
the data stays honest and reproducible.

Networks use GeckoTerminal / DexScreener slugs: "solana", "base", "ethereum".

Note on PEPE: PEPE is an Ethereum-native memecoin, not a Solana or Base token.
It is included here as a well-known reference memecoin and is clearly labelled
with the "ethereum" network. Everything else is Solana or Base, as requested.
"""

BASKET = [
    # --- Solana ---
    ("WIF",    "solana",   "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"),  # dogwifhat
    ("BONK",   "solana",   "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"),  # Bonk
    ("POPCAT", "solana",   "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"),  # Popcat
    ("MEW",    "solana",   "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5"),   # cat in a dogs world
    ("PNUT",   "solana",   "2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump"),  # Peanut the Squirrel (newer)

    # --- Base ---
    ("BRETT",  "base",     "0x532f27101965dd16442E59d40670FaF5eBB142E4"),    # Brett
    ("TOSHI",  "base",     "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4"),    # Toshi
    ("DEGEN",  "base",     "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed"),    # Degen

    # --- Ethereum (reference memecoin, clearly labelled) ---
    ("PEPE",   "ethereum", "0x6982508145454Ce325dDbE47a25d4ec3d2311933"),    # Pepe
]
