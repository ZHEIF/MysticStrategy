"use strict";

const STORAGE_KEY = "quan_model_battle_mvp_v1";
const ACCESS_CODE_KEY = "quan_model_battle_access_code_v1";
const REQUEST_TIMEOUT_MS = 280000;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function apiURL(path) {
  if (window.location.protocol === "file:") {
    return `http://127.0.0.1:8000${path}`;
  }
  if (window.location.hostname === "fatelinkmodel.com") {
    return `https://www.fatelinkmodel.com${path}`;
  }
  return path;
}

const defaultState = {
  mode: "self",
  self: {
    name: "",
    birth_date: "",
    birth_place: "",
    recent_plans: "",
    major_experiences: "",
  },
  friends: [
    emptyFriend(),
  ],
  my_relationship_tendency: "",
  results: {
    self: null,
    friends: null,
  },
};

let state = loadState();
let currentMode = state.mode || "self";
let accessCode = sessionStorage.getItem(ACCESS_CODE_KEY) || "";
let accessCodeResolver = null;

const elements = {
  apiStatus: $("#apiStatus"),
  modelStatus: $("#modelStatus"),
  tabSelf: $("#tabSelf"),
  tabFriends: $("#tabFriends"),
  selfForm: $("#selfForm"),
  friendsForm: $("#friendsForm"),
  selfName: $("#selfName"),
  selfBirthDate: $("#selfBirthDate"),
  selfBirthPlace: $("#selfBirthPlace"),
  selfRecentPlans: $("#selfRecentPlans"),
  selfMajorExperiences: $("#selfMajorExperiences"),
  myRelationshipTendency: $("#myRelationshipTendency"),
  friendList: $("#friendList"),
  friendCardTemplate: $("#friendCardTemplate"),
  resultMeta: $("#resultMeta"),
  resultBody: $("#resultBody"),
  analyzeSelf: $("#analyzeSelf"),
  analyzeFriends: $("#analyzeFriends"),
  addFriend: $("#addFriend"),
  clearDrafts: $("#clearDrafts"),
  accessCodeModal: $("#accessCodeModal"),
  accessCodeBackdrop: $("#accessCodeBackdrop"),
  accessCodeTitle: $("#accessCodeTitle"),
  accessCodeHint: $("#accessCodeHint"),
  accessCodeInput: $("#accessCodeInput"),
  accessCodeError: $("#accessCodeError"),
  accessCodeSubmit: $("#accessCodeSubmit"),
  accessCodeClose: $("#accessCodeClose"),
};

init();

function init() {
  hydrateForms();
  wireEvents();
  renderMode(currentMode);
  renderFriendList();
  renderResult();
  syncHealth();
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return structuredCloneDefault();
    const parsed = JSON.parse(raw);
    return mergeState(parsed);
  } catch {
    return structuredCloneDefault();
  }
}

function structuredCloneDefault() {
  return JSON.parse(JSON.stringify(defaultState));
}

function mergeState(raw) {
  const next = structuredCloneDefault();
  if (raw && typeof raw === "object") {
    next.mode = raw.mode === "friends" ? "friends" : "self";
    next.self = {
      name: raw.self?.name || "",
      birth_date: raw.self?.birth_date || "",
      birth_place: raw.self?.birth_place || "",
      recent_plans: raw.self?.recent_plans || "",
      major_experiences: raw.self?.major_experiences || "",
    };
    next.my_relationship_tendency = typeof raw.my_relationship_tendency === "string" ? raw.my_relationship_tendency : "";
    next.friends = Array.isArray(raw.friends) && raw.friends.length ? raw.friends.map(normalizeFriend).filter(Boolean) : [emptyFriend()];
    next.results = {
      self: raw.results?.self || null,
      friends: raw.results?.friends || null,
    };
  }
  return next;
}

function normalizeFriend(friend) {
  if (!friend || typeof friend !== "object") return null;
  return {
    id: friend.id || uid(),
    name: friend.name || "",
    birth_date: friend.birth_date || "",
    recent_plans: friend.recent_plans || "",
    relationship_tendency: friend.relationship_tendency || "",
  };
}

function emptyFriend() {
  return {
    id: uid(),
    name: "",
    birth_date: "",
    recent_plans: "",
    relationship_tendency: "",
  };
}

function uid() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function hydrateForms() {
  const self = state.self || {};
  elements.selfName.value = self.name || "";
  elements.selfBirthDate.value = self.birth_date || "";
  elements.selfBirthPlace.value = self.birth_place || "";
  elements.selfRecentPlans.value = self.recent_plans || "";
  elements.selfMajorExperiences.value = self.major_experiences || "";
  elements.myRelationshipTendency.value = state.my_relationship_tendency || "";
}

function wireEvents() {
  [
    [elements.tabSelf, "self"],
    [elements.tabFriends, "friends"],
  ].forEach(([button, mode]) => {
    button.addEventListener("click", () => {
      currentMode = mode;
      state.mode = mode;
      saveState();
      renderMode(mode);
      renderResult();
    });
  });

  [
    [elements.selfName, "name"],
    [elements.selfBirthDate, "birth_date"],
    [elements.selfBirthPlace, "birth_place"],
    [elements.selfRecentPlans, "recent_plans"],
    [elements.selfMajorExperiences, "major_experiences"],
  ].forEach(([input, field]) => {
    input.addEventListener("input", () => {
      state.self[field] = input.value;
      saveState();
    });
  });

  elements.myRelationshipTendency.addEventListener("input", () => {
    state.my_relationship_tendency = elements.myRelationshipTendency.value;
    saveState();
  });

  elements.addFriend.addEventListener("click", () => {
    state.friends.push(emptyFriend());
    saveState();
    renderFriendList();
  });

  elements.clearDrafts.addEventListener("click", () => {
    state = structuredCloneDefault();
    currentMode = "self";
    saveState();
    hydrateForms();
    renderMode(currentMode);
    renderFriendList();
    renderResult();
  });

  elements.analyzeSelf.addEventListener("click", () => analyzeSelf());
  elements.analyzeFriends.addEventListener("click", () => analyzeFriends());
  elements.accessCodeSubmit.addEventListener("click", submitAccessCode);
  elements.accessCodeClose.addEventListener("click", cancelAccessCodeDialog);
  elements.accessCodeBackdrop.addEventListener("click", cancelAccessCodeDialog);
  elements.accessCodeInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submitAccessCode();
    }
  });
}

function renderMode(mode) {
  const isSelf = mode === "self";
  elements.tabSelf.classList.toggle("active", isSelf);
  elements.tabFriends.classList.toggle("active", !isSelf);
  elements.selfForm.hidden = !isSelf;
  elements.friendsForm.hidden = isSelf;
}

function renderFriendList() {
  elements.friendList.innerHTML = "";
  state.friends.forEach((friend, index) => {
    const node = elements.friendCardTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.friendId = friend.id;
    $(".friend-title", node).textContent = `朋友 ${index + 1}`;

    const removeBtn = $(".remove-friend", node);
    removeBtn.addEventListener("click", () => {
      state.friends = state.friends.filter((item) => item.id !== friend.id);
      if (!state.friends.length) state.friends.push(emptyFriend());
      saveState();
      renderFriendList();
    });

    $$("[data-field]", node).forEach((input) => {
      const field = input.dataset.field;
      input.value = friend[field] || "";
      input.addEventListener("input", () => {
        const current = state.friends.find((item) => item.id === friend.id);
        if (!current) return;
        current[field] = input.value;
        saveState();
      });
    });

    elements.friendList.appendChild(node);
  });
}

async function analyzeSelf() {
  setBusy(true);
  syncResultLoading("正在分析自我画像...");
  const payload = {
    mode: "self",
    ...state.self,
  };
  try {
    const response = await postJSON("/api/analyze", payload);
    state.results.self = response;
    currentMode = "self";
    state.mode = "self";
    saveState();
    renderMode("self");
    renderResult();
  } catch (error) {
    currentMode = "self";
    state.mode = "self";
    saveState();
    renderMode("self");
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function analyzeFriends() {
  setBusy(true);
  syncResultLoading("正在拆解关系结构...");
  const payload = {
    mode: "friends",
    people: state.friends.map((friend) => ({
      name: friend.name,
      birth_date: friend.birth_date,
      recent_plans: friend.recent_plans,
      relationship_tendency: friend.relationship_tendency,
    })),
    my_relationship_tendency: state.my_relationship_tendency,
  };
  try {
    const response = await postJSON("/api/analyze", payload);
    state.results.friends = response;
    currentMode = "friends";
    state.mode = "friends";
    saveState();
    renderMode("friends");
    renderResult();
  } catch (error) {
    currentMode = "friends";
    state.mode = "friends";
    saveState();
    renderMode("friends");
    showError(error);
  } finally {
    setBusy(false);
  }
}

async function postJSON(path, payload) {
  return postJSONWithAuth(path, payload, true);
}

async function postJSONWithAuth(path, payload, allowAuthRetry) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    const requestPayload = accessCode ? { ...payload, access_code: accessCode } : payload;
    response = await fetch(apiURL(path), {
      method: "POST",
      headers: {
        "Content-Type": "text/plain;charset=UTF-8",
      },
      body: JSON.stringify(requestPayload),
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      const timeoutError = new Error("DeepSeek 深度思考请求超时，请稍后重试。");
      timeoutError.code = "request_timeout";
      timeoutError.category = "network";
      timeoutError.retryable = true;
      throw timeoutError;
    }
    throw buildFetchNetworkError(error, path);
  } finally {
    window.clearTimeout(timeout);
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (
      allowAuthRetry &&
      response.status === 401 &&
      (data.code === "access_code_required" || data.code === "access_code_invalid")
    ) {
      if (data.code === "access_code_invalid") {
        sessionStorage.removeItem(ACCESS_CODE_KEY);
        accessCode = "";
      }
      const nextCode = await requestAccessCode(data.detail || data.error || "请输入访问码");
      if (nextCode) {
        accessCode = nextCode;
        sessionStorage.setItem(ACCESS_CODE_KEY, accessCode);
        return postJSONWithAuth(path, payload, false);
      }
    }
    if (response.status === 429 && data.code === "rate_limited") {
      throw buildApiError(data, response.status);
    }
    throw buildApiError(data, response.status);
  }
  return data;
}

function buildFetchNetworkError(originalError, path) {
  const target = apiURL(path);
  const error = new Error("网络层请求失败：浏览器没有拿到后端响应。");
  error.code = "fetch_failed";
  error.category = "network";
  error.detail = `原始错误：${originalError?.message || originalError || "Failed to fetch"}；请求地址：${target}`;
  error.remedy = [
    "优先打开 https://www.fatelinkmodel.com，不要停留在裸域 fatelinkmodel.com。",
    "如果是本地测试，不要双击 index.html，先运行 python3 server.py，再打开 http://127.0.0.1:8000。",
    "打开 /api/health 检查后端是否在线；如果 health 可用但 analyze 失败，通常是网络拦截、浏览器插件或部署域名跳转导致。",
  ].join(" ");
  error.retryable = true;
  error.httpStatus = "";
  error.source = "browser";
  error.diagnostics = {
    currentOrigin: window.location.origin,
    currentHref: window.location.href,
    requestURL: target,
    originalErrorName: originalError?.name || "",
    originalErrorMessage: originalError?.message || "",
  };
  return error;
}

function buildApiError(data, status) {
  const message = data?.error || data?.detail || "DeepSeek 请求失败";
  const error = new Error(message);
  error.code = data?.code || "deepseek_request_failed";
  error.category = data?.category || "unknown";
  error.detail = data?.detail || "";
  error.remedy = data?.remedy || "";
  error.retryable = Boolean(data?.retryable);
  error.status = status;
  error.httpStatus = data?.httpStatus || status;
  error.source = data?.source || "deepseek";
  error.diagnostics = data?.diagnostics || null;
  return error;
}

function openAccessCodeDialog(message) {
  if (!elements.accessCodeModal) return;
  if (message) {
    elements.accessCodeHint.textContent = message;
  }
  setAccessCodeError("");
  document.body.classList.add("access-code-open");
  elements.accessCodeModal.hidden = false;
  elements.accessCodeModal.setAttribute("aria-hidden", "false");
  window.requestAnimationFrame(() => {
    elements.accessCodeInput.focus();
    elements.accessCodeInput.select();
  });
}

function hideAccessCodeDialog() {
  if (!elements.accessCodeModal) return;
  document.body.classList.remove("access-code-open");
  elements.accessCodeModal.hidden = true;
  elements.accessCodeModal.setAttribute("aria-hidden", "true");
  setAccessCodeError("");
}

function setAccessCodeError(message) {
  if (!elements.accessCodeError) return;
  if (message) {
    elements.accessCodeError.textContent = message;
    elements.accessCodeError.hidden = false;
  } else {
    elements.accessCodeError.textContent = "";
    elements.accessCodeError.hidden = true;
  }
}

function requestAccessCode(message) {
  if (accessCodeResolver) {
    accessCodeResolver("");
    accessCodeResolver = null;
  }
  if (elements.accessCodeInput) {
    elements.accessCodeInput.value = accessCode || "";
  }
  openAccessCodeDialog(message);
  return new Promise((resolve) => {
    accessCodeResolver = resolve;
  });
}

function finishAccessCodeDialog(value) {
  const resolver = accessCodeResolver;
  accessCodeResolver = null;
  hideAccessCodeDialog();
  if (resolver) resolver(value || "");
}

function submitAccessCode() {
  const nextCode = elements.accessCodeInput.value.trim();
  if (!nextCode) {
    setAccessCodeError("请输入访问码");
    elements.accessCodeInput.focus();
    return;
  }
  accessCode = nextCode;
  sessionStorage.setItem(ACCESS_CODE_KEY, accessCode);
  finishAccessCodeDialog(accessCode);
}

function cancelAccessCodeDialog() {
  finishAccessCodeDialog("");
}

function setBusy(isBusy) {
  elements.analyzeSelf.disabled = isBusy;
  elements.analyzeFriends.disabled = isBusy;
  elements.addFriend.disabled = isBusy;
}

function renderResult() {
  const result = currentMode === "self" ? state.results.self : state.results.friends;
  if (!result) {
    elements.resultMeta.innerHTML = "";
    elements.resultBody.innerHTML = '<div class="empty-state">等待输入。</div>';
    return;
  }

  const source = result.source || "deepseek";
  const model = result.model || "-";
  const timestamp = result.timestamp ? new Date(result.timestamp).toLocaleString("zh-CN") : "";
  elements.resultMeta.innerHTML = [
    badge(source === "deepseek" ? "DeepSeek 深度思考" : "非 DeepSeek 结果", source === "deepseek" ? "good" : "bad"),
    badge(model, "muted"),
    timestamp ? badge(timestamp, "muted") : "",
    result.reasoningEffort ? badge(`reasoning ${result.reasoningEffort}`, "muted") : "",
  ].filter(Boolean).join("");

  elements.resultBody.innerHTML = currentMode === "self"
    ? renderSelfResult(result.analysis || {})
    : renderFriendsResult(result.analysis || {});
}

function renderSelfResult(data) {
  const overview = data.overview || {};
  const self = data.self_analysis || {};
  const ninety = data.next_90_days || {};
  const three = data.next_3_years || {};

  return [
    sectionHTML("总览", `
      <div class="card">
        <h4>${escapeHtml(overview.headline || "暂无")}</h4>
        <div>${escapeHtml(overview.core_archetype || "")}</div>
        ${renderChipRow(overview.key_strengths || [])}
        ${renderChipRow(overview.main_pressure_points || [])}
        <div>${escapeHtml(overview.bottom_line || "")}</div>
      </div>
    `),
    sectionHTML("自我分析", `
      <div class="card">
        <div>${escapeHtml(self.nature || "")}</div>
        <div>${escapeHtml(self.pattern || "")}</div>
      </div>
      <div class="subgrid">
        ${(self.supporting_models || []).map((item) => {
          if (typeof item === "string") {
            return `<div class="card"><h4>模型</h4><div>${escapeHtml(item)}</div></div>`;
          }
          return `<div class="card"><h4>${escapeHtml(item.model || "模型")}</h4><div>${escapeHtml(item.read || "")}</div></div>`;
        }).join("")}
      </div>
    `),
    sectionHTML("接下来三个月", renderQuarterGrid(ninety)),
    sectionHTML("接下来三年", renderThreeYearGrid(three)),
    sectionHTML("高杠杆动作", `
      <div class="card">
        <ul class="list">${(data.high_leverage_moves || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
    `),
    sectionHTML("风险控制", `
      <div class="card">
        <ul class="list">${(data.risk_controls || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
    `),
    sectionHTML("结论", `<div class="card"><div>${escapeHtml(data.closing || "")}</div></div>`),
  ].join("");
}

function renderQuarterGrid(data) {
  const entries = [
    ["career", "事业 / 工作"],
    ["study", "学业 / 认知"],
    ["family", "家庭"],
    ["love", "爱情"],
    ["relationships", "人际关系"],
    ["health", "健康"],
    ["wealth", "财运"],
    ["hobbies", "兴趣爱好"],
  ];

  return `<div class="subgrid">${entries.map(([key, label]) => renderCategoryCard(label, data[key] || {})).join("")}</div>`;
}

function renderCategoryCard(title, value) {
  return `
    <div class="card">
      <h4>${escapeHtml(title)}</h4>
      <div>${escapeHtml(value.trend || "")}</div>
      ${value.advantages?.length ? `<div class="field-label">优势</div>${renderChipRow(value.advantages)}` : ""}
      ${value.risks?.length ? `<div class="field-label">风险</div>${renderChipRow(value.risks)}` : ""}
      ${value.control_plan?.length ? `<div class="field-label">控制 / 预案</div>${renderChipRow(value.control_plan)}` : ""}
      ${value.best_actions?.length ? `<div class="field-label">动作</div>${renderChipRow(value.best_actions)}` : ""}
    </div>
  `;
}

function renderThreeYearGrid(data) {
  const entries = [
    ["year_1", "第 1 年"],
    ["year_2", "第 2 年"],
    ["year_3", "第 3 年"],
  ];
  return `
    <div class="subgrid">
      ${entries.map(([key, label]) => {
        const item = data[key] || {};
        return `
          <div class="card">
            <h4>${escapeHtml(label)}</h4>
            <div class="keyline">${escapeHtml(item.theme || "")}</div>
            <div>${escapeHtml(item.career || "")}</div>
            <div>${escapeHtml(item.study || "")}</div>
            <div>${escapeHtml(item.family || "")}</div>
            <div>${escapeHtml(item.love || "")}</div>
            <div>${escapeHtml(item.relationships || "")}</div>
            <div>${escapeHtml(item.health || "")}</div>
            <div>${escapeHtml(item.wealth || "")}</div>
          </div>
        `;
      }).join("")}
    </div>
    ${data.cross_year_trends?.length ? `<div class="card"><h4>跨年趋势</h4>${renderChipRow(data.cross_year_trends)}</div>` : ""}
  `;
}

function renderFriendsResult(data) {
  return [
    sectionHTML("原则", `
      <div class="card">
        <ul class="list">${(data.overall_principles || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
    `),
    sectionHTML("逐人分析", `
      <div class="stack">
        ${(data.people || []).map((person) => `
          <article class="card">
            <h4>${escapeHtml(person.name || "朋友")}</h4>
            <div>${escapeHtml(person.profile || "")}</div>
            <div>${escapeHtml(person.dynamics || "")}</div>
            ${renderChipRow(person.symbolic_reading || [])}
            <div>${escapeHtml(person.best_interaction_style || "")}</div>
            ${person.recommended_next_steps?.length ? `
              <div class="field-label">推荐步骤</div>
              <div class="stack">
                ${person.recommended_next_steps.map((step) => `
                  <div class="card">
                    <div><strong>时机：</strong>${escapeHtml(step.timing || "")}</div>
                    <div><strong>场景：</strong>${escapeHtml(step.setting || "")}</div>
                    <div><strong>动作：</strong>${escapeHtml(step.action || "")}</div>
                    <div><strong>原因：</strong>${escapeHtml(step.why || "")}</div>
                  </div>
                `).join("")}
              </div>
            ` : ""}
            ${person.watchouts?.length ? `<div class="field-label">风险</div>${renderChipRow(person.watchouts)}` : ""}
            <div>${escapeHtml(person.mutual_benefit_positioning || "")}</div>
            ${person.do_not_do?.length ? `<div class="field-label">不要做</div>${renderChipRow(person.do_not_do)}` : ""}
          </article>
        `).join("")}
      </div>
    `),
    sectionHTML("整体策略", `
      <div class="card">
        <ul class="list">${(data.cross_person_strategy || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
    `),
    sectionHTML("接下来 7 天", `
      <div class="card">
        <ul class="list">${(data.next_7_days || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
    `),
    sectionHTML("接下来 30 天", `
      <div class="card">
        <ul class="list">${(data.next_30_days || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
    `),
    sectionHTML("结论", `<div class="card"><div>${escapeHtml(data.closing || "")}</div></div>`),
  ].join("");
}

function sectionHTML(title, body) {
  return `
    <section class="section">
      <h3>${escapeHtml(title)}</h3>
      ${body}
    </section>
  `;
}

function renderChipRow(items) {
  const chips = (items || []).filter(Boolean).map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("");
  return chips ? `<div class="chip-row">${chips}</div>` : "";
}

function badge(text, tone) {
  return `<span class="status-chip ${tone || ""}">${escapeHtml(text)}</span>`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[ch]));
}

function syncResultLoading(message) {
  elements.resultMeta.innerHTML = badge("DeepSeek 请求中", "warn");
  elements.resultBody.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function showError(error) {
  const text = error instanceof Error ? error.message : String(error);
  elements.resultMeta.innerHTML = badge("DeepSeek 请求失败", "bad");
  elements.resultBody.innerHTML = renderErrorDetails(error, text);
}

function renderErrorDetails(error, fallbackMessage) {
  const code = error && typeof error === "object" ? error.code || "" : "";
  const category = error && typeof error === "object" ? error.category || "" : "";
  const detail = error && typeof error === "object" ? error.detail || "" : "";
  const remedy = error && typeof error === "object" ? error.remedy || "" : "";
  const retryable = error && typeof error === "object" && typeof error.retryable === "boolean" ? error.retryable : null;
  const httpStatus = error && typeof error === "object" ? error.httpStatus || error.status || "" : "";
  const diagnostics = error && typeof error === "object" ? error.diagnostics || null : null;

  const chips = [
    code ? badge(code, "muted") : "",
    category ? badge(category, "muted") : "",
    httpStatus ? badge(`HTTP ${httpStatus}`, "muted") : "",
    retryable === true ? badge("可重试", "good") : retryable === false ? badge("不可重试", "warn") : "",
  ].filter(Boolean).join("");

  return `
    <div class="stack">
      <section class="section">
        <h3>失败详情</h3>
        <div class="card error-card">
          <h4>${escapeHtml(fallbackMessage || "DeepSeek 请求失败")}</h4>
          ${chips ? `<div class="chip-row">${chips}</div>` : ""}
          ${detail ? `<div><strong>原因：</strong>${escapeHtml(detail)}</div>` : ""}
          ${remedy ? `<div><strong>排查建议：</strong>${escapeHtml(remedy)}</div>` : ""}
          ${renderDiagnostics(diagnostics)}
        </div>
      </section>
    </div>
  `;
}

function renderDiagnostics(diagnostics) {
  if (!diagnostics || typeof diagnostics !== "object") {
    return "";
  }
  const entries = Object.entries(diagnostics).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!entries.length) {
    return "";
  }
  return `
    <div class="field-label">诊断信息</div>
    <div class="card diagnostic-card">
      <ul class="list">
        ${entries.map(([key, value]) => `<li><strong>${escapeHtml(formatDiagnosticKey(key))}：</strong>${escapeHtml(formatDiagnosticValue(value))}</li>`).join("")}
      </ul>
    </div>
  `;
}

function formatDiagnosticKey(key) {
  return String(key)
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .trim();
}

function formatDiagnosticValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

async function syncHealth() {
  try {
    const response = await fetch(apiURL("/api/health"));
    const data = await response.json();
    if (!data.ok) throw new Error("health not ok");
    if (data.accessCodeRequired) {
      elements.apiStatus.textContent = data.deepseekConfigured ? "DeepSeek 已接入，访问码保护中" : "访问码保护中";
      elements.apiStatus.className = `status-chip ${data.deepseekConfigured ? "warn" : "bad"}`;
    } else {
      elements.apiStatus.textContent = data.deepseekConfigured ? "DeepSeek 已接入" : "DeepSeek 未配置";
      elements.apiStatus.className = `status-chip ${data.deepseekConfigured ? "good" : "warn"}`;
    }
    elements.modelStatus.textContent = `模型 ${data.model || "-"}`;
    if (data.accessCodeRequired && !accessCode) {
      openAccessCodeDialog("当前站点已启用访问码保护，请先输入访问码。");
    }
  } catch {
    elements.apiStatus.textContent = "后端未连接";
    elements.apiStatus.className = "status-chip bad";
    elements.modelStatus.textContent = "模型 -";
  }
}
