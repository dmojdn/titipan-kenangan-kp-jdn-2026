/**
 * Titipan Kenangan KP JDN - Main Javascript
 */

document.addEventListener('DOMContentLoaded', () => {
  // Auto-dismiss alerts selepas 6 saat
  const alerts = document.querySelectorAll('.alert');
  alerts.forEach(alert => {
    setTimeout(() => {
      alert.style.transition = 'opacity 0.5s ease';
      alert.style.opacity = '0';
      setTimeout(() => alert.remove(), 500);
    }, 6000);
  });

  // Mulakan pemasa detik (Countdown ke 23 Oktober 2026)
  initCountdown();
});

/**
 * COUNTDOWN TIMER KE 23 OKTOBER 2026
 * Mengira detik hari, jam, minit, dan saat menjelang persaraan KP JDN
 */
function initCountdown() {
  const targetDate = new Date("2026-10-23T00:00:00+08:00").getTime();

  function update() {
    const now = new Date().getTime();
    const distance = targetDate - now;

    const elDays = document.getElementById("cd-days");
    const elHours = document.getElementById("cd-hours");
    const elMinutes = document.getElementById("cd-minutes");
    const elSeconds = document.getElementById("cd-seconds");
    const elNav = document.getElementById("nav-countdown-text");

    if (distance <= 0) {
      if (elDays) elDays.innerText = "00";
      if (elHours) elHours.innerText = "00";
      if (elMinutes) elMinutes.innerText = "00";
      if (elSeconds) elSeconds.innerText = "00";
      if (elNav) elNav.innerText = "Hari Persaraan Telah Tiba";
      return;
    }

    const days = Math.floor(distance / (1000 * 60 * 60 * 24));
    const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((distance % (1000 * 60)) / 1000);

    const pad = (n) => String(n).padStart(2, "0");

    if (elDays) elDays.innerText = pad(days);
    if (elHours) elHours.innerText = pad(hours);
    if (elMinutes) elMinutes.innerText = pad(minutes);
    if (elSeconds) elSeconds.innerText = pad(seconds);

    if (elNav) {
      elNav.innerText = `${days}h ${pad(hours)}j ${pad(minutes)}m`;
    }
  }

  update();
  setInterval(update, 1000);
}
