/* Logic dashboard: hỏi /api/status và /api/signals mỗi giây, hiện ba tín hiệu
 * trạng thái học (có mặt / điện thoại / danh tính) kèm tuổi tín hiệu, điều
 * khiển phiên học, xoay camera, và quản lý phần "Người học" — thêm người bằng
 * hộp quét khuôn mặt kiểu Face ID, chọn người đang học, xoá.
 *
 * Nguyên tắc bắt buộc (spec v3 §5.16):
 * - Màu không bao giờ là kênh truyền đạt duy nhất: mỗi dòng có biểu tượng và
 *   nhãn chữ đi kèm.
 * - Tín hiệu cũ (fresh = false) phải hiện "chưa có dữ liệu mới", KHÔNG được
 *   lặp lại kết luận cũ như vừa đo được. Đây là yêu cầu chống hiểu nhầm.
 * - Không nạp gì từ Internet; không lưu dữ liệu người vào localStorage.
 *
 * Hộp quét khuôn mặt: máy chủ là bên DUY NHẤT quyết định một phiên đăng ký đã
 * xong hay hỏng (``PeopleService`` đếm số mẫu và tự hết hạn theo thời gian).
 * Giao diện chỉ đọc ``/api/enroll/<id>`` rồi vẽ lại. Nhờ vậy không có chuyện
 * giao diện báo "xong" trong khi kho khuôn mặt chưa ghi gì.
 */
(function () {
  "use strict";

  var STATUS_INTERVAL_MS = 1000;
  var ENROLL_POLL_MS = 700;

  var el = function (id) {
    return document.getElementById(id);
  };

  var els = {
    signsCard: el("status-card"),
    updated: el("updated"),
    liveDot: el("live-dot"),
    stale: el("stale-warning"),
    muteBtn: el("mute-btn"),
    muteText: el("mute-text"),
    calibrateBtn: el("calibrate-btn"),
    message: el("action-message"),
    ptzButtons: Array.prototype.slice.call(
      document.querySelectorAll("[data-ptz-direction]")
    ),
    camera: el("camera-stream"),
    cameraNote: el("camera-note"),
    addBtn: el("add-person-btn"),
    addSheet: el("sheet-add"),
    addSheetClose: el("add-sheet-close"),
    addForm: el("add-person-form"),
    addSubmit: el("add-person-submit"),
    addCancel: el("add-person-cancel"),
    nameInput: el("new-person-name"),
    pickBtn: el("pick-person-btn"),
    pickSheet: el("sheet-pick"),
    pickSheetClose: el("pick-sheet-close"),
    pickList: el("pick-list"),
    pickEmpty: el("pick-empty"),
    selected: el("selected-person"),
    schedule: el("schedule-summary"),
    scan: el("scan"),
    scanViewport: el("scan-viewport"),
    scanCamera: el("scan-camera"),
    scanProgress: el("scan-progress"),
    scanBadge: el("scan-badge"),
    scanSteps: el("scan-steps"),
    scanHint: el("scan-hint"),
    scanRetry: el("scan-retry-btn"),
    scanClose: el("scan-close-btn"),
    enrollPanel: el("enroll-panel"),
    enrollNameNode: el("enroll-name"),
    enrollStep: el("enroll-step"),
    enrollSamples: el("enroll-samples"),
    enrollCancel: el("enroll-cancel-btn"),
    sessionCard: el("session-card"),
    sessionBadge: el("session-badge"),
    sessionLive: document.querySelector(".session__left"),
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
    document.body.dataset.peopleEnabled === "1" ||
    (els.signsCard && els.signsCard.dataset.peopleEnabled === "1");

  /* ---- Thẻ "Trạng thái học" ---------------------------------------- */

  /* Biểu tượng + nhãn chữ đi cùng màu: màu không bao giờ là kênh duy nhất.
   *
   * Khoá của các bảng phải là **đúng giá trị server gửi**, không phải khoá
   * CSS: `presence.py` trả "co_mat"/"vang_mat", còn phone là "dung"/
   * "khong_dung" (xem `people_service.note_phone`). Giá trị của bảng *_STATE
   * mới là khoá CSS trong `style.css`; tách riêng để đổi tên phía server không
   * kéo theo đổi giao diện. */
  var PRESENCE_TEXT = {
    co_mat: "Đang trong khung hình",
    vang_mat: "Không thấy ai"
  };
  /* Dấu hiệu là ký tự hình học, không phải emoji: emoji bị cấm trên giao diện
   * này (nó đổi hình theo từng hệ điều hành và đọc thành biểu tượng cảm xúc).
   * Màu trạng thái do `data-state` trong style.css quyết định, nên hình dấu
   * hiệu chỉ cần đọc được cùng nhãn chữ bên cạnh. */
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

  /* Giá trị server gửi mà giao diện không có nhãn cho nó. KHÔNG được im lặng
   * thay bằng "Chưa rõ": như thế một giá trị mới của server (hoặc một lỗi
   * đánh máy) trông y như "chưa đo được" và không ai biết để sửa. Hiện nguyên
   * giá trị thô kèm nhãn đánh dấu; giá trị rỗng thì nói rõ là rỗng. */
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

  /* Thông báo nổi: một chỗ duy nhất cho mọi câu phản hồi của máy chủ, tự tắt
   * sau 6 giây. Câu chữ là câu tiếng Việt máy chủ gửi, không bị viết lại. */
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
    var stale = !!data.stale;
    if (els.stale) els.stale.hidden = !stale;
    if (els.liveDot) els.liveDot.dataset.stale = stale ? "1" : "0";
    if (els.updated) {
      /* Dòng ngắn ở đây, câu giải thích đầy đủ nằm trong thẻ trạng thái: nói
       * cùng một chuyện ở hai chỗ chỉ làm mắt đọc hai lần. */
      els.updated.textContent = stale
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
        if (els.liveDot) els.liveDot.dataset.stale = "1";
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
   * trình duyệt bắn 'error' một lần rồi thôi. Không tự thử lại thì ảnh vỡ
   * đứng nguyên mãi. Thử lại bằng cách gắn lại src (kèm mốc thời gian để
   * trình duyệt không dùng bản cache).
   *
   * Khung hình chỉ đi qua bộ nhớ phía server và tới trình duyệt, không ghi ra
   * đĩa, không lưu lịch sử (spec v2 §11.5). */
  var CAMERA_RETRY_MS = 5000;
  /* Bao lâu thì thôi chờ khung đầu tiên. Camera IP cần vài giây để mở luồng
   * RTSP nên phải rộng hơn một nhịp mạng thường; quá mốc này thì để lời nhắn
   * "Đang kết nối…" lại cho tới khi 'error' hoặc khung thật tới. */
  var CAMERA_FIRST_FRAME_MS = 15000;
  var cameraRetryTimer = null;

  function setCameraNote(text) {
    if (!els.cameraNote) return;
    /* Ghi vào phần tử con khi có: khung hình đặt `display: flex` nên mỗi con
     * trực tiếp trở thành một ô flex riêng — chữ bị chia thành nhiều cột hẹp
     * thay vì xuống dòng. Một lớp bọc duy nhất giữ cho lời nhắn chỉ là một
     * khối chữ. */
    var target = els.cameraNote.firstElementChild || els.cameraNote;
    target.textContent = text;
    /* Ẩn hẳn khi không có chữ: khối rỗng vẫn giữ padding. */
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
      setCameraNote("Đang thử kết nối lại tới camera…");
      els.camera.src = "/stream?t=" + Date.now();
    }, CAMERA_RETRY_MS);
  }

  /* Đặt tỉ lệ khung theo đúng tỉ lệ nguồn ảnh thật.
   *
   * Khung hình khai `aspect-ratio` dự phòng 4:3 cho lúc chưa có hình. Camera
   * thật thường không phải 4:3 — bản đang chạy là 704x576 (11:9) — nên giữ
   * nguyên tỉ lệ dự phòng sẽ đặt một ảnh 11:9 vào khung 4:3 và sinh hai dải
   * đen hai bên. Đọc `naturalWidth/naturalHeight` của khung đầu tiên rồi đặt
   * biến CSS là cách duy nhất biết đúng tỉ lệ mà không phải khai cứng con số
   * của một camera cụ thể. */
  function matchFrameRatio() {
    if (!els.camera || !els.camera.parentElement) return;
    var w = els.camera.naturalWidth;
    var h = els.camera.naturalHeight;
    if (!w || !h) return;
    els.camera.parentElement.style.setProperty(
      "--frame-ratio",
      w + " / " + h
    );
  }

  function setupCamera() {
    if (!els.camera) return; // stream đang tắt: template đã hiện lời nhắn
    els.camera.addEventListener("load", function () {
      window.clearTimeout(cameraRetryTimer);
      els.camera.hidden = false;
      matchFrameRatio();
      setCameraNote("");
    });
    els.camera.addEventListener("error", cameraFailed);
    /* Ảnh đã có src trong template; nếu server trả 403/không có response thì
     * 'error' vẫn bắn và ta hiện đúng thông báo ở trên.
     *
     * Luồng MJPEG là request không bao giờ kết thúc nên `load` có thể không
     * bắn (Chromium: không bắn). Vì vậy còn một đường kiểm tra theo nhịp:
     * khung đầu tiên thật sự tới là lúc `naturalWidth > 0`. Không có đường
     * này thì trang đứng ở "Đang kết nối tới camera…" mãi mãi dù hình đã có —
     * đúng hiện tượng gặp khi chạy thật. */
    if (!els.camera.complete || !els.camera.naturalWidth) {
      setCameraNote("Đang kết nối tới camera…");
      var waited = 0;
      var firstFrame = window.setInterval(function () {
        waited += 250;
        if (!els.camera) {
          window.clearInterval(firstFrame);
          return;
        }
        if (els.camera.naturalWidth > 0) {
          window.clearInterval(firstFrame);
          window.clearTimeout(cameraRetryTimer);
          els.camera.hidden = false;
          matchFrameRatio();
          setCameraNote("");
        } else if (waited > CAMERA_FIRST_FRAME_MS) {
          window.clearInterval(firstFrame);
        }
      }, 250);
    } else {
      matchFrameRatio();
      setCameraNote("");
    }
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

  /* Lỗi dịch vụ luôn là {"ok": false, "message": "..."} tiếng Việt; giữ nguyên
   * câu đó để người dùng biết phải làm gì. */
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
   * đang chạy không" là cách chắc chắn nhất để nút và thực tế lệch nhau. */
  var sessionEnabled =
    (els.sessionCard && els.sessionCard.dataset.sessionEnabled === "1") ||
    false;
  var SESSION_POLL_MS = 1000;
  /* Mốc {remaining, at, total}: số giây còn lại của lần đồng bộ gần nhất và
   * thời điểm (Date.now) nhận được nó. Nhờ vậy giữa hai lần poll vẫn vẽ được
   * số giảm. */
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

    if (els.sessionBadge) {
      els.sessionBadge.hidden = !running;
      els.sessionBadge.textContent = running ? "Đang học" : "";
    }

    /* Ngoài phiên, số đếm ngược chỉ là "–": hiện cả nhóm thì tấm thẻ mang một
     * dòng 40px trống và một thanh tiến độ 0 %. Chỉ bật nhóm khi có số thật.
     * Phiên đã hết giờ thì vẫn hiện "00:00" — đó là kết quả, không phải chỗ
     * trống. */
    if (els.sessionLive) {
      els.sessionLive.dataset.live =
        running || state === "finished" ? "1" : "0";
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
      els.sessionStart.textContent = running ? "Bắt đầu lại" : "Bắt đầu học";
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
    if (els.sessionMinutes) {
      /* Đang chạy thì khoá ô nhập: đổi số giữa phiên không có tác dụng (máy
       * chủ đã chốt ends_at), để nó sửa được sẽ khiến người dùng tưởng đã đổi
       * thời lượng. Muốn đổi thì bấm "Bắt đầu lại". */
      els.sessionMinutes.disabled = running;
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

  /* Thanh tiến độ: phần đã trôi qua trên tổng thời lượng. Ngoài phiên thì để
   * rãnh rỗng, không bịa một thanh "0 %" trông như đang chạy. */
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
    window.setInterval(tickSessionCountdown, 250);
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

  /* Một bản sao danh sách gần nhất, dùng cho hộp chọn người và để biết tên
   * của người đang chọn. Không bao giờ ghi xuống localStorage: đây là thông
   * tin sinh trắc học. */
  var peopleCache = [];

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

  function initials(name) {
    var text = String(name || "").trim();
    return text ? text.charAt(0).toUpperCase() : "?";
  }

  /* Hộp chọn người: mỗi người một hàng bấm được. "Xoá" là hành động không
   * hoàn tác được nên luôn hỏi lại trước khi gọi. */
  function renderPickList(data) {
    var people = (data && data.people) || [];
    var selected = data ? data.selected : null;
    peopleCache = people;
    setSelected(selected, people);
    if (!els.pickList) return;
    els.pickList.textContent = "";

    if (els.pickEmpty) els.pickEmpty.hidden = people.length > 0;

    people.forEach(function (person) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "pick__row";
      row.dataset.selected = person.id === selected ? "1" : "0";

      var avatar = document.createElement("span");
      avatar.className = "pick__avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = initials(person.name);

      var name = document.createElement("span");
      name.className = "pick__name";
      name.textContent = person.name;

      var state = document.createElement("span");
      state.className = "pick__state";
      state.textContent = person.id === selected ? "Đang học" : "Chọn";

      row.appendChild(avatar);
      row.appendChild(name);
      row.appendChild(state);
      row.addEventListener("click", function () {
        if (person.id === selected) return; /* bấm lại người đang chọn: thôi */
        selectPerson(person.id);
      });

      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "pick__remove";
      remove.setAttribute("aria-label", "Xoá " + person.name);
      remove.textContent = "×";
      remove.addEventListener("click", function () {
        if (!window.confirm("Xoá người học \"" + person.name + "\"?")) return;
        deletePerson(person.id);
      });

      /* Hàng và nút xoá là hai phần tử ngang cấp: một <button> không được
       * lồng trong một <button> khác. */
      var line = document.createElement("div");
      line.className = "people__item";
      line.appendChild(row);
      line.appendChild(remove);
      els.pickList.appendChild(line);
    });
  }

  function fetchPeople() {
    if (!peopleEnabled) return;
    return fetch("/api/people", { cache: "no-store" })
      .then(function (res) {
        return readJson(res).then(function (data) {
          if (!res.ok) {
            showMessage(failText(res, data));
            return;
          }
          renderPickList(data);
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
    done: "Đã quét xong khuôn mặt.",
    cancelled: "Đã huỷ phiên đăng ký.",
    failed: "Quét không đạt."
  };

  /* ---- Hộp nổi: mở / đóng ----------------------------------------- */

  /* Hộp nổi không phải "trang mới": mở thì khoá cuộn nền để bánh xe không
   * đẩy trang phía sau, và đóng thì trả lại đúng trạng thái trước đó. */
  var openSheet = null;

  function lockScroll(locked) {
    document.body.style.overflow = locked ? "hidden" : "";
  }

  function openOverlay(node, focusNode) {
    if (!node) return;
    node.hidden = false;
    openSheet = node;
    lockScroll(true);
    if (focusNode && focusNode.focus) {
      /* Đợi một nhịp vẽ: phần tử vừa bỏ `hidden` chưa nhận được focus trên
       * một số trình duyệt di động. */
      window.setTimeout(function () {
        focusNode.focus();
      }, 30);
    }
  }

  function closeOverlay(node) {
    if (!node) return;
    node.hidden = true;
    if (openSheet === node) openSheet = null;
    if (!openSheet) lockScroll(false);
  }

  function closeAllOverlays() {
    [els.addSheet, els.pickSheet, els.scan].forEach(function (node) {
      if (node) node.hidden = true;
    });
    openSheet = null;
    lockScroll(false);
  }

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (openSheet) {
      /* Esc đóng đúng hộp đang mở. Đóng hộp quét khi đang quét phải huỷ phiên
       * ở máy chủ, nếu không kho khuôn mặt vẫn nhận mẫu của một phiên người
       * dùng đã bỏ đi. */
      if (openSheet === els.scan) {
        cancelEnroll();
      } else {
        closeOverlay(openSheet);
      }
    }
  });

  /* ---- Hộp quét khuôn mặt ----------------------------------------- */

  var enrollTimer = null;
  var enrollId = null;
  var enrollName = "";
  var enrollSteps = [];
  var enrollAutoClose = null;

  /* Chu vi vòng tiến độ (r = 56 theo SVG trong template). Một chỗ duy nhất để
   * đổi nếu đổi bán kính. */
  var RING_LENGTH = 351.86;

  function stopEnrollPolling() {
    window.clearTimeout(enrollTimer);
    enrollTimer = null;
    window.clearTimeout(enrollAutoClose);
    enrollAutoClose = null;
  }

  function setScanState(state) {
    if (!els.scanViewport) return;
    els.scanViewport.dataset.state = state;
    if (els.scanBadge) {
      els.scanBadge.textContent =
        state === "done"
          ? "Đã quét xong"
          : state === "failed"
          ? "Quét không đạt"
          : state === "starting"
          ? "Đang chuẩn bị"
          : "Đang quét";
    }
  }

  function setScanProgress(ratio) {
    if (!els.scanProgress) return;
    var value = Math.min(1, Math.max(0, ratio));
    els.scanProgress.style.strokeDashoffset = String(
      (RING_LENGTH * (1 - value)).toFixed(2)
    );
  }

  /* Năm chấm cho năm bước. Dựng lại mỗi lần số bước đổi (thường là một lần
   * cho cả phiên), rồi chỉ đổi thuộc tính của chấm. */
  function renderStepDots(stepIndex) {
    if (!els.scanSteps) return;
    if (els.scanSteps.children.length !== enrollSteps.length) {
      els.scanSteps.textContent = "";
      enrollSteps.forEach(function () {
        var dot = document.createElement("span");
        dot.className = "scan__step-dot";
        els.scanSteps.appendChild(dot);
      });
    }
    Array.prototype.forEach.call(
      els.scanSteps.children,
      function (dot, index) {
        dot.dataset.done = index < stepIndex ? "1" : "0";
        dot.dataset.current = index === stepIndex ? "1" : "0";
      }
    );
  }

  /* Phiên đã dừng (xong hoặc hỏng): không chấm nào còn là "bước đang làm".
   * Giữ lại dấu "đã xong" của các bước đã đi qua để người dùng thấy tiến độ
   * thật, nhưng bỏ chấm xanh nhấp nháy của bước hiện tại — nó chỉ có nghĩa
   * khi hệ thống còn đang quét. */
  function markStepsStopped() {
    if (!els.scanSteps) return;
    Array.prototype.forEach.call(els.scanSteps.children, function (dot) {
      dot.dataset.current = "0";
    });
  }

  function resetScanPanel() {
    setScanState("starting");
    setScanProgress(0);
    if (els.enrollStep) els.enrollStep.textContent = "Đang chuẩn bị camera…";
    if (els.enrollSamples) els.enrollSamples.textContent = "Mẫu hợp lệ: 0";
    if (els.scanHint) {
      els.scanHint.textContent =
        "Giữ mặt trong vòng tròn, nhìn thẳng vào camera và đủ sáng.";
    }
    if (els.enrollCancel) {
      els.enrollCancel.hidden = false;
      els.enrollCancel.textContent = "Huỷ";
    }
    if (els.scanRetry) els.scanRetry.hidden = true;
    if (els.scanClose) els.scanClose.hidden = true;
    if (els.enrollPanel) els.enrollPanel.hidden = false;
  }

  /* Chỉ bật hình camera trong lúc hộp quét mở: mỗi kết nối MJPEG là một luồng
   * sống, giữ nó thường trực sau khi đóng hộp là tốn CPU của Pi cho một khung
   * hình không ai nhìn. */
  function bindScanCamera(on) {
    if (!els.scanCamera) return;
    if (on) {
      els.scanCamera.src = "/stream?t=" + Date.now();
      els.scanCamera.hidden = false;
      if (els.scanViewport) els.scanViewport.dataset.hasVideo = "1";
    } else {
      els.scanCamera.hidden = true;
      els.scanCamera.removeAttribute("src");
      if (els.scanViewport) delete els.scanViewport.dataset.hasVideo;
    }
  }

  function openScan(name) {
    enrollName = name;
    if (els.enrollNameNode) els.enrollNameNode.textContent = name;
    resetScanPanel();
    openOverlay(els.scan, els.scanRetry && !els.scanRetry.hidden
      ? els.scanRetry
      : els.enrollCancel);
    bindScanCamera(true);
  }

  function closeScan() {
    stopEnrollPolling();
    enrollId = null;
    bindScanCamera(false);
    closeOverlay(els.scan);
  }

  function finishEnroll(state, message) {
    stopEnrollPolling();
    enrollId = null;

    if (state === "done") {
      setScanState("done");
      setScanProgress(1);
      /* Tất cả các bước phải hiện "đã xong". Không có bước cuối cùng của một
       * lần quét thành công: để nguyên chấm "đang làm" của lần cập nhật trước
       * là một câu sai trên màn hình. */
      renderStepDots(enrollSteps.length);
      if (els.enrollStep) els.enrollStep.textContent = "Đã đăng ký";
      if (els.enrollSamples) {
        els.enrollSamples.textContent =
          "Khuôn mặt của " + enrollName + " đã được lưu.";
      }
      if (els.scanHint) {
        els.scanHint.textContent =
          "Từ lần này hệ thống nhận ra " + enrollName + " khi bạn chọn người " +
          "học. Hình ảnh không được lưu lại.";
      }
      if (els.enrollCancel) els.enrollCancel.hidden = true;
      if (els.scanRetry) els.scanRetry.hidden = true;
      if (els.scanClose) {
        els.scanClose.hidden = false;
        els.scanClose.focus();
      }
      showMessage(message || "Đã thêm người học.");
      fetchPeople();
      /* Tự đóng sau một nhịp ngắn để người dùng kịp đọc kết quả, nhưng vẫn
       * giữ nút Đóng cho người muốn chủ động. */
      enrollAutoClose = window.setTimeout(closeScan, 1800);
      return;
    }

    if (state === "failed") {
      /* Quét không đạt: nói rõ đã thu được bao nhiêu mẫu trên bao nhiêu, và
       * đưa nút Quét lại lên làm hành động chính. Đây là yêu cầu "quét sai
       * thì quét lại". */
      setScanState("failed");
      /* Không còn bước nào "đang làm" khi phiên đã hỏng: để nguyên chấm xanh
       * của bước hiện tại là màn hình vẫn nói "đang quét" trong khi máy chủ
       * đã dừng. Các bước đã qua vẫn giữ dấu "đã xong" để thấy đã đi được đến
       * đâu. */
      markStepsStopped();
      if (els.enrollStep) els.enrollStep.textContent = "Chưa đạt";
      if (els.scanHint) {
        els.scanHint.textContent =
          message && message !== ENROLL_STATE_TEXT.failed
            ? message
            : "Không thu đủ mẫu khuôn mặt. Giữ mặt trong vòng tròn, đủ sáng " +
              "rồi quét lại.";
      }
      if (els.enrollCancel) els.enrollCancel.hidden = true;
      if (els.scanRetry) {
        els.scanRetry.hidden = false;
        els.scanRetry.focus();
      }
      if (els.scanClose) els.scanClose.hidden = false;
      showMessage(message || ENROLL_STATE_TEXT.failed);
      return;
    }

    /* cancelled: người dùng chủ động dừng, không cần báo lỗi. */
    closeScan();
    if (message) showMessage(message);
  }

  function renderEnroll(data) {
    var state = String(data.state || "failed");
    var samples = Number(data.samples || 0);
    var needed = Math.max(1, Number(data.samples_needed || 1));
    var stepIndex = Number(data.step_index || 0);

    if (state !== "running") {
      finishEnroll(state, data.error || ENROLL_STATE_TEXT[state]);
      return;
    }

    setScanState("scanning");
    setScanProgress(samples / needed);

    if (els.enrollStep) {
      els.enrollStep.textContent =
        enrollSteps[stepIndex] || data.step_name || "Nhìn thẳng";
    }
    renderStepDots(stepIndex);
    if (els.enrollSamples) {
      els.enrollSamples.textContent =
        "Mẫu hợp lệ: " + samples + " / " + needed;
    }

    /* Nói đúng việc phải làm ở bước hiện tại thay vì lặp lại câu hướng dẫn
     * chung: người đang ngồi trước camera cần biết quay đầu sang đâu. */
    if (els.scanHint) {
      els.scanHint.textContent = samples === 0
        ? "Chưa nhận được khuôn mặt. Bỏ kính râm, đủ sáng và nhìn thẳng."
        : "Giữ mặt trong vòng tròn và làm theo hướng dẫn từng bước.";
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
        finishEnroll("failed", "Mất kết nối khi đang quét khuôn mặt.");
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
          enrollSteps = Array.isArray(data.steps) ? data.steps : [];
          closeOverlay(els.addSheet);
          openScan(name);
          pollEnroll();
        });
      })
      .catch(function () {
        showMessage("Không bắt đầu được phiên đăng ký.");
      });
  }

  function cancelEnroll() {
    if (!enrollId) {
      closeScan();
      return;
    }
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
        finishEnroll("cancelled", "Không huỷ được phiên đăng ký.");
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
        if (els.nameInput) els.nameInput.value = "";
        openOverlay(els.addSheet, els.nameInput);
      });
    }
    if (els.addSheetClose) {
      els.addSheetClose.addEventListener("click", function () {
        closeOverlay(els.addSheet);
      });
    }
    if (els.addCancel) {
      els.addCancel.addEventListener("click", function () {
        closeOverlay(els.addSheet);
      });
    }
    if (els.addForm) {
      els.addForm.addEventListener("submit", function (event) {
        event.preventDefault();
        var name = els.nameInput ? els.nameInput.value.trim() : "";
        if (!name) {
          showMessage("Hãy nhập tên người học.");
          if (els.nameInput) els.nameInput.focus();
          return;
        }
        setBusy(els.addSubmit, true, "Đang chuẩn bị…");
        startEnroll(name);
        window.setTimeout(function () {
          setBusy(els.addSubmit, false);
        }, 600);
      });
    }
    if (els.pickBtn) {
      els.pickBtn.addEventListener("click", function () {
        fetchPeople().then(function () {
          openOverlay(els.pickSheet, els.pickSheetClose);
        });
      });
    }
    if (els.pickSheetClose) {
      els.pickSheetClose.addEventListener("click", function () {
        closeOverlay(els.pickSheet);
      });
    }
    if (els.enrollCancel) {
      els.enrollCancel.addEventListener("click", cancelEnroll);
    }
    if (els.scanRetry) {
      els.scanRetry.addEventListener("click", function () {
        var name = enrollName;
        resetScanPanel();
        setScanState("starting");
        startEnroll(name);
      });
    }
    if (els.scanClose) {
      els.scanClose.addEventListener("click", closeScan);
    }
    /* Bấm ra ngoài tấm thẻ để đóng. Hộp quét cố ý KHÔNG đóng theo cách này:
     * một cú chạm trượt trên điện thoại sẽ huỷ mất phiên đang quét. */
    [els.addSheet, els.pickSheet].forEach(function (node) {
      if (!node) return;
      node.addEventListener("click", function (event) {
        if (event.target === node) closeOverlay(node);
      });
    });
  }

  /* ---- Giọng đọc cảnh báo ------------------------------------------ */

  /* Ba câu cảnh báo là cố định, nên lựa chọn cũng cố định; danh sách nút dựng
   * từ /api/voice để nhãn và tình trạng khớp dữ liệu thật. Mỗi lựa chọn ghi rõ
   * câu nào còn thiếu bản thu, người dùng chép file vào là thấy ngay, không
   * phải đoán xem đã nhận chưa.
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
      els.voiceStatus.textContent = "Chưa đọc được giọng đang dùng.";
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
