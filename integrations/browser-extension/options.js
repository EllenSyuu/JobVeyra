const $ = s => document.querySelector(s);
chrome.storage.local.get("base", ({ base }) => { $("#base").value = base || ""; });
$("#save").onclick = async () => {
  const v = $("#base").value.trim();
  if (v && !/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(v)) { $("#msg").textContent = "Only a local address is allowed."; return; }
  await chrome.storage.local.set({ base: v });
  chrome.runtime.sendMessage("refresh");
  $("#msg").textContent = "Saved.";
};
$("#unmute").onclick = async () => { await chrome.storage.local.set({ muted: [] }); $("#msg").textContent = "Done."; };
