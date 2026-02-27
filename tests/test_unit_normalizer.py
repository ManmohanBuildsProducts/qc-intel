"""Tests for unit normalizer — covers R3 (normalization accuracy)."""

from src.embeddings.unit_normalizer import normalize_unit


class TestVolumeNormalization:
    def test_ml_lowercase(self) -> None:
        assert normalize_unit("500ml") == "500ml"

    def test_ml_with_space(self) -> None:
        assert normalize_unit("500 ml") == "500ml"

    def test_ml_uppercase(self) -> None:
        assert normalize_unit("500ML") == "500ml"

    def test_ml_mixed_case(self) -> None:
        assert normalize_unit("500 Ml") == "500ml"

    def test_litre_to_ml(self) -> None:
        assert normalize_unit("0.5 L") == "500ml"

    def test_half_litre(self) -> None:
        assert normalize_unit("0.5l") == "500ml"

    def test_one_litre(self) -> None:
        assert normalize_unit("1 L") == "1l"

    def test_one_ltr(self) -> None:
        assert normalize_unit("1 ltr") == "1l"

    def test_two_litres(self) -> None:
        assert normalize_unit("2 litres") == "2l"

    def test_200ml(self) -> None:
        assert normalize_unit("200ml") == "200ml"

    def test_1500ml(self) -> None:
        assert normalize_unit("1500ml") == "1500ml"


class TestWeightNormalization:
    def test_kg_lowercase(self) -> None:
        assert normalize_unit("1kg") == "1kg"

    def test_kg_with_space(self) -> None:
        assert normalize_unit("1 Kg") == "1kg"

    def test_1000g_to_kg(self) -> None:
        assert normalize_unit("1000g") == "1kg"

    def test_1000gm(self) -> None:
        assert normalize_unit("1000 gm") == "1kg"

    def test_500g(self) -> None:
        assert normalize_unit("500g") == "500g"

    def test_250gms(self) -> None:
        assert normalize_unit("250 gms") == "250g"

    def test_half_kg(self) -> None:
        assert normalize_unit("0.5 kg") == "500g"

    def test_2kg(self) -> None:
        assert normalize_unit("2 kgs") == "2kg"


class TestCountNormalization:
    def test_pcs(self) -> None:
        assert normalize_unit("6 pcs") == "6pcs"

    def test_pack(self) -> None:
        assert normalize_unit("1 pack") == "1pcs"

    def test_unit(self) -> None:
        assert normalize_unit("2 units") == "2pcs"

    def test_dozen(self) -> None:
        assert normalize_unit("1 dozen") == "1dozen"

    def test_piece(self) -> None:
        assert normalize_unit("4 pieces") == "4pcs"


class TestEdgeCases:
    def test_none_input(self) -> None:
        assert normalize_unit(None) is None

    def test_empty_string(self) -> None:
        assert normalize_unit("") is None

    def test_whitespace_only(self) -> None:
        assert normalize_unit("   ") is None

    def test_unknown_unit(self) -> None:
        assert normalize_unit("5 foobar") is None

    def test_no_number(self) -> None:
        assert normalize_unit("ml") is None

    def test_leading_trailing_spaces(self) -> None:
        assert normalize_unit("  500 ml  ") == "500ml"
