import argparse
import json
from playwright.sync_api import sync_playwright

def main():
    parser = argparse.ArgumentParser(description='Scrape Moneycontrol Home Page')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--screenshot', help='Path to save screenshot on completion/failure')
    parser.add_argument('--snapshot', help='Path to save HTML DOM snapshot on completion/failure')
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context()
        page = context.new_page()

        try:
            # STEP 1: Navigate to the Moneycontrol home page
            page.goto("https://www.moneycontrol.com/", timeout=5000)

            # STEP 2: Assert the main content wrapper is visible
            assert page.query_selector("#mc_mainWrapper", timeout=5000) is not None, "Main content wrapper is not visible"

            # STEP 3: Assert the content wrapper is visible
            assert page.query_selector(".content_wrapper", timeout=5000) is not None, "Content wrapper is not visible"

            # STEP 4: Assert the article list is visible
            assert page.query_selector(".article-list", timeout=5000) is not None, "Article list is not visible"

            # STEP 5: Assert at least one article is visible
            assert page.query_selector(".article-list > li", timeout=5000) is not None, "At least one article is not visible"

        except Exception as e:
            error_report = {
                "type": type(e).__name__,
                "message": str(e),
                "step_id": None,
                "selector": None
            }

            if hasattr(e, 'selector'):
                error_report['selector'] = e.selector
            if hasattr(e, 'step_id'):
                error_report['step_id'] = e.step_id

            print(f"ERROR_REPORT: {json.dumps(error_report)}", file=(args.screenshot or args.snapshot and open(args.screenshot or args.snapshot, 'w')) or None)

            if args.screenshot:
                page.screenshot(path=args.screenshot)
            if args.snapshot:
                with open(args.snapshot, 'w') as f:
                    f.write(page.content())

            exit(1)

        finally:
            browser.close()

if __name__ == "__main__":
    main()