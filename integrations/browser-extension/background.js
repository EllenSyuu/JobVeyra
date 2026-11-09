// Reads the digest from the local JobVeyra dashboard once a minute. Nothing leaves this computer.
const DEFAULT = "http://127.0.0.1:8765";

async function poll() {
  const { base } = await chrome.storage.local.get("base");
  const url = (base || DEFAULT).replace(/\/+$/, "") + "/api/digest";
  let digest = null, error = "";
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`dashboard answered ${r.status}`);
    digest = await r.json();
  } catch (e) {
    error = "dashboard not running: start it with `jobveyra dashboard`";
  }
  const prev = (await chrome.storage.local.get("digest")).digest;
  await chrome.storage.local.set({ digest: digest || prev || null, error, fetchedAt: Date.now(), live: !!digest });
}

function schedule() { chrome.alarms.create("poll", { periodInMinutes: 1 }); poll(); }
chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.alarms.onAlarm.addListener(a => { if (a.name === "poll") poll(); });
chrome.runtime.onMessage.addListener(m => { if (m === "refresh") poll(); });
chrome.action.onClicked.addListener(async () => {
  const { hidden } = await chrome.storage.local.get("hidden");
  await chrome.storage.local.set({ hidden: !hidden });
});
