import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def is_url_safe(url: str) -> tuple[bool, str]:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False, "unsupported scheme"
    host = (p.hostname or "").lower()
    if not host:
        return False, "missing host"
    if host in BLOCKED_HOSTS or host.endswith(".internal") or host.endswith(".local"):
        return False, "blocked host"

    # If literal IP, check directly
    try:
        ipaddress.ip_address(host)
        return (not _is_private_ip(host), "private ip") if _is_private_ip(host) else (True, "ok")
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "dns failure"

    for info in infos:
        ip = info[4][0]
        if _is_private_ip(ip):
            return False, f"private ip {ip}"
    return True, "ok"