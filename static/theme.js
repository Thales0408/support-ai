(function () {
    const storageKey = "55pbx-ai-theme"
    const media = window.matchMedia("(prefers-color-scheme: dark)")

    function storedTheme() {
        try {
            const value = localStorage.getItem(storageKey)
            return value === "light" || value === "dark" ? value : null
        } catch (_) {
            return null
        }
    }

    function applyTheme(theme) {
        document.documentElement.dataset.theme = theme
        document.dispatchEvent(new Event("themechange"))
        const toggle = document.querySelector("[data-theme-toggle]")
        if (!toggle) return

        const nextIsDark = theme !== "dark"
        toggle.setAttribute("aria-label", `Ativar modo ${nextIsDark ? "noite" : "dia"}`)
        toggle.setAttribute("aria-pressed", String(theme === "dark"))
        toggle.querySelector("[data-theme-label]").textContent = nextIsDark ? "Noite" : "Dia"
    }

    applyTheme(storedTheme() || (media.matches ? "dark" : "light"))

    document.addEventListener("DOMContentLoaded", () => {
        applyTheme(document.documentElement.dataset.theme)
        document.querySelector("[data-theme-toggle]")?.addEventListener("click", () => {
            const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"
            try {
                localStorage.setItem(storageKey, theme)
            } catch (_) {
                // The chosen theme still applies for this page when storage is unavailable.
            }
            applyTheme(theme)
        })
    })

    media.addEventListener?.("change", () => {
        if (!storedTheme()) applyTheme(media.matches ? "dark" : "light")
    })
})()
