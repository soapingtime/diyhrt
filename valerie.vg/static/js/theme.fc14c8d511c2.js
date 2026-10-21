/*!
 * Color mode toggler — adapted from Bootstrap docs
 * https://getbootstrap.com/docs/5.3/customize/color-modes/#javascript
 */
(function () {
    'use strict';

    var themeIcons = {
        light: 'fa-solid fa-sun',
        dark: 'fa-solid fa-moon',
        auto: 'fa-solid fa-circle-half-stroke'
    };

    function getStoredTheme() {
        return localStorage.getItem('theme');
    }

    function setStoredTheme(theme) {
        localStorage.setItem('theme', theme);
    }

    function getPreferredTheme() {
        var stored = getStoredTheme();
        if (stored) { return stored; }
        return 'auto';
    }

    function setTheme(theme) {
        if (theme === 'auto') {
            document.documentElement.setAttribute('data-bs-theme',
                window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        } else {
            document.documentElement.setAttribute('data-bs-theme', theme);
        }
    }

    function showActiveTheme(theme, focus) {
        var btns = document.querySelectorAll('[data-bs-theme-value]');
        for (var i = 0; i < btns.length; i++) {
            btns[i].classList.remove('active');
            btns[i].setAttribute('aria-pressed', 'false');
        }

        var matching = document.querySelectorAll('[data-bs-theme-value="' + theme + '"]');
        for (var j = 0; j < matching.length; j++) {
            matching[j].classList.add('active');
            matching[j].setAttribute('aria-pressed', 'true');
            if (focus && j === 0) { matching[j].focus(); }
        }

        // Font Awesome SVG+JS replaces <i> with <svg>, so we must swap in a
        // fresh <i> element for it to pick up the new icon class.
        var icon = document.querySelector('#theme-toggle-icon');
        if (icon && themeIcons[theme]) {
            var newIcon = document.createElement('i');
            newIcon.id = 'theme-toggle-icon';
            newIcon.className = themeIcons[theme];
            icon.replaceWith(newIcon);
        }
    }

    // Exposed globally so inline onclick handlers on the dropdown buttons
    // can call it directly, avoiding Bootstrap dropdown JS interference.
    window.setThemePreference = function (theme) {
        setStoredTheme(theme);
        setTheme(theme);
        showActiveTheme(theme, true);
    };

    // Follow OS theme changes when in auto mode
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () {
        var stored = getStoredTheme();
        if (stored !== 'light' && stored !== 'dark') {
            setTheme(getPreferredTheme());
        }
    });

    // Set initial icon and active state once the DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            showActiveTheme(getPreferredTheme());
        });
    } else {
        showActiveTheme(getPreferredTheme());
    }
})();
