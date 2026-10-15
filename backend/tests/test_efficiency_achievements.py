"""Unit tests for achievement display metadata."""
from app.models.models import AchievementType
from app.services.efficiency.achievements import achievement_display


def test_known_achievement_type_has_metadata():
    title, description, icon = achievement_display(
        AchievementType.SPEED_DEMON.value
    )
    assert title == "Speed Demon"
    assert description
    assert icon


def test_unknown_achievement_type_falls_back_to_type_and_medal():
    title, description, icon = achievement_display("future_type")
    assert title == "future_type"
    assert description == ""
    assert icon == "🏅"
