import socket

def send_magic_packet(mac: str):
    mac_clean = mac.replace(":", "").replace("-", "")
    if len(mac_clean) != 12 or "ADD_" in mac:
        raise ValueError("Invalid or missing MAC address")
    packet = bytes.fromhex("FF" * 6 + mac_clean * 16)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(packet, ("255.255.255.255", 9))
    sock.close()
