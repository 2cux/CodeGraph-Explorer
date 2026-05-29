"""Tests for token budget tracking and estimation."""

from codegraph.context.token_budget import estimate_tokens, TokenBudget


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_text(self):
        assert estimate_tokens("abc") == 1  # 3//4 = 0, clamped to 1

    def test_typical_content(self):
        text = "x" * 400
        assert estimate_tokens(text) == 100

    def test_non_empty_minimum(self):
        assert estimate_tokens("ab") == 1


class TestTokenBudget:
    def test_initial_state(self):
        budget = TokenBudget(6000)
        assert budget.remaining == 6000
        assert budget.used == 0

    def test_spend_and_remaining(self):
        budget = TokenBudget(6000)
        budget.spend(100)
        assert budget.remaining == 5900
        assert budget.used == 100

    def test_can_fit_critical_always_true(self):
        budget = TokenBudget(100)
        budget.spend(99)
        assert budget.can_fit(9999, "critical") is True

    def test_can_fit_high_always_true(self):
        budget = TokenBudget(100)
        budget.spend(99)
        assert budget.can_fit(9999, "high") is True

    def test_can_fit_under_budget(self):
        budget = TokenBudget(6000)
        budget.spend(3000)
        assert budget.can_fit(2000, "medium") is True

    def test_can_fit_over_budget(self):
        budget = TokenBudget(6000)
        budget.spend(5000)
        assert budget.can_fit(2000, "medium") is False

    def test_as_dict(self):
        budget = TokenBudget(6000)
        budget.spend(2500)
        d = budget.as_dict()
        assert d == {"max_tokens": 6000, "used_tokens": 2500, "remaining": 3500}

    def test_remaining_never_negative(self):
        budget = TokenBudget(100)
        budget.spend(200)
        assert budget.remaining == 0

    def test_multiple_spends(self):
        budget = TokenBudget(1000)
        budget.spend(200)
        budget.spend(300)
        budget.spend(100)
        assert budget.used == 600
        assert budget.remaining == 400
