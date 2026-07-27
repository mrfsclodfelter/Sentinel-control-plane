import time
from modules.logger import log

def trigger_relay(device):
    if not device.get("relay_enabled", False):
        log(f"{device['name']}: relay not enabled yet")
        return False
    from gpiozero import OutputDevice
    relay = OutputDevice(device["relay_gpio"], active_high=False, initial_value=False)
    relay.on()
    time.sleep(0.5)
    relay.off()
    log(f"{device['name']}: relay triggered")
    return True
