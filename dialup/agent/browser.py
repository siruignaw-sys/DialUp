"""Thin Playwright wrapper. The agent refers to elements by number, not CSS selectors.

Every action returns an observation dict:
  {url, title, text, elements, page_hash, error}
"""
import asyncio
import hashlib

from playwright.async_api import async_playwright

MAX_TEXT = 6000
MAX_ELEMENTS = 120

_LABEL_JS = """
() => {
  document.querySelectorAll('[data-dialup-id]').forEach(e => e.removeAttribute('data-dialup-id'));
  const sel = 'a[href], button, input, select, textarea, [role=button], [role=link], [onclick]';
  const out = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (el.type === 'hidden' || el.disabled) continue;
    i += 1;
    el.setAttribute('data-dialup-id', String(i));
    const tag = el.tagName.toLowerCase();
    let label = (el.innerText || el.value || el.getAttribute('aria-label') ||
                 el.getAttribute('placeholder') || el.getAttribute('name') || el.title || '');
    const lab = (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) || el.closest('label');
    const hint = (lab && lab.innerText.trim()) || el.getAttribute('aria-label') ||
                 el.getAttribute('placeholder') || el.getAttribute('name') || el.id || '';
    if (tag === 'input' || tag === 'textarea') {
      label = hint + (el.value && el.type !== 'password' ? ` (current: ${el.value})` : '');
    }
    if (tag === 'select') {
      const opts = Array.from(el.options).map(o => o.text.trim()).slice(0, 15);
      const cur = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.trim() : '';
      label = `${hint} (current: ${cur}) options: ` + opts.join(' | ');
    }
    out.push({id: i, tag, type: el.type || '', label: String(label).trim().replace(/\\s+/g, ' ').slice(0, 100),
              href: (el.getAttribute('href') || '').slice(0, 80)});
    if (out.length >= %d) break;
  }
  return out;
}
""" % MAX_ELEMENTS


class Browser:
    def __init__(self, headless=True):
        self.headless = headless
        self._pw = None
        self._browser = None
        self.page = None

    async def start(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        ctx = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
        )
        self.page = await ctx.new_page()

    async def close(self):
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def _settle(self):
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(0.6)

    async def observe(self, error=None):
        url = self.page.url
        try:
            title = await self.page.title()
            text = await self.page.evaluate("() => document.body ? document.body.innerText : ''")
            elements = await self.page.evaluate(_LABEL_JS)
        except Exception as e:  # page mid-navigation, etc.
            title, text, elements = "", "", []
            error = error or f"could not read page: {e}"
        text = " ".join(text.split())
        page_hash = hashlib.sha1((url + "|" + text[:20000]).encode()).hexdigest()[:12]
        return {"url": url, "title": title, "text": text[:MAX_TEXT],
                "elements": elements, "page_hash": page_hash, "error": error}

    def _el(self, element_id):
        return self.page.locator(f'[data-dialup-id="{int(element_id)}"]').first

    async def navigate(self, url):
        if "://" not in url:
            url = "https://" + url
        try:
            await self.page.goto(url, timeout=20000, wait_until="domcontentloaded")
            await self._settle()
            return await self.observe()
        except Exception as e:
            return await self.observe(error=f"navigation failed: {e}")

    async def click(self, element_id):
        try:
            await self._el(element_id).click(timeout=6000)
            await self._settle()
            return await self.observe()
        except Exception as e:
            return await self.observe(error=f"click on [{element_id}] failed: {e}")

    async def type(self, element_id, text, submit=False):
        try:
            el = self._el(element_id)
            await el.fill(text, timeout=6000)
            if submit:
                await el.press("Enter")
                await self._settle()
            return await self.observe()
        except Exception as e:
            return await self.observe(error=f"typing into [{element_id}] failed: {e}")

    async def select(self, element_id, option):
        try:
            await self._el(element_id).select_option(label=option, timeout=6000)
            await self._settle()
            return await self.observe()
        except Exception as e:
            return await self.observe(error=f"selecting '{option}' in [{element_id}] failed: {e}")


def format_observation(obs):
    lines = [f"URL: {obs['url']}", f"TITLE: {obs['title']}"]
    if obs.get("error"):
        lines.append(f"ERROR: {obs['error']}")
    lines.append("ELEMENTS (use the number as element_id):")
    for e in obs["elements"]:
        kind = e["tag"] + (f"({e['type']})" if e["type"] and e["tag"] == "input" else "")
        href = f" -> {e['href']}" if e["href"] else ""
        lines.append(f"[{e['id']}] {kind} \"{e['label']}\"{href}")
    lines.append("PAGE TEXT:")
    lines.append(obs["text"] or "(empty)")
    return "\n".join(lines)
