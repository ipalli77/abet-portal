"use strict";

function filterIndicators() {
  const outcome = document.querySelector("#outcome-select");
  const indicators = document.querySelector("#indicator-select");
  if (!outcome || !indicators) return;
  let firstVisible = null;
  let placeholder = null;
  for (const option of indicators.options) {
    if (!option.value) {
      placeholder = option;
      option.hidden = false;
      option.disabled = true;
      continue;
    }
    const visible = option.dataset.outcome === outcome.value;
    option.hidden = !visible;
    option.disabled = !visible;
    if (visible && !firstVisible) firstVisible = option;
  }
  if (indicators.selectedOptions.length === 0 || indicators.selectedOptions[0].disabled) {
    if (placeholder) indicators.value = "";
    else if (firstVisible) firstVisible.selected = true;
  }
}

function filterAnalysisIndicators() {
  const outcome = document.querySelector("#analysis-outcome");
  const indicators = document.querySelector("select[name='indicator_id']");
  if (!outcome || !indicators) return;
  for (const option of indicators.options) {
    if (!option.value) continue;
    const visible = !outcome.value || option.dataset.outcome === outcome.value;
    option.hidden = !visible;
    option.disabled = !visible;
  }
  if (indicators.selectedOptions.length && indicators.selectedOptions[0].disabled) indicators.value = "";
}

function showRubric() {
  const select = document.querySelector("#rubric-select");
  if (!select) return;
  document.querySelectorAll("[data-rubric-group]").forEach((group) => {
    group.hidden = group.dataset.rubricGroup !== select.value;
    group.querySelectorAll("input").forEach((input) => { input.disabled = group.hidden; });
  });
  checkScoreTotal();
}

function checkScoreTotal() {
  const sample = document.querySelector("#sample-size");
  const message = document.querySelector("#score-check");
  const visible = document.querySelector("[data-rubric-group]:not([hidden])");
  if (!sample || !message || !visible) return;
  const total = [...visible.querySelectorAll("input")].reduce((sum, input) => sum + (Number(input.value) || 0), 0);
  const expected = Number(sample.value) || 0;
  message.textContent = expected ? `${total} of ${expected} students allocated` : `${total} students allocated — enter a sample size`;
  message.className = `score-check ${expected && total === expected ? "good" : "bad"}`;
}

function formatPercent(value) {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function checkEpanTotal() {
  const distribution = document.querySelector("[data-epan-distribution]");
  const message = document.querySelector("#epan-total-message");
  if (!distribution || !message) return true;
  const inputs = [...distribution.querySelectorAll("input[type='number']")];
  if (!inputs.length) return true;

  const completed = inputs.every((input) => input.value.trim() !== "");
  const values = inputs.map((input) => Number(input.value));
  const finite = values.every((value) => Number.isFinite(value));
  const inRange = finite && values.every((value) => value >= 0 && value <= 100);
  const total = finite ? values.reduce((sum, value) => sum + value, 0) : 0;
  const isExact = completed && inRange && Math.abs(total - 100) < 0.000001;
  let validationMessage = "";

  if (!completed) {
    validationMessage = "Enter a percentage for all four EPAN categories.";
    message.textContent = `${validationMessage} Current total: ${formatPercent(total)}%.`;
  } else if (!finite) {
    validationMessage = "Enter a valid percentage in every EPAN category.";
    message.textContent = validationMessage;
  } else if (!inRange) {
    validationMessage = "Every EPAN percentage must be between 0% and 100%.";
    message.textContent = `${validationMessage} Current total: ${formatPercent(total)}%.`;
  } else if (!isExact) {
    const difference = 100 - total;
    const direction = difference > 0 ? "Add" : "Remove";
    validationMessage = `The EPAN percentages must total exactly 100%. Current total: ${formatPercent(total)}%.`;
    message.textContent = `${validationMessage} ${direction} ${formatPercent(Math.abs(difference))}%.`;
  } else {
    message.textContent = `Total: ${formatPercent(total)}% — ready to save.`;
  }

  message.className = `score-check epan-total-message ${isExact ? "good" : "bad"}`;
  distribution.classList.toggle("invalid", !isExact);
  inputs[0].setCustomValidity(validationMessage);
  return isExact;
}

function setupCourseCampusAccessForms() {
  document.querySelectorAll("[data-course-campus-access-form]").forEach((form) => {
    const group = form.querySelector("[data-course-campus-access]");
    const checkboxes = [...form.querySelectorAll("input[name='course_campus_pairs']")];
    const message = form.querySelector("[data-course-campus-validation]");
    if (!group || !checkboxes.length || !message) return;

    function updateAccessSummary(showError = false) {
      const selected = checkboxes.filter((box) => box.checked);
      const courseIds = new Set(selected.map((box) => box.value.split(":", 1)[0]));
      const valid = selected.length > 0;
      group.classList.toggle("invalid", showError && !valid);
      if (!valid) {
        message.textContent = showError
          ? "Select Edinburg, Brownsville, or both for at least one course."
          : "No course–campus access selected yet.";
        message.className = `course-campus-validation${showError ? " bad" : ""}`;
      } else {
        message.textContent = `${selected.length} approved ${selected.length === 1 ? "combination" : "combinations"} across ${courseIds.size} ${courseIds.size === 1 ? "course" : "courses"}.`;
        message.className = "course-campus-validation good";
      }
      return valid;
    }

    checkboxes.forEach((box) => box.addEventListener("change", () => updateAccessSummary(false)));
    form.addEventListener("submit", (event) => {
      if (!updateAccessSummary(true)) {
        event.preventDefault();
        message.setAttribute("role", "alert");
        message.setAttribute("tabindex", "-1");
        message.focus();
      }
    });
    updateAccessSummary(false);
  });
}

function setupAssessmentCourseCampusScope() {
  const form = document.querySelector("#assessment-form[data-course-campus-scoped]");
  const course = form?.querySelector("#course-select");
  const campus = form?.querySelector("#campus-select");
  const help = form?.querySelector("[data-course-campus-help]");
  if (!form || !course || !campus || !help) return;

  const courseOptions = [...course.options].filter((option) => option.value);
  const campusOptions = [...campus.options].filter((option) => option.value);
  const allowedCampuses = (option) => (option?.dataset.allowedCampuses || "").split("|").filter(Boolean);
  const resetCourses = () => courseOptions.forEach((option) => {
    option.disabled = false;
    option.hidden = false;
  });
  const resetCampuses = () => campusOptions.forEach((option) => {
    option.disabled = false;
    option.hidden = false;
  });

  function explainScope() {
    const selectedCourse = course.selectedOptions[0];
    const courseName = selectedCourse?.value ? selectedCourse.textContent.split("·", 1)[0].trim() : "";
    const approved = allowedCampuses(selectedCourse);
    if (selectedCourse?.value && campus.value) {
      help.textContent = `${courseName} at ${campus.value} is within your approved access.`;
    } else if (selectedCourse?.value) {
      help.textContent = `${courseName} is approved for ${approved.join(" and ") || "no campus"}. Choose one of those campuses.`;
    } else if (campus.value) {
      help.textContent = `Showing only courses you may access at ${campus.value}.`;
    } else {
      help.textContent = "Choose a campus or course; the other list will show only approved combinations.";
    }
  }

  function constrainCoursesToCampus() {
    resetCourses();
    if (campus.value) {
      courseOptions.forEach((option) => {
        const permitted = allowedCampuses(option).includes(campus.value);
        option.disabled = !permitted;
        option.hidden = !permitted;
      });
      if (course.selectedOptions[0]?.disabled) course.value = "";
    }
    if (!course.value) resetCampuses();
    explainScope();
  }

  function constrainCampusesToCourse() {
    resetCampuses();
    const selectedCourse = course.selectedOptions[0];
    if (selectedCourse?.value) {
      const approved = allowedCampuses(selectedCourse);
      campusOptions.forEach((option) => {
        const permitted = approved.includes(option.value);
        option.disabled = !permitted;
        option.hidden = !permitted;
      });
      if (campus.selectedOptions[0]?.disabled) campus.value = "";
    }
    if (!campus.value) resetCourses();
    explainScope();
  }

  campus.addEventListener("change", constrainCoursesToCampus);
  course.addEventListener("change", constrainCampusesToCourse);
  if (campus.value) constrainCoursesToCampus();
  if (course.value) constrainCampusesToCourse();
  explainScope();
}

function setupAnalysisCourseCampusScope() {
  const form = document.querySelector("[data-analysis-course-campus-scoped]");
  if (!form) return;
  const campusBoxes = [...form.querySelectorAll("input[name='campus']")];
  const courseBoxes = [...form.querySelectorAll("input[name='course_id'][data-allowed-campuses]")];
  const message = form.querySelector("[data-analysis-course-campus-help]");
  if (!campusBoxes.length || !courseBoxes.length) return;

  function updateAvailableCourses() {
    const selectedCampuses = campusBoxes.filter((box) => box.checked).map((box) => box.value);
    let availableCount = 0;
    courseBoxes.forEach((box) => {
      const approved = (box.dataset.allowedCampuses || "").split("|").filter(Boolean);
      const available = selectedCampuses.some((campusName) => approved.includes(campusName));
      box.disabled = !available;
      box.closest("label")?.classList.toggle("unavailable", !available);
      if (!available) box.checked = false;
      else availableCount += 1;
    });
    if (message) {
      if (!selectedCampuses.length) message.textContent = "Select at least one campus to make its approved courses available.";
      else message.textContent = `${availableCount} ${availableCount === 1 ? "course is" : "courses are"} available for ${selectedCampuses.join(" and ")}.`;
    }
  }

  campusBoxes.forEach((box) => box.addEventListener("change", updateAvailableCourses));
  updateAvailableCourses();
}

function setupAssessmentFilterCourseCampusScope() {
  const form = document.querySelector("[data-assessment-filter-course-campus-scoped]");
  const campus = form?.querySelector("#assessment-filter-campus");
  const course = form?.querySelector("#assessment-filter-course");
  if (!form || !campus || !course) return;
  const courseOptions = [...course.options].filter((option) => option.value);

  function updateCourseOptions() {
    courseOptions.forEach((option) => {
      const approved = (option.dataset.allowedCampuses || "").split("|").filter(Boolean);
      const available = !campus.value || approved.includes(campus.value);
      option.disabled = !available;
      option.hidden = !available;
    });
    if (course.selectedOptions[0]?.disabled) course.value = "";
  }

  campus.addEventListener("change", updateCourseOptions);
  updateCourseOptions();
}

function setupFacultyPreviewScope() {
  const form = document.querySelector("[data-faculty-preview-scope-form]");
  if (!form) return;
  const campusBoxes = [...form.querySelectorAll("input[name='campus']")];
  const message = form.querySelector("[data-faculty-preview-scope-validation]");
  if (!campusBoxes.length || !message) return;

  function updateScopeStatus(showError = false) {
    const selected = campusBoxes.filter((box) => box.checked).map((box) => box.value);
    const valid = selected.length > 0;
    if (valid) {
      message.textContent = `Faculty View will include ${selected.join(" and ")}.`;
      message.className = "faculty-view-scope-validation good";
    } else {
      message.textContent = showError
        ? "Select Edinburg, Brownsville, or both before continuing."
        : "No campus selected yet.";
      message.className = `faculty-view-scope-validation${showError ? " bad" : ""}`;
    }
    return valid;
  }

  campusBoxes.forEach((box) => box.addEventListener("change", () => updateScopeStatus(false)));
  form.querySelector("[data-faculty-preview-both]")?.addEventListener("click", () => {
    campusBoxes.forEach((box) => { box.checked = true; });
    updateScopeStatus(false);
  });
  form.querySelector("[data-faculty-preview-clear]")?.addEventListener("click", () => {
    campusBoxes.forEach((box) => { box.checked = false; });
    updateScopeStatus(false);
  });
  form.addEventListener("submit", (event) => {
    if (!updateScopeStatus(true)) {
      event.preventDefault();
      message.setAttribute("role", "alert");
      message.setAttribute("tabindex", "-1");
      message.focus();
    }
  });
  updateScopeStatus(false);
}

function setupBulkApproval() {
  const form = document.querySelector("[data-bulk-approval-form]");
  if (!form) return;

  const modes = [...form.querySelectorAll("input[name='selection_mode']")];
  const recordBoxes = [...form.querySelectorAll("[data-bulk-record-checkbox]")];
  const courseBoxes = [...form.querySelectorAll("[data-bulk-course-checkbox]")];
  const recordMaster = form.querySelector("[data-bulk-record-master]");
  const recordControls = form.querySelector("[data-bulk-record-controls]");
  const courseControls = form.querySelector("[data-bulk-course-controls]");
  const allControls = form.querySelector("[data-bulk-all-controls]");
  const status = form.querySelector("[data-bulk-selection-status]");
  const submitButton = form.querySelector("[data-bulk-approve-button]");
  if (!modes.length || !status || !submitButton) return;

  const currentMode = () => modes.find((radio) => radio.checked)?.value || "records";
  const checkedRecords = () => recordBoxes.filter((box) => box.checked);
  const checkedCourses = () => courseBoxes.filter((box) => box.checked);

  function selectMode(mode) {
    const radio = modes.find((item) => item.value === mode);
    if (radio) radio.checked = true;
  }

  function updateBulkApproval() {
    const mode = currentMode();
    const records = checkedRecords();
    const courses = checkedCourses();

    if (recordControls) recordControls.hidden = mode !== "records";
    if (courseControls) courseControls.hidden = mode !== "courses";
    if (allControls) allControls.hidden = mode !== "all";
    recordBoxes.forEach((box) => { box.disabled = mode !== "records"; });
    courseBoxes.forEach((box) => { box.disabled = mode !== "courses"; });
    if (recordMaster) {
      recordMaster.disabled = mode !== "records";
      recordMaster.checked = records.length > 0 && records.length === recordBoxes.length;
      recordMaster.indeterminate = records.length > 0 && records.length < recordBoxes.length;
    }

    let ready = false;
    if (mode === "records") {
      ready = records.length > 0;
      status.textContent = ready
        ? `${records.length} ${records.length === 1 ? "record" : "records"} selected.`
        : "No records selected.";
      submitButton.textContent = "Approve selected records";
    } else if (mode === "courses") {
      ready = courses.length > 0;
      const courseIds = new Set(courses.map((box) => box.value));
      const matchingRecords = recordBoxes.filter((box) => courseIds.has(box.dataset.courseId)).length;
      status.textContent = ready
        ? `${courses.length} ${courses.length === 1 ? "course" : "courses"} selected · ${matchingRecords} eligible ${matchingRecords === 1 ? "record" : "records"} in this view.`
        : "No courses selected.";
      submitButton.textContent = "Approve selected courses";
    } else {
      ready = recordBoxes.length > 0;
      status.textContent = `${recordBoxes.length} eligible ${recordBoxes.length === 1 ? "record" : "records"} match the current filters.`;
      submitButton.textContent = "Approve all matching records";
    }
    submitButton.disabled = !ready;
  }

  modes.forEach((radio) => radio.addEventListener("change", updateBulkApproval));
  recordBoxes.forEach((box) => box.addEventListener("change", updateBulkApproval));
  courseBoxes.forEach((box) => box.addEventListener("change", updateBulkApproval));
  recordMaster?.addEventListener("change", () => {
    selectMode("records");
    recordBoxes.forEach((box) => { box.checked = recordMaster.checked; });
    updateBulkApproval();
  });

  form.querySelector("[data-bulk-select-records]")?.addEventListener("click", () => {
    selectMode("records");
    recordBoxes.forEach((box) => { box.checked = true; });
    updateBulkApproval();
  });
  form.querySelector("[data-bulk-clear-records]")?.addEventListener("click", () => {
    recordBoxes.forEach((box) => { box.checked = false; });
    updateBulkApproval();
  });
  form.querySelector("[data-bulk-select-courses]")?.addEventListener("click", () => {
    selectMode("courses");
    courseBoxes.forEach((box) => { box.checked = true; });
    updateBulkApproval();
  });
  form.querySelector("[data-bulk-clear-courses]")?.addEventListener("click", () => {
    courseBoxes.forEach((box) => { box.checked = false; });
    updateBulkApproval();
  });

  form.addEventListener("submit", (event) => {
    updateBulkApproval();
    if (submitButton.disabled) {
      event.preventDefault();
      status.textContent = currentMode() === "courses"
        ? "Select at least one course before approving."
        : "Select at least one record before approving.";
      status.setAttribute("role", "alert");
      status.setAttribute("tabindex", "-1");
      status.focus();
      return;
    }

    const mode = currentMode();
    let scope;
    if (mode === "records") {
      const count = checkedRecords().length;
      scope = `${count} selected ${count === 1 ? "record" : "records"}`;
    } else if (mode === "courses") {
      const courses = checkedCourses().map((box) => box.closest("label")?.querySelector("strong")?.textContent.trim()).filter(Boolean);
      scope = `eligible records for ${courses.join(", ")}`;
    } else {
      scope = `all ${recordBoxes.length} eligible records matching the current filters`;
    }
    const confirmed = window.confirm(
      `Approve ${scope}? Draft records will be submitted and approved in one action. This approval will be recorded in the audit history.`,
    );
    if (!confirmed) event.preventDefault();
  });

  updateBulkApproval();
}

document.addEventListener("DOMContentLoaded", () => {
  setupCourseCampusAccessForms();
  setupAssessmentCourseCampusScope();
  setupAssessmentFilterCourseCampusScope();
  setupAnalysisCourseCampusScope();
  setupFacultyPreviewScope();
  const outcome = document.querySelector("#outcome-select");
  if (outcome) { outcome.addEventListener("change", filterIndicators); filterIndicators(); }
  const analysisOutcome = document.querySelector("#analysis-outcome");
  if (analysisOutcome) {
    analysisOutcome.addEventListener("change", filterAnalysisIndicators);
    filterAnalysisIndicators();
  }
  const rubric = document.querySelector("#rubric-select");
  if (rubric) { rubric.addEventListener("change", showRubric); showRubric(); }
  const form = document.querySelector("#assessment-form");
  if (form) {
    if (document.querySelector("[data-epan-distribution]")) {
      form.addEventListener("input", checkEpanTotal);
      form.addEventListener("submit", (event) => {
        if (!checkEpanTotal()) {
          event.preventDefault();
          document.querySelector("#epan-total-message")?.focus();
        }
      });
      document.querySelector("[data-epan-distribution] input")?.addEventListener("invalid", () => {
        const message = document.querySelector("#epan-total-message");
        if (message) message.setAttribute("role", "alert");
      });
      checkEpanTotal();
    } else {
      form.addEventListener("input", checkScoreTotal);
    }
  }
  document.querySelectorAll("[data-print]").forEach((button) => button.addEventListener("click", () => window.print()));
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
  const courseBoxes = [...document.querySelectorAll(".course-choice-grid input[type='checkbox']")];
  document.querySelectorAll("[data-course-select-all]").forEach((button) => {
    button.addEventListener("click", () => courseBoxes.forEach((box) => { if (!box.disabled) box.checked = true; }));
  });
  document.querySelectorAll("[data-course-clear]").forEach((button) => {
    button.addEventListener("click", () => courseBoxes.forEach((box) => { box.checked = false; }));
  });
  setupBulkApproval();
});
