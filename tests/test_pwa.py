"""The installable web app: manifest, service worker, icons and offline page are served."""

import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"


def test_manifest_is_valid_and_icons_exist(env):
    c = env.anonymous()
    r = c.get("/manifest.webmanifest")
    assert r.status_code == 200
    manifest = json.loads(r.text)
    assert manifest["display"] == "standalone" and manifest["start_url"].startswith("/")
    purposes = {i["purpose"] for i in manifest["icons"]}
    assert {"any", "maskable"} <= purposes
    for icon in manifest["icons"]:
        assert c.get(icon["src"]).status_code == 200, icon["src"]


@pytest.mark.parametrize("path", ["/sw.js", "/offline.html", "/js/install.js", "/icons/apple-touch-icon.png"])
def test_pwa_files_served(env, path):
    assert env.anonymous().get(path).status_code == 200


def test_service_worker_precache_list_points_at_real_files():
    sw = (STATIC / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    for url in re.findall(r'"(/[^"]*)"', shell):
        if url == "/":
            continue
        assert (STATIC / url.lstrip("/")).is_file(), url


@pytest.mark.parametrize("page", ["index.html", "login.html", "billing.html", "billing-stub.html"])
def test_pages_link_manifest_and_theme_color(page):
    html = (STATIC / page).read_text(encoding="utf-8")
    assert 'rel="manifest"' in html and 'name="theme-color"' in html and "viewport-fit=cover" in html


def test_assetlinks_empty_until_configured(env):
    r = env.anonymous().get("/.well-known/assetlinks.json")
    assert r.status_code == 200 and r.json() == []


def test_assetlinks_lists_the_android_app(settings, env):
    settings.twa_package_name = "in.eztrading.app"
    settings.twa_sha256_fingerprints = "aa:bb, CC:DD"
    body = env.anonymous().get("/.well-known/assetlinks.json").json()
    assert body == [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {"namespace": "android_app", "package_name": "in.eztrading.app",
                   "sha256_cert_fingerprints": ["AA:BB", "CC:DD"]},
    }]
