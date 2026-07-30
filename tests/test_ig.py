# -*- coding: utf-8 -*-
from tarrafa.tools.ig.scraper import (
    instagram_media_urls,
    instagram_profile_url,
    instagram_reported_posts,
)


def test_instagram_profile_url_accepts_handle_and_canonicalizes_host():
    assert (
        instagram_profile_url("@perfil.exemplo")
        == "https://www.instagram.com/perfil.exemplo/"
    )
    assert (
        instagram_profile_url("https://instagram.com/perfil_exemplo/?hl=pt-br")
        == "https://www.instagram.com/perfil_exemplo/"
    )


def test_instagram_profile_url_rejects_media_and_reserved_routes():
    assert instagram_profile_url("https://instagram.com/reel/ABC123/") is None
    assert instagram_profile_url("https://instagram.com/accounts/login/") is None
    assert instagram_profile_url("https://example.com/perfil/") is None


def test_instagram_media_urls_canonicalizes_deduplicates_and_limits():
    urls = instagram_media_urls(
        [
            "https://instagram.com/reel/ABC123/?utm_source=share",
            "https://www.instagram.com/reel/ABC123/",
            "https://instagram.com/perfil.exemplo/p/POST_2/comments/",
            "https://example.com/outro",
        ],
        limit=2,
    )

    assert urls == [
        "https://www.instagram.com/reel/ABC123/",
        "https://www.instagram.com/p/POST_2/",
    ]


def test_instagram_reported_posts_reads_profile_count_only():
    assert (
        instagram_reported_posts("53 posts, 751 seguidores, 932 seguindo")
        == 53
    )
    assert instagram_reported_posts("0 publicações · 2 seguidores") == 0
    assert instagram_reported_posts("751 seguidores") is None
