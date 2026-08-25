class RobotsDisallowed(Exception):
    """robots.txt (or its unreachability, which fails closed) forbids fetching this URL."""


class RobotsFetchFailed(RobotsDisallowed):
    """robots.txt could not be retrieved; treated as disallowed until the cache entry expires."""


class AllStagesFailed(Exception):
    """Every configured stage failed its quality check or raised."""


class UnsupportedContentType(Exception):
    """The fetched resource isn't HTML (e.g. a PDF/image) — no stage in this
    pipeline (including a browser) can turn that into better HTML, so the
    whole job aborts immediately instead of wasting the rest of the chain."""
