"""Tests for config module — covers R8 (all Gurugram pincodes), R2 (platform configs)."""

from src.config.settings import (
    DEFAULT_CATEGORIES,
    GURUGRAM_PINCODES,
    SEED_PINCODES,
    USER_AGENTS,
    Settings,
    get_pincode_location,
    get_random_user_agent,
)


class TestPincodes:
    def test_exactly_18_pincodes(self) -> None:
        assert len(GURUGRAM_PINCODES) == 18

    def test_all_pincodes_unique(self) -> None:
        codes = [p.pincode for p in GURUGRAM_PINCODES]
        assert len(codes) == len(set(codes))

    def test_all_coords_valid(self) -> None:
        for loc in GURUGRAM_PINCODES:
            # Gurugram is roughly 28.3-28.5 lat, 76.9-77.1 lng
            assert 28.0 <= loc.lat <= 29.0, f"{loc.pincode} lat out of range: {loc.lat}"
            assert 76.5 <= loc.lng <= 77.5, f"{loc.pincode} lng out of range: {loc.lng}"

    def test_all_pincodes_start_with_122(self) -> None:
        for loc in GURUGRAM_PINCODES:
            assert loc.pincode.startswith("122"), f"{loc.pincode} doesn't start with 122"

    def test_seed_pincodes_subset(self) -> None:
        all_codes = {p.pincode for p in GURUGRAM_PINCODES}
        for seed in SEED_PINCODES:
            assert seed in all_codes, f"Seed {seed} not in main pincode list"

    def test_seed_pincodes_count(self) -> None:
        assert len(SEED_PINCODES) == 8

    def test_lookup_valid_pincode(self) -> None:
        loc = get_pincode_location("122001")
        assert loc is not None
        assert loc.lat == 28.4595
        assert loc.lng == 77.0266

    def test_lookup_invalid_pincode(self) -> None:
        assert get_pincode_location("999999") is None


class TestCategories:
    def test_default_categories(self) -> None:
        assert len(DEFAULT_CATEGORIES) == 3
        assert "Dairy & Bread" in DEFAULT_CATEGORIES

    def test_three_platforms(self) -> None:
        from src.models.product import Platform
        assert len(Platform) == 3


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.db_path == "data/qc_intel.db"
        assert s.embedding_similarity_threshold == 0.85
        assert s.embedding_batch_size == 64
        assert s.scrape_max_retries == 3

    def test_delay_range(self) -> None:
        s = Settings()
        assert s.scrape_delay_min < s.scrape_delay_max


class TestUserAgents:
    def test_has_agents(self) -> None:
        assert len(USER_AGENTS) >= 3

    def test_random_returns_string(self) -> None:
        ua = get_random_user_agent()
        assert isinstance(ua, str)
        assert "Mozilla" in ua
