import pytest
from mergescope.integrations.github import GitHubError, parse_github_pr_url


def test_parse_github_pull_request_url() -> None:
    assert parse_github_pr_url("https://github.com/openai/openai-python/pull/42") == (
        "openai",
        "openai-python",
        42,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/openai/openai-python/pull/42",
        "https://example.com/openai/openai-python/pull/42",
        "https://github.com/openai/openai-python/issues/42",
        "https://github.com/openai/openai-python",
    ],
)
def test_rejects_non_pull_request_urls(url: str) -> None:
    with pytest.raises(GitHubError):
        parse_github_pr_url(url)
