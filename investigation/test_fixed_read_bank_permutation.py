#!/usr/bin/env python3
"""Check the fixed-read probe's 32-byte line permutation and HBM bank walk."""

import unittest


def permute_line(index: int) -> int:
    # Matches Cat(issued(high, 9), issued(3, 0), issued(8, 4)).
    return (index & ~0x1FF) | ((index & 0xF) << 5) | ((index >> 4) & 0x1F)


class FixedReadBankPermutationTest(unittest.TestCase):
    def test_one_and_four_port_address_sets_are_exact_permutations(self) -> None:
        for count in (8192, 32768):
            with self.subTest(count=count):
                mapped = [permute_line(index) for index in range(count)]
                self.assertEqual(len(set(mapped)), count)
                self.assertEqual(min(mapped), 0)
                self.assertEqual(max(mapped), count - 1)

    def test_each_sixteen_request_group_walks_all_hbm_banks(self) -> None:
        for start in range(0, 32768, 16):
            banks = [(permute_line(index) << 5 >> 10) & 0xF for index in range(start, start + 16)]
            self.assertEqual(banks, list(range(16)))


if __name__ == "__main__":
    unittest.main()
