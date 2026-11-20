"""Read registered official HTTPS pages with pinned public DNS and bounded parsing."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from queue import Queue, Empty
import socket
import ssl
import subprocess
import sys
from threading import Thread
from time import monotonic
from urllib.parse import urlsplit, urljoin

from bs4 import BeautifulSoup


class FetchError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class Page:
    url: str
    retrieved_at: str
    content_type: str
    raw_sha256: str
    text_sha256: str
    text: str
    page_requests: int

    def public(self):
        return dict(self.__dict__)


def public_addresses(host, timeout=5):
    queue = Queue(maxsize=1)

    def resolve():
        try:
            queue.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError:
            queue.put(None)

    Thread(target=resolve, daemon=True).start()
    try:
        answers = queue.get(timeout=timeout)
    except Empty:
        raise FetchError("DNS_TIMEOUT") from None
    if not answers:
        raise FetchError("DNS_FAILED")
    addresses = sorted({row[4][0] for row in answers})
    if any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise FetchError("NON_PUBLIC_ADDRESS")
    return addresses


def check_url(url, allowed_hosts):
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.fragment
            or any(ord(c) < 33 or ord(c) > 126 for c in url)
            or "\\" in url
        ):
            raise FetchError("URL_NOT_ALLOWED")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise FetchError("NON_PUBLIC_ADDRESS")
        return parsed
    except (ValueError, TypeError):
        raise FetchError("URL_NOT_ALLOWED") from None


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def parse_document(raw, content_type, timeout):
    if content_type == "application/pdf" or raw.startswith(b"%PDF-"):
        try:
            result = subprocess.run(
                [sys.executable, "-m", "gradmatch.pdf_reader"],
                input=raw,
                capture_output=True,
                timeout=max(0.05, min(8, timeout)),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode:
                raise FetchError("UNSUPPORTED_PDF")
            text = json.loads(result.stdout)["text"]
        except (subprocess.TimeoutExpired, ValueError, KeyError):
            raise FetchError("PDF_PARSE_FAILED") from None
    elif content_type in {"text/html", "application/xhtml+xml"}:
        soup = BeautifulSoup(raw, "html.parser")
        for element in soup(
            ["script", "style", "noscript", "form", "nav", "footer", "iframe"]
        ):
            element.decompose()
        text = " ".join(soup.stripped_strings)[:30000]
    else:
        raise FetchError("UNSUPPORTED_CONTENT")
    if len(text.strip()) < 30:
        raise FetchError("NO_READABLE_TEXT")
    return text[:30000]


def read_page(
    url,
    allowed_hosts,
    *,
    timeout=15,
    before_request=lambda: None,
    resolver=public_addresses,
    connection_factory=PinnedHTTPS,
):
    deadline = monotonic() + timeout
    current, requests = url, 0
    for hop in range(4):
        parsed = check_url(current, allowed_hosts)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise FetchError("FETCH_TIMEOUT")
        addresses = resolver(parsed.hostname, min(5, remaining))
        # Test transports also receive numeric, validated addresses; DNS is never re-resolved by hostname.
        if not addresses or any(
            not ipaddress.ip_address(ip).is_global for ip in addresses
        ):
            raise FetchError("NON_PUBLIC_ADDRESS")
        before_request()
        requests += 1
        connection = connection_factory(
            parsed.hostname, addresses[0], max(0.05, deadline - monotonic())
        )
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request(
                "GET",
                path,
                headers={
                    "User-Agent": "GradMatchCourseProject/0.4 (read-only official verification)",
                    "Accept": "text/html,application/pdf",
                    "Accept-Encoding": "identity",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or hop == 3:
                    raise FetchError("REDIRECT_LIMIT")
                current = urljoin(current, location)
                continue
            if response.status in {401, 403, 429}:
                raise FetchError("ACCESS_DENIED")
            if response.status != 200:
                raise FetchError("FETCH_FAILED")
            if response.getheader("Content-Encoding", "identity").lower() not in {
                "identity",
                "",
            }:
                raise FetchError("UNSUPPORTED_ENCODING")
            declared = response.getheader("Content-Length")
            if declared and (
                not declared.isdigit() or int(declared) > 10 * 1024 * 1024
            ):
                raise FetchError("DOWNLOAD_LIMIT")
            chunks, size = [], 0
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise FetchError("FETCH_TIMEOUT")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read(min(65536, 10 * 1024 * 1024 + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > 10 * 1024 * 1024:
                    raise FetchError("DOWNLOAD_LIMIT")
            raw = b"".join(chunks)
            mime = response.getheader("Content-Type", "").split(";")[0].strip().lower()
            text = parse_document(raw, mime, deadline - monotonic())
            return Page(
                current,
                datetime.now(timezone.utc).isoformat(),
                mime,
                hashlib.sha256(raw).hexdigest(),
                hashlib.sha256(text.encode()).hexdigest(),
                text,
                requests,
            )
        except (OSError, http.client.HTTPException, ssl.SSLError):
            raise FetchError("FETCH_FAILED") from None
        finally:
            connection.close()
    raise FetchError("REDIRECT_LIMIT")
