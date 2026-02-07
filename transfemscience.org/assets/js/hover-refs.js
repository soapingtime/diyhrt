/**
 * Hover References Feature
 * 
 * Matches inline citation links with their corresponding full reference
 * from the reference list by comparing URLs (hrefs).
 */

(function () {
  document.addEventListener('DOMContentLoaded', function () {
    initHoverReferences();
  });

  function initHoverReferences() {
    // 1. Find the References section and list
    const referencesHeader = findReferencesHeader();
    if (!referencesHeader) return;

    // Helper to normalize URLs for matching
    // 1. Decode URI (handles %5B vs [ mismatch)
    // 2. Lowercase
    const normalizeRefUrl = (url) => {
      let u = "";
      try {
        u = decodeURI(url).toLowerCase();
      } catch (e) {
        u = url.toLowerCase();
      }
      u = u.replace(/^(https?:)?\/\//, '').replace(/^www\./, '');

      // Check for archive.org URL (e.g. web.archive.org/web/20070430161048/http://... or .../20210717084442if_/...)
      const archiveRegex = /^web\.archive\.org\/web\/\d+(?:if_)?\//;
      if (archiveRegex.test(u)) {
        u = u.replace(archiveRegex, '');
        // Re-strip protocol and www from the target URL
        u = u.replace(/^(https?:)?\/\//, '').replace(/^www\./, '');
      }

      return u.split('#')[0].replace(/\/$/, '');
    };

    // Find all reference lists within the References section
    // The References section might have subsections, each with their own list
    // We need to find the container element that encompasses all References content

    // Strategy: Find the parent section/container, or collect all siblings until next same-level header
    let referenceLists = [];
    let currentElement = referencesHeader.nextElementSibling;
    const headerLevel = parseInt(referencesHeader.tagName.charAt(1)) || 2;

    while (currentElement) {
      // Stop if we hit another header of same or higher level (lower number)
      if (/^H[1-6]$/.test(currentElement.tagName)) {
        const currentLevel = parseInt(currentElement.tagName.charAt(1));
        if (currentLevel <= headerLevel) {
          break; // End of References section
        }
      }

      // Collect all UL and OL elements (including nested ones in subsections)
      if (currentElement.tagName === 'UL' || currentElement.tagName === 'OL') {
        referenceLists.push(currentElement);
      }
      // Also check for lists inside divs or other container elements
      const nestedLists = currentElement.querySelectorAll('ul, ol');
      nestedLists.forEach(list => referenceLists.push(list));

      currentElement = currentElement.nextElementSibling;
    }

    if (referenceLists.length === 0) return;

    // 2. Parse all reference list items from all lists
    // Map of "URL" -> HTML content
    const urlMap = new Map();

    referenceLists.forEach(referenceList => {
      const listItems = referenceList.querySelectorAll(':scope > li'); // Direct children only to avoid duplicates

      listItems.forEach(item => {
        // Find all links in the reference item
        const links = item.querySelectorAll('a');
        links.forEach(link => {
          const rawHref = link.getAttribute('href');
          if (rawHref && !rawHref.startsWith('#')) { // Ignore anchor links if any
            const href = normalizeRefUrl(rawHref); // Normalized for storage
            // Store the item HTML for this URL
            // If multiple refs share a URL (unlikely but possible), the last one wins, 
            // or we could store an array. For citations, usually unique DOI/URL per ref.
            urlMap.set(href, item.innerHTML);
          }
        });
      });
    });

    // 3. Find inline citation links
    // We look for links inside the article body
    const articleBody = document.getElementById('article');
    if (!articleBody) return;

    const links = articleBody.querySelectorAll('a');

    // Create the hover box element
    const hoverBox = document.createElement('div');
    hoverBox.classList.add('reference-hover-box');
    hoverBox.style.display = 'none';
    document.body.appendChild(hoverBox);

    let hideTimeout;

    // Keep box open when hovering over it
    hoverBox.addEventListener('mouseenter', () => {
      if (hideTimeout) clearTimeout(hideTimeout);
    });

    hoverBox.addEventListener('mouseleave', () => {
      hideTimeout = setTimeout(() => {
        hoverBox.style.display = 'none';
      }, 100);
    });

    links.forEach(link => {
      const rawHref = link.getAttribute('href');

      // Skip links inside any of the reference lists
      const isInReferenceList = referenceLists.some(list => list.contains(link));
      if (isInReferenceList) return;

      // We only care if the link HAS an href and it's in our map
      if (rawHref && !rawHref.startsWith('#')) {
        const exactHref = normalizeRefUrl(rawHref);
        const baseHref = exactHref.split('#')[0];

        let bestMatchHTML = urlMap.get(exactHref);
        if (!bestMatchHTML) {
          bestMatchHTML = urlMap.get(baseHref);
        }

        // Fallback for unmatched links (e.g. Wiki links, or refs without date/year)
        // User requested to show just the URL, but ONLY if it looks like a ref (in parentheses)
        if (!bestMatchHTML) {
          // Check if the link itself contains parentheses with a year (e.g. "(2005)" or "(2005a)" or "(Aly, 2020)")
          // We allow other text inside the parens, but it MUST contain a year-like number.
          const yearParensRegex = /\([^)]*\b\d{4}[a-z]?\b[^)]*\)/i;
          const textHasParens = link.textContent.includes('(') || link.textContent.includes(')');
          const textMatchingParensYear = yearParensRegex.test(link.textContent);

          // Check if enclosed in parentheses or brackets by walking siblings
          let isEnclosed = false;
          // We only scan if:
          // 1. The text itself doesn't contain matching parens (if it does, we already know if it's valid or not)
          // OR
          // 2. The text doesn't contain parens at all (so we look for surrounding ones)

          if (!textMatchingParensYear && !textHasParens) {
            // If text has parens but didn't match yearParensRegex, it's invalid (e.g. "Kuhl (Citation)")
            // So we only scan if text does NOT have parens.

            let openParenCount = 0;
            let openBracketCount = 0;
            let foundOpen = false;

            let curr = link.previousSibling;
            let scans = 0;
            const MAX_SCANS = 100; // Reasonable lookbehind limit

            while (curr && scans < MAX_SCANS) {
              if (curr.nodeType === 3) { // Text node
                const txt = curr.textContent;
                // Count parens from right to left
                for (let i = txt.length - 1; i >= 0; i--) {
                  const c = txt[i];
                  if (c === ')') openParenCount--;
                  else if (c === '(') openParenCount++;
                  else if (c === ']') openBracketCount--;
                  else if (c === '[') openBracketCount++;

                  if (openParenCount > 0 || openBracketCount > 0) {
                    foundOpen = true;
                    break;
                  }
                }
              } else if (curr.nodeType === 1) { // Element node
                const tagName = curr.tagName;
                // Stop at block boundaries
                if (/^(DIV|P|BODY|MAIN|SECTION|BLOCKQUOTE|UL|OL|LI|TABLE|BR|HR|H[1-6])$/.test(tagName)) {
                  break;
                }
                // Check text content of inline elements
                const txt = curr.textContent;
                for (let i = txt.length - 1; i >= 0; i--) {
                  const c = txt[i];
                  if (c === ')') openParenCount--;
                  else if (c === '(') openParenCount++;
                  else if (c === ']') openBracketCount--;
                  else if (c === '[') openBracketCount++;

                  if (openParenCount > 0 || openBracketCount > 0) {
                    foundOpen = true;
                    break;
                  }
                }
              }

              if (foundOpen) break;
              curr = curr.previousSibling;
              scans++;
            }

            if (foundOpen) {
              isEnclosed = true;
            }
          }

          if (textMatchingParensYear || isEnclosed) {
            let displayUrl = rawHref;
            if (rawHref.startsWith('/')) {
              displayUrl = 'https://transfemscience.org' + rawHref;
            }
            bestMatchHTML = `<div class="fallback-url-content"><a href="${rawHref}" target="_blank">${displayUrl}</a></div>`;
          }
        }

        if (bestMatchHTML) {

          link.classList.add('reference-link');

          link.addEventListener('mouseenter', (e) => {
            // Clear any pending hide timeout
            if (hideTimeout) clearTimeout(hideTimeout);

            hoverBox.innerHTML = bestMatchHTML;
            hoverBox.style.display = 'block';

            // Use getClientRects to handle multi-line links; find the rect under the mouse
            const rects = link.getClientRects();
            let rect = rects.length > 0 ? rects[0] : link.getBoundingClientRect();

            // Find the rect that contains the mouse Y position
            if (rects.length > 1) {
              let bestRect = rects[0];
              let minDistance = Infinity;

              for (let i = 0; i < rects.length; i++) {
                const r = rects[i];
                // Check if mouse Y is within this rect's vertical bounds
                if (e.clientY >= r.top && e.clientY <= r.bottom) {
                  bestRect = r;
                  break; // Found exact line match
                }

                // Fallback: distance to vertical center
                const centerY = r.top + (r.height / 2);
                const dist = Math.abs(e.clientY - centerY);
                if (dist < minDistance) {
                  minDistance = dist;
                  bestRect = r;
                }
              }
              rect = bestRect;
            }

            // Positioning
            let top = rect.bottom + window.scrollY; // 0px gap
            let left = rect.left + window.scrollX;

            // Boundary checks
            if (left + hoverBox.offsetWidth > window.innerWidth) {
              left = window.innerWidth - hoverBox.offsetWidth - 10;
            }

            hoverBox.style.top = `${top}px`;
            hoverBox.style.left = `${left}px`;
          });

          link.addEventListener('mouseleave', () => {
            // Set a timeout to hide the box, giving time to move into it
            hideTimeout = setTimeout(() => {
              hoverBox.style.display = 'none';
            }, 100);

            // Mobile Long Press Support (Touch) AND Desktop Click-and-Hold
            let longPressTimer;
            let isLongPress = false;

            const startPress = (e) => {
              // Only left click for mouse (button 0)
              if (e.type === 'mousedown' && e.button !== 0) return;

              isLongPress = false;
              longPressTimer = setTimeout(() => {
                isLongPress = true;

                // Show hover box
                if (hideTimeout) clearTimeout(hideTimeout);
                hoverBox.innerHTML = bestMatchHTML;
                hoverBox.style.display = 'block';

                hoverBox.style.display = 'block';

                const rects = link.getClientRects();
                const rect = rects.length > 0 ? rects[0] : link.getBoundingClientRect();

                let top = rect.bottom + window.scrollY;
                let left = rect.left + window.scrollX;

                if (left + hoverBox.offsetWidth > window.innerWidth) {
                  left = window.innerWidth - hoverBox.offsetWidth - 10;
                }

                hoverBox.style.top = `${top}px`;
                hoverBox.style.left = `${left}px`;

              }, 500); // 500ms for long press
            };

            const cancelPress = () => {
              clearTimeout(longPressTimer);
            };

            const endPress = (e) => {
              clearTimeout(longPressTimer);
              if (isLongPress) {
                e.preventDefault(); // Prevent default action (click/navigate)
                // Note for desktop: 'click' event might still fire after mouseup if we don't prevent it there too
              }
            };

            // Touch Listeners
            link.addEventListener('touchstart', startPress, { passive: true });
            link.addEventListener('touchend', endPress);
            link.addEventListener('touchmove', cancelPress);

            // Mouse Listeners (Desktop)
            link.addEventListener('mousedown', startPress);
            link.addEventListener('mouseup', endPress);
            link.addEventListener('mouseleave', cancelPress);

            link.addEventListener('click', (e) => {
              if (isLongPress) {
                e.preventDefault();
                e.stopPropagation();
                isLongPress = false; // Reset
              }
            });

            link.addEventListener('contextmenu', (e) => {
              if (isLongPress) {
                e.preventDefault(); // Prevent default context menu
                isLongPress = false; // Reset
              }
            });
          });
        }
      }
    });
  }

  function findReferencesHeader() {
    // Try by ID first
    let header = document.getElementById('references');
    if (header) return header;

    // Try by text content
    const headers = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
    for (const h of headers) {
      if (h.textContent.trim().toLowerCase() === 'references') {
        return h;
      }
    }
    return null;
  }

})();
