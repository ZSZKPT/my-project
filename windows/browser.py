"""Local-only browser connection. Never exports cookies or accepts remote commands."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = 'https://agentseller.temu.com/goods/list'


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'agentseller.temu.com' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Only HTTPS agentseller.temu.com URLs are allowed.')
    return url


def page_kind(url):
    query = parse_qs(urlsplit(url).query)
    if query.get('productDraftId'):
        return 'draft'
    if query.get('productId'):
        return 'existing-product'
    return 'other'


def main():
    parser = argparse.ArgumentParser(description='Open a dedicated local Temu browser. No automated submission.')
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--browser', choices=['chrome', 'chromium'], default='chrome', help='Use installed Google Chrome by default.')
    args = parser.parse_args()
    url = validate_url(args.url)
    from playwright.sync_api import sync_playwright
    profile = ROOT / 'data' / ('chrome-profile' if args.browser == 'chrome' else 'browser-profile')
    profile.mkdir(parents=True, exist_ok=True)
    print('Login manually in the browser. Profile stays on this computer.')
    print('No copying, filling, saving, or publishing is performed by this launcher.')
    print('Close the browser or press Ctrl+C to stop. Do not run two launchers at once.')
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile), channel='chrome' if args.browser == 'chrome' else None,
                headless=False, viewport=None, args=['--start-maximized'])
        except Exception as error:
            raise RuntimeError('Could not open browser. Ensure Google Chrome is installed and close other tool windows using this profile. No changes were made to your everyday Chrome profile.') from error
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            print('Browser opened. You may open your draft in this same window.')
            if page_kind(page.url) == 'existing-product':
                print('This is an existing product editing page. It is not a copy draft.')
            while context.pages:
                context.pages[0].wait_for_timeout(1000)
        except KeyboardInterrupt:
            pass
        except Exception as error:
            # A user closing the last window is an expected termination.
            if context.pages:
                raise RuntimeError('Browser operation failed; check network and login in the browser.') from error
        finally:
            try:
                context.close()
            except Exception:
                pass


if __name__ == '__main__':
    main()
