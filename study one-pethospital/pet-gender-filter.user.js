// ==UserScript==
// @name         宠物医院 · 公母筛选
// @namespace    local.pethospital
// @version      1.0.0
// @description  给 pethospital.exe 内嵌网页增加客户端「公母」筛选（服务端忽略 gender）
// @author       local
// @match        http://127.0.0.1:8080/*
// @run-at       document-start
// @grant        none
// ==/UserScript==
(function () {
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
})();