"""Resolve the client address using explicit reverse-proxy trust."""

from ipaddress import ip_address, ip_network

from fastapi import Request


def recovery_client_ip(request: Request, trusted_cidrs: list[str]) -> str:
    networks = [ip_network(cidr) for cidr in trusted_cidrs]
    peer = request.client.host if request.client else "unknown"
    try:
        current = ip_address(peer)
    except ValueError:
        return "unknown"
    if any(current in network for network in networks):
        # Read from the trusted end; arbitrary leftmost forwarded values cannot
        # override the first untrusted address in the chain.
        for candidate in reversed(request.headers.get("x-forwarded-for", "").split(",")):
            if not any(current in network for network in networks):
                break
            try:
                current = ip_address(candidate.strip())
            except ValueError:
                return str(ip_address(peer))
    return str(current.ipv4_mapped or current) if current.version == 6 else str(current)
