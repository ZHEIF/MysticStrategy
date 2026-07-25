"use strict";

const STORAGE_KEY = "quan_model_battle_mvp_v1";
const REQUEST_TIMEOUT_MS = 70000;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

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
  } catch (error) {
    state.results.self = buildLocalSelfFallback(payload, error);
  } finally {
    currentMode = "self";
    state.mode = "self";
    saveState();
    renderMode("self");
    renderResult();
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
  } catch (error) {
    state.results.friends = buildLocalFriendsFallback(payload, error);
  } finally {
    currentMode = "friends";
    state.mode = "friends";
    saveState();
    renderMode("friends");
    renderResult();
    setBusy(false);
  }
}

async function postJSON(path, payload) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeout);
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function setBusy(isBusy) {
  elements.analyzeSelf.disabled = isBusy;
  elements.analyzeFriends.disabled = isBusy;
  elements.addFriend.disabled = isBusy;
}

function buildLocalSelfFallback(payload, error) {
  const name = payload.name || "你";
  const birthPlace = payload.birth_place || "出生地";
  const plans = payload.recent_plans || "近期主要规划";
  const experiences = payload.major_experiences || "阶段性变化";
  const block = (title, trend) => ({
    trend,
    advantages: [
      `把${title}拆成周计划，先完成最可见的一步。`,
      "把外部反馈当作校准信号，而不是否定信号。",
    ],
    risks: [
      "目标过多时容易同时开太多口子。",
      "情绪波动会拖慢连续性。",
    ],
    control_plan: [
      "把风险写成触发条件，提前设好止损线。",
      "每周固定一次复盘，避免靠感觉推进。",
    ],
    best_actions: [
      `围绕${title}只保留一个主任务和一个备选任务。`,
      "把重要沟通前置成书面摘要，减少误差。",
    ],
  });

  return {
    ok: true,
    source: "local-fallback",
    model: "browser-local",
    timestamp: new Date().toISOString(),
    warning: error instanceof Error ? error.message : String(error || "backend unavailable"),
    analysis: {
      overview: {
        headline: `${name} 的总基调是先定方向，再定节奏。`,
        core_archetype: `更适合把 ${birthPlace} 和当前规划转成稳定的行动锚点。`,
        key_strengths: ["信息吸收快，适合做整合型判断。", "一旦节奏固定，执行力会明显提升。"],
        main_pressure_points: ["对不确定性的耐受度会影响推进速度。", "多个方向并行时容易分散火力。"],
        bottom_line: "先稳住一条主线，再让其他领域围绕主线协同。",
      },
      self_analysis: {
        nature: `你给出的经历更像是“${experiences.slice(0, 80)}”，这会让你对趋势很敏感，也更需要有节奏地筛选信息。`,
        pattern: `当前主线可以围绕“${plans.slice(0, 80)}”做收束，先布局，再放大。`,
        supporting_models: [
          { model: "奇门遁甲", read: "先找门，再找局，不要一上来就全面铺开。" },
          { model: "五行六运", read: "当前更适合补节奏和补短板，而不是一味追求强刺激。" },
          { model: "幸福数字密码", read: "高频重复动作比一次性爆发更有收益。" },
          { model: "占星术", read: "更需要可复盘的轨道，而不是完全靠临场灵感。" },
        ],
      },
      next_90_days: {
        career: block("事业/工作", "未来三个月适合低噪音推进，先把最能见效的任务打穿。"),
        study: block("学业/认知", "认知提升来自持续输入和定期输出，而不是大量囤积。"),
        family: block("家庭", "家庭面宜保持低摩擦沟通，先稳情绪，再谈支持。"),
        love: block("爱情", "感情面更看重真实、稳定和一致性，急推进反而容易失衡。"),
        relationships: block("人际关系", "人际面适合筛选高质量互动，把资源给值得长期协作的人。"),
        health: block("健康", "身体面要把作息、运动和饮食做成固定流程。"),
        wealth: block("财运", "财务面以稳健现金流和风险边界优先，先守再攻。"),
        hobbies: block("兴趣爱好", "兴趣面适合把喜欢的东西变成长期可持续的小节奏。"),
      },
      next_3_years: {
        year_1: { theme: "先搭骨架", career: "建立稳定产出结构。", study: "建立方法论和复盘习惯。", family: "以稳定沟通为主。", love: "识别真正适配的人。", relationships: "先做圈层筛选。", health: "重在作息和节奏。", wealth: "重在止损和储备。" },
        year_2: { theme: "再扩边界", career: "在稳定主线外增加第二增长点。", study: "把方法外化成工具或流程。", family: "边界更清楚，协作更顺。", love: "进入更现实的检验期。", relationships: "合作关系开始分层。", health: "身体管理更系统。", wealth: "现金流更重视结构优化。" },
        year_3: { theme: "形成风格", career: "个人风格和位置感更明确。", study: "认知模型开始稳定输出。", family: "支持方式更成熟。", love: "更适合稳定、互相尊重的连接。", relationships: "人际网络趋向少而精。", health: "健康更可控。", wealth: "财富更依赖长期纪律。" },
        cross_year_trends: ["主线会越来越清晰，但前提是愿意删掉次要噪音。", "每次阶段变化，都要先复盘再出手。"],
      },
      high_leverage_moves: ["把最近最重要的 1-2 个目标写成周度行动清单。", "每周固定一次复盘。", "先建立稳定的睡眠、运动和工作节奏。"],
      risk_controls: ["超过三条的并行目标都要重新排序。", "遇到焦虑时先减速，不要在情绪最高点做重大决定。"],
      closing: "这是浏览器本地兜底结果。后端或 DeepSeek 恢复后，会自动使用更完整的模型分析。",
    },
  };
}

function buildLocalFriendsFallback(payload, error) {
  const people = (payload.people || []).map((person) => {
    const name = person.name || "某位朋友";
    return {
      name,
      profile: `${name} 当前更像是在推进“${(person.recent_plans || "自己的目标").slice(0, 70)}”，关系上适合公开、低压、可持续地相处。`,
      dynamics: `你对 ${name} 的关系倾向是“${person.relationship_tendency || "保持清晰方向"}”，建议把关系定位成透明协作，而不是隐性操控。`,
      symbolic_reading: [
        "奇门遁甲：先看场，再看门，别急着上强度。",
        "五行六运：先补稳态，再谈放大。",
        "幸福数字密码：稳定重复比一次性拉满更重要。",
        "占星术：先对齐节奏，再对齐期待。",
        "塔罗牌：先看对方是否愿意继续牌局。",
        "孙子兵法/博弈论：长期互利优先，短期压制会损伤信任。",
      ],
      best_interaction_style: "自然、直接、礼貌、节奏稳定，少试探，多确认。",
      recommended_next_steps: [
        {
          timing: "在对方有空且压力不高的时候",
          setting: "公开、轻松、低噪音的场景",
          action: "用清晰、尊重的方式表达你的想法，并给对方明确退出空间。",
          why: "这样能减少误读，也更容易形成真正互利的关系。",
        },
      ],
      watchouts: ["不要把推进关系变成逼近关系。", "不要在对方忙乱或情绪低谷时施压。"],
      mutual_benefit_positioning: "把关系放在互相支持、信息透明、边界清晰的位置上。",
      do_not_do: ["不要绕过对方的明确边界。", "不要用隐瞒意图或制造亏欠感的方式推进。"],
    };
  });

  return {
    ok: true,
    source: "local-fallback",
    model: "browser-local",
    timestamp: new Date().toISOString(),
    warning: error instanceof Error ? error.message : String(error || "backend unavailable"),
    analysis: {
      overall_principles: [
        payload.my_relationship_tendency ? `你的关系倾向是：${payload.my_relationship_tendency}。` : "",
        "先把意图说清楚，再谈推进。",
        "所有互动都要保留对方拒绝的余地。",
        "长期关系的核心是互利和稳定，不是压迫和试探。",
      ].filter(Boolean),
      people,
      cross_person_strategy: ["把时间投给愿意双向沟通的人。", "把场景放在公开、轻松、低压力的地方。", "把推进目标拆成小步，不要一次拉太满。"],
      next_7_days: ["先把每个人的关系目标写成一句话。", "优先沟通最自然的那一个人。", "观察反馈后再决定下一步，不要连推。"],
      next_30_days: ["把关系定位和边界校准清楚。", "挑选一到两个适合长期投入的人重点维护。", "把合作与情感需求分开处理，避免混线。"],
      closing: "这是浏览器本地兜底结果。后端或 DeepSeek 恢复后，会自动使用更完整的模型分析。",
    },
  };
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
    badge(source === "deepseek" ? "DeepSeek" : "本地兜底", source === "deepseek" ? "good" : "warn"),
    badge(model, "muted"),
    timestamp ? badge(timestamp, "muted") : "",
    result.warning ? badge("请求失败后已降级", "warn") : "",
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
  elements.resultMeta.innerHTML = badge("请求失败", "bad");
  elements.resultBody.innerHTML = `<div class="empty-state">${escapeHtml(text)}</div>`;
}

async function syncHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    if (!data.ok) throw new Error("health not ok");
    elements.apiStatus.textContent = data.deepseekConfigured ? "DeepSeek 已接入" : "DeepSeek 未配置";
    elements.apiStatus.className = `status-chip ${data.deepseekConfigured ? "good" : "warn"}`;
    elements.modelStatus.textContent = `模型 ${data.model || "-"}`;
  } catch {
    elements.apiStatus.textContent = "后端未连接";
    elements.apiStatus.className = "status-chip bad";
    elements.modelStatus.textContent = "模型 -";
  }
}

function renderResult() {
  const result = currentMode === "self" ? state.results.self : state.results.friends;
  if (!result) {
    elements.resultMeta.innerHTML = "";
    elements.resultBody.innerHTML = '<div class="empty-state">等待输入。</div>';
    return;
  }

  const sourceLabel = result.source === "deepseek" ? "DeepSeek" : "本地兜底";
  const sourceTone = result.source === "deepseek" ? "good" : "warn";
  const timestamp = result.timestamp ? new Date(result.timestamp).toLocaleString("zh-CN") : "";
  elements.resultMeta.innerHTML = [
    badge(sourceLabel, sourceTone),
    badge(result.model || "-", "muted"),
    timestamp ? badge(timestamp, "muted") : "",
    result.warning ? badge("已降级", "warn") : "",
  ].filter(Boolean).join("");

  elements.resultBody.innerHTML = currentMode === "self"
    ? renderSelfResult(result.analysis || {})
    : renderFriendsResult(result.analysis || {});
}
