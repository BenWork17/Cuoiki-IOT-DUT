/* Logic dashboard: hỏi /api/signals mỗi giây, hiện ba tín hiệu trạng thái học
 * (có mặt / điện thoại / danh tính) kèm tuổi tín hiệu, và điều khiển phần
 * "Người học" (thêm người, chọn người đang học, xoá, đọc giờ học).
 *
 * Nguyên tắc bắt buộc (spec v3 §5.16):
 * - Màu không bao giờ là kênh truyền đạt duy nhất: mỗi dòng có biểu tượng và
 *   nhãn chữ đi kèm.
 * - Tín hiệu cũ (fresh = false) phải hiện "chưa có dữ liệu mới", KHÔNG được
 *   lặp lại kết luận cũ như vừa đo được. Đây là yêu cầu chống hiểu nhầm.
 * - Không nạp gì từ Internet; không lưu dữ liệu người vào localStorage.
 */
(function () {
  "use strict";

  var STATUS_INTERVAL_MS = 1000;
  var ENROLL_POLL_MS = 1000;

  var el = function (id) {
    return document.getElementById(id);
  };

  var els = {
    signsCard: el("status-card"),
    updated: el("updated"),
    stale: el("stale-warning"),
    muteBtn: el("mute-btn"),
    muteIcon: el("mute-icon"),
    muteText: el("mute-text"),
    calibrateBtn: el("calibrate-btn"),
    message: el("action-message"),
    ptzButtons: Array.prototype.slice.call(
      document.querySelectorAll("[data-ptz-direction]")
    ),
    camera: el("camera-stream"),
    cameraNote: el("camera-note"),
    addBtn: el("add-person-btn"),
    addForm: el("add-person-form"),
    addSubmit: el("add-person-submit"),
    addCancel: el("add-person-cancel"),
    nameInput: el("new-person-name"),
    pickBtn: el("pick-person-btn"),
    peopleListWrap: el("people-list-wrap"),
    peopleList: el("people-list"),
    peopleEmpty: el("people-list-empty"),
    selected: el("selected-person"),
    enrollPanel: el("enroll-panel"),
    enrollName: el("enroll-name"),
    enrollStep: el("enroll-step"),
    enrollSamples: el("enroll-samples"),
    enrollCancel: el("enroll-cancel-btn"),
    schedule: el("schedule-summary")
  };

  var peopleEnabled =
    (document.body.dataset.peopleEnabled === "1") ||
    (els.signsCard && els.signsCard.dataset.peopleEnabled === "1");

  var enrollTimer = null;
  var enrollId = null;

  /* ---- Thẻ "Trạng thái học" ---------------------------------------- */

  /* Biểu tượng + nhãn chữ đi cùng màu: màu không bao giờ là kênh duy nhất. */
  var PRESENCE_TEXT = { present: "Có mặt", absent: "Vắng mặt" };
  var PRESENCE_ICON = { present: "●", absent: "○" };
  var PHONE_TEXT = { none: "Không dùng", use: "Đang dùng" };
  var PHONE_ICON = { none: "✓", use: "!" };
  var IDENTITY_TEXT = {
    MATCH: "Đúng người",
    MISMATCH: "Khác người",
    UNKNOWN: "Chưa nhận ra"
  };
  var IDENTITY_ICON = { MATCH: "✓", MISMATCH: "✕", UNKNOWN: "?" };

  /* Câu bắt buộc khi tín hiệu không còn mới (§5.16). Không được thay bằng
   * kết luận cũ: người dùng sẽ tưởng hệ thống vừa đo. */
  var NO_FRESH_TEXT = "Chưa có dữ liệu mới";

  function formatAge(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    var value = Number(seconds);
    if (!isFinite(value)) return "—";
    return "cập nhật " + value.toFixed(1).replace(".", ",") + " s trước";
  }

  /* Hàm thuần: quyết định chữ của một dòng tín hiệu. Tách khỏi DOM để test
   * được bằng cách đọc file và để nhánh "dữ liệu cũ" có đúng một chỗ. */
  function signalPresentation(kind, signal) {
    var data = signal || {};
    if (data.fresh !== true) {
      return { text: NO_FRESH_TEXT, icon: "…", state: "stale", age: "—" };
    }
    var state = String(data.state || "").toLowerCase();
    if (kind === "presence") {
      var known = Object.prototype.hasOwnProperty.call(PRESENCE_TEXT, state);
      return {
        text: known ? PRESENCE_TEXT[state] : "Chưa rõ",
        icon: known ? PRESENCE_ICON[state] : "•",
        state: known ? state : "unknown",
        age: formatAge(data.age_s)
      };
    }
    if (kind === "phone") {
      var phoneKnown = Object.prototype.hasOwnProperty.call(PHONE_TEXT, state);
      return {
        text: phoneKnown ? PHONE_TEXT[state] : "Chưa rõ",
        icon: phoneKnown ? PHONE_ICON[state] : "•",
        state: phoneKnown ? state : "unknown",
        age: formatAge(data.age_s)
      };
    }
    var upper = String(data.state || "").toUpperCase();
    var identityKnown = Object.prototype.hasOwnProperty.call(
      IDENTITY_TEXT,
      upper
    );
    var label = identityKnown ? IDENTITY_TEXT[upper] : "Chưa rõ";
    if (identityKnown && upper === "MATCH" && data.name) {
      label += " (" + data.name + ")";
    }
    return {
      text: label,
      icon: identityKnown ? IDENTITY_ICON[upper] : "•",
      state: identityKnown ? upper.toLowerCase() : "unknown",
      age: formatAge(data.age_s)
    };
  }

  function renderSign(kind, signal) {
    var row = el("sign-" + kind);
    if (!row) return;
    var presentation = signalPresentation(kind, signal);
    row.dataset.fresh = signal && signal.fresh === true ? "true" : "false";
    row.dataset.state = presentation.state;
    var icon = el("sign-" + kind + "-icon");
    var text = el("sign-" + kind + "-text");
    var age = el("sign-" + kind + "-age");
    if (icon) icon.textContent = presentation.icon;
    if (text) text.textContent = presentation.text;
    if (age) age.textContent = presentation.age;
  }

  function renderSignals(data) {
    ["presence", "phone", "identity"].forEach(function (kind) {
      renderSign(kind, data[kind] || null);
    });
  }

  function showMessage(text) {
    if (!els.message) return;
    els.message.textContent = text;
    els.message.hidden = !text;
    if (text) {
      window.clearTimeout(showMessage.timer);
      showMessage.timer = window.setTimeout(function () {
        els.message.hidden = true;
      }, 6000);
    }
  }

  function renderStatus(data) {
    if (els.stale) els.stale.hidden = !data.stale;
    if (els.updated) {
      els.updated.textContent = data.stale
        ? "Dữ liệu đã cũ — vòng lặp giám sát có thể đã dừng."
        : "Cập nhật liên tục · " + new Date().toLocaleTimeString("vi-VN");
    }

    var muted = !!data.muted;
    if (els.muteBtn) els.muteBtn.dataset.muted = muted ? "1" : "0";
    if (els.muteIcon) els.muteIcon.textContent = muted ? "🔇" : "🔊";
    if (els.muteText) {
      els.muteText.textContent = muted
        ? "Bật lại tiếng cảnh báo"
        : "Tắt tiếng cảnh báo";
    }
  }

  function fetchStatus() {
    fetch("/api/status", { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(renderStatus)
      .catch(function () {
        if (els.updated) els.updated.textContent = "Mất kết nối tới máy chủ.";
        if (els.stale) els.stale.hidden = false;
      });
  }

  function fetchSignals() {
    if (!peopleEnabled) return;
    fetch("/api/signals", { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(renderSignals)
      .catch(function () {
        /* Không có dữ liệu: mọi dòng phải rơi về "chưa có dữ liệu mới"
         * thay vì giữ kết luận cũ trên màn hình. */
        renderSignals({ presence: null, phone: null, identity: null });
      });
  }

  /* ---- Camera trực tiếp ------------------------------------------- */

  /* Ảnh MJPEG sống trong một request dài: khi camera hỏng hoặc mất mạng,
   * trình duyệt bắn 'error' một lần rồi thôi. Không tự thử lại thì ảnh
   * vỡ đứng nguyên mãi. Thử lại bằng cách gắn lại src (kèm mốc thời gian
   * để trình duyệt không dùng bản cache).
   *
   * Khung hình chỉ đi qua bộ nhớ phía server và tới trình duyệt — không
   * ghi ra đĩa, không lưu lịch sử (spec v2 §11.5). */
  var CAMERA_RETRY_MS = 5000;
  var cameraRetryTimer = null;

  function setCameraNote(text) {
    if (els.cameraNote) els.cameraNote.textContent = text;
  }

  function cameraFailed() {
    if (!els.camera) return;
    els.camera.hidden = true;
    setCameraNote(
      "Không nhận được hình từ camera. Có thể camera mất kết nối hoặc " +
        "chương trình giám sát đã dừng. Đang tự thử lại…"
    );
    window.clearTimeout(cameraRetryTimer);
    cameraRetryTimer = window.setTimeout(function () {
      if (els.cameraNote) {
        els.cameraNote.textContent = "Đang thử kết nối lại tới camera…";
      }
      els.camera.src = "/stream?t=" + Date.now();
    }, CAMERA_RETRY_MS);
  }

  function setupCamera() {
    if (!els.camera) return; // stream đang tắt: template đã hiện lời nhắn
    els.camera.addEventListener("load", function () {
      window.clearTimeout(cameraRetryTimer);
      els.camera.hidden = false;
      setCameraNote("");
    });
    els.camera.addEventListener("error", cameraFailed);
    /* Ảnh đã có src trong template; nếu server trả 403/không có response
     * thì 'error' vẫn bắn và ta hiện đúng thông báo ở trên. */
    if (!els.camera.complete) setCameraNote("Đang kết nối tới camera…");
  }

  /* ---- Lệnh ------------------------------------------------------- */

  function setBusy(button, busy, busyText) {
    if (!button) return;
    if (busy) {
      button.dataset.originalText = button.textContent;
      button.disabled = true;
      button.textContent = busyText;
    } else {
      button.disabled = false;
      if (button.dataset.originalText) {
        button.textContent = button.dataset.originalText;
      }
    }
  }

  function readJson(response) {
    return response.json().catch(function () {
      return null;
    });
  }

  /* Lỗi dịch vụ luôn là {"ok": false, "message": "..."} tiếng Việt; giữ
   * nguyên câu đó để người dùng biết phải làm gì. */
  function failText(response, data) {
    if (data && typeof data.message === "string" && data.message) {
      return data.message;
    }
    if (response && response.status === 503) {
      return "Tính năng người học chưa được bật trong phiên chạy này.";
    }
    return "Máy chủ không xử lý được yêu cầu này.";
  }

  if (els.muteBtn) {
    els.muteBtn.addEventListener("click", function () {
      fetch("/api/mute", { method: "POST" })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          showMessage(data.message || "Đã đổi trạng thái tiếng.");
          fetchStatus();
        })
        .catch(function () {
          showMessage("Không gửi được lệnh tắt/bật tiếng.");
        });
    });
  }

  if (els.calibrateBtn) {
    els.calibrateBtn.addEventListener("click", function () {
      setBusy(els.calibrateBtn, true, "Đang gửi…");
      fetch("/api/calibrate", { method: "POST" })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          showMessage(data.message || "Đã gửi yêu cầu hiệu chỉnh.");
        })
        .catch(function () {
          showMessage("Không gửi được yêu cầu hiệu chỉnh.");
        })
        .finally(function () {
          setBusy(els.calibrateBtn, false);
          els.calibrateBtn.textContent = "Hiệu chỉnh lại";
        });
    });
  }

  /* ---- Xoay camera (PTZ) ------------------------------------------ */

  /* Bấm giữ = gửi liên tiếp từng bước ngắn cho tới khi nhả. Backend chặn mỗi
   * lệnh tối đa 3 giây, nên chia nhỏ ở đây vẫn an toàn và phản hồi nhả tay
   * nhanh hơn. Một cú bấm cũng đi qua đúng đường này với một bước. */
  var PTZ_STEP_S = 0.4;
  var ptzHold = null;

  function ptzFailText(response, data) {
    /* Backend luôn trả {"ok": false, "message": "..."} bằng tiếng Việt; giữ
     * nguyên câu đó để người dùng biết phải sửa gì (bật ONVIF, đặt mật khẩu…).
     * Vẫn có câu dự phòng nếu một proxy nào đó trả về thứ khác. */
    if (data && typeof data.message === "string" && data.message) {
      return data.message;
    }
    if (data && typeof data.error === "string" && data.error) {
      return data.error;
    }
    if (response && response.status === 404) {
      return "Máy chủ này không hỗ trợ điều khiển camera.";
    }
    return "Camera không nhận lệnh xoay.";
  }

  function requestPtz(direction, duration) {
    return fetch("/api/ptz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ direction: direction, duration: duration })
    })
      .then(function (response) {
        return response
          .json()
          .catch(function () {
            return null;
          })
          .then(function (data) {
            if (!response.ok || !data || data.ok !== true) {
              showMessage(ptzFailText(response, data));
              return false;
            }
            showMessage(data.message || "Đã xoay camera.");
            return true;
          });
      })
      .catch(function () {
        showMessage("Không gửi được lệnh xoay camera. Kiểm tra kết nối mạng.");
        return false;
      });
  }

  function setPtzBusy(busy) {
    els.ptzButtons.forEach(function (button) {
      button.classList.toggle("btn--busy", busy);
      button.setAttribute("aria-busy", busy ? "true" : "false");
    });
  }

  function stopHold() {
    if (!ptzHold) return;
    ptzHold.held = false;
    ptzHold = null;
    setPtzBusy(false);
  }

  function startHold(direction) {
    if (ptzHold) return;
    var state = { held: true, direction: direction };
    ptzHold = state;
    setPtzBusy(true);

    function step() {
      if (!state.held) return;
      requestPtz(direction, PTZ_STEP_S).then(function (ok) {
        if (!state.held) return;
        if (!ok) {
          /* Lỗi (PTZ chưa cấu hình, mất mạng): dừng ngay, đừng thử lại liên
           * tục — người dùng đã thấy thông báo giải thích. */
          if (ptzHold === state) stopHold();
          return;
        }
        step();
      });
    }

    step();
  }

  els.ptzButtons.forEach(function (button) {
    var direction = button.dataset.ptzDirection;

    button.addEventListener("pointerdown", function (event) {
      /* Chuột phải / bút cảm ứng thứ hai: bỏ qua. Chặn luôn việc trình duyệt
       * bôi chữ khi giữ lâu. */
      if (event.pointerType === "mouse" && event.button !== 0) return;
      event.preventDefault();
      if (button.setPointerCapture) {
        try {
          button.setPointerCapture(event.pointerId);
        } catch (err) {
          /* Không bắt được con trỏ vẫn xoay được; chỉ mất khả năng nhận
           * pointerup ngoài nút, nên vẫn gắn thêm pointerleave bên dưới. */
        }
      }
      startHold(direction);
    });

    ["pointerup", "pointercancel", "pointerleave"].forEach(function (name) {
      button.addEventListener(name, stopHold);
    });

    /* Bàn phím: Enter/Space phát sinh click với detail = 0. Cú click do chuột
     * cũng có detail = 1 nhưng đã được xử lý ở pointerdown, nên bỏ qua để
     * không xoay hai lần cho một cú bấm. */
    button.addEventListener("click", function (event) {
      if (event.detail === 0) {
        requestPtz(direction, PTZ_STEP_S);
      }
    });
  });

  /* Chốt an toàn: nếu tab mất focus khi đang giữ (đổi ứng dụng trên điện
   * thoại), nhả tay sẽ không bao giờ tới nơi — phải tự dừng. */
  window.addEventListener("blur", stopHold);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stopHold();
  });

  /* ---- Người học -------------------------------------------------- */

  function setSelected(personId, people) {
    if (!els.selected) return;
    if (personId === null || personId === undefined) {
      els.selected.textContent = "Chưa chọn người đang học.";
      return;
    }
    var match = (people || []).filter(function (person) {
      return person.id === personId;
    })[0];
    els.selected.textContent = match
      ? "Đang chọn: " + match.name
      : "Đang chọn người học có mã " + personId + ".";
  }

  function renderPeople(data) {
    var people = (data && data.people) || [];
    setSelected(data ? data.selected : null, people);
    if (!els.peopleList) return;
    els.peopleList.innerHTML = "";
    people.forEach(function (person) {
      var item = document.createElement("li");
      item.className = "people__item";

      var name = document.createElement("span");
      name.className = "people__name";
      name.textContent = person.name;
      item.appendChild(name);

      var choose = document.createElement("button");
      choose.type = "button";
      choose.className = "btn btn--quiet people__pick";
      choose.textContent = "Chọn";
      choose.addEventListener("click", function () {
        selectPerson(person.id);
      });
      item.appendChild(choose);

      /* Xoá là hành động không hoàn tác được: luôn hỏi lại trước khi gọi. */
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn--quiet people__delete";
      remove.textContent = "Xoá";
      remove.addEventListener("click", function () {
        if (!window.confirm("Xoá người học \"" + person.name + "\"?")) return;
        deletePerson(person.id);
      });
      item.appendChild(remove);

      els.peopleList.appendChild(item);
    });
    if (els.peopleEmpty) els.peopleEmpty.hidden = people.length > 0;
  }

  function fetchPeople() {
    if (!peopleEnabled) return;
    fetch("/api/people", { cache: "no-store" })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok) {
            showMessage(failText(res, data));
            return;
          }
          renderPeople(data);
        });
      })
      .catch(function () {
        showMessage("Không tải được danh sách người học.");
      });
  }

  function selectPerson(personId) {
    fetch("/api/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ person_id: personId })
    })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok || !data || data.ok !== true) {
            showMessage(failText(res, data));
            return;
          }
          showMessage(data.message || "Đã chọn người đang học.");
          fetchPeople();
        });
      })
      .catch(function () {
        showMessage("Không gửi được lựa chọn người đang học.");
      });
  }

  function deletePerson(personId) {
    fetch("/api/people/" + encodeURIComponent(personId), { method: "DELETE" })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok || !data || data.ok !== true) {
            showMessage(failText(res, data));
            return;
          }
          showMessage(data.message || "Đã xoá người học.");
          fetchPeople();
        });
      })
      .catch(function () {
        showMessage("Không xoá được người học.");
      });
  }

  var ENROLL_STATE_TEXT = {
    running: "Đang thu mẫu…",
    done: "Đã đăng ký xong.",
    cancelled: "Đã huỷ phiên đăng ký.",
    failed: "Đăng ký thất bại."
  };

  function stopEnrollPolling() {
    window.clearTimeout(enrollTimer);
    enrollTimer = null;
  }

  function finishEnroll(state, message) {
    stopEnrollPolling();
    enrollId = null;
    if (els.enrollPanel) els.enrollPanel.hidden = true;
    showMessage(message || ENROLL_STATE_TEXT[state] || "Đã xong.");
    if (state === "done") fetchPeople();
  }

  function renderEnroll(data) {
    var state = String(data.state || "failed");
    if (state !== "running") {
      finishEnroll(state, data.error || ENROLL_STATE_TEXT[state]);
      return;
    }
    if (els.enrollStep) {
      els.enrollStep.textContent =
        "Bước " + (Number(data.step_index) + 1) + ": " + (data.step_name || "—");
    }
    if (els.enrollSamples) {
      els.enrollSamples.textContent =
        "Mẫu hợp lệ: " + Number(data.samples || 0) + " / " +
        Number(data.samples_needed || 0);
    }
  }

  function pollEnroll() {
    if (!enrollId) return;
    var current = enrollId;
    fetch("/api/enroll/" + encodeURIComponent(current), { cache: "no-store" })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (enrollId !== current) return; // đã huỷ/đổi phiên
          if (!res.ok || !data) {
            finishEnroll("failed", failText(res, data));
            return;
          }
          renderEnroll(data);
          if (data.state === "running") {
            enrollTimer = window.setTimeout(pollEnroll, ENROLL_POLL_MS);
          }
        });
      })
      .catch(function () {
        if (enrollId !== current) return;
        finishEnroll("failed", "Mất kết nối khi đang theo dõi đăng ký.");
      });
  }

  function startEnroll(name) {
    fetch("/api/people", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name })
    })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if ((res.status !== 201 && !res.ok) || !data) {
            showMessage(failText(res, data));
            return;
          }
          enrollId = data.enroll_id || null;
          if (!enrollId) {
            showMessage("Máy chủ không trả về mã phiên đăng ký.");
            return;
          }
          if (els.addForm) els.addForm.hidden = true;
          if (els.enrollPanel) els.enrollPanel.hidden = false;
          if (els.enrollName) els.enrollName.textContent = name;
          if (els.enrollStep) {
            els.enrollStep.textContent =
              "Bước 1: " + ((data.steps || [])[0] || "Nhìn thẳng");
          }
          if (els.enrollSamples) els.enrollSamples.textContent = "Mẫu hợp lệ: 0";
          pollEnroll();
        });
      })
      .catch(function () {
        showMessage("Không bắt đầu được phiên đăng ký.");
      });
  }

  function cancelEnroll() {
    if (!enrollId) return;
    var current = enrollId;
    fetch("/api/enroll/" + encodeURIComponent(current) + "/cancel", {
      method: "POST"
    })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok || !data || data.ok !== true) {
            showMessage(failText(res, data));
            return;
          }
          finishEnroll("cancelled", data.message);
        });
      })
      .catch(function () {
        finishEnroll("failed", "Không huỷ được phiên đăng ký.");
      });
  }

  function renderSchedule(data) {
    if (!els.schedule) return;
    var schedule = (data && data.schedule) || null;
    if (!schedule) {
      els.schedule.textContent = "Giờ học: chưa đọc được.";
      return;
    }
    if (schedule.enabled === false) {
      els.schedule.textContent = "Giờ học: không giới hạn giờ.";
      return;
    }
    var windows = schedule.windows || [];
    if (!windows.length) {
      els.schedule.textContent = "Giờ học: chưa đặt khung giờ nào.";
      return;
    }
    var dayNames = {
      mon: "thứ 2",
      tue: "thứ 3",
      wed: "thứ 4",
      thu: "thứ 5",
      fri: "thứ 6",
      sat: "thứ 7",
      sun: "chủ nhật"
    };
    var parts = windows.map(function (window) {
      var days = (window.days || []).map(function (day) {
        return dayNames[day] || day;
      });
      return days.join(", ") + " " + window.start + "–" + window.end;
    });
    els.schedule.textContent = "Giờ học: " + parts.join("; ");
  }

  function fetchSchedule() {
    if (!peopleEnabled) return;
    fetch("/api/schedule", { cache: "no-store" })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok) {
            if (els.schedule) {
              els.schedule.textContent = failText(res, data);
            }
            return;
          }
          renderSchedule(data);
        });
      })
      .catch(function () {
        if (els.schedule) els.schedule.textContent = "Giờ học: mất kết nối.";
      });
  }

  if (peopleEnabled) {
    if (els.addBtn) {
      els.addBtn.addEventListener("click", function () {
        if (els.addForm) els.addForm.hidden = !els.addForm.hidden;
        if (els.addForm && !els.addForm.hidden && els.nameInput) {
          els.nameInput.focus();
        }
      });
    }
    if (els.addCancel) {
      els.addCancel.addEventListener("click", function () {
        if (els.addForm) els.addForm.hidden = true;
      });
    }
    if (els.addForm) {
      els.addForm.addEventListener("submit", function (event) {
        event.preventDefault();
        var name = els.nameInput ? els.nameInput.value.trim() : "";
        if (!name) {
          showMessage("Hãy nhập tên người học.");
          return;
        }
        setBusy(els.addSubmit, true, "Đang bắt đầu…");
        startEnroll(name);
        window.setTimeout(function () {
          setBusy(els.addSubmit, false);
        }, 500);
      });
    }
    if (els.pickBtn) {
      els.pickBtn.addEventListener("click", function () {
        if (els.peopleListWrap) {
          els.peopleListWrap.hidden = !els.peopleListWrap.hidden;
        }
        fetchPeople();
      });
    }
    if (els.enrollCancel) {
      els.enrollCancel.addEventListener("click", cancelEnroll);
    }
  }

  /* Cập nhật mỗi giây một lần. Dữ liệu người không bao giờ vào localStorage:
   * đây là thông tin sinh trắc học, không phải sở thích giao diện. */
  fetchStatus();
  setupCamera();
  fetchSignals();
  fetchPeople();
  fetchSchedule();
  window.setInterval(fetchStatus, STATUS_INTERVAL_MS);
  window.setInterval(fetchSignals, STATUS_INTERVAL_MS);
})();
