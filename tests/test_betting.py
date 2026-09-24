import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tennis_betting.calculations import bookmaker_margin, combined_odds, implied_probability, simulate, value_indicator
from tennis_betting.models import BetType, Selection, Slip
from tennis_betting.storage import load_slip, save_slip
from tennis_betting.validation import ValidationError


def selection(match="1", player="A", opponent="B", odds="2.00", probability=None):
    return Selection(match, player, opponent, odds, probability)


class BettingTests(unittest.TestCase):
    def test_decimal_calculations_and_margin(self):
        choices = [selection(odds="2.00"), selection("2", "C", "D", "1.50")]
        self.assertEqual(combined_odds(choices), Decimal("3.0000"))
        self.assertEqual(implied_probability(Decimal("2")), Decimal("0.5"))
        self.assertEqual(bookmaker_margin([selection(odds="2"), selection("2", "C", "D", "2")]), Decimal("0.0"))

    def test_duplicate_and_conflicting_selections(self):
        slip = Slip()
        slip.add(selection())
        with self.assertRaises(ValidationError):
            slip.add(selection())
        with self.assertRaises(ValidationError):
            slip.add(selection(player="B", opponent="A"))

    def test_bets_and_persistence(self):
        slip = Slip("saved", bet_type=BetType.ACCUMULATOR)
        slip.add(selection())
        slip.stake = Decimal("10")
        self.assertEqual(slip.remove(0).player, "A")
        slip.add(selection())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slip.json"
            save_slip(slip, path)
            loaded = load_slip(path)
        self.assertEqual(loaded.name, "saved")
        self.assertEqual(loaded.selections[0].odds, Decimal("2.00"))

    def test_system_and_value_and_deterministic_simulation(self):
        slip = Slip(bet_type=BetType.SYSTEM, system_size=2)
        for i in range(3):
            slip.add(selection(str(i), f"A{i}", f"B{i}", "2.00", "0.60"))
        self.assertEqual(len(__import__("tennis_betting.calculations", fromlist=["potential_returns"]).potential_returns(slip, Decimal("6"))), 3)
        self.assertTrue(value_indicator(slip.selections[0]))
        self.assertEqual(simulate(slip, 100, seed=7), simulate(slip, 100, seed=7))


if __name__ == "__main__":
    unittest.main()
