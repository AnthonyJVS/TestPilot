"""`goto` URL joining shared by the browser worker and the code renderer."""

from __future__ import annotations

import pytest

from app.domain.test_plan import TestPlan
from app.services.test_generation.renderer import render
from browser_worker.urls import resolve_url

QUIZ = "https://uquiz.com/quiz/6PG8Tf/%D0%BA%D0%B0%D0%BA%D0%BE%D0%B9"


@pytest.mark.parametrize(
    ("base", "value", "expected"),
    [
        ("https://a.test", "/login", "https://a.test/login"),
        ("https://a.test/app", "/login", "https://a.test/app/login"),
        ("https://a.test/app/", "/login", "https://a.test/app/login"),
        ("https://a.test/app", "/apple", "https://a.test/app/apple"),  # not a path boundary
        ("https://a.test/app", "/app/login", "https://a.test/app/login"),
        ("https://a.test/app", "/app?tab=2", "https://a.test/app?tab=2"),
        ("https://a.test/app", "https://b.test/x", "https://b.test/x"),
        # The report that found it: the step repeated the quiz path of the base URL.
        (QUIZ, "/quiz/6PG8Tf/%D0%BA%D0%B0%D0%BA%D0%BE%D0%B9", QUIZ),
        (QUIZ, "/quiz/6PG8Tf/какой", QUIZ),  # decoded spelling of the same path
        (QUIZ, "/quiz/6PG8Tf/какой/results", QUIZ + "/results"),
    ],
)
def test_goto_paths_join_the_base_url_without_doubling(
    base: str, value: str, expected: str
) -> None:
    assert resolve_url(base, value) == expected


def test_generated_code_opens_the_same_address_as_the_run() -> None:
    plan = TestPlan.model_validate(
        {
            "name": "Quiz",
            "steps": [
                {"action": "goto", "description": "Open", "value": "/quiz/42"},
                {"action": "goto", "description": "Results", "value": "/quiz/42/results"},
                {"action": "goto", "description": "Help", "value": "/help"},
            ],
        }
    )
    code = render(plan, base_url="https://site.test/quiz/42")
    assert "page.goto(BASE_URL)" in code.python
    assert 'page.goto(BASE_URL + "/results")' in code.python
    assert 'page.goto(BASE_URL + "/help")' in code.python
    assert "await page.goto(BASE_URL);" in code.typescript
    assert 'await page.goto(BASE_URL + "/results");' in code.typescript
    assert "/quiz/42/quiz/42" not in code.python + code.typescript
