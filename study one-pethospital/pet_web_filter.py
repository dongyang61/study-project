#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宠物医院网页性别筛选 · 本地注入代理（零依赖，仅标准库）

在 pethospital.exe(8080) 前面加一层本地代理：网页原样转发，但在 HTML 末尾
自动注入一段脚本，为内嵌网页增加「公母（性别）筛选」。

无需浏览器扩展、不修改 exe / 网页 / 数据库。pethospital.exe 需保持运行。

用法:
    python pet_web_filter.py
    然后浏览器打开  http://127.0.0.1:8081/

    python pet_web_filter.py --listen 127.0.0.1:8081 --upstream http://127.0.0.1:8080
"""
import argparse
import http.server
import socket
import sys
import urllib.error
import urllib.request

# 注入到网页 </body> 前的脚本（与服务端无关，纯客户端拦截 /api/v1/pets 做性别过滤）
INJECT_JS = r'''(function () {
  'use strict';

  var API = '/api/v1';
  var KEY = 'pethospital.gender';
  var PAGE_SIZE = 500;
  var NUM_KEYS = { totalCost: 1, visitCount: 1, ageMonths: 1 };

  var GENDER_ALIASES = {
    '公': '公', 'male': '公', 'm': '公', '男': '公',
    '母': '母', 'female': '母', 'f': '母', '女': '母'
  };

  var origFetch = window.fetch.bind(window);

  function normalizeGender(value) {
    var key = String(value == null ? '' : value).trim().toLowerCase();
    return GENDER_ALIASES[key] || '';
  }

  function getGender() {
    try { return normalizeGender(localStorage.getItem(KEY)); } catch (e) { return ''; }
  }

  function setGender(value) {
    try {
      if (value) localStorage.setItem(KEY, value);
      else localStorage.removeItem(KEY);
    } catch (e) { /* localStorage 不可用时忽略 */ }
  }

  function pullAll(urlStr) {
    var u = new URL(urlStr, location.origin);
    var base = new URLSearchParams(u.search);
    base.delete('page');
    base.delete('pageSize');
    // 用唯一键 id 排序，规避服务端默认排序分页不稳定（跨页重复/遗漏）
    base.set('sortBy', 'id');
    base.set('order', 'asc');

    var all = [];
    var page = 1;
    var totalPages = 1;
    return (function step() {
      var p = new URLSearchParams(base);
      p.set('page', String(page));
      p.set('pageSize', String(PAGE_SIZE));
      return origFetch(u.origin + u.pathname + '?' + p.toString(), {
        headers: { Accept: 'application/json' }
      }).then(function (r) {
        return r.json();
      }).then(function (j) {
        var d = (j && j.data) || {};
        var batch = d.items || [];
        for (var i = 0; i < batch.length; i++) all.push(batch[i]);
        totalPages = d.totalPages || 1;
        page++;
        if (page <= totalPages) return step();
        return all;
      });
    })();
  }

  function sortItems(items, sortBy, order) {
    var desc = order === 'desc';
    items.sort(function (a, b) {
      var av = a ? a[sortBy] : undefined;
      var bv = b ? b[sortBy] : undefined;
      var c;
      if (NUM_KEYS[sortBy]) {
        c = (Number(av) || 0) - (Number(bv) || 0);
      } else {
        c = String(av == null ? '' : av).localeCompare(String(bv == null ? '' : bv), 'zh-Hans-CN');
      }
      return desc ? -c : c;
    });
    return items;
  }

  function pullAndFilter(urlStr) {
    var u = new URL(urlStr, location.origin);
    var gender = getGender();
    return pullAll(urlStr).then(function (all) {
      var filtered = all.filter(function (it) { return it && it.gender === gender; });

      var sortBy = u.searchParams.get('sortBy') || 'createdAt';
      var order = u.searchParams.get('order') || 'desc';
      sortItems(filtered, sortBy, order);

      var pageNo = Math.max(1, parseInt(u.searchParams.get('page') || '1', 10) || 1);
      var pageSize = Math.max(1, parseInt(u.searchParams.get('pageSize') || '15', 10) || 15);
      var total = filtered.length;
      var totalPages = Math.max(1, Math.ceil(total / pageSize));
      var safePage = Math.min(pageNo, totalPages);
      var start = (safePage - 1) * pageSize;
      var totalCost = filtered.reduce(function (s, it) {
        return s + (Number(it && it.totalCost) || 0);
      }, 0);

      return {
        items: filtered.slice(start, start + pageSize),
        total: total,
        page: safePage,
        pageSize: pageSize,
        totalPages: totalPages,
        totalCost: totalCost
      };
    });
  }

  window.fetch = function (input, init) {
    var method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    var raw = typeof input === 'string' ? input : (input && input.url) || '';
    var u;
    try { u = new URL(raw, location.origin); } catch (e) { return origFetch(input, init); }

    if (method !== 'GET' || u.pathname !== API + '/pets' || !getGender()) {
      return origFetch(input, init);
    }

    return pullAndFilter(u.toString()).then(function (data) {
      var env = { code: 200, message: 'ok', data: data, time: new Date().toISOString() };
      return new Response(JSON.stringify(env), {
        status: 200,
        headers: { 'Content-Type': 'application/json; charset=utf-8' }
      });
    }).catch(function () {
      return origFetch(input, init);
    });
  };

  function injectUI() {
    var grid = document.querySelector('.filter-grid');
    if (!grid || document.getElementById('fGender')) return false;

    var field = document.createElement('div');
    field.className = 'field';
    field.innerHTML =
      '<label for="fGender">性别</label>' +
      '<select id="fGender">' +
      '<option value="">全部</option>' +
      '<option value="公">公</option>' +
      '<option value="母">母</option>' +
      '</select>';
    grid.appendChild(field);

    var sel = field.querySelector('select');
    sel.value = getGender();
    sel.addEventListener('change', function () {
      setGender(sel.value);
      if (typeof window.load === 'function') window.load(1);
    });

    if (typeof window.resetFilters === 'function' && !window.resetFilters.__genderPatched) {
      var origReset = window.resetFilters;
      var patched = function () {
        setGender('');
        sel.value = '';
        return origReset.apply(this, arguments);
      };
      patched.__genderPatched = true;
      window.resetFilters = patched;
    }

    if (getGender() && typeof window.load === 'function') window.load(1);
    return true;
  }

  function boot() {
    if (injectUI()) return;
    var tries = 0;
    var timer = setInterval(function () {
      tries++;
      if (injectUI() || tries > 60) clearInterval(timer);
    }, 100);
    if (typeof MutationObserver === 'function') {
      var mo = new MutationObserver(function () {
        if (injectUI()) mo.disconnect();
      });
      mo.observe(document.documentElement || document, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();'''

INJECT_TAG = "\n<script>\n" + INJECT_JS + "\n</script>\n"

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "host", "content-length", "accept-encoding",
}


def parse_addr(text):
    host, _, port = text.rpartition(":")
    return (host or "127.0.0.1", int(port))


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream = "http://127.0.0.1:8080"
    inject_tag = INJECT_TAG

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    def _proxy(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        url = self.upstream + self.path
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["Accept-Encoding"] = "identity"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                self._send(resp.status, resp.headers, data, method)
        except urllib.error.HTTPError as e:
            data = e.read()
            self._send(e.code, e.headers, data, method)
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            msg = ("无法连接上游 %s，请先运行 pethospital.exe。\n详情: %s\n"
                   % (self.upstream, e)).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(msg)

    def _send(self, status, resp_headers, data, method):
        ctype = resp_headers.get("Content-Type", "")
        if method == "GET" and "text/html" in ctype.lower():
            text = data.decode("utf-8", "replace")
            if "</body>" in text:
                text = text.replace("</body>", self.inject_tag + "</body>", 1)
            else:
                text += self.inject_tag
            data = text.encode("utf-8")

        self.send_response(status)
        for k, v in resp_headers.items():
            lk = k.lower()
            if lk in HOP_BY_HOP or lk == "content-encoding":
                continue
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        self._proxy("GET")

    def do_HEAD(self):
        self._proxy("HEAD")

    def do_POST(self):
        self._proxy("POST")

    def do_PUT(self):
        self._proxy("PUT")

    def do_PATCH(self):
        self._proxy("PATCH")

    def do_DELETE(self):
        self._proxy("DELETE")


def main(argv=None):
    ap = argparse.ArgumentParser(description="宠物医院网页性别筛选注入代理")
    ap.add_argument("--listen", default="127.0.0.1:8081",
                    help="本地监听地址，默认 127.0.0.1:8081")
    ap.add_argument("--upstream", default="http://127.0.0.1:8080",
                    help="pethospital.exe 地址，默认 http://127.0.0.1:8080")
    args = ap.parse_args(argv)

    host, port = parse_addr(args.listen)
    Handler.upstream = args.upstream.rstrip("/")

    try:
        with urllib.request.urlopen(Handler.upstream + "/health", timeout=3) as r:
            r.read()
    except Exception as e:
        print("警告：暂时连不上 %s（%s）。请先运行 pethospital.exe。"
              % (Handler.upstream, e), file=sys.stderr)

    srv = http.server.ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    print("")
    print("  宠物医院 · 性别筛选注入代理已启动")
    print("  ------------------------------------------------")
    print("  请在浏览器打开：  http://%s:%d/" % (host, port))
    print("  上游服务：        %s" % Handler.upstream)
    print("  按 Ctrl+C 退出")
    print("")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())