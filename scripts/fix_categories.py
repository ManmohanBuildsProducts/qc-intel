"""
Bulk category remapping fix for qc_intel.db.
Corrects ~60 miscategorized products across Beverages, Atta & Staples,
and Fruits & Vegetables. Runs all UPDATEs in one transaction.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "qc_intel.db"

REMAPS = [
    # Group 1 — Beverages → Fruits & Vegetables (fresh produce mislabeled)
    {
        "ids": [2971, 2972, 2981, 2984, 2990, 2991, 3079, 3082, 3496],
        "from": "Beverages",
        "to": "Fruits & Vegetables",
        "note": "Kinnaur/Shimla apples, raw banana, raw coconuts",
    },
    # Group 2 — Beverages → Chocolates & Sweets (candy mislabeled as drink)
    {
        "ids": [3471, 3474],
        "from": "Beverages",
        "to": "Chocolates & Sweets",
        "note": "Dobra Pop Goli Apple Mojito & Rose Apple — flavoured soda candy",
    },
    # Group 3 — Atta & Staples → Dairy & Bread (bread mislabeled as grain)
    {
        "ids": [2696, 2700, 2708, 2712, 2720],
        "from": "Atta & Staples",
        "to": "Dairy & Bread",
        "note": "Health Factory, Theobroma, Harvest Gold, English Oven whole wheat breads",
    },
    # Group 4 — Atta & Staples → Bakery & Biscuits (rusk mislabeled as grain)
    {
        "ids": [3621],
        "from": "Atta & Staples",
        "to": "Bakery & Biscuits",
        "note": "The Baker's Dozen Elaichi Rusk",
    },
    # Group 5 — Fruits & Vegetables → Dairy & Bread (dairy mislabeled)
    {
        "ids": [2807, 2809, 2831],
        "from": "Fruits & Vegetables",
        "to": "Dairy & Bread",
        "note": "Nandini milk x2, Nandini curd",
    },
    # Group 6 — Fruits & Vegetables → Instant & Frozen Food (frozen items mislabeled)
    {
        "ids": [2956, 3011, 3116, 3117, 3119, 3120],
        "from": "Fruits & Vegetables",
        "to": "Instant & Frozen Food",
        "note": "Safal frozen corn, Switz samosa patti, McCain products",
    },
    # Group 7 — Fruits & Vegetables → Snacks & Munchies (chips/namkeen mislabeled)
    {
        "ids": [2996, 2997, 3006, 3007],
        "from": "Fruits & Vegetables",
        "to": "Snacks & Munchies",
        "note": "Garden Onion Pakoda, Too Yumm Veggie Stix, Too Yumm Bhoot Wafer, Crax Fritts",
    },
    # Group 8 — Fruits & Vegetables → Bakery & Biscuits (biscuits/cookies mislabeled)
    {
        "ids": [3113, 3118],
        "from": "Fruits & Vegetables",
        "to": "Bakery & Biscuits",
        "note": "Sunfeast All Rounder Potato Biscuit, Slurrp Farm Choco Ragi Cookies",
    },
    # Group 9 — Fruits & Vegetables → Atta & Staples (condiments/sauces/processed tomatoes)
    {
        "ids": [
            2706, 2924, 3000, 3002, 3003, 3004, 3005, 3016, 3017, 3018, 3019,
            3020, 3021, 3022, 3023, 3024, 3025, 3026, 3027, 3028, 3029, 3030,
            3031, 3032, 3033, 3034, 3035, 3036, 3037, 3038, 3039, 3040, 3126, 3127,
        ],
        "from": "Fruits & Vegetables",
        "to": "Atta & Staples",
        "note": "Sundried tomatoes, cooking mix, ketchup brands, chutneys, sauces",
    },
]


def get_counts(cur):
    cur.execute(
        "SELECT category, COUNT(*) FROM product_catalog GROUP BY category ORDER BY category"
    )
    return dict(cur.fetchall())


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("=== BEFORE ===")
    before = get_counts(cur)
    total_before = sum(before.values())
    for cat, count in sorted(before.items()):
        print(f"  {count:4d}  {cat}")
    print(f"  ----")
    print(f"  {total_before:4d}  TOTAL\n")

    total_remapped = 0
    with conn:
        for group in REMAPS:
            placeholders = ",".join("?" * len(group["ids"]))
            cur.execute(
                f"UPDATE product_catalog SET category = ? WHERE id IN ({placeholders})",
                [group["to"]] + group["ids"],
            )
            affected = cur.rowcount
            total_remapped += affected
            print(
                f"  [{affected:2d} rows]  {group['from']} → {group['to']}  ({group['note']})"
            )

    print(f"\n  {total_remapped} products remapped\n")

    print("=== AFTER ===")
    after = get_counts(cur)
    total_after = sum(after.values())
    for cat, count in sorted(after.items()):
        delta = count - before.get(cat, 0)
        sign = f"+{delta}" if delta > 0 else str(delta)
        marker = f"  ({sign})" if delta != 0 else ""
        print(f"  {count:4d}  {cat}{marker}")
    print(f"  ----")
    print(f"  {total_after:4d}  TOTAL")

    if total_after == total_before:
        print(f"\n  OK — total unchanged at {total_after}")
    else:
        print(f"\n  ERROR — total changed: {total_before} → {total_after}")

    conn.close()


if __name__ == "__main__":
    main()
