/* Logic dashboard: hỏi /api/status mỗi giây, vẽ biểu đồ từ /api/history.
 *
 * Không phụ thuộc mạng ngoài: Chart.js được nạp cục bộ từ static/. Nếu file
 * đó vì lý do nào không nạp được (hỏng, chặn), phần biểu đồ tự vẽ bằng SVG
 * thay vì để trống — dashboard không bao giờ "trắng xoá" khi offline.
 */
(function () {
  "use strict";

  var STATUS_INTERVAL_MS = 1000;
  var HISTORY_REFRESH_MS = 30000;

  var els = {
    card: document.getElementById("status-card"),
    icon: document.getElementById("status-icon"),
    statusText: document.getElementById("status-text"),
    labelsText: document.getElementById("labels-text"),
    score: document.getElementById("score"),
    sitting: document.getElementById("sitting"),
    distance: document.getElementById("distance"),
    updated: document.getElementById("updated"),
    stale: document.getElementById("stale-warning"),
    muteBtn: document.getElementById("mute-btn"),
    muteIcon: document.getElementById("mute-icon"),
    muteText: document.getElementById("mute-text"),
    calibrateBtn: document.getElementById("calibrate-btn"),
    message: document.getElementById("action-message"),
    chart: document.getElementById("chart"),
    chartEmpty: document.getElementById("chart-empty"),
    caption: document.getElementById("chart-caption"),
    table: document.getElementById("chart-table"),
    camera: document.getElementById("camera-stream"),
    cameraNote: document.getElementById("camera-note"),
    tabs: Array.prototype.slice.call(document.querySelectorAll(".tab"))
  };

  var minDistance = parseFloat(document.body.dataset.minDistance || "35");
  var currentRange = "today";
  var chart = null;
  var chartBroken = false;

  var STATE_CLASS = {
    GOOD: "status--good",
    WARN: "status--warn",
    BAD: "status--bad",
    ABSENT: "status--absent"
  };

  /* Biểu tượng + nhãn chữ đi cùng màu trạng thái: màu không bao giờ là
   * kênh truyền đạt duy nhất. */
  var STATE_ICON = {
    GOOD: "✓",
    WARN: "!",
    BAD: "✕",
    ABSENT: "○"
  };

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function formatDuration(seconds) {
    var total = Math.max(0, Math.round(Number(seconds) || 0));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    if (h > 0) return h + " giờ " + m + " phút";
    if (m > 0) return m + " phút " + s + " giây";
    return s + " giây";
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
    var state = STATE_CLASS[data.state] ? data.state : "ABSENT";
    if (els.card) {
      els.card.className = "card status " + STATE_CLASS[state];
    }
    if (els.icon) els.icon.textContent = STATE_ICON[state] || "•";
    if (els.statusText) {
      els.statusText.textContent = data.state_text || data.state || "—";
    }
    if (els.labelsText) {
      var texts = data.label_texts || [];
      els.labelsText.textContent = texts.length
        ? "Nhãn: " + texts.join(" · ")
        : "Không có nhãn bất thường.";
    }
    if (els.score) {
      els.score.textContent =
        typeof data.score === "number" && data.state !== "ABSENT"
          ? Math.round(data.score) + " / 100"
          : "—";
    }
    if (els.sitting) els.sitting.textContent = formatDuration(data.sitting_s);
    if (els.distance) {
      els.distance.textContent =
        data.distance_cm === null || data.distance_cm === undefined
          ? "Chưa có cảm biến"
          : Math.round(data.distance_cm) + " cm";
      if (
        typeof data.distance_cm === "number" &&
        data.distance_cm < minDistance
      ) {
        els.distance.textContent += " (quá gần)";
      }
    }
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

  /* ---- Biểu đồ ---------------------------------------------------- */

  function chartColors() {
    return {
      series: cssVar("--series-1") || "#2a78d6",
      grid: cssVar("--grid") || "#e1e0d9",
      axis: cssVar("--axis") || "#c3c2b7",
      ink: cssVar("--ink") || "#0b0b0b",
      ink2: cssVar("--ink-2") || "#52514e",
      surface: cssVar("--surface-1") || "#fcfcfb"
    };
  }

  function renderTable(data) {
    if (!els.table) return;
    els.table.innerHTML = "";
    data.labels.forEach(function (label, index) {
      var row = document.createElement("tr");
      var cells = [
        label,
        data.good_pct[index] === null ? "—" : data.good_pct[index] + " %",
        data.avg_score[index] === null ? "—" : data.avg_score[index],
        data.absent_s[index] === null ? "—" : Math.round(data.absent_s[index])
      ];
      cells.forEach(function (value) {
        var td = document.createElement("td");
        td.textContent = value;
        row.appendChild(td);
      });
      els.table.appendChild(row);
    });
  }

  function drawFallback(data, colors) {
    /* Bản vẽ tay bằng SVG: chỉ dùng khi Chart.js không nạp được. Cột một
     * chuỗi duy nhất, nhãn trục thưa, không cần thư viện. */
    var wrap = els.chart ? els.chart.parentNode : null;
    if (!wrap) return;
    var old = wrap.querySelector("svg.chart-fallback");
    if (old) old.remove();

    var width = wrap.clientWidth || 320;
    var height = wrap.clientHeight || 240;
    var padLeft = 34;
    var padBottom = 26;
    var padTop = 8;
    var plotW = width - padLeft - 6;
    var plotH = height - padTop - padBottom;
    var n = data.labels.length || 1;
    var gap = 2;
    var barW = Math.max(1, plotW / n - gap);

    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("class", "chart-fallback");
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    svg.setAttribute("role", "img");
    svg.setAttribute(
      "aria-label",
      "Biểu đồ cột tỉ lệ tư thế đúng: " + data.labels.join(", ")
    );

    [0, 50, 100].forEach(function (tick) {
      var y = padTop + plotH * (1 - tick / 100);
      var line = document.createElementNS(svgNS, "line");
      line.setAttribute("x1", padLeft);
      line.setAttribute("x2", width - 4);
      line.setAttribute("y1", y);
      line.setAttribute("y2", y);
      line.setAttribute("stroke", tick === 0 ? colors.axis : colors.grid);
      line.setAttribute("stroke-width", "1");
      svg.appendChild(line);

      var text = document.createElementNS(svgNS, "text");
      text.setAttribute("x", padLeft - 6);
      text.setAttribute("y", y + 4);
      text.setAttribute("text-anchor", "end");
      text.setAttribute("font-size", "10");
      text.setAttribute("fill", colors.ink2);
      text.textContent = tick + "%";
      svg.appendChild(text);
    });

    data.labels.forEach(function (label, index) {
      var value = data.good_pct[index];
      if (value === null || value === undefined) return;
      var barH = Math.max(0, (plotH * value) / 100);
      var x = padLeft + index * (plotW / n) + gap / 2;
      var y = padTop + plotH - barH;
      var rect = document.createElementNS(svgNS, "rect");
      rect.setAttribute("x", x);
      rect.setAttribute("y", y);
      rect.setAttribute("width", Math.max(1, barW));
      rect.setAttribute("height", barH);
      rect.setAttribute("rx", "4");
      rect.setAttribute("fill", colors.series);
      var title = document.createElementNS(svgNS, "title");
      title.textContent = label + ": " + value + "%";
      rect.appendChild(title);
      svg.appendChild(rect);
    });

    /* Nhãn trục X thưa: tối đa 6 nhãn để không chồng chữ trên điện thoại. */
    var step = Math.max(1, Math.ceil(n / 6));
    data.labels.forEach(function (label, index) {
      if (index % step !== 0) return;
      var text = document.createElementNS(svgNS, "text");
      text.setAttribute("x", padLeft + (index + 0.5) * (plotW / n));
      text.setAttribute("y", height - 8);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("font-size", "10");
      text.setAttribute("fill", colors.ink2);
      text.textContent = label;
      svg.appendChild(text);
    });

    wrap.appendChild(svg);
  }

  function renderChart(data) {
    var colors = chartColors();
    var hasData = (data.labels || []).length > 0 && data.has_data !== false;
    if (els.chartEmpty) els.chartEmpty.hidden = hasData;
    renderTable(data);
    if (!hasData) {
      if (chart) {
        chart.destroy();
        chart = null;
      }
      return;
    }

    if (typeof window.Chart === "undefined") {
      chartBroken = true;
      drawFallback(data, colors);
      return;
    }

    if (chartBroken) return; // đã chuyển hẳn sang bản vẽ tay

    var config = {
      type: "bar",
      data: {
        labels: data.labels,
        datasets: [
          {
            label: "Tỉ lệ tư thế đúng (%)",
            data: data.good_pct,
            backgroundColor: colors.series,
            borderRadius: 4,
            borderSkipped: "bottom",
            /* Khe 2px giữa các cột để hai cột cạnh nhau không dính thành
             * một khối. */
            barPercentage: 0.85,
            categoryPercentage: 0.85
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 6 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            displayColors: false,
            backgroundColor: colors.ink,
            titleColor: colors.surface,
            bodyColor: colors.surface,
            callbacks: {
              label: function (item) {
                var value = item.parsed.y;
                return value === null || value === undefined
                  ? "Không có dữ liệu"
                  : value.toFixed(1) + "% thời gian đúng tư thế";
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: colors.axis },
            ticks: {
              color: colors.ink2,
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 6,
              font: { size: 11 }
            }
          },
          y: {
            min: 0,
            max: 100,
            grid: { color: colors.grid, drawTicks: false },
            border: { display: false },
            ticks: {
              color: colors.ink2,
              stepSize: 25,
              callback: function (value) {
                return value + "%";
              },
              font: { size: 11 }
            }
          }
        }
      }
    };

    if (chart) {
      chart.data.labels = data.labels;
      chart.data.datasets[0].data = data.good_pct;
      chart.data.datasets[0].backgroundColor = colors.series;
      chart.update("none");
    } else {
      chart = new window.Chart(els.chart, config);
    }
  }

  function fetchHistory() {
    fetch("/api/history?range=" + encodeURIComponent(currentRange), {
      cache: "no-store"
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (els.caption) {
          els.caption.textContent =
            currentRange === "today"
              ? "Phần trăm thời gian có người ngồi đúng tư thế trong mỗi giờ."
              : "Phần trăm thời gian có người ngồi đúng tư thế trong 7 ngày qua.";
        }
        renderChart(data);
      })
      .catch(function () {
        if (els.chartEmpty) {
          els.chartEmpty.textContent = "Không tải được số liệu.";
          els.chartEmpty.hidden = false;
        }
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

  els.tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      currentRange = tab.dataset.range;
      els.tabs.forEach(function (other) {
        var active = other === tab;
        other.classList.toggle("tab--active", active);
        other.setAttribute("aria-selected", active ? "true" : "false");
      });
      fetchHistory();
    });
  });

  /* Cập nhật lại biểu đồ khi đổi chế độ sáng/tối để màu bám đúng bề mặt. */
  if (window.matchMedia) {
    var media = window.matchMedia("(prefers-color-scheme: dark)");
    if (media.addEventListener) {
      media.addEventListener("change", function () {
        if (chartBroken) {
          fetchHistory();
        } else if (chart) {
          fetchHistory();
        }
      });
    }
  }

  fetchStatus();
  setupCamera();
  fetchHistory();
  window.setInterval(fetchStatus, STATUS_INTERVAL_MS);
  window.setInterval(fetchHistory, HISTORY_REFRESH_MS);
})();
