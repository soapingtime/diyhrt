/* These need to be here and run before DOMContentLoaded to prevent flash of unstyled content (FOUC) */
/* Only <html> and <head> are available by this point (based on when script called in HTML) */

// For preventing jump of scroll position on click when scrolled down in sidebar
var toc_sidebar_no_scroll_jump = false;

// Set theme if applicable
if (is_local_storage_available() == true && localStorage.getItem('theme')) {
  document.documentElement.setAttribute('data-theme', localStorage.getItem('theme'));
} else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches == true) {
  document.documentElement.setAttribute('data-theme', 'dark');
}

// Set persistent header to hidden if applicable
if (is_local_storage_available() == true && localStorage.getItem('persistent-header-hidden')) {
  if (localStorage.getItem('persistent-header-hidden') == 'true') {
    toggle_persistent_header(false);
  }
}

// Show sidebar if applicable
if (is_local_storage_available() == true && localStorage.getItem('show-sidebar')) {
  if (localStorage.getItem('show-sidebar') == 'true' && is_mobile() == false) {
    toggle_sidebar(false);
  }
// If no sidebar show setting and if screen is reasonably wide, then show it by default
} else {
  if (window.matchMedia && is_mobile() == false) {
    var media_query = window.matchMedia('(min-width: 1250px)');
    if (media_query.matches == true) {
      toggle_sidebar(false);
    }
  }
}

window.addEventListener('DOMContentLoaded', function () {

  // Set first current sidebar section
  if (does_sidebar_exist() == true) {
    update_current_sidebar_section();
  }

  // Set up for Google Translate if applicable
  if (is_google_translate_open() == true) {
    // Get and set Google Translate bar height
    update_google_translate_bar_height();

    // Mutation observer to watch for and update upon changes of Google Translate bar show/hide
    var observer = new MutationObserver(update_google_translate_bar_height);
    observer.observe(document.body, { attributes: true, attributeFilter: ['style'] });
  }

  // Set up site event listeners (scroll, buttons, color scheme change, keyboard keys, etc.)
  set_up_site_event_listeners();

  return;
});

// Set up site event listeners
function set_up_site_event_listeners() {
  /* Scroll, resize, fullscreen, and color scheme change listeners */

  // Page scroll listener
  window.addEventListener('scroll', function () {
    // Check and set persistent header status
    update_header_persistent_status();

    // Update sidebar current section
    if (does_sidebar_exist() == true) {
      update_current_sidebar_section();
    }

    return;
  });

  // Mobile change listener
  if (window.matchMedia) {
    matchMediaAddEventListener('(max-width: 900px)', function () {
      // If switching to mobile
      if (is_mobile() == true) {
        // Close sidebar if it's open
        if (is_sidebar_open() == true) {
          toggle_sidebar(false);
        }
      // If switching to desktop
      } else {
        // Open sidebar if it should be open
        if (is_sidebar_open() == false) {
          if (is_local_storage_available() == true && localStorage.getItem('show-sidebar') == 'true') {
            toggle_sidebar(false);
          }
        }
      }
      return;
    });
  }

  // Theme (light/dark mode) listener (follow system)
  if (window.matchMedia) {
    matchMediaAddEventListener('(prefers-color-scheme: dark)', function (event) {
      if (is_local_storage_available() == true && !localStorage.getItem('theme')) {
        var theme = event.matches == true ? 'dark' : 'light';
        if (theme == 'light') {
          document.documentElement.setAttribute('data-theme', 'light');
        } else {
          document.documentElement.setAttribute('data-theme', 'dark');
        }
      }
      return;
    });
  }

  /* Button listeners */

  // Theme (light/dark mode) button listener
  ['mousedown', 'keydown'].forEach(function (event_type) {
    document.getElementById('theme-button').addEventListener(event_type, function (event) {
      // If keydown event and not Enter or Space key
      if (event_type == 'keydown' && event.code != 'Enter' && event.code != 'Space') { return; }

      // If mousedown event
      if (event_type == 'mousedown') {
        // Prevent setting button active and therefore outline
        event.preventDefault();

        // If not main mouse button (e.g., context menu)
        if (event.button != 0) {
          return;
        }
      }

      // Execute button action
      toggle_theme(true);

      return;
    });
  });

  // Theme (light/dark mode) button reset listener (context menu)
  document.getElementById('theme-button').addEventListener('contextmenu', function (event) {
    event.preventDefault();
    if (!window.confirm('Clear theme (light/dark mode) setting? (This will reset the theme setting to the default of follow system theme.)')) {
      return;
    }
    if (is_local_storage_available() == true) {
      localStorage.removeItem('theme');
    }
    if (window.matchMedia) {
      var media_query = window.matchMedia('(prefers-color-scheme: light)');
      if (media_query.matches == true) {
        document.documentElement.setAttribute('data-theme', 'light');
      } else {
        document.documentElement.setAttribute('data-theme', 'dark');
      }
    }
    // alert('Theme (light/dark mode) setting reset.');
    return;
  });

  // Translate button listener
  ['mousedown', 'keydown'].forEach(function (event_type) {
    document.getElementById('language-button').addEventListener(event_type, function (event) {
      // If keydown event and not Enter or Space key
      if (event_type == 'keydown' && event.code != 'Enter' && event.code != 'Space') { return; }

      // If mousedown event
      if (event_type == 'mousedown') {
        // Prevent setting button active and therefore outline
        event.preventDefault();

        // If not main mouse button (e.g., context menu)
        if (event.button != 0) {
          return;
        }
      }

      // Execute button action
      // If Google Translate mode isn't already active
      if (is_google_translate_open() == false) {
        // Get user's preferred language from browser settings
        var preferred_language = String(navigator.language);
        // Need to get rid of country code but Chinese simplified vs. traditional are exceptions for Google Translate
        // https://cloud.google.com/translate/docs/languages
        if (preferred_language != 'zh-CN' && preferred_language != 'zh-TW') {
          preferred_language = preferred_language.split('-')[0];
        }
        // Fix Filipino (seems to be an exception with mismatched code here among many languages)
        // It's "Filipino" ("fil") in Chrome but "Tagalog" ("tl") in Firefox; Google Translate uses "tl"
        if (preferred_language == 'fil') {
          preferred_language = 'tl';
        }
        // Set Google Translate settings
        var source_language = 'auto'; // Must be 'auto' if trying to translate from 'en' to 'en' or will error
        var target_language = preferred_language;
        var interface_language = preferred_language;
        // Open Google Translate for the site
        window.open('https://translate.google.com/translate?sl=' + source_language + '&tl=' + target_language + 
          '&hl=' + interface_language + '&u=' + window.location.href + '&client=webapp', '_self');
      // If Google Translate mode is active
      } else {
        var gtranslate_script = document.querySelector('[data-source-url]');
        // Other Google Translate data attributes of potential inerest: data-proxy-url, data-proxy-full-url, data-source-language, data-target-language, data-display-language, data-detected-source-language, data-is-source-untranslated, data-source-untranslated-url
        var return_url = gtranslate_script.getAttribute('data-source-url');
        // Fallback
        if (!return_url) {
          return_url = 'https://transfemscience.org' + window.location.pathname;
        }
        // Take user back to site (exit Google Translate)
        window.location.href = return_url;
      }

      return;
    });
  });

  // Search button listener
  ['mousedown', 'keydown'].forEach(function (event_type) {
    document.getElementById('search-button').addEventListener(event_type, function (event) {
      // If keydown event and not Enter or Space key
      if (event_type == 'keydown' && event.code != 'Enter' && event.code != 'Space') { return; }

      // If mousedown event
      if (event_type == 'mousedown') {
        // Prevent setting button active and therefore outline
        event.preventDefault();

        // If not main mouse button (e.g., context menu)
        if (event.button != 0) {
          return;
        }
      }

      // Execute button action
      // Open search (Google Custom Search Engine) in a new tab
      // var search_url = 'https://cse.google.com/cse?cx=368ceeb2b0e46ce35';
      // The regex checks for either GitHub or Google Translate format (periods substituted with dashes)
      if (String(window.location.hostname).match(/[.-]github[.-]io/)) {
        var search_url = String(location.origin) + '/transfemscience' + '/search/' + window.location.search;
      } else {
        var search_url = String(location.origin) + '/search/' + window.location.search;
      }
      window.open(search_url, '_self');

      return;
    });
  });

  // Contents sidebar open/close button listener
  ['sidebar-button', 'sidebar-button-standalone', 'toc-button-mobile'].forEach(function (element_id) {
    ['mousedown', 'keydown'].forEach(function (event_type) {
      document.getElementById(element_id).addEventListener(event_type, function (event) {
        // If keydown event and not Enter or Space key
        if (event_type == 'keydown' && event.code != 'Enter' && event.code != 'Space') { return; }

        // If mousedown event
        if (event_type == 'mousedown') {
          // Prevent setting button active and therefore outline
          event.preventDefault();

          // If not main mouse button (e.g., context menu)
          if (event.button != 0) {
            return;
          }
        }

        // Execute button action
        toggle_sidebar(true);

        return;
      });
    });

    // Contents sidebar open/close button reset listener (context menu)
    document.getElementById(element_id).addEventListener('contextmenu', function (event) {
      event.preventDefault();
      if (!window.confirm('Clear sidebar show/hide by default setting?')) {
        return;
      }
      if (is_local_storage_available() == true) {
        localStorage.removeItem('show-sidebar');
      }
      // alert('Sidebar show/hide by default setting reset.');
      return;
    });
  });

  /*
  // Contents sidebar swipe left to close listener
  document.addEventListener('swiped-left', function (event) {
    // If sidebar is open and swiped element is not a table (with potential horizontal scroll)
    if (is_sidebar_open() == true && !event.target.closest('table')) {
      toggle_sidebar(true);
    } else {
      return;
    }
  });

  // Contents sidebar swipe right to open listener
  document.addEventListener('swiped-right', function (event) {
    // If sidebar is closed and swiped element is not a table (with potential horizontal scroll)
    if (is_sidebar_open() == false && !event.target.closest('table')) {
      toggle_sidebar(true);
    } else {
      return;
    }
  });
  */

  // Contents sidebar item listeners
  var links = document.querySelectorAll('.toc-link');
  for (var i = 0; i < links.length; i++) {
    links[i].onclick = function (event) {
      // If mobile, hide contents menu after clicking a ToC link
      if (is_mobile() == true) {
        if (is_sidebar_open() == true) {
          // Prevent slide transition for sidebar hide
          document.documentElement.setAttribute('data-sidebar-slide-transition-disable', '');

          // Following a short delay (to show tap / link highlight)...
          setTimeout(function () {
            // Close the sidebar
            toggle_sidebar();

            // Reset prevent sidebar hide slide transition
            setTimeout(function () {
              document.documentElement.removeAttribute('data-sidebar-slide-transition-disable');
            }, 150);
          }, 100);
        }
      }

      // Hide anchor tag from URL in the case of sidebar #top link click
      if (event.target.hash == '#top') {
        window.scrollTo(0, 0);
        history.pushState({}, document.title, window.location.href.split('#')[0]);
        return false;  
      }

      // Prevent jump of scroll position on click if scrolled down in sidebar
      toc_sidebar_no_scroll_jump = true;
      setInterval(function () {
        toc_sidebar_no_scroll_jump = false;
      }, 200);

      return;
    }
  }

  // Mobile menu open/close button listener
  ['mousedown', 'keydown'].forEach(function (event_type) {
    document.getElementById('menu-button-mobile-menu').addEventListener(event_type, function (event) {
      // If keydown event and not Enter or Space key
      if (event_type == 'keydown' && event.code != 'Enter' && event.code != 'Space') { return; }

      // If mousedown event
      if (event_type == 'mousedown') {
        // Prevent setting button active and therefore outline
        event.preventDefault();

        // If not main mouse button (e.g., context menu)
        if (event.button != 0) {
          return;
        }
      }

      // Execute button action
      toggle_mobile_menu();

      return;
    });
  });

  // Persistent header hide/restore button listeners
  ['hide-persistent-header-button', 'restore-persistent-header-button'].forEach(function (element_id) {
    ['mousedown', 'keydown'].forEach(function (event_type) {
      document.getElementById(element_id).addEventListener(event_type, function (event) {
        // If keydown event and not Enter or Space key
        if (event_type == 'keydown' && event.code != 'Enter' && event.code != 'Space') { return; }

        // If mousedown event
        if (event_type == 'mousedown') {
          // Prevent setting button active and therefore outline
          event.preventDefault();

          // If not main mouse button (e.g., context menu)
          if (event.button != 0) {
            return;
          }
        }

        // Execute button action
        toggle_persistent_header(true);

        return;
      });
    });

    // Persistent header hide/restore button reset listeners (context menu)
    document.getElementById(element_id).addEventListener('contextmenu', function (event) {
      event.preventDefault();
      if (!window.confirm('Clear persistent top bar show/hide by default setting?')) {
        return;
      }
      if (is_local_storage_available() == true) {
        localStorage.removeItem('persistent-header-hidden');
      }
      if (is_persistent_header_hidden() == true) {
        toggle_persistent_header(false);
      }
      // alert('Persistent top bar show/hide by default setting reset.');
      return;
    });
  });  

  /* Keyboard listeners */

  // Keyboard input listener
  document.addEventListener('keydown', function (event) {
    // Sidebar keyboard shortcut handler (Ctrl+Shift+L)
    if (event.ctrlKey && event.shiftKey && (event.key === 'l' || event.key === 'L')) {
      event.preventDefault();
      toggle_sidebar(true);
    // Persistent header / top bar keyboard shortcut handler (Ctrl+Shift+H)
    } else if (event.ctrlKey && event.shiftKey && (event.key === 'h' || event.key === 'H')) {
      event.preventDefault();
      toggle_persistent_header(true);
    }
    return;
  });

  /* Miscellaneous listeners */

  // Spoiler image listeners
  var spoilers = document.getElementsByClassName('spoiler');
  Array.prototype.forEach.call(spoilers, function (spoiler) {
    spoiler.addEventListener('click', function () {
      if (spoiler.classList.contains('spoiler')) {
        spoiler.classList.remove('spoiler');
      }
      return;
    });
    return;
  });

  return;
}

function is_dark_theme() {
  var current_theme = document.documentElement.getAttribute('data-theme');
  return current_theme == 'dark' ? true : false;
}

function toggle_theme(remember) {
  var new_theme = is_dark_theme() == false ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', new_theme);
  if (remember == true && is_local_storage_available() == true) {
    localStorage.setItem('theme', new_theme);
  }
  return;
}

function is_header_persistent() {
  var is_header_persistent = document.documentElement.hasAttribute('data-header-persistent');
  return is_header_persistent;
}

function update_header_persistent_status() {
  if (window.scrollY > 20) {
    document.documentElement.setAttribute('data-header-persistent', '');
  } else {
    document.documentElement.removeAttribute('data-header-persistent');
  }
  return;
}

function is_mobile() {
  if (window.matchMedia) {
    var media_query = window.matchMedia('(max-width: 900px)');
    if (media_query.matches == true) {
      return true;
    } else {
      return false;
    }
  }
  return;
}

function is_mobile_menu_open() {
  return document.documentElement.hasAttribute('data-mobile-menu-open');
}

function toggle_mobile_menu() {
  if (is_mobile_menu_open() == false) {
    document.documentElement.setAttribute('data-mobile-menu-open', '');
  } else {
    document.documentElement.removeAttribute('data-mobile-menu-open');
  }
  return;
}

function is_persistent_header_hidden() {
  return document.documentElement.hasAttribute('data-persistent-header-hidden');
}

function toggle_persistent_header(remember) {
  // Prevent grow/shrink transition for persistent header hide/show
  document.documentElement.setAttribute('data-persistent-header-toggle-no-transition', '');

  // Toggle persistent header
  if (is_persistent_header_hidden() == false) {
    document.documentElement.setAttribute('data-persistent-header-hidden', '');
    if (remember == true && is_local_storage_available() == true) {
      localStorage.setItem('persistent-header-hidden', 'true');
    }
  } else {
    document.documentElement.removeAttribute('data-persistent-header-hidden');
    if (remember == true && is_local_storage_available() == true) {
      localStorage.setItem('persistent-header-hidden', 'false');
    }
  }

  // Reset prevent grow/shrink transition for persistent header hide/show
  setTimeout(function () {
    document.documentElement.removeAttribute('data-persistent-header-toggle-no-transition');
  }, 200);

  return;
}

function does_sidebar_exist() {
  var does_sidebar_exist = !document.documentElement.hasAttribute('data-no-contents-sidebar');
  return does_sidebar_exist;
}

function is_sidebar_open() {
  var is_sidebar_open = document.documentElement.hasAttribute('data-sidebar-open');
  return is_sidebar_open;
}

function toggle_sidebar(remember) {
  if (is_sidebar_open() == false) {
    document.documentElement.setAttribute('data-sidebar-open', '');
    if (remember == true && is_local_storage_available() == true) {
      localStorage.setItem('show-sidebar', 'true');
    }
  } else {
    document.documentElement.removeAttribute('data-sidebar-open');
    if (remember == true && is_local_storage_available() == true) {
      localStorage.setItem('show-sidebar', 'false');
    }
  }
  return;
}

function update_current_sidebar_section() {
  var section_indice = get_current_sidebar_section_indice();

  var sidebar_contents = document.getElementById('sidebar-contents');
  var section_links = sidebar_contents.querySelectorAll('a[id^="heading-"]');
  for (var i = 0; i < section_links.length; i++) {
    if (section_links[i].id != 'heading-' + section_indice) {
      if (section_links[i].classList.contains('active-section')) {
        section_links[i].classList.remove('active-section');
      }
    } else {
      if (!section_links[i].classList.contains('active-section')) {
        section_links[i].classList.add('active-section');
        if (toc_sidebar_no_scroll_jump == false) {
          section_links[i].scrollIntoView(false);
        }
      }
    }
  }
  return;
}

function get_current_sidebar_section_indice() {
  var article = document.getElementById('article');
  var sections = article.querySelectorAll('h1, h2, h3, h4, h5, h6');

  var scroll_position = window.scrollY;
  var page_height = document.documentElement.scrollHeight;
  var window_height = window.innerHeight;

  for (var i = sections.length - 1; i >= 0; i--) {
    var section_position = sections[i].offsetTop;

    // Very bottom (remove later (?))
    if (i == sections.length - 1 && page_height - (scroll_position + window_height) <= 30) {
      return i;
    }

    // Bottom
    /*if (scroll_position >= page_height - window_height * 1.5) {
      // ...
      return sections.length; // Not this! (But just for now...)
    }*/

    // Very top (remove later (?))
    if (scroll_position <= 30) {
      return 0; // Top of page "section"
    }

    // Top
    if (scroll_position < window_height * 0.5) {
      if (scroll_position + window_height * 0.5 > section_position) {
        return i;
      }
    }

    // Top
    /*if (scroll_position < window_height * 0.5) {
      // ...
      if (scroll_position >= section_position) {
        return i - 1; // Not this! (But just for now...)
      }
    }*/

    // Mid
    if (scroll_position + window_height * 0.5 > section_position) {
      return i;
    }
  }

  // Scrolled midway (Luna-esque function—works (?) but could be better) (to-do: use/remove)
  // } else if (section_position > scroll_position + window_height * (scroll_position / page_height)) {

  return;
}

// Is Google Translate mode active?
function is_google_translate_open() {
  return String(window.location.hostname).includes('translate.goog');
}

// Is Google Translate bar open? (Currently unused)
function is_google_translate_bar_open() {
  if (is_google_translate_open() == false) {
    return false;
  } else {
    var google_translate_bar_height = get_google_translate_bar_height();
    return google_translate_bar_height == 0 ? false : true;
  }
}

// Get Google Translate bar height
function get_google_translate_bar_height() {
  return parseFloat(document.body.style.marginTop);
}

// Set Google Translate bar height
// For CSS styling to update site top positioning to account for Google Translate bar
function update_google_translate_bar_height() {
  var google_translate_bar_height = get_google_translate_bar_height();
  google_translate_bar_height = String(google_translate_bar_height) + 'px';
  document.documentElement.style.setProperty('--google-translate-bar-height', google_translate_bar_height);
  return;
}

// Wrapper function for window.matchMedia().addEventListener() for cross-browser support
// https://stackoverflow.com/questions/56466261/matchmedia-addlistener-marked-as-deprecated-addeventlistener-equivalent
function matchMediaAddEventListener(media_query, listener_function) {
	try {
    // Chrome, Firefox, iOS/Safari 14+, etc.
		window.matchMedia(media_query).addEventListener('change', listener_function);
	} catch {
    try {
      // iOS/Safari 13 and below
      window.matchMedia(media_query).addListener(listener_function);
    } catch {
      console.error('window.matchMedia.addEventListener() and window.matchMedia.addListener() not supported.');
    }
	}
	return;
}

// Check if local storage is supported and available (avoid exceptions)
// https://stackoverflow.com/questions/16427636/check-if-localstorage-is-available
// https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API/Using_the_Web_Storage_API
function is_local_storage_available() {
  let storage;
  try {
    storage = window['localStorage'];
    const x = '__storage_test__';
    storage.setItem(x, x);
    storage.removeItem(x);
    return true;
  }
  catch (error) {
    return error instanceof DOMException && (
      // Everything except Firefox
      error.code === 22 ||
      // Firefox
      error.code === 1014 ||
      // Test name field too, because code might not be present
      // Everything except Firefox
      error.name === 'QuotaExceededError' ||
      // Firefox
      error.name === 'NS_ERROR_DOM_QUOTA_REACHED') &&
      // Acknowledge QuotaExceededError only if there's something already stored
      (storage && storage.length !== 0);
  }
}

