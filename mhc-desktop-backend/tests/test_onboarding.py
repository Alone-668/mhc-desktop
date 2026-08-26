"""Tests for the onboarding cards endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mhc_desktop_backend.app import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_onboarding_returns_non_empty_list(client: TestClient) -> None:
    r = client.get("/api/v1/onboarding")
    assert r.status_code == 200
    cards = r.json()
    assert isinstance(cards, list)
    assert len(cards) >= 3  # spec calls for three card types


def test_onboarding_card_shape(client: TestClient) -> None:
    r = client.get("/api/v1/onboarding")
    cards = r.json()
    for c in cards:
        assert set(c.keys()) >= {
            "id",
            "type",
            "title",
            "body",
            "title_i18n",
            "body_i18n",
            "media_kind",
            "media_color",
            "media_label",
            "media_image",
        }
        assert isinstance(c["id"], str) and c["id"]
        assert c["type"] in ("centered", "media-text", "media-top")
        assert isinstance(c["title"], str) and c["title"]
        assert isinstance(c["body"], str) and c["body"]
        # i18n dicts must always carry both locales — the renderer
        # switches on the fly when the user flips Settings.
        assert set(c["title_i18n"].keys()) == {"en", "zh"}
        assert set(c["body_i18n"].keys()) == {"en", "zh"}
        assert c["media_kind"] in ("none", "color", "image")


def test_onboarding_covers_all_three_card_types(client: TestClient) -> None:
    cards = client.get("/api/v1/onboarding").json()
    types = {c["type"] for c in cards}
    assert types == {"centered", "media-text", "media-top"}, (
        f"every layout should ship at least one demo card; got {types}"
    )


def test_onboarding_ids_are_unique(client: TestClient) -> None:
    cards = client.get("/api/v1/onboarding").json()
    ids = [c["id"] for c in cards]
    assert len(ids) == len(set(ids)), f"duplicate card id: {ids}"


def test_centered_cards_have_no_media(client: TestClient) -> None:
    cards = client.get("/api/v1/onboarding").json()
    for c in cards:
        if c["type"] == "centered":
            assert c["media_kind"] == "none"
            assert c.get("media_color") is None
            assert c.get("media_label") is None
            assert c.get("media_image") is None


def test_non_centered_cards_carry_media(client: TestClient) -> None:
    cards = client.get("/api/v1/onboarding").json()
    for c in cards:
        if c["type"] in ("media-text", "media-top"):
            assert c["media_kind"] in ("color", "image"), (
                f"{c['id']} should declare media"
            )
            # Either an image or a label + color must be present.
            assert c.get("media_image") or (
                c.get("media_color") and c.get("media_label")
            ), f"{c['id']} media is empty"


# ── Locale resolution ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "header, expected",
    [
        ("zh", "zh"),
        ("zh-CN", "zh"),
        ("zh-TW", "zh"),
        ("zh-Hans", "zh"),
        ("en", "en"),
        ("en-US", "en"),
        ("en-GB", "en"),
        ("fr", "en"),  # unsupported → default
        ("", "en"),
    ],
)
def test_parse_locale_header_mapping(
    client: TestClient, header: str, expected: str
) -> None:
    cards = client.get("/api/v1/onboarding", headers={"Accept-Language": header}).json()
    # The resolved strings must match the corresponding i18n entry.
    for c in cards:
        assert c["title"] == c["title_i18n"][expected], (
            f"locale {expected!r} didn't resolve title: {c['title']!r}"
        )
        assert c["body"] == c["body_i18n"][expected]


def test_default_locale_is_english(client: TestClient) -> None:
    cards = client.get("/api/v1/onboarding").json()
    for c in cards:
        assert c["title"] == c["title_i18n"]["en"]
        assert c["body"] == c["body_i18n"]["en"]


def test_chinese_and_english_cards_differ(client: TestClient) -> None:
    en = client.get("/api/v1/onboarding", headers={"Accept-Language": "en"}).json()
    zh = client.get("/api/v1/onboarding", headers={"Accept-Language": "zh"}).json()
    for c_en, c_zh in zip(en, zh):
        assert c_en["title"] != c_zh["title"], (
            f"{c_en['id']} translation should differ between locales"
        )


def test_full_i18n_dicts_always_returned(client: TestClient) -> None:
    """Locale switch in the UI happens client-side; the response
    must always include both locales so the renderer can re-key
    without a refetch."""
    cards = client.get("/api/v1/onboarding", headers={"Accept-Language": "zh"}).json()
    for c in cards:
        assert set(c["title_i18n"].keys()) == {"en", "zh"}
        assert set(c["body_i18n"].keys()) == {"en", "zh"}
        # Even when the request asks for zh, the English copy
        # must still be present so the locale switch is instant.
        assert c["title_i18n"]["en"]
        assert c["body_i18n"]["en"]
