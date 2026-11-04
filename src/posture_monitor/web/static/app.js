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
    schedule: el("schedule-summary"),
    sessionCard: el("session-card"),
    sessionState: el("session-state"),
    sessionCountdown: el("session-countdown"),
    sessionCountdownLabel: el("session-countdown-label"),
    sessionTrack: el("session-track"),
    sessionFill: el("session-fill"),
    sessionMinutes: el("session-minutes"),
    sessionStart: el("session-start-btn"),
    sessionStop: el("session-stop-btn"),
    voiceCard: el("voice-card"),
    voiceOptions: el("voice-options"),
    voiceStatus: el("voice-status")
  };

  var peopleEnabled =
    (document.body.dataset.peopleEnabled === "1") ||
    (els.signsCard && els.signsCard.dataset.peopleEnabled === "1");

  var enrollTimer = null;
  var enrollId = null;

  /* ---- Thẻ "Trạng thái học" ---------------------------------------- */

  /* Biểu tượng + nhãn chữ đi cùng màu: màu không bao giờ là kênh duy nhất.
   *
   * Khoá của các bảng phải là **đúng giá trị server gửi**, không phải khoá
   * CSS: `presence.py` trả "co_mat"/"vang_mat", còn phone là "dung"/
   * "khong_dung" (xem `people_service.note_phone`). Bản cũ tra "present"/
   * "absent" nên dòng "Có mặt" không bao giờ hiện chữ của mình.
   * Giá trị của bảng *_STATE mới là khoá CSS trong `style.css`; tách riêng
   * để đổi tên phía server không kéo theo đổi giao diện. */
  /* Nhãn dòng đã là "Có mặt"; giá trị nói thêm *điều gì đang xảy ra* thay vì
   * lặp lại đúng hai chữ đó ("Có mặt / Có mặt"). */
  var PRESENCE_TEXT = {
    co_mat: "Đang trong khung hình",
    vang_mat: "Không thấy ai"
  };
  /* Dấu hiệu là ký tự hình học, không phải emoji: emoji bị cấm trên giao
   * diện này (nó đổi hình theo từng hệ điều hành và đọc thành biểu tượng
   * cảm xúc). Màu trạng thái do `data-state` trong style.css quyết định, nên
   * hình dấu hiệu chỉ cần đọc được cùng nhãn chữ bên cạnh. */
  var PRESENCE_ICON = { co_mat: "●", vang_mat: "○" };
  var PRESENCE_STATE = { co_mat: "present", vang_mat: "absent" };
  var PHONE_TEXT = { khong_dung: "Không dùng", dung: "Đang dùng" };
  var PHONE_ICON = { khong_dung: "○", dung: "●" };
  var PHONE_STATE = { khong_dung: "none", dung: "use" };
  var IDENTITY_TEXT = {
    MATCH: "Đúng người",
    MISMATCH: "Khác người",
    UNKNOWN: "Chưa nhận ra"
  };
  var IDENTITY_ICON = { MATCH: "●", MISMATCH: "○", UNKNOWN: "?" };

  /* Câu bắt buộc khi tín hiệu không còn mới (§5.16). Không được thay bằng
   * kết luận cũ: người dùng sẽ tưởng hệ thống vừa đo. */
  var NO_FRESH_TEXT = "Chưa có dữ liệu mới";

  /* Giá trị server gửi mà giao diện không có nhãn cho nó. KHÔNG được im
   * lặng thay bằng "Chưa rõ": như thế một giá trị mới của server (hoặc một
   * lỗi đánh máy) trông y như "chưa đo được" và không ai biết để sửa. Hiện
   * nguyên giá trị thô kèm nhãn đánh dấu; giá trị rỗng thì nói rõ là rỗng. */
  function unknownText(rawState) {
    var shown = rawState === null || rawState === undefined ? "" : String(rawState);
    if (!shown) return "Chưa rõ (server không gửi giá trị)";
    return "Chưa rõ (" + shown + ")";
  }

  function formatAge(seconds) {
    if (seconds === null || seconds === undefined) return "–";
    var value = Number(seconds);
    if (!isFinite(value)) return "–";
    return "cập nhật " + value.toFixed(1).replace(".", ",") + " s trước";
  }

  /* Hàm thuần: quyết định chữ của một dòng tín hiệu. Tách khỏi DOM để test
   * được bằng cách đọc file và để nhánh "dữ liệu cũ" có đúng một chỗ. */
  function signalPresentation(kind, signal) {
    var data = signal || {};
    if (data.fresh !== true) {
      return { text: NO_FRESH_TEXT, icon: "…", state: "stale", age: "–" };
    }
    var state = String(data.state || "").toLowerCase();
    if (kind === "presence") {
      var known = Object.prototype.hasOwnProperty.call(PRESENCE_TEXT, state);
      return {
        text: known ? PRESENCE_TEXT[state] : unknownText(data.state),
        icon: known ? PRESENCE_ICON[state] : "•",
        state: known ? PRESENCE_STATE[state] : "unknown",
        age: formatAge(data.age_s)
      };
    }
    if (kind === "phone") {
      var phoneKnown = Object.prototype.hasOwnProperty.call(PHONE_TEXT, state);
      return {
        text: phoneKnown ? PHONE_TEXT[state] : unknownText(data.state),
        icon: phoneKnown ? PHONE_ICON[state] : "•",
        state: phoneKnown ? PHONE_STATE[state] : "unknown",
        age: formatAge(data.age_s)
      };
    }
    var upper = String(data.state || "").toUpperCase();
    var identityKnown = Object.prototype.hasOwnProperty.call(
      IDENTITY_TEXT,
      upper
    );
    var label = identityKnown ? IDENTITY_TEXT[upper] : unknownText(data.state);
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
      /* Dòng ngắn ở đây, câu giải thích đầy đủ nằm trong thẻ trạng thái: nói
       * cùng một chuyện ở hai chỗ chỉ làm mắt đọc hai lần. */
      els.updated.textContent = data.stale
        ? "Dữ liệu đã cũ"
        : "Cập nhật liên tục · " + new Date().toLocaleTimeString("vi-VN");
    }

    var muted = !!data.muted;
    if (els.muteBtn) {
      /* Nút hiện trạng thái bằng dấu gạch chéo trong SVG và bằng nhãn chữ;
       * `data-muted` chỉ để style.css bật/tắt nét gạch. */
      els.muteBtn.dataset.muted = muted ? "1" : "0";
      els.muteBtn.setAttribute("aria-pressed", muted ? "true" : "false");
    }
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
   * Khung hình chỉ đi qua bộ nhớ phía server và tới trình duyệt, không
   * ghi ra đĩa, không lưu lịch sử (spec v2 §11.5). */
  var CAMERA_RETRY_MS = 5000;
  var cameraRetryTimer = null;

  function setCameraNote(text) {
    if (!els.cameraNote) return;
    els.cameraNote.textContent = text;
    /* Ẩn hẳn khi không có chữ: khối rỗng vẫn giữ padding và cộng thêm chiều
     * cao vào khung hình. */
    els.cameraNote.hidden = !text;
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

  /* ---- Phiên học (bắt đầu / dừng) ---------------------------------- */

  /* Đây là công tắc DUY NHẤT bật model AI. Toàn bộ quyết định "đang chạy hay
   * không" nằm ở máy chủ (StudySession): web chỉ hiển thị và gửi lệnh. Không
   * đoán trạng thái ở client, hai nguồn sự thật cho một câu hỏi "model có
   * đang chạy không" là cách chắc chắn nhất để nút và thực tế lệch nhau.
   *
   * Đếm ngược hiển thị theo `remaining_s` máy chủ trả, trừ dần bằng đồng hồ
   * trình duyệt giữa hai lần hỏi, để số không đứng im 1 giây một nhịp. */
  var sessionEnabled =
    (els.sessionCard && els.sessionCard.dataset.sessionEnabled === "1") ||
    false;
  var SESSION_POLL_MS = 1000;
  var sessionTimer = null;
  /* Mốc {status, at}: số giây còn lại của lần đồng bộ gần nhất và thời điểm
   * (Date.now) nhận được nó. Nhờ vậy giữa hai lần poll vẫn vẽ được số giảm. */
  var sessionBase = null;

  function renderSession(data) {
    if (!data) return;
    var state = String(data.state || "idle");
    var running = state === "running";

    if (els.sessionState) {
      els.sessionState.dataset.running = running ? "1" : "0";
      if (running) {
        els.sessionState.textContent =
          "Đang trong phiên " + Number(data.minutes || 0) + " phút. " +
          "Hệ thống đang theo dõi người học và điện thoại.";
      } else if (state === "finished") {
        els.sessionState.textContent =
          data.finish_text ||
          data.finished_message ||
          "Đã hết giờ học. Bấm “Bắt đầu học” để vào phiên mới.";
      } else {
        els.sessionState.textContent =
          "Chưa bắt đầu. Bấm “Bắt đầu học” để hệ thống theo dõi.";
      }
    }

    if (els.sessionCountdown) {
      els.sessionCountdown.textContent = running
        ? data.ends_in_text || "–"
        : state === "finished"
        ? "00:00"
        : "–";
    }
    if (els.sessionCountdownLabel) {
      els.sessionCountdownLabel.textContent = running
        ? "còn lại"
        : state === "finished"
        ? "đã hết giờ"
        : "";
    }

    if (els.sessionStart) {
      els.sessionStart.disabled = false;
      els.sessionStart.textContent = running
        ? "Bắt đầu lại"
        : "Bắt đầu học";
      /* Đang chạy thì việc duy nhất người dùng làm được là dừng: nút đậm phải
       * là nút đó. Để "Bắt đầu lại" đậm trong khi phiên đang chạy là chỉ sai
       * việc chính. */
      els.sessionStart.classList.toggle("btn--primary", !running);
      els.sessionStart.classList.toggle("btn--quiet", running);
    }
    if (els.sessionStop) {
      els.sessionStop.disabled = !running;
      els.sessionStop.classList.toggle("btn--primary", running);
      els.sessionStop.classList.toggle("btn--quiet", !running);
    }
    if (els.sessionMinutes && running) {
      /* Đang chạy thì khoá ô nhập: đổi số giữa phiên không có tác dụng (máy
       * chủ đã chốt ends_at), để nó sửa được sẽ khiến người dùng tưởng đã
       * đổi thời lượng. Muốn đổi thì bấm "Bắt đầu lại". */
      els.sessionMinutes.disabled = true;
    } else if (els.sessionMinutes) {
      els.sessionMinutes.disabled = false;
    }

    if (running && Number.isFinite(Number(data.remaining_s))) {
      sessionBase = {
        remaining: Number(data.remaining_s),
        at: Date.now(),
        total: Math.max(1, Number(data.minutes) || 0) * 60
      };
    } else {
      sessionBase = null;
    }

    paintSessionBar();
  }

  /* Thanh tiến độ: phần đã trôi qua trên tổng thời lượng. Đây là phần duy
   * nhất của màn hình mang sắc xanh (xem style.css), nên nó chỉ được vẽ khi
   * con số thật sự có nghĩa, ngoài phiên thì để rãnh rỗng, không bịa một
   * thanh "0 %" trông như đang chạy. */
  function paintSessionBar() {
    if (!els.sessionFill) return;
    var ratio = 0;
    if (sessionBase && sessionBase.total > 0) {
      var left = Math.max(
        0,
        sessionBase.remaining - (Date.now() - sessionBase.at) / 1000
      );
      ratio = Math.min(1, Math.max(0, 1 - left / sessionBase.total));
    }
    els.sessionFill.style.width = (ratio * 100).toFixed(2) + "%";
    if (els.sessionTrack) {
      els.sessionTrack.setAttribute(
        "aria-valuenow",
        String(Math.round(ratio * 100))
      );
    }
  }

  /* Vẽ lại số đếm mỗi 250 ms mà không hỏi máy chủ: chỉ trừ đồng hồ trình
   * duyệt. Hỏi máy chủ mỗi 250 ms sẽ đập vào Pi 4 lần/giây cho một con số. */
  function tickSessionCountdown() {
    if (!sessionBase || !els.sessionCountdown) return;
    var passed = (Date.now() - sessionBase.at) / 1000;
    var left = Math.max(0, sessionBase.remaining - passed);
    var total = Math.ceil(left - 1e-9);
    var mm = Math.floor(total / 60);
    var ss = total % 60;
    els.sessionCountdown.textContent =
      (mm < 10 ? "0" + mm : String(mm)) + ":" + (ss < 10 ? "0" + ss : String(ss));
    paintSessionBar();
  }

  function fetchSession() {
    if (!sessionEnabled) return;
    fetch("/api/session", { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(renderSession)
      .catch(function () {
        if (els.sessionState) {
          els.sessionState.textContent =
            "Không đọc được trạng thái phiên học.";
        }
      });
  }

  function sendSession(path, body) {
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok || !data || data.ok !== true) {
            showMessage(failText(res, data));
            return;
          }
          showMessage(data.message || "Đã cập nhật phiên học.");
          renderSession(data);
        });
      })
      .catch(function () {
        showMessage("Không gửi được lệnh phiên học. Kiểm tra kết nối mạng.");
      });
  }

  if (sessionEnabled && els.sessionStart) {
    els.sessionStart.addEventListener("click", function () {
      var raw = els.sessionMinutes ? els.sessionMinutes.value : "";
      var body = {};
      /* Để trống = dùng mặc định của máy chủ. Gửi số 0 hay NaN sẽ bị từ chối
       * 400 và người dùng không hiểu vì sao, bỏ hẳn khóa thì máy chủ dùng
       * `default_minutes`. */
      if (raw !== "" && raw !== null) {
        var minutes = Number(raw);
        if (isFinite(minutes)) body.minutes = minutes;
      }
      sendSession("/api/session/start", body);
    });
  }

  if (sessionEnabled && els.sessionStop) {
    els.sessionStop.addEventListener("click", function () {
      sendSession("/api/session/stop", {});
    });
  }

  if (sessionEnabled) {
    fetchSession();
    window.setInterval(fetchSession, SESSION_POLL_MS);
    sessionTimer = window.setInterval(tickSessionCountdown, 250);
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
           * tục, người dùng đã thấy thông báo giải thích. */
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
   * thoại), nhả tay sẽ không bao giờ tới nơi, phải tự dừng. */
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
      ? match.name
      : "mã " + personId + " (không có trong danh sách)";
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
        "Bước " + (Number(data.step_index) + 1) + ": " + (data.step_name || "–");
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
      els.schedule.textContent = "Chưa đọc được.";
      return;
    }
    if (schedule.enabled === false) {
      els.schedule.textContent = "Không giới hạn giờ.";
      return;
    }
    var windows = schedule.windows || [];
    if (!windows.length) {
      els.schedule.textContent = "Chưa đặt khung giờ nào.";
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
    els.schedule.textContent = parts.join("; ");
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
        if (els.schedule) els.schedule.textContent = "Mất kết nối.";
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

  /* ---- Giọng đọc cảnh báo ------------------------------------------ */

  /* Ba câu cảnh báo là cố định, nên lựa chọn cũng cố định; danh sách nút
   * dựng từ /api/voice để nhãn và tình trạng khớp dữ liệu thật. Mỗi lựa chọn
   * ghi rõ câu nào còn thiếu bản thu, người dùng chép file vào là thấy ngay,
   * không phải đoán xem đã nhận chưa.
   *
   * Không lưu gì vào localStorage: đây là cấu hình thiết bị, server đã ghi
   * xuống data/audio/voice.json rồi. */
  var voiceEnabled = !!(els.voiceCard &&
    els.voiceCard.dataset.speakerEnabled === "1");

  function voiceChoiceText(voiceKey, info) {
    var note = "";
    if (info && info.missing && info.missing.length) {
      var labels = { leave_frame: "rời khung hình", phone: "dùng điện thoại",
                     stranger: "người lạ" };
      var names = info.missing.map(function (kind) {
        return labels[kind] || kind;
      });
      note = "Thiếu bản thu cho câu " + names.join(", ") + ", câu đó dùng giọng máy.";
    } else if (voiceKey === "espeak") {
      note = "Giọng tổng hợp của máy; khó nghe hơn trên loa camera.";
    } else {
      note = "Đủ ba câu, phát bằng bản thu.";
    }
    return note;
  }

  function renderVoice(data) {
    if (!els.voiceOptions) return;
    var voices = (data && data.voices) || {};
    var current = data && data.voice;
    var order = ["nam", "nu", "espeak"];
    els.voiceOptions.textContent = "";

    order.forEach(function (key) {
      var info = voices[key];
      if (!info) return;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "voice__choice";
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", key === current ? "true" : "false");
      button.dataset.voice = key;

      var mark = document.createElement("span");
      mark.className = "voice__mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = key === current ? "●" : "○";

      var body = document.createElement("span");
      var label = document.createElement("span");
      label.className = "voice__label";
      label.textContent = info.label || key;
      var note = document.createElement("span");
      note.className = "voice__note";
      note.textContent = voiceChoiceText(key, info);
      body.appendChild(label);
      body.appendChild(note);

      button.appendChild(mark);
      button.appendChild(body);
      button.addEventListener("click", function () {
        setVoice(key, button);
      });
      els.voiceOptions.appendChild(button);
    });

    if (!els.voiceStatus) return;
    if (!current) {
      els.voiceStatus.textContent =
        "Chưa đọc được giọng đang dùng.";
      return;
    }
    var currentInfo = voices[current];
    var label = (currentInfo && currentInfo.label) || current;
    var fallbacks = (data && data.fallbacks) || {};
    var fallbackNotes = Object.keys(fallbacks).map(function (kind) {
      return fallbacks[kind];
    });
    var base = "Đang dùng: " + label + ".";
    if (data && typeof data.speed === "number" && typeof data.volume === "number") {
      base +=
        " Tốc độ " +
        data.speed.toFixed(2) +
        "×, âm lượng " +
        data.volume.toFixed(2) +
        ".";
    }
    if (fallbackNotes.length) {
      base += " " + fallbackNotes.join(" ");
    }
    if (data && data.error) {
      base += " Lưu ý: " + data.error + ".";
    }
    els.voiceStatus.textContent = base;
  }

  function fetchVoice() {
    if (!voiceEnabled) return;
    fetch("/api/voice", { cache: "no-store" })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok) {
            if (els.voiceStatus) {
              els.voiceStatus.textContent = failText(res, data);
            }
            return;
          }
          renderVoice(data);
        });
      })
      .catch(function () {
        if (els.voiceStatus) {
          els.voiceStatus.textContent = "Không tải được trạng thái giọng đọc.";
        }
      });
  }

  function setVoice(key, button) {
    if (button) button.disabled = true;
    fetch("/api/voice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ voice: key })
    })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok) {
            showMessage(failText(res, data));
            return;
          }
          showMessage(data.message || "Đã đổi giọng đọc.");
          renderVoice(data);
        });
      })
      .catch(function () {
        showMessage("Không gửi được yêu cầu đổi giọng đọc.");
      })
      .finally(function () {
        if (button) button.disabled = false;
      });
  }

  if (voiceEnabled) {
    fetchVoice();
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
