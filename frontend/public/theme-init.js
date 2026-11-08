// Applies the saved theme before first paint (external file so the CSP can forbid inline scripts).
try {
  if (localStorage.getItem("tp-theme") === "light") {
    document.documentElement.classList.remove("dark");
  }
} catch {
  /* storage unavailable: keep the dark default */
}
