// auth.js — optional DASHBOARD_TOKEN support.
// Loaded first on every page. Adds X-Dashboard-Token to same-origin /api/ calls
// and mirrors the token into a SameSite=Strict cookie so the WebSocket
// handshake (which cannot set headers) carries it too.
(function () {
    const KEY = 'dashboard_token';
    const store = {
        get() { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } },
        set(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* ignore */ } },
    };

    function setCookie(token) {
        document.cookie = `${KEY}=${encodeURIComponent(token)}; path=/; SameSite=Strict`;
    }

    function promptForToken() {
        const t = window.prompt('This dashboard is protected. Enter the DASHBOARD_TOKEN:');
        if (t) { store.set(t.trim()); setCookie(t.trim()); }
        return !!t;
    }

    const saved = store.get();
    if (saved) setCookie(saved);

    const nativeFetch = window.fetch.bind(window);
    window.fetch = async function (input, init) {
        const url = typeof input === 'string' ? input : input.url;
        const isApi = url.startsWith('/api/') || url.startsWith(window.location.origin + '/api/');
        if (!isApi) return nativeFetch(input, init);

        const send = () => {
            const opts = Object.assign({}, init);
            const headers = new Headers(opts.headers || (typeof input !== 'string' ? input.headers : undefined));
            const tok = store.get();
            if (tok) headers.set('X-Dashboard-Token', tok);
            opts.headers = headers;
            return nativeFetch(input, opts);
        };
        let res = await send();
        if (res.status === 401 && promptForToken()) res = await send();
        return res;
    };

    window.dashboardAuth = { getToken: store.get, promptForToken };
})();
