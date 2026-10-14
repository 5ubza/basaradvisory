"""Polite HTTP client: honest User-Agent, per-host delay, retries, robots.txt check, optional offline fixtures."""
from __future__ import annotations

import logging
import time
import urllib.robotparser as robotparser
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = ("Mozilla/5.0 (compatible; BasarAdvisory-JobHunt/0.1; personal job-search agent; "
              "+https://basaradvisory.com; mailto:ibrahimhalsalem@gmail.com)")


class PoliteSession:
    def __init__(self, user_agent: str = DEFAULT_UA, min_delay: float = 2.0, timeout: int = 20,
                 respect_robots: bool = True, offline_dir: Optional[Path] = None,
                 host_failure_budget: int = 3, deadline_seconds: int = 900):
        self.s = requests.Session()
        self.host_failure_budget = host_failure_budget   # after N failures/timeouts a host is skipped for the run
        self.deadline = time.time() + deadline_seconds    # hard stop for all network activity
        self._failures: dict[str, int] = {}
        self._dead_hosts: set[str] = set()
        self.s.headers.update({"User-Agent": user_agent, "Accept-Language": "en"})
        self.min_delay = min_delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.offline_dir = Path(offline_dir) if offline_dir else None
        self._last: dict[str, float] = {}
        self._robots: dict[str, Optional[robotparser.RobotFileParser]] = {}

    # ---- robots -----------------------------------------------------------------------------------------
    def _robot(self, url: str) -> Optional[robotparser.RobotFileParser]:
        host = urlparse(url).netloc
        if host in self._robots:
            return self._robots[host]
        rp = robotparser.RobotFileParser()
        try:
            r = self.s.get(f"https://{host}/robots.txt", timeout=15)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp = None
        except requests.RequestException:
            rp = None
        self._robots[host] = rp
        return rp

    def allowed(self, url: str) -> bool:
        if not self.respect_robots or self.offline_dir:
            return True
        rp = self._robot(url)
        if rp is None:
            return True
        return rp.can_fetch(self.s.headers["User-Agent"], url) and rp.can_fetch("*", url)

    # ---- fetch --------------------------------------------------------------------------------------------
    def _host_ok(self, url: str) -> bool:
        host = urlparse(url).netloc
        if time.time() > self.deadline:
            log.warning("network deadline reached - skipping %s", url)
            return False
        if host in self._dead_hosts:
            log.info("host %s marked unreachable this run - skipping %s", host, url)
            return False
        return True

    def _fail(self, url: str) -> None:
        host = urlparse(url).netloc
        self._failures[host] = self._failures.get(host, 0) + 1
        if self._failures[host] >= self.host_failure_budget:
            self._dead_hosts.add(host)
            log.warning("host %s failed %d times - giving up on it for this run", host, self._failures[host])

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        wait = self.min_delay - (time.time() - self._last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()

    def get(self, url: str, fixture: str | None = None, retries: int = 1, **kw) -> Optional[requests.Response]:
        """GET with throttle/retries. In offline mode, `fixture` names a file in offline_dir and is returned instead."""
        if self.offline_dir is not None:
            if fixture and (self.offline_dir / fixture).exists():
                resp = requests.Response()
                resp.status_code = 200
                resp._content = (self.offline_dir / fixture).read_bytes()
                resp.url = url
                resp.encoding = "utf-8"
                return resp
            log.info("offline: no fixture %s for %s", fixture, url)
            return None
        if not self._host_ok(url):
            return None
        if not self.allowed(url):
            log.warning("robots.txt disallows %s - skipping", url)
            return None
        for attempt in range(retries + 1):
            self._throttle(url)
            try:
                r = self.s.get(url, timeout=self.timeout, **kw)
                if r.status_code in (429, 503) and attempt < retries:
                    time.sleep(5 * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    log.warning("GET %s -> %s", url, r.status_code)
                    self._fail(url)
                    return None
                return r
            except requests.RequestException as e:
                log.warning("GET %s failed (%s) attempt %d", url, e, attempt + 1)
        self._fail(url)
        return None

    def post_json(self, url: str, payload, headers: dict | None = None) -> Optional[dict | list]:
        if self.offline_dir is not None or not self._host_ok(url):
            return None
        self._throttle(url)
        try:
            r = self.s.post(url, json=payload, headers=headers or {}, timeout=self.timeout)
            if r.status_code >= 400:
                log.warning("POST %s -> %s %s", url, r.status_code, r.text[:200])
                return None
            return r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("POST %s failed: %s", url, e)
            self._fail(url)
            return None

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None, auth=None):
        if self.offline_dir is not None or not self._host_ok(url):
            return None
        self._throttle(url)
        try:
            r = self.s.get(url, params=params, headers=headers or {}, auth=auth, timeout=self.timeout)
            if r.status_code >= 400:
                log.warning("GET %s -> %s %s", url, r.status_code, r.text[:200])
                return None
            return r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("GET %s failed: %s", url, e)
            self._fail(url)
            return None
