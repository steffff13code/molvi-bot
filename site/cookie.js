/* МОЛВИ — cookie-баннер. Самодостаточный, без зависимостей.
   Подключение: <script src="/cookie.js" defer></script> */
(function () {
  var KEY = "molvi_cookie_ok";
  try { if (localStorage.getItem(KEY) === "1") return; } catch (e) { return; }

  function build() {
    var bar = document.createElement("div");
    bar.id = "molvi-cookie";
    bar.setAttribute("role", "dialog");
    bar.setAttribute("aria-label", "Использование cookie");
    bar.style.cssText = [
      "position:fixed", "left:16px", "right:16px", "bottom:16px", "z-index:99999",
      "max-width:760px", "margin:0 auto",
      "background:rgba(15,20,32,.97)", "color:#e8edf6",
      "border:1px solid rgba(255,255,255,.12)", "border-radius:14px",
      "box-shadow:0 12px 40px rgba(0,0,0,.45)",
      "padding:16px 18px", "display:flex", "gap:14px", "align-items:center",
      "flex-wrap:wrap", "justify-content:space-between",
      "font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif",
      "font-size:14px", "line-height:1.55", "backdrop-filter:blur(12px)"
    ].join(";");

    var txt = document.createElement("div");
    txt.style.cssText = "flex:1 1 320px;color:#aab3c5";
    txt.innerHTML = 'Мы используем cookie для работы сайта и аналитики. Продолжая пользоваться сайтом, вы соглашаетесь с этим. Подробнее — в <a href="/legal/privacy/" style="color:#60a5fa">Политике конфиденциальности</a>.';

    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Принять";
    btn.style.cssText = [
      "flex:0 0 auto", "cursor:pointer", "border:0", "border-radius:10px",
      "padding:10px 22px", "font-weight:700", "font-size:14px", "color:#fff",
      "background:linear-gradient(135deg,#2563eb,#06b6d4)"
    ].join(";");
    btn.onclick = function () {
      try { localStorage.setItem(KEY, "1"); } catch (e) {}
      bar.parentNode && bar.parentNode.removeChild(bar);
    };

    bar.appendChild(txt);
    bar.appendChild(btn);
    document.body.appendChild(bar);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
