// Tutoring Manager: the static UI. It replaces the server-rendered pages of
// Assignment 1. Every page is built here in the browser from JSON that it
// fetches from the two services:
//   customers service: login, students
//   lessons service:   tutors, lessons (it asks the customers service for
//                      student data itself, server side)
// The booking form also lists students; it gets them straight from the
// customers service (a client-side call to each service).
"use strict";

const CONFIG = window.APP_CONFIG || {};
const SERVICES = { customers: CONFIG.customersUrl, lessons: CONFIG.lessonsUrl };
const TOKEN_KEY = "tutoring.token";
const USER_KEY = "tutoring.username";
const app = document.getElementById("app");
let flash = null; // { kind: "success" | "error", text } shown once on the next page

// ---------- login token, kept for this browser tab only ----------

function readStored(key) {
  try { return sessionStorage.getItem(key); } catch { return null; }
}

function writeStored(key, value) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch { /* storage blocked: the login lasts until the page is reloaded */ }
}

let token = readStored(TOKEN_KEY);
let username = readStored(USER_KEY);

function setLogin(newToken, newUsername) {
  token = newToken;
  username = newUsername;
  writeStored(TOKEN_KEY, newToken);
  writeStored(USER_KEY, newUsername);
}

// ---------- calling the services ----------

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function call(service, method, path, body) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(SERVICES[service] + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // Network error. On Azure this is usually a cold start: after a quiet
    // period the container and its database need up to a minute to wake up,
    // and Azure's "starting" answer has no CORS header, so the browser only
    // sees a failed request.
    throw new ApiError(
      `The ${service} service is not reachable right now. It may be starting up after a quiet period: try again in a minute.`, 0);
  }
  if (response.status === 401 && path !== "/auth/login") {
    // The token expired or is wrong: back to the login page. The promise never
    // settles, so the page that made this call does not draw over the login.
    setLogin(null, null);
    flash = { kind: "error", text: "Please log in again." };
    render();
    return new Promise(() => {});
  }
  if (response.status === 204) return null;
  let data = null;
  try { data = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    if (!data && [502, 503, 504].includes(response.status)) {
      throw new ApiError(`The ${service} service is starting up. Try again in about a minute.`, response.status);
    }
    const message = (data && data.error) || `The ${service} service answered with error ${response.status}.`;
    throw new ApiError(message, response.status);
  }
  return data;
}

// ---------- building HTML safely ----------

// el("a", { href: "#/x" }, "text", child) creates an element. Text is always
// added as text, never as HTML, so names typed by users cannot inject code.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function show(...nodes) {
  // Parts that are not there (null, e.g. no message) are left out.
  app.replaceChildren(...nodes.flat().filter((n) => n !== null && n !== undefined && n !== false));
}

function flashMessage() {
  if (!flash) return null;
  const node = el("p", { class: `flash flash-${flash.kind}`, role: "status" }, flash.text);
  flash = null;
  return node;
}

function errorBox(error) {
  return el("p", { class: "flash flash-error", role: "alert" }, error.message);
}

function go(hash, message) {
  if (message) flash = message;
  if (location.hash === hash) render();
  else location.hash = hash;
}

function formValues(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function field(label, name, attrs = {}) {
  return [el("label", { for: name }, label), el("input", { id: name, name, ...attrs })];
}

function formatStart(text) {
  // "2030-10-05T16:00" becomes "5 Oct 2030, 16:00" without time-zone surprises.
  const [date, time] = text.split("T");
  const [year, month, day] = date.split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${day} ${months[month - 1]} ${year}, ${time}`;
}

// ---------- login ----------

function renderLogin() {
  // Wake both services while the user types: on Azure they sleep when unused,
  // and starting takes a while. The answers are not needed, so errors are ignored.
  for (const url of Object.values(SERVICES)) fetch(`${url}/health`).catch(() => {});
  const message = flashMessage();
  const form = el("form", { class: "record-form login" },
    ...field("Username", "username", { autocomplete: "username", required: true }),
    ...field("Password", "password", { type: "password", autocomplete: "current-password", required: true }),
    el("div", { class: "form-actions" }, el("button", { type: "submit" }, "Log in")),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await call("customers", "POST", "/auth/login", formValues(form));
      setLogin(result.token, result.username);
      go("#/lessons");
    } catch (error) {
      form.querySelector(".flash")?.remove();
      form.prepend(errorBox(error));
    }
  });
  show(el("h1", {}, "Staff login"), message, form);
}

// ---------- lessons ----------

const STATUSES = ["scheduled", "completed", "cancelled"];

function studentCell(lesson, studentsAvailable) {
  if (lesson.student_name) return lesson.student_name;
  const text = studentsAvailable
    ? `Unknown student (#${lesson.student_id})`
    : `Name unavailable (#${lesson.student_id})`;
  return el("span", { class: "unavailable" }, text);
}

async function renderLessons(query) {
  const status = query.get("status") || "";
  const tutorId = query.get("tutor_id") || "";
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (tutorId) params.set("tutor_id", tutorId);

  const message = flashMessage();
  const head = el("div", { class: "page-head" },
    el("h1", {}, "Lessons"),
    el("a", { class: "button", href: "#/lessons/new" }, "Schedule lesson"));

  let result;
  let tutors = [];
  try {
    [result, tutors] = await Promise.all([
      call("lessons", "GET", `/lessons?${params}`),
      call("lessons", "GET", "/tutors"),
    ]);
  } catch (error) {
    show(head, message, errorBox(error));
    return;
  }

  const link = (newStatus) => {
    const p = new URLSearchParams(params);
    if (newStatus) p.set("status", newStatus); else p.delete("status");
    return `#/lessons?${p}`;
  };
  const tabs = el("div", { class: "tabs" },
    el("a", { href: link(""), "aria-current": status === "" ? "page" : null }, "All"),
    STATUSES.map((s) => el("a", { href: link(s), "aria-current": status === s ? "page" : null },
      s[0].toUpperCase() + s.slice(1))));

  const tutorSelect = el("select", { id: "tutor-filter" },
    el("option", { value: "" }, "All tutors"),
    tutors.map((t) => el("option", { value: t.id, selected: String(t.id) === tutorId }, t.name)));
  tutorSelect.addEventListener("change", () => {
    const p = new URLSearchParams(params);
    if (tutorSelect.value) p.set("tutor_id", tutorSelect.value); else p.delete("tutor_id");
    go(`#/lessons?${p}`);
  });
  const filters = el("div", { class: "filters" },
    el("label", { for: "tutor-filter" }, "Tutor"), tutorSelect);

  // Degraded, not broken: the lessons service tells us when names are missing.
  const notice = result.notice ? el("p", { class: "notice", role: "status" }, result.notice) : null;

  let table;
  if (result.lessons.length === 0) {
    table = el("p", { class: "empty" }, "No lessons match this view.");
  } else {
    table = el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {},
        ["Start", "Student", "Tutor", "Subject", "Length", "Status"].map((h) => el("th", {}, h)),
        el("th", {}, el("span", { class: "visually-hidden" }, "Actions")))),
      el("tbody", {}, result.lessons.map((lesson) => el("tr", {},
        el("td", {}, formatStart(lesson.start_time)),
        el("td", {}, studentCell(lesson, result.students_available)),
        el("td", {}, lesson.tutor_name),
        el("td", {}, lesson.subject),
        el("td", {}, `${lesson.duration_minutes} min`),
        el("td", {}, el("span", { class: `status status-${lesson.status}` }, lesson.status)),
        el("td", {}, lesson.status === "scheduled" ? el("div", { class: "actions" },
          el("button", { type: "button", class: "link", onclick: () => changeStatus(lesson.id, "completed") }, "Mark completed"),
          el("button", { type: "button", class: "link-danger", onclick: () => changeStatus(lesson.id, "cancelled") }, "Cancel"),
        ) : null),
      )))));
  }
  show(head, message, notice, tabs, filters, table);
}

async function changeStatus(lessonId, status) {
  try {
    await call("lessons", "POST", `/lessons/${lessonId}/status`, { status });
    flash = { kind: "success", text: `Lesson marked as ${status}.` };
  } catch (error) {
    flash = { kind: "error", text: error.message };
  }
  render();
}

async function renderLessonForm() {
  const title = el("h1", {}, "Schedule lesson");
  // Two independent calls: one to each service. If one fails, we still know
  // which one, and can say so.
  const [tutorsResult, studentsResult] = await Promise.allSettled([
    call("lessons", "GET", "/tutors"),
    call("customers", "GET", "/students"),
  ]);
  if (tutorsResult.status === "rejected") { show(title, errorBox(tutorsResult.reason)); return; }
  if (studentsResult.status === "rejected") { show(title, errorBox(studentsResult.reason)); return; }
  const tutors = tutorsResult.value;
  const students = studentsResult.value;

  if (tutors.length === 0 || students.length === 0) {
    show(title, el("p", { class: "empty" }, "To schedule a lesson you need at least one ",
      el("a", { href: "#/students/new" }, "student"), " and one ",
      el("a", { href: "#/tutors/new" }, "tutor"), "."));
    return;
  }

  const form = el("form", { class: "record-form" },
    el("label", { for: "student_id" }, "Student"),
    el("select", { id: "student_id", name: "student_id", required: true },
      el("option", { value: "" }, "Choose a student"),
      students.map((s) => el("option", { value: s.id }, s.name))),
    el("label", { for: "tutor_id" }, "Tutor"),
    el("select", { id: "tutor_id", name: "tutor_id", required: true },
      el("option", { value: "" }, "Choose a tutor"),
      tutors.map((t) => el("option", { value: t.id }, t.subjects ? `${t.name} (${t.subjects})` : t.name))),
    ...field("Subject", "subject", { required: true }),
    ...field("Start", "start_time", { type: "datetime-local", required: true }),
    ...field("Length in minutes", "duration_minutes", { type: "number", min: 15, max: 240, step: 5, required: true }),
    el("div", { class: "form-actions" },
      el("button", { type: "submit" }, "Schedule lesson"),
      el("a", { href: "#/lessons" }, "Back to lessons")),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await call("lessons", "POST", "/lessons", formValues(form));
      go("#/lessons", { kind: "success", text: "Lesson scheduled." });
    } catch (error) {
      // 400, 409 or 503: the message from the service explains it; the form keeps its values.
      form.querySelector(".flash")?.remove();
      form.prepend(errorBox(error));
    }
  });
  show(title, form);
}

// ---------- students ----------

async function renderStudents(query) {
  const search = query.get("q") || "";
  const message = flashMessage();
  const head = el("div", { class: "page-head" },
    el("h1", {}, "Students"),
    el("a", { class: "button", href: "#/students/new" }, "Add student"));

  const searchForm = el("form", { class: "search" },
    el("label", { for: "q" }, "Search by name"),
    el("input", { id: "q", name: "q", type: "search", value: search }),
    el("button", { type: "submit" }, "Search"),
    search ? el("a", { href: "#/students" }, "Show all") : null);
  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const q = searchForm.elements.q.value.trim();
    go(q ? `#/students?q=${encodeURIComponent(q)}` : "#/students");
  });

  let students;
  try {
    students = await call("customers", "GET", `/students${search ? `?q=${encodeURIComponent(search)}` : ""}`);
  } catch (error) {
    show(head, message, searchForm, errorBox(error));
    return;
  }

  let content;
  if (students.length) {
    content = el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {},
        ["Name", "Guardian", "Email", "Phone"].map((h) => el("th", {}, h)),
        el("th", {}, el("span", { class: "visually-hidden" }, "Actions")))),
      el("tbody", {}, students.map((s) => el("tr", {},
        el("td", {}, s.name),
        el("td", {}, s.guardian_name || ""),
        el("td", {}, s.guardian_email || ""),
        el("td", {}, s.guardian_phone || ""),
        el("td", {}, el("div", { class: "actions" },
          el("a", { href: `#/students/${s.id}` }, "Edit"),
          el("button", { type: "button", class: "link-danger", onclick: () => deleteStudent(s) }, "Delete"))),
      )))));
  } else if (search) {
    content = el("p", { class: "empty" }, `No students match "${search}".`);
  } else {
    content = el("p", { class: "empty" }, "No students yet. Add the first one to start scheduling lessons.");
  }
  show(head, message, searchForm, content);
}

async function deleteStudent(student) {
  if (!window.confirm(`Delete ${student.name}?`)) return;
  try {
    await call("customers", "DELETE", `/students/${student.id}`);
    flash = { kind: "success", text: `${student.name} was deleted.` };
  } catch (error) {
    flash = { kind: "error", text: error.message };
  }
  render();
}

async function renderStudentForm(studentId) {
  const editing = studentId !== null;
  const title = el("h1", {}, editing ? "Edit student" : "Add student");
  let student = {};
  if (editing) {
    try {
      student = await call("customers", "GET", `/students/${studentId}`);
    } catch (error) {
      show(title, errorBox(error));
      return;
    }
  }
  const form = el("form", { class: "student-form" },
    ...field("Student name", "name", { required: true, maxlength: 100, value: student.name || "" }),
    el("fieldset", {},
      el("legend", {}, "Guardian"),
      el("p", { class: "hint" }, "Enter an email address or a phone number, or both."),
      ...field("Name", "guardian_name", { maxlength: 100, value: student.guardian_name || "" }),
      ...field("Email", "guardian_email", { type: "email", value: student.guardian_email || "" }),
      ...field("Phone", "guardian_phone", { type: "tel", value: student.guardian_phone || "" })),
    el("div", { class: "form-actions" },
      el("button", { type: "submit" }, editing ? "Save changes" : "Add student"),
      el("a", { href: "#/students" }, "Back to students")),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      if (editing) await call("customers", "PUT", `/students/${studentId}`, formValues(form));
      else await call("customers", "POST", "/students", formValues(form));
      go("#/students", { kind: "success", text: editing ? "Student updated." : "Student added." });
    } catch (error) {
      form.querySelector(".flash")?.remove();
      form.prepend(errorBox(error));
    }
  });
  show(title, form);
}

// ---------- tutors ----------

async function renderTutors() {
  const message = flashMessage();
  const head = el("div", { class: "page-head" },
    el("h1", {}, "Tutors"),
    el("a", { class: "button", href: "#/tutors/new" }, "Add tutor"));
  let tutors;
  try {
    tutors = await call("lessons", "GET", "/tutors");
  } catch (error) {
    show(head, message, errorBox(error));
    return;
  }
  const content = tutors.length === 0
    ? el("p", { class: "empty" }, "No tutors yet.")
    : el("div", { class: "table-wrap" }, el("table", {},
      el("thead", {}, el("tr", {},
        ["Name", "Email", "Subjects", "Hourly rate"].map((h) => el("th", {}, h)),
        el("th", {}, el("span", { class: "visually-hidden" }, "Actions")))),
      el("tbody", {}, tutors.map((t) => el("tr", {},
        el("td", {}, t.name),
        el("td", {}, t.email || ""),
        el("td", {}, t.subjects || "Any subject"),
        el("td", {}, `€${t.hourly_rate.toFixed(2)}`),
        el("td", {}, el("div", { class: "actions" }, el("a", { href: `#/tutors/${t.id}` }, "Edit"))),
      )))));
  show(head, message, content);
}

async function renderTutorForm(tutorId) {
  const editing = tutorId !== null;
  const title = el("h1", {}, editing ? "Edit tutor" : "Add tutor");
  let tutor = {};
  if (editing) {
    try {
      tutor = await call("lessons", "GET", `/tutors/${tutorId}`);
    } catch (error) {
      show(title, errorBox(error));
      return;
    }
  }
  const form = el("form", { class: "record-form" },
    ...field("Name", "name", { required: true, maxlength: 100, value: tutor.name || "" }),
    ...field("Email", "email", { type: "email", value: tutor.email || "" }),
    ...field("Subjects", "subjects", { value: tutor.subjects || "" }),
    el("p", { class: "hint" }, "Separate subjects with commas. Leave empty if the tutor can teach any subject."),
    ...field("Hourly rate (€)", "hourly_rate", {
      type: "number", min: 0, max: 1000, step: "0.01", required: true,
      value: tutor.hourly_rate === undefined ? "" : tutor.hourly_rate,
    }),
    el("div", { class: "form-actions" },
      el("button", { type: "submit" }, editing ? "Save changes" : "Add tutor"),
      el("a", { href: "#/tutors" }, "Back to tutors")),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      if (editing) await call("lessons", "PUT", `/tutors/${tutorId}`, formValues(form));
      else await call("lessons", "POST", "/tutors", formValues(form));
      go("#/tutors", { kind: "success", text: editing ? "Tutor updated." : "Tutor added." });
    } catch (error) {
      form.querySelector(".flash")?.remove();
      form.prepend(errorBox(error));
    }
  });
  show(title, form);
}

// ---------- page selection ----------

// "#/students/7?q=x" -> section "students", id "7", query q=x
function currentRoute() {
  const [path, queryString = ""] = location.hash.replace(/^#/, "").split("?");
  const [, section = "lessons", id = null] = path.split("/");
  return { section, id, query: new URLSearchParams(queryString) };
}

function render() {
  const loggedIn = Boolean(token);
  document.getElementById("nav").hidden = !loggedIn;
  document.getElementById("signed-in").hidden = !loggedIn;
  document.getElementById("signed-in-name").textContent = username || "";
  if (!loggedIn) {
    renderLogin();
    return;
  }

  const { section, id, query } = currentRoute();
  for (const link of document.querySelectorAll("#nav a")) {
    if (link.dataset.section === section) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const recordId = id === "new" ? null : id;
  if (section === "students") {
    if (id) renderStudentForm(recordId); else renderStudents(query);
  } else if (section === "tutors") {
    if (id) renderTutorForm(recordId); else renderTutors();
  } else if (id === "new") {
    renderLessonForm();
  } else {
    renderLessons(query);
  }
}

document.getElementById("logout").addEventListener("click", () => {
  setLogin(null, null);
  flash = { kind: "success", text: "You are logged out." };
  go("#/lessons");
});
window.addEventListener("hashchange", render);

if (!SERVICES.customers || !SERVICES.lessons) {
  show(el("p", { class: "flash flash-error" }, "config.js is missing the services' URLs."));
} else {
  render();
}
