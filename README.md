# Framer Updates RSS

This repository checks [Framer Updates](https://www.framer.com/updates) hourly and publishes an RSS feed at `https://kyetbed.github.io/framer-updates-feed/rss.xml`.

It stores previously discovered updates in the feed, so older entries remain in the RSS archive when they leave the main updates page. New entries are sent as JSON to the `WEBHOOK_URL` GitHub Actions secret. The first run seeds the feed without sending old entries. A monthly heartbeat commit keeps GitHub's schedule active during quiet periods.

To test delivery without announcing an old post as new, run the **Update Framer RSS** workflow manually with a currently listed Framer update URL in `test_url`. The payload sets `test: true` and `event: framer.update.test`. A test run does not change the feed.

The scraper deliberately fails if it cannot find any update entries, so a site layout change does not erase the feed. GitHub Actions run history will show the failure.
