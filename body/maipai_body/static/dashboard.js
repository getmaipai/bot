"use strict";
const NS = "http://www.w3.org/2000/svg";
const deg = (r) => (r * 180) / Math.PI;
const fmt = (v, d = 1) => (v === null || v === undefined ? "n/a" : v.toFixed(d));
const $ = (id) => document.getElementById(id);

function el(parent, tag, attrs, text) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  parent.appendChild(node);
  return node;
}

// Angles are radians from the seam. Screen rotation is clockwise degrees.
function drawTop(s) {
  const svg = $("top");
  svg.replaceChildren();
  el(svg, "circle", { class: "ghost", cx: 0, cy: 0, r: 80 });
  el(svg, "text", { x: -4, y: -84 }, "front");
  const bodyYaw = s.body_yaw === null ? 0 : -deg(s.body_yaw);
  const headYaw = s.head_pose ? -deg(s.head_pose.yaw) : 0;
  const base = el(svg, "g", { transform: `rotate(${bodyYaw})` });
  el(base, "circle", { class: "head", cx: 0, cy: 0, r: 46 });
  el(base, "line", { class: "stroke", x1: 0, y1: 0, x2: 0, y2: -46 });
  const head = el(base, "g", { transform: `rotate(${headYaw})` });
  el(head, "ellipse", { class: "head", cx: 0, cy: 0, rx: 28, ry: 24 });
  el(head, "line", { class: "stroke", x1: 0, y1: 0, x2: 0, y2: -34 });
  if (s.doa) {
    const a = -deg(s.doa.angle_rad);
    const g = el(svg, "g", { transform: `rotate(${a})` });
    el(g, "line", { class: "doa" + (s.doa.speech_detected ? " speech" : ""), x1: 0, y1: -52, x2: 0, y2: -88 });
  }
}

function drawFront(s) {
  const svg = $("front");
  svg.replaceChildren();
  el(svg, "line", { class: "ghost", x1: -90, y1: 60, x2: 90, y2: 60 });
  const roll = s.head_pose ? deg(s.head_pose.roll) : 0;
  const head = el(svg, "g", { transform: `translate(0 20) rotate(${roll})` });
  el(head, "rect", { class: "head", x: -40, y: -30, width: 80, height: 60, rx: 14 });
  el(head, "circle", { class: "stroke", cx: -15, cy: -2, r: 5 });
  el(head, "circle", { class: "stroke", cx: 15, cy: -2, r: 5 });
  if (s.antennas) {
    // Seen from the front, the robot's left is on the viewer's right. The
    // two antennas' angles are mirrored in the seam (the recorded rest pose
    // is -a, +a), so the same rotation sign on both draws a symmetric pair.
    // Which sign is "outward" is not verified against the hardware.
    for (const [rad, x] of [[s.antennas.left, 28], [s.antennas.right, -28]]) {
      const a = el(head, "g", { transform: `translate(${x} -30) rotate(${deg(rad)})` });
      el(a, "line", { class: "ant", x1: 0, y1: 0, x2: 0, y2: -42 });
      el(a, "circle", { cx: 0, cy: -44, r: 4, fill: "var(--accent)" });
    }
  }
}

function drawSide(s) {
  const svg = $("side");
  svg.replaceChildren();
  el(svg, "line", { class: "ghost", x1: -90, y1: 60, x2: 90, y2: 60 });
  const pitch = s.head_pose ? deg(s.head_pose.pitch) : 0;
  const head = el(svg, "g", { transform: `translate(0 20) rotate(${pitch})` });
  el(head, "rect", { class: "head", x: -34, y: -30, width: 68, height: 60, rx: 14 });
  el(head, "line", { class: "stroke", x1: 34, y1: -4, x2: 48, y2: -4 });
  el(head, "text", { x: 38, y: -10 }, "front");
}

function rows(tableId, data) {
  const body = $(tableId).tBodies[0];
  body.replaceChildren();
  for (const [k, v] of data) {
    const tr = body.insertRow();
    tr.insertCell().textContent = k;
    tr.insertCell().textContent = v;
  }
}

function render(s) {
  $("body-id").textContent = s.body;
  const link = $("link");
  link.textContent = s.connected ? "connected" : "body lost";
  link.className = "pill " + (s.connected ? "ok" : "bad");
  drawTop(s); drawFront(s); drawSide(s);
  const p = s.head_pose;
  rows("telemetry", [
    ["frame", s.seq === null ? "n/a" : `#${s.seq} (${fmt(s.age_ms, 0)} ms old)`],
    ["head x, y, z (mm)", p ? [p.x, p.y, p.z].map((v) => fmt(v * 1000)).join(", ") : "n/a"],
    ["head roll (deg)", p ? fmt(deg(p.roll)) : "n/a"],
    ["head pitch (deg)", p ? fmt(deg(p.pitch)) : "n/a"],
    ["head yaw (deg)", p ? fmt(deg(p.yaw)) : "n/a"],
    ["antenna left (deg)", s.antennas ? fmt(deg(s.antennas.left)) : "n/a"],
    ["antenna right (deg)", s.antennas ? fmt(deg(s.antennas.right)) : "n/a"],
    ["body yaw (deg)", s.body_yaw === null ? "n/a" : fmt(deg(s.body_yaw))],
    ["direction of arrival (deg)", s.doa ? fmt(deg(s.doa.angle_rad)) : "n/a"],
  ]);
  const pr = s.presence;
  rows("funnel", [
    ["driving the head", s.arbitration.priority.toLowerCase()],
    ["face tracked", pr ? String(pr.face_detected) : "n/a"],
    ["speech heard", pr ? String(pr.speech_detected) : "n/a"],
    ["tipped / freefall", pr ? `${pr.tip_detected} / ${pr.freefall_detected}` : "n/a"],
    ["muted", String(s.muted)],
  ]);
  const mute = $("mute");
  mute.setAttribute("aria-pressed", String(s.muted));
  mute.textContent = s.muted ? "Unmute" : "Mute";
}

async function post(path, body) {
  const out = $("outcome");
  try {
    const r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const j = await r.json();
    out.className = r.ok && j.rendered ? "" : "bad";
    if (!r.ok) out.textContent = `Refused (${r.status}): ${j.error}`;
    else if (j.rendered) out.textContent = `Rendered ${j.rendered_primitive}.`;
    else out.textContent = `Withheld ${j.primitive || "mute"}: ${j.suppressed_reason || "no change"}.`;
  } catch (e) {
    out.className = "bad";
    out.textContent = "The dashboard server did not answer.";
  }
}

let direction = null;
$("direction").addEventListener("input", (e) => {
  direction = (Number(e.target.value) * Math.PI) / 180;
  $("direction-out").textContent = `${e.target.value} deg`;
});
$("direction").addEventListener("dblclick", (e) => {
  direction = null; e.target.value = 0; $("direction-out").textContent = "auto";
});
let muted = false;
$("mute").addEventListener("click", () => post("/api/muted", { muted: !muted }));

fetch("/api/primitives").then((r) => r.json()).then(({ primitives }) => {
  for (const name of primitives) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = name; b.dataset.primitive = name;
    if (name === "stop") b.className = "stop";
    b.addEventListener("click", () =>
      post(`/api/primitive/${name}`, direction === null ? {} : { direction_rad: direction }));
    $("buttons").appendChild(b);
  }
});

const feed = new EventSource("/events");
feed.onmessage = (e) => { const s = JSON.parse(e.data); muted = s.muted; render(s); };
feed.onerror = () => { $("link").textContent = "dashboard offline"; $("link").className = "pill bad"; };
