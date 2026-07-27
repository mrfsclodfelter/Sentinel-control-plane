const topologyMap = {
  cerberus_heavy: "svg-heavy",
  cerberus_light: "svg-light",
  argus: "svg-argus",
  osiris: "svg-osiris",
  atlas: "svg-atlas",
  wazuh_server: "svg-wazuh",
  cerberus_noc_pi: "svg-pi",
  hades: "svg-hades",
};

async function refreshTopologyStatus(){
  try {
    const data = await fetch('/api/status').then(r => r.json());
    for (const [key, id] of Object.entries(topologyMap)) {
      const el = document.getElementById(id);
      const status = data.statuses[key];
      if (el && status) {
        el.classList.remove("online", "offline", "disabled", "unknown");
        el.classList.add(status);
      }
    }
  } catch (e) {
    console.log("Topology status update failed", e);
  }
}
refreshTopologyStatus();
setInterval(refreshTopologyStatus, 5000);
