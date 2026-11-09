// The floating card, drawn in a closed shadow root so no page can read or restyle it.
(() => {
  if (window.top !== window || document.getElementById("jv-pulse")) return;
  const host = document.createElement("div");
  host.id = "jv-pulse";
  host.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `<style>
    .c{font:12px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:#1c1917;background:#fafaf9f2;border:1px solid #d6d3d1;
       border-radius:10px;box-shadow:0 6px 20px #0002;padding:8px 10px;min-width:210px;max-width:290px}
    @media (prefers-color-scheme:dark){.c{color:#f5f5f4;background:#1c1917f2;border-color:#44403c}}
    .top{display:flex;align-items:center;gap:8px;cursor:move}.lamp{width:8px;height:8px;border-radius:50%;background:#a8a29e}
    .live .lamp{background:#16a34a}.t{font-weight:600;letter-spacing:.04em}.n{margin-left:auto;font-weight:700;font-size:14px}
    .bars{display:flex;align-items:flex-end;gap:2px;height:22px;margin:6px 0}.bars i{flex:1;background:currentColor;opacity:.75;min-height:1px;border-radius:1px}
    .l{opacity:.8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.more{display:none;margin-top:6px;border-top:1px solid #d6d3d1;padding-top:6px}
    .open .more{display:block}button{all:unset;cursor:pointer;opacity:.6;padding:0 2px}</style>
    <div class="c"><div class="top"><span class="lamp"></span><span class="t">JobVeyra</span><span class="n"></span>
    <button class="x" title="Hide on this site">×</button></div><div class="bars"></div><div class="sum l"></div><div class="more"></div></div>`;
  const $ = s => root.querySelector(s);
  const card = $(".c");
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function draw({ digest, error, live, hidden, muted }) {
    const off = hidden || (muted || []).includes(location.hostname);
    host.style.display = off ? "none" : "";
    if (off) return;
    card.classList.toggle("live", !!live);
    if (!digest) { $(".n").textContent = ""; $(".sum").textContent = error || "waiting for the dashboard"; return; }
    const t = digest.totals || {}, series = digest.series || [];
    const max = Math.max(1, ...series.map(s => s.sent));
    $(".bars").innerHTML = series.map(s => `<i title="${esc(s.date)}: ${s.sent}" style="height:${100 * s.sent / max}%"></i>`).join("");
    $(".n").textContent = `${t.submitted ?? 0} sent`;
    const pl = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    $(".sum").textContent = `${digest.last7 ?? 0} this week · ${pl(t.replies ?? 0, "reply", "replies")} · `
      + pl(t.interviews ?? 0, "interview", "interviews");
    const needs = digest.needs || {};
    const rows = (needs.auth || []).map(g => `Sign in: ${esc(g.scope)} (${g.count})`);
    if (needs.needs_check) rows.push(`${needs.needs_check} to check on a portal`);
    if (needs.human) rows.push(`${needs.human} question(s) for you`);
    (digest.coming_up?.deadlines || []).slice(0, 3).forEach(d => rows.push(`Due ${esc(d.date)}: ${esc(d.employer)}`));
    $(".more").innerHTML = (rows.map(r => `<div class="l">${r}</div>`).join("") || `<div class="l">Nothing needs you.</div>`)
      + (error ? `<div class="l">${esc(error)}</div>` : "");
  }

  const keys = ["digest", "error", "live", "hidden", "muted"];
  chrome.storage.local.get(keys, draw);
  chrome.storage.onChanged.addListener(() => chrome.storage.local.get(keys, draw));
  $(".top").addEventListener("click", e => { if (e.target.className !== "x") card.classList.toggle("open"); });
  $(".x").addEventListener("click", async () => {
    const { muted } = await chrome.storage.local.get("muted");
    await chrome.storage.local.set({ muted: [...new Set([...(muted || []), location.hostname])] });
  });
  let drag = null;
  $(".top").addEventListener("mousedown", e => { drag = { x: e.clientX, y: e.clientY, r: parseInt(host.style.right), b: parseInt(host.style.bottom) }; });
  addEventListener("mousemove", e => { if (!drag) return; host.style.right = drag.r - (e.clientX - drag.x) + "px"; host.style.bottom = drag.b - (e.clientY - drag.y) + "px"; });
  addEventListener("mouseup", () => { drag = null; });
  document.documentElement.appendChild(host);
})();
