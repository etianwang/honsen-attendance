(function () {
  const dataEl = document.getElementById("app-data");
  const EMPLOYEES = JSON.parse(dataEl.dataset.employees);
  const VALUES = JSON.parse(dataEl.dataset.values);
  const CTX = {
    year: dataEl.dataset.year,
    month: dataEl.dataset.month,
    day: dataEl.dataset.day,
    // apiBase points at this day's endpoints (bulk/individual/photo);
    // jumpBase is the same prefix minus the trailing /{day}, used to build
    // prev/next/jump-to-date links. Team pages set these to
    // /attendance/{team_id}[...]; the admin "全体录入" page (no team_id in
    // its URL) sets them to /admin/attendance[...] — same JS either way.
    apiBase: dataEl.dataset.apiBase,
    jumpBase: dataEl.dataset.jumpBase,
  };

  const valuesById = new Map(VALUES.map((v) => [String(v.id), v]));

  // Composite mode: the admin "全体录入" page sends a team_id on every
  // employee record because one person can appear more than once (身兼数职,
  // one row per team they're on). Row keys become "team_id:employee_id" and
  // requests carry both. Single-team pages never send team_id, so this
  // whole branch is a no-op there and behaviour is unchanged.
  const COMPOSITE = EMPLOYEES.some((e) => e.team_id !== undefined);
  function rowKey(emp) {
    return COMPOSITE ? `${emp.team_id}:${emp.id}` : String(emp.id);
  }

  const state = new Map(EMPLOYEES.map((e) => [rowKey(e), Object.assign({}, e)]));

  function genUUID() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function composeDisplay(amCode, pmCode, ot) {
    let base;
    if (!amCode && !pmCode) base = "";
    else if (amCode === pmCode) base = amCode;
    else base = [amCode, pmCode].filter(Boolean).join("-");
    if (ot && base) base += "-加班";
    else if (ot) base = "加班";
    return base;
  }

  function baseUrl() {
    return CTX.apiBase;
  }

  const queue = new AttendanceQueue({
    storageKey: `pending_${CTX.apiBase.replace(/\//g, "_")}`,
    onCountChange: (n) => {
      const el = document.getElementById("sync-banner");
      if (n > 0) {
        el.style.display = "";
        el.textContent = `待同步 ${n} 条（会自动重试，不用管它）`;
      } else {
        el.style.display = "none";
      }
    },
  });

  function populateSelect(sel, { includeBlank } = { includeBlank: true }) {
    sel.innerHTML = "";
    if (includeBlank) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "—";
      sel.appendChild(opt);
    }
    const groups = { worksite: "上班 / 工地", nonwork: "非上班" };
    for (const catKey of ["worksite", "nonwork"]) {
      const group = document.createElement("optgroup");
      group.label = groups[catKey];
      VALUES.filter((v) => v.category === catKey).forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v.id;
        opt.textContent = v.code;
        group.appendChild(opt);
      });
      sel.appendChild(group);
    }
  }

  // ---- bulk toolbar ----
  const scopeSel = document.getElementById("bulk-scope");
  const valueWrap = document.getElementById("bulk-value-wrap");
  const valueSel = document.getElementById("bulk-value");
  const noteWrap = document.getElementById("bulk-note-wrap");
  const noteInput = document.getElementById("bulk-note");
  populateSelect(valueSel);

  function refreshBulkVisibility() {
    const isOt = scopeSel.value === "ot";
    valueWrap.style.display = isOt ? "none" : "";
    const val = valuesById.get(valueSel.value);
    noteWrap.style.display = !isOt && val && val.requires_note ? "" : "none";
  }
  scopeSel.addEventListener("change", refreshBulkVisibility);
  valueSel.addEventListener("change", refreshBulkVisibility);
  refreshBulkVisibility();

  // ---- two-step wizard cards driving the hidden bulk-scope/bulk-value
  // selects above — clicking a card just sets the hidden select's value and
  // fires a native "change" event, so refreshBulkVisibility() and the apply
  // handler below (which only ever reads scopeSel.value/valueSel.value)
  // don't need to know the picker UI changed at all.
  function wireCardPicker(container, hiddenSelect) {
    function syncActive() {
      container.querySelectorAll("[data-value]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.value === hiddenSelect.value);
      });
    }
    container.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-value]");
      if (!btn) return;
      hiddenSelect.value = btn.dataset.value;
      hiddenSelect.dispatchEvent(new Event("change"));
      syncActive();
    });
    return syncActive;
  }

  const scopeCardsSync = wireCardPicker(document.getElementById("scope-cards"), scopeSel);
  scopeCardsSync();

  const valueCardsContainer = document.getElementById("value-cards");
  const valueCardsSync = wireCardPicker(valueCardsContainer, valueSel);

  const GROUP_ICONS = {
    worksite:
      '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="1"/><path d="M9 21v-4h6v4M8 7h2M14 7h2M8 11h2M14 11h2M8 15h2M14 15h2"/></svg>',
    nonwork:
      '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 18v-6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v6"/><path d="M3 18v2M21 18v2"/><path d="M3 12v-3a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v3"/></svg>',
  };

  function renderValueCards() {
    valueCardsContainer.innerHTML = "";
    const groups = { worksite: "上班 / 工地", nonwork: "非上班" };
    for (const catKey of ["worksite", "nonwork"]) {
      const catValues = VALUES.filter((v) => v.category === catKey);
      if (!catValues.length) continue;
      const label = document.createElement("div");
      label.className = "wizard-group-label";
      label.innerHTML = `${GROUP_ICONS[catKey]}<span>${groups[catKey]}</span>`;
      valueCardsContainer.appendChild(label);
      const row = document.createElement("div");
      row.className = "wizard-cards";
      catValues.forEach((v) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `wizard-card wizard-card-${catKey}`;
        btn.dataset.value = String(v.id);
        btn.textContent = v.code;
        row.appendChild(btn);
      });
      valueCardsContainer.appendChild(row);
    }
    valueCardsSync();
  }
  renderValueCards();

  const selectAll = document.getElementById("select-all");
  selectAll.addEventListener("change", () => {
    document.querySelectorAll(".row-select").forEach((cb) => (cb.checked = selectAll.checked));
  });
  // Default: checked unless the employee left ("回国") the day before.
  let anyDefaultExcluded = false;
  document.querySelectorAll(".row-select").forEach((cb) => {
    const emp = state.get(cb.dataset.id);
    cb.checked = !emp.default_excluded;
    if (emp.default_excluded) anyDefaultExcluded = true;
  });
  selectAll.checked = !anyDefaultExcluded;

  document.getElementById("bulk-apply-btn").addEventListener("click", () => {
    const ids = Array.from(document.querySelectorAll(".row-select:checked")).map((cb) => cb.dataset.id);
    if (ids.length === 0) {
      alert("先勾选人员");
      return;
    }
    const scope = scopeSel.value;
    const valueId = scope === "ot" ? null : parseInt(valueSel.value, 10) || null;
    if (scope !== "ot" && !valueId) {
      alert("请选择一个值");
      return;
    }
    const val = valueId ? valuesById.get(String(valueId)) : null;
    const note = val && val.requires_note ? noteInput.value.trim() : null;

    ids.forEach((id) => {
      const emp = state.get(id);
      if (scope === "full") {
        emp.am_value_id = valueId;
        emp.am_note = note;
        emp.pm_value_id = valueId;
        emp.pm_note = note;
      } else if (scope === "am") {
        emp.am_value_id = valueId;
        emp.am_note = note;
      } else if (scope === "pm") {
        emp.pm_value_id = valueId;
        emp.pm_note = note;
      } else if (scope === "ot") {
        emp.evening_overtime = true;
      }
      renderRow(id);
    });
    updateBanner();

    const bulkBody = {
      idempotency_key: genUUID(),
      scope,
      value_id: valueId,
      note,
      ot_value: true,
    };
    if (COMPOSITE) {
      bulkBody.targets = ids.map((id) => {
        const [tid, eid] = id.split(":");
        return { team_id: parseInt(tid, 10), employee_id: parseInt(eid, 10) };
      });
    } else {
      bulkBody.employee_ids = ids.map((id) => parseInt(id, 10));
    }
    queue.enqueue(`${baseUrl()}/bulk`, bulkBody);
  });

  // ---- per-row rendering ----
  function renderRow(id) {
    const emp = state.get(id);
    const tr = document.querySelector(`tr[data-employee-id="${id}"]`);
    if (!tr) return;
    const amCode = emp.am_value_id ? valuesById.get(String(emp.am_value_id)).code : null;
    const pmCode = emp.pm_value_id ? valuesById.get(String(emp.pm_value_id)).code : null;
    const text = composeDisplay(amCode, pmCode, emp.evening_overtime) || "未填写";
    const complete = !!emp.am_value_id && !!emp.pm_value_id;
    tr.querySelector(".row-preview").textContent = text;
    const completeCell = tr.querySelector(".row-complete");
    completeCell.innerHTML = complete
      ? '<span class="pill ok">完成</span>'
      : '<span class="pill nonwork">未完成</span>';
    tr.classList.toggle("filled", complete);
  }

  function updateBanner() {
    const missing = [];
    state.forEach((emp) => {
      const parts = [];
      if (!emp.am_value_id) parts.push("上午");
      if (!emp.pm_value_id) parts.push("下午");
      if (parts.length) missing.push(`${emp.name}（${parts.join("/")}未分配）`);
    });
    const banner = document.getElementById("incomplete-banner");
    if (missing.length) {
      banner.style.display = "";
      banner.textContent = "未分配工作地点：" + missing.join("，");
    } else {
      banner.style.display = "none";
    }
  }

  state.forEach((_, id) => renderRow(id));
  updateBanner();

  // ---- individual edit modal ----
  const modal = document.getElementById("edit-modal");
  const editAm = document.getElementById("edit-am");
  const editPm = document.getElementById("edit-pm");
  const editAmNoteWrap = document.getElementById("edit-am-note-wrap");
  const editAmNote = document.getElementById("edit-am-note");
  const editPmNoteWrap = document.getElementById("edit-pm-note-wrap");
  const editPmNote = document.getElementById("edit-pm-note");
  const editOt = document.getElementById("edit-ot");
  populateSelect(editAm);
  populateSelect(editPm);

  let editingId = null;

  function refreshEditNoteVisibility() {
    const amVal = valuesById.get(editAm.value);
    const pmVal = valuesById.get(editPm.value);
    editAmNoteWrap.style.display = amVal && amVal.requires_note ? "" : "none";
    editPmNoteWrap.style.display = pmVal && pmVal.requires_note ? "" : "none";
  }
  editAm.addEventListener("change", refreshEditNoteVisibility);
  editPm.addEventListener("change", refreshEditNoteVisibility);

  function openEdit(id) {
    editingId = id;
    const emp = state.get(id);
    document.getElementById("edit-modal-name").textContent = emp.name;
    editAm.value = emp.am_value_id || "";
    editPm.value = emp.pm_value_id || "";
    editAmNote.value = emp.am_note || "";
    editPmNote.value = emp.pm_note || "";
    editOt.checked = !!emp.evening_overtime;
    refreshEditNoteVisibility();
    modal.style.display = "flex";
  }

  document.querySelectorAll(".row-name").forEach((cell) => {
    cell.addEventListener("click", () => {
      const tr = cell.closest("tr");
      openEdit(tr.dataset.employeeId);
    });
  });

  document.getElementById("edit-cancel-btn").addEventListener("click", () => {
    modal.style.display = "none";
    editingId = null;
  });

  document.getElementById("edit-save-btn").addEventListener("click", () => {
    if (!editingId) return;
    const emp = state.get(editingId);
    const amValueId = parseInt(editAm.value, 10) || null;
    const pmValueId = parseInt(editPm.value, 10) || null;
    const amVal = amValueId ? valuesById.get(String(amValueId)) : null;
    const pmVal = pmValueId ? valuesById.get(String(pmValueId)) : null;

    emp.am_value_id = amValueId;
    emp.am_note = amVal && amVal.requires_note ? editAmNote.value.trim() : null;
    emp.pm_value_id = pmValueId;
    emp.pm_note = pmVal && pmVal.requires_note ? editPmNote.value.trim() : null;
    emp.evening_overtime = editOt.checked;

    renderRow(editingId);
    updateBanner();

    const editUrl = COMPOSITE ? `${baseUrl()}/${editingId.replace(":", "/")}` : `${baseUrl()}/${editingId}`;
    queue.enqueue(editUrl, {
      idempotency_key: genUUID(),
      am_value_id: emp.am_value_id,
      am_note: emp.am_note,
      pm_value_id: emp.pm_value_id,
      pm_note: emp.pm_note,
      evening_overtime: emp.evening_overtime,
    });

    modal.style.display = "none";
    editingId = null;
  });

  const jumpDateEl = document.getElementById("jump-date");
  if (jumpDateEl) {
    jumpDateEl.addEventListener("change", function () {
      const v = this.value.split("-");
      location.href = `${CTX.jumpBase}/${parseInt(v[0], 10)}/${parseInt(v[1], 10)}/${parseInt(v[2], 10)}`;
    });
  }

  // ---- daily group photos (up to MAX per day, no fixed clock-in/out slots —
  // each upload just adds one more to the filmstrip, in whatever order they
  // actually get taken that day) ----
  const photoBase = CTX.apiBase;
  const photoInput = document.getElementById("photo-input");
  const photoUploadStatus = document.getElementById("photo-upload-status");

  if (photoInput) {
    photoInput.addEventListener("change", async () => {
      if (!photoInput.files[0]) return;
      const fd = new FormData();
      fd.append("photo", photoInput.files[0]);
      photoUploadStatus.style.display = "";
      photoUploadStatus.textContent = "上传中…";
      try {
        const resp = await fetch(`${photoBase}/photo`, { method: "POST", body: fd });
        if (!resp.ok) {
          const data = await resp.json().catch(() => ({}));
          throw new Error(data.detail || "http " + resp.status);
        }
        location.reload();
      } catch (err) {
        photoUploadStatus.textContent = "上传失败：" + err.message;
        photoInput.value = "";
      }
    });
  }

  document.querySelectorAll(".photo-retry-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const photoId = btn.dataset.photoId;
      btn.textContent = "同步中…";
      btn.disabled = true;
      try {
        await fetch(`${photoBase}/photo/${photoId}/retry-sync`, { method: "POST" });
      } finally {
        location.reload();
      }
    });
  });

  document.querySelectorAll(".photo-delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("确定要删除这张照片吗？")) return;
      const photoId = btn.dataset.photoId;
      btn.disabled = true;
      try {
        const resp = await fetch(`${photoBase}/photo/${photoId}/delete`, { method: "POST" });
        if (!resp.ok) throw new Error("http " + resp.status);
        const data = await resp.json();
        if (data.warning) alert(data.warning);
      } catch (err) {
        alert("删除失败，请检查网络后重试");
      } finally {
        location.reload();
      }
    });
  });

  const previewModal = document.getElementById("photo-preview-modal");
  const previewImg = document.getElementById("photo-preview-img");
  const previewClose = document.getElementById("photo-preview-close");

  function openPhotoPreview(url) {
    previewImg.src = url;
    previewModal.style.display = "flex";
  }
  function closePhotoPreview() {
    previewModal.style.display = "none";
    previewImg.src = "";
  }

  document.querySelectorAll(".photo-preview-link").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      openPhotoPreview(link.href);
    });
  });
  if (previewClose) previewClose.addEventListener("click", closePhotoPreview);
  if (previewModal) {
    previewModal.addEventListener("click", (e) => {
      if (e.target === previewModal) closePhotoPreview();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && previewModal && previewModal.style.display !== "none") {
      closePhotoPreview();
    }
  });
})();
