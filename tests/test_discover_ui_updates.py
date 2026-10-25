import re
import os

def test_index_html_updates():
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Hero banner removed
    assert '<div id="discover-hero-banner"' not in html

    # 2. Continue watching collapsible elements exist
    assert 'id="continue-watching-section"' in html
    assert 'id="btn-toggle-continue-shelf"' in html
    assert 'id="continue-watching-shelf-icon"' in html
    assert 'id="continue-watching-shelf-body"' in html
    assert 'class="shelf-body-collapsible"' in html

    # 3. Order check: continue-watching and bookmarks appear before anime-category-bar and genre-ribbon-bar
    idx_continue = html.find('id="continue-watching-section"')
    idx_bookmarks = html.find('id="bookmarks-section"')
    idx_anime_format = html.find('id="anime-category-bar"')
    idx_genre = html.find('class="genre-ribbon-bar"')
    idx_catalog_header = html.find('class="catalog-section-header"')

    assert idx_continue != -1 and idx_bookmarks != -1 and idx_anime_format != -1 and idx_genre != -1
    assert idx_continue < idx_bookmarks < idx_anime_format < idx_genre < idx_catalog_header

    # 4. Sorting selector exists
    assert 'id="discover-sort-select"' in html
    assert 'value="trending"' in html
    assert 'value="seeds_desc"' in html

    # 5. Creative loading animation exists
    assert 'id="discover-more-loading"' in html
    assert 'spiral-vortex' in html


def test_style_css_updates():
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # Spacing between header and categories bar
    assert 'margin-top: 1.75rem;' in css

    # Red hold ring
    assert 'stroke: #ff3355;' in css

    # Fixed popup
    assert '.bookmark-quick-popup {' in css
    assert 'position: fixed;' in css

    # Spiral loader keyframes & classes
    assert '.discover-spiral-loader' in css
    assert '@keyframes spiralSpin' in css

    # Header GUI scale isolation
    assert '.navbar .btn {' in css
    assert 'font-size: 11px !important;' in css

    # Suggestions dropdown on top of all other elements
    assert '.discover-suggestions-dropdown {' in css
    assert 'z-index: 999999 !important;' in css
    assert '.discover-nav-bar.suggestions-open' in css
    assert '.discover-search-wrap.suggestions-open' in css


def test_app_js_updates():
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Discover sort logic
    assert 'applyDiscoverSort' in js
    assert 'setDiscoverSort' in js

    # Continue watching collapse toggle
    assert 'toggleContinueWatchingShelf' in js
    assert 'evoscrapper_shelf_continue_collapsed' in js

    # Center-bottom spiral loading toggle
    assert 'discover-more-loading' in js

    # Fixed positioning for quick bookmark popup
    assert 'getBoundingClientRect()' in js
    assert 'document.body.appendChild(popup)' in js

    # Suggestions elevation classes
    assert 'suggestions-open' in js


def test_sitewide_evo_loader_and_cast_enhancements():
    """Verify EVO loader is used sitewide and cast/recommendations are enhanced."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="discover-loading"' in html
    assert 'loader evo-loader size-lg' in html
    assert 'Loading catalog...' in html
    assert 'id="trending-results-container"' in html
    assert 'Loading trending...' in html

    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert '.crew-row' in css
    assert '.director-pill' in css
    assert '.cast-pill-more' in css

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert 'director-pill' in js
    assert 'cast-pill-more' in js
    assert 'Finding similar titles...' in js
