const $ = id => document.getElementById(id);
let controller, report;
const steps = [...document.querySelectorAll("[data-step]")];
const text = (tag, value, cls) => { const el = document.createElement(tag); el.textContent = value; if (cls) el.className = cls; return el; };
function link(url, title) {
  const a = text("a", title);
  try { if (new URL(url).protocol !== "https:") return text("span", title); } catch { return text("span", title); }
  a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; return a;
}
async function health() {
  try {
    const r = await fetch("/api/health"); if (!r.ok) throw Error();
    const data = await r.json();
    $("connection").textContent = data.ready ? "Agent connected" : "Setup needed · Add API keys";
    $("connection").classList.toggle("ready", data.ready);
  } catch { $("connection").textContent = "Server unavailable"; }
}
health();
function renderJobs() {
  const jobs = report.jobs.filter(j => $("filter").value === "All sources" || j.source === $("filter").value);
  $("count").textContent = `${jobs.length} ${jobs.length === 1 ? "opportunity" : "opportunities"}`;
  $("jobs").replaceChildren();
  for (const job of jobs) {
    const card = text("article", "", "job");
    const top = text("div", "", "job-top");
    top.append(text("span", job.source), text("span", `${job.relevance} fit`));
    card.append(top, text("h3", job.title), text("p", `${job.company} / ${job.location} / ${job.kind}`), text("p", job.reason));
    if (job.gaps.length) card.append(text("p", `Worth considering: ${job.gaps.join(", ")}`));
    const evidence = text("details", "");
    evidence.append(text("summary", "Why this appeared"), text("p", job.evidence || "No additional snippet provided."));
    const apply = link(job.url, "View original posting ↗"); apply.className = "apply";
    card.append(evidence, apply, text("p", job.availability, "availability"));
    $("jobs").append(card);
  }
  if (!jobs.length) {
    const empty = text("div", "", "empty");
    empty.append(text("h3", "A little more direction could help."), text("p", "No matching listings in this view. Try another source, a broader location, or add more skills and experience."));
    $("jobs").append(empty);
  }
}
function render(data) {
  report = data;
  $("summary").textContent = data.summary;
  $("profile-summary").textContent = data.profile.summary;
  $("skills").replaceChildren(...data.profile.skills.map(s => text("span", s)));
  $("warnings").replaceChildren(...[...data.warnings, ...data.profile.limitations].map(s => text("p", s)));
  $("coverage").replaceChildren(...data.sources.map(s => text("div", `${s.name}: ${s.count} candidate listings (${s.status})`)));
  $("evidence").replaceChildren(...data.evidence.map(e => e.url ? link(e.url, e.title || e.url) : text("p", e.title)));
  if (data.profile.interests_from_posts.length) $("evidence").append(text("p", `Post interests: ${data.profile.interests_from_posts.join(", ")}`));
  $("results").hidden = false; $("filter").value = "All sources"; renderJobs();
  $("results").scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block:"start"});
}
$("filter").addEventListener("change", renderJobs);
$("cancel").addEventListener("click", () => controller?.abort());
$("search-form").addEventListener("submit", async event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.target));
  if (![body.prompt, body.linkedin_url, body.profile_text, body.domain].some(s => s.trim())) {
    $("error").textContent = "Add a LinkedIn profile, your skills, or a preferred domain to get started.";
    $("error").hidden = false; return;
  }
  controller = new AbortController();
  $("error").hidden = true; $("results").hidden = true;
  $("submit").disabled = true; $("cancel").hidden = false;
  steps.forEach(s => s.className = ""); steps[0].className = "active";
  $("live-status").textContent = "Getting to know your profile…";
  try {
    const response = await fetch("/api/search", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body), signal:controller.signal});
    if (!response.ok) {
      const data = await response.json();
      throw Error(typeof data.detail === "string" ? data.detail : data.detail?.map(e => e.msg).join(" ") || "Request failed.");
    }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let pending = "", received = false;
    function consume(line) {
      if (!line.trim()) return;
      const data = JSON.parse(line);
      if (data.type === "error") throw Error(data.message);
      if (data.type === "progress") {
        const index = steps.findIndex(s => s.dataset.step === data.node);
        if (index >= 0) { steps[index].className = "done"; if (steps[index + 1]) steps[index + 1].className = "active"; }
        $("live-status").textContent = index < steps.length - 1 ? `${steps[index + 1].querySelector("b").textContent}…` : "Your shortlist is ready.";
      }
      if (data.type === "result") { received = true; render(data); }
    }
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      pending += decoder.decode(value, {stream:true});
      const lines = pending.split("\n"); pending = lines.pop(); lines.forEach(consume);
    }
    pending += decoder.decode(); consume(pending);
    if (!received) throw Error("Connection ended before results arrived. Please try again.");
  } catch (error) {
    const message = error.name === "AbortError" ? "Search cancelled. You can adjust your preferences and try again." : error.message;
    $("error").textContent = message; $("error").hidden = false;
    $("live-status").textContent = error.name === "AbortError" ? "Search cancelled." : "Search needs attention.";
  } finally {
    steps.forEach(s => s.classList.remove("active"));
    $("submit").disabled = false; $("cancel").hidden = true; controller = null;
  }
});
$("download").addEventListener("click", () => {
  if (!report) return;
  const content = [report.summary, "\nProfile\n" + report.profile.summary, "Skills: " + report.profile.skills.join(", "),
    ...report.jobs.map(j => `\n${j.title}\n${j.company} — ${j.location}\n${j.reason}\n${j.url}\n${j.availability}`),
    "\nLimitations\n" + [...report.warnings, ...report.profile.limitations].join("\n")].join("\n");
  const url = URL.createObjectURL(new Blob([content], {type:"text/plain;charset=utf-8"}));
  const a = document.createElement("a"); a.href = url; a.download = "jobseeker-report.txt"; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
