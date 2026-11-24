"use strict";

const candidates = [
  {
    name: "Alice Web3", handle: "@alice", initials: "AW", score: 87,
    wallet: "0x4a7b00000000000000000000000000000000e3c9",
    sources: [["GitHub", "@alice"], ["Farcaster", "@alice"], ["ENS", "alice.eth"]],
  },
  {
    name: "Rowan Labs", handle: "@rowan", initials: "RL", score: 63,
    wallet: "0x8f2a00000000000000000000000000000000b174",
    sources: [["GitHub", "@rowan"], ["ENS", "rowan.eth"]],
  },
];

const query = document.querySelector("#query");
const results = document.querySelector("#results");
const status = document.querySelector("#search-status");
const tabs = [...document.querySelectorAll("nav a")];
const template = document.querySelector("#profile-template");
const directory = document.querySelector("#directory");
const live = /^\/miniapp\/(?:index\.html)?$/.test(location.pathname) &&
  location.protocol !== "file:";
let requestId = 0;
let telegramInitData = "";

function initializeTelegram() {
  if (location.protocol !== "https:") return Promise.resolve();
  return new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-web-app.js";
    script.onload = () => {
      const webApp = window.Telegram?.WebApp;
      telegramInitData = webApp?.initData || "";
      webApp?.ready();
      resolve();
    };
    script.onerror = resolve;
    document.head.append(script);
  });
}

class AccessError extends Error {}

function message(target, text) {
  const paragraph = document.createElement("p");
  paragraph.className = "empty";
  paragraph.setAttribute("role", "status");
  paragraph.textContent = text;
  target.replaceChildren(paragraph);
}

async function get(path) {
  const headers = telegramInitData ? { "X-Telegram-Init-Data": telegramInitData } : {};
  const response = await fetch(path, {
    headers, cache: "no-store", signal: AbortSignal.timeout(10000),
  });
  if (response.status === 401) throw new AccessError("Open Crycon again from the Telegram bot.");
  if (response.status === 403) throw new AccessError("This Telegram account has no access.");
  if (!response.ok) throw new Error("Crycon API request failed.");
  return response.json();
}

function candidateSummary(row) {
  const name = row.display_name || row.main_username;
  return {
    id: row.id,
    name,
    handle: "@" + row.main_username.replace(/^@/, ""),
    initials: name.trim().split(/\s+/).slice(0, 2).map((word) => word[0] || "").join("").toUpperCase(),
    score: row.overall_trust_score,
  };
}

async function openCandidate(candidate, focus = false) {
  const request = ++requestId;
  try {
    if (live) {
      message(results, "Loading profile…");
      const detail = await get("/candidates/" + encodeURIComponent(candidate.id));
      if (request !== requestId) return;
      candidate = {
        ...candidateSummary(detail.candidate),
        wallets: detail.wallets.map((wallet) => [wallet.name_service, wallet.wallet_address]),
        sources: detail.profiles.map((profile) => [
          profile.platform, profile.username, profile.profile_url || profile.source_url,
        ]),
      };
    }
    renderProfile(candidate);
    if (focus) results.querySelector("h1").focus();
  } catch (error) {
    if (request === requestId) message(results, error instanceof AccessError
      ? error.message : "Could not load the profile. Try searching again.");
  }
}

function candidateButton(candidate) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "candidate";
  const score = document.createElement("span");
  score.className = "mono";
  score.textContent = candidate.score + "/100";
  button.append(candidate.name + " · " + candidate.handle, score);
  button.addEventListener("click", () => {
    query.value = candidate.handle;
    location.hash = "search";
    showView();
    void openCandidate(candidate, true);
  });
  return button;
}

function renderProfile(candidate) {
  const fragment = template.content.cloneNode(true);
  const title = fragment.querySelector("h1");
  title.textContent = candidate.name;
  title.tabIndex = -1;
  fragment.querySelector(".initials").textContent = candidate.initials;
  fragment.querySelector(".handle").textContent = candidate.handle;
  fragment.querySelector(".score strong").textContent = candidate.score + "/100";
  for (const [name, value] of candidate.wallets || [[null, candidate.wallet]]) {
    if (!name && !value) continue;
    const row = document.createElement("div");
    row.className = "wallet";
    const address = document.createElement("code");
    address.textContent = name || (value.length > 18 ? value.slice(0, 6) + "…" + value.slice(-4) : value);
    const copy = document.createElement("button");
    copy.className = "copy";
    copy.type = "button";
    copy.textContent = "Copy";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(value || name);
        copy.textContent = "Copied";
      } catch {
        address.textContent = value || name;
        copy.textContent = "Copy unavailable";
      }
    });
    row.append("Wallet", address, copy);
    fragment.querySelector(".wallets").append(row);
  }
  const sources = fragment.querySelector("ul");
  for (const [platform, value, url] of candidate.sources) {
    const row = document.createElement("li");
    row.className = "source";
    const handle = document.createElement("span");
    handle.className = "mono";
    handle.textContent = value;
    row.append(platform, handle);
    if (url && URL.canParse(url)) {
      const source = new URL(url);
      if (["https:", "http:"].includes(source.protocol) && !source.username && !source.password) {
        const link = document.createElement("a");
        link.href = source.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "Open";
        link.setAttribute("aria-label", "Open " + platform + " source");
        row.append(link);
      }
    }
    sources.append(row);
  }
  if (!sources.children.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No sources recorded.";
    sources.append(empty);
  }
  results.replaceChildren(fragment);
  status.textContent = "Showing " + candidate.name + ".";
}

function showView() {
  const active = tabs.find((tab) => tab.hash === location.hash) || tabs[0];
  for (const tab of tabs) {
    if (tab === active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
    document.querySelector(tab.hash + "-view").hidden = tab !== active;
  }
}

document.querySelector("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const term = query.value.trim();
  const request = ++requestId;
  if (!term) {
    message(results, "Enter a handle, wallet or ENS name.");
    return;
  }
  let matches;
  if (live) {
    message(results, "Searching…");
    try {
      await telegramReady;
      if (request !== requestId) return;
      const data = await get("/search?" + new URLSearchParams({ q: term }));
      if (request !== requestId) return;
      matches = data.items.map(candidateSummary);
    } catch (error) {
      if (request === requestId) message(results, error instanceof AccessError
        ? error.message : "Search unavailable. Try again.");
      return;
    }
  } else {
    matches = candidates.filter((candidate) =>
      [candidate.name, candidate.handle, candidate.wallet, ...candidate.sources.map((source) => source[1])]
        .some((value) => value.toLowerCase().includes(term.toLowerCase()))
    );
  }
  if (matches.length === 1) {
    void openCandidate(matches[0]);
  } else if (matches.length > 1) {
    results.replaceChildren(...matches.map(candidateButton));
    status.textContent = matches.length + " matches.";
  } else {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No candidates found.";
    results.replaceChildren(empty);
    status.textContent = empty.textContent;
  }
});

const telegramReady = live ? initializeTelegram() : Promise.resolve();
if (live) {
  document.querySelector("#data-mode").hidden = true;
  message(results, "Enter a handle, wallet or ENS name.");
  message(directory, "Loading candidates…");
  telegramReady.then(() => get("/candidates")).then(({ items }) => {
    if (items.length) directory.replaceChildren(...items.map((row) => candidateButton(candidateSummary(row))));
    else message(directory, "No candidates recorded.");
  }).catch((error) => message(directory, error instanceof AccessError
    ? error.message : "Could not load candidates. Reload to try again."));
} else {
  directory.append(...candidates.map(candidateButton));
  renderProfile(candidates[0]);
}
showView();
window.addEventListener("hashchange", showView);
