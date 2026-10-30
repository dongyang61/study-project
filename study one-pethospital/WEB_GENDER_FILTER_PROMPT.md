# Development Prompt: 网页前端 · 宠物公母筛选（Tampermonkey 注入版）

## Task

在不修改 `pethospital.exe`、不反编译、不重新编译、不修改任何现有文件的前提下，
用一个 **Tampermonkey 用户脚本**，给 `pethospital.exe` 已内嵌的网页
`http://127.0.0.1:8080/` **增加「公母（性别）筛选」**，并让它与现有的
关键词 / 种类 / 医生 / 状态 / 排序 / 分页 全部自由组合。

> 背景：网页已编译进 exe，仓库里没有 `index.html` 源码；且服务端列表接口
> 会忽略 `gender` 参数。因此唯一可行路径是：浏览器侧脚本拦截列表请求，
> 在客户端完成性别过滤。本文件指导从零写出该脚本。

## 背景事实（已抓取真实页面源码 + 实测接口，必须遵守）

1. 页面地址 `http://127.0.0.1:8080/`，单页应用，**只有一个 `<script>` 标签且非 module**，
   因此 `load / render / resetFilters / api / state` 等函数都是**全局**的，
   行内 `onclick="load(1)"` 可直接调用。
2. API 前缀：`const API = '/api/v1';`
3. 请求封装（页面源码）：

   ```js
   async function api(path, opts){
     const r = await fetch(API+path, Object.assign({headers:{'Content-Type':'application/json'}}, opts));
     let j; try{ j = await r.json(); } catch { throw new Error('服务器返回异常'); }
     if(!r.ok) throw new Error(j.message || ('HTTP '+r.status));
     return j.data;
   }
   ```

4. 列表加载逻辑（页面源码）：

   ```js
   async function load(page){
     state.page = page || 1;
     const sort = $('#fSort').value.split(':');
     const p = new URLSearchParams({page: state.page, pageSize: state.pageSize, sortBy: sort[0], order: sort[1]});
     const q=$('#q').value.trim(), doc=$('#fDoctor').value.trim(), sp=$('#fSpecies').value, st=$('#fStatus').value;
     if(q) p.set('q', q); if(doc) p.set('doctor', doc); if(sp) p.set('species', sp); if(st) p.set('status', st);
     const d = await api('/pets?'+p);
     render(d);
     $('#countInfo').textContent = `共 ${d.total} 条 · 结果合计 ${yuan(d.totalCost)}`;
   }
   ```

5. `state = {page:1, pageSize:15, meta:null}` —— 前端默认每页 15 条。
6. `render(d)` 只依赖这些字段：`d.items`、`d.total`、`d.totalCost`、`d.page`、`d.totalPages`。
   `d.items[]` 每项用到 `id,name,species,ownerName,ownerPhone,disease,doctor,status,visitCount,totalCost`。
7. 筛选区 DOM 结构（`.filter-grid` 内）：

   | 控件 | id | 事件 |
   | --- | --- | --- |
   | 关键词 | `#q` | Enter → `load(1)` |
   | 种类 | `#fSpecies` | change → `load(1)` |
   | 主治医生 | `#fDoctor` | Enter → `load(1)` |
   | 就诊状态 | `#fStatus` | change → `load(1)` |
   | 排序方式 | `#fSort` | change → `load(1)` |

   按钮：「查询」`onclick="load(1)"`；「重置条件」`onclick="resetFilters()"`。
8. `resetFilters()` 会清空 `#q/#fDoctor/#fSpecies/#fStatus` 并重置排序，最后 `load(1)`。
9. 新增/编辑弹窗里有性别下拉（`f_gender`），但**列表筛选区没有性别**。
10. `/api/v1/meta` 的 `gender` 枚举为 `["公","母"]`。
11. 列表接口 `GET /api/v1/pets` 支持 `q,name,ownerName,ownerPhone,species,doctor,disease,status,min,max,sortBy,order,page,pageSize`；
    **`gender` 会被服务端忽略**：实测 `?gender=公` 仍返回 `data.total=1008`。
    服务端 `pageSize` 上限 500（请求更大值被钳制为 500）。
12. 实测全量分布（当前库）：**总数 1008，公 516，母 492**。
13. **服务端默认排序分页不稳定**：不带 `sortBy`（或按存在并列值的字段排序）翻页时，跨页会出现**重复与遗漏**。实测：默认排序拉 1008 条，唯一 id 仅 518 个；`sortBy=totalCost` 也可能因并列值不稳定。→ 客户端拉全量时**必须强制用唯一键排序** `sortBy=id&order=asc`，否则性别统计会出错。
14. 响应信封：`{ "code":200, "message":"ok", "data":{...}, "time":"RFC3339" }`。

## 技术路线

### 方案 A（推荐）：拦截 `window.fetch`

用用户脚本包装 `window.fetch`，只拦截 **GET `/api/v1/pets`** 这一条列表请求：

- **未选性别** → 原样调用原生 fetch，行为与原来完全一致。
- **选了性别** → 不再相信服务端那一页的结果，而是：
  1. 用原生 fetch 把该请求的**全部命中数据分页拉全**（保留 `q/doctor/species/status/...`，
     去掉 `page/pageSize`，改用 `pageSize=500` 循环，直到 `page > totalPages`；**并强制 `sortBy=id&order=asc`**，唯一键排序以避免服务端分页重复/遗漏）；
  2. 本地 `items.filter(it => it.gender === 目标值)`；
  3. 按 `sortBy/order` 本地排序（数值字段与字符串字段分别处理）；
  4. 按前端请求的 `page/pageSize` 切片；
  5. 重算 `total / totalPages / totalCost`，合成标准信封，用 `new Response(...)` 返回。

这样网页本身**完全无感**：它照常调 `api('/pets?...')`、照常 `render(d)`，
但拿到的已经是「按性别过滤后再分页」的正确结果，`#countInfo` 的条数与合计也会自动正确。

### 方案 B（备选）：包装全局 `load()`

注入性别下拉后，覆盖 `window.load`：读取 `#fGender`，若为空则调用原 `load`；
否则自行按上面第 1–5 步拉全量、过滤、分页，再调用全局 `render(d)` 并更新 `#countInfo`。
缺点是要复刻原 `load` 的参数拼装逻辑，页面改版易失效；**优先用方案 A**。

## 核心需求

### 1. 注入性别筛选控件

- 在 `.filter-grid` 内追加一个 `.field`，含 `<label>性别</label>` 与
  `<select id="fGender">`，选项：`全部`（value=""）、`公`、`母`。
- 复用页面既有 class（`field`/`label`/`select`），无需自定义样式，自动融入响应式布局。
- `change` 事件：把选择写入 `localStorage`（key 建议 `pethospital.gender`），然后 `window.load(1)`。
- 用 `MutationObserver` 或 `DOMContentLoaded` 等待 `.filter-grid` 出现再注入；
  若已存在则不要重复注入（用 `#fGender` 判重）。
- 覆盖 `window.resetFilters`，在调用原逻辑前清空 `#fGender` 与 localStorage。

### 2. 性别值规范化

- UI 只提供 `公`/`母`/全部；内部可兼容别名 `male/female/m/f/男/女` → `公/母`。
- 目标值为空字符串表示不筛选。

### 3. 请求拦截契约（方案 A 细节）

- 只处理：`method === 'GET'` 且 `new URL(input, location.origin).pathname === '/api/v1/pets'`。
- **必须放行**（直接 `origFetch`）：
  - `/api/v1/pets/{id}`、`/api/v1/pets/{id}/summary|records|charges`
  - `/api/v1/pets/search`、`/by-*`、`/top-spenders`、`/cost-range`
  - `/api/v1/meta`、`/api/v1/stats`、`/health`、`/api/v1/export`
  - 所有非 GET（POST/PUT/PATCH/DELETE）
- `input` 可能是字符串，也可能是 `Request` 对象；URL 解析要兼容两者。
- **防递归**：拉全量时必须调用保存的 `origFetch`，绝不能再走被包装的 `fetch`。
- 合成响应：

  ```js
  const env = { code:200, message:'ok', data, time:new Date().toISOString() };
  return new Response(JSON.stringify(env), {
    status: 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8' }
  });
  ```

- 拉取失败时兜底：`return origFetch(input, init)`，不要让页面白屏。

### 4. 排序

- 排序字段来自 `sortBy`（如 `createdAt`/`totalCost`/`visitCount`/`name`/`ownerName`），
  `order` 为 `asc`/`desc`。
- 数值字段（`totalCost`、`visitCount`、`ageMonths`；`createdAt`/`updatedAt` 为 ISO 字符串按字典序）
  与字符串字段分别处理；缺失值统一按 0 / 空串处理，避免 `NaN`。
- 中文姓名排序用 `localeCompare(..., 'zh-Hans-CN')`。

### 5. 分页与统计

- 过滤后 `total = filtered.length`；
  `totalPages = max(1, ceil(total / pageSize))`；
  `page` 保持请求值（越界时钳制到 `totalPages`）；
  `totalCost = Σ Number(item.totalCost||0)`（只统计过滤后的集合）。
- 空结果：`items:[]`，`total:0`，`totalPages:1`，`totalCost:0`，
  页面会自然显示「没有符合条件的档案」。

### 6. 持久化与刷新恢复

- 页面加载完成后读取 `localStorage`，回填 `#fGender`；若已有值，触发一次 `load(1)`，
  确保首屏就是过滤后的结果（因为页面 `boot()` 自带的 `load(1)` 发生在注入之前）。

## 参考实现骨架

```js
// ==UserScript==
// @name         宠物医院 · 公母筛选
// @namespace    local.pethospital
// @version      1.0.0
// @description  给内嵌网页增加客户端性别筛选（服务端忽略 gender）
// @match        http://127.0.0.1:8080/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==
(function () {
  'use strict';
  const API = '/api/v1';
  const KEY = 'pethospital.gender';
  const origFetch = window.fetch.bind(window);

  const getGender = () => localStorage.getItem(KEY) || '';

  async function pullAndFilter(urlStr) {
    const u = new URL(urlStr, location.origin);
    const base = new URLSearchParams(u.search);
    base.delete('page'); base.delete('pageSize');
    // 强制唯一键排序，规避服务端分页重复/遗漏
    base.set('sortBy', 'id'); base.set('order', 'asc');

    const all = [];
    let page = 1, totalPages = 1;
    do {
      const p = new URLSearchParams(base);
      p.set('page', String(page));
      p.set('pageSize', '500');
      const r = await origFetch(u.pathname + '?' + p, { headers: { Accept: 'application/json' } });
      const j = await r.json();
      const d = j.data || {};
      all.push(...(d.items || []));
      totalPages = d.totalPages || 1;
      page++;
    } while (page <= totalPages);

    const gender = getGender();
    const filtered = all.filter(it => it.gender === gender);

    const sortBy = u.searchParams.get('sortBy') || 'createdAt';
    const order  = u.searchParams.get('order')  || 'desc';
    const numKeys = new Set(['totalCost', 'visitCount', 'ageMonths']);
    filtered.sort((a, b) => {
      const av = a[sortBy], bv = b[sortBy];
      let c;
      if (numKeys.has(sortBy)) c = (Number(av) || 0) - (Number(bv) || 0);
      else c = String(av ?? '').localeCompare(String(bv ?? ''), 'zh-Hans-CN');
      return order === 'desc' ? -c : c;
    });

    const pageNo   = Math.max(1, parseInt(u.searchParams.get('page') || '1', 10));
    const pageSize = Math.max(1, parseInt(u.searchParams.get('pageSize') || '15', 10));
    const total = filtered.length;
    const totalPages2 = Math.max(1, Math.ceil(total / pageSize));
    const safePage = Math.min(pageNo, totalPages2);
    const start = (safePage - 1) * pageSize;
    const totalCost = filtered.reduce((s, it) => s + (Number(it.totalCost) || 0), 0);

    return {
      items: filtered.slice(start, start + pageSize),
      total, page: safePage, pageSize, totalPages: totalPages2, totalCost
    };
  }

  window.fetch = async function (input, init) {
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    const raw = typeof input === 'string' ? input : (input && input.url) || '';
    let u;
    try { u = new URL(raw, location.origin); } catch { return origFetch(input, init); }

    if (method !== 'GET' || u.pathname !== API + '/pets' || !getGender()) {
      return origFetch(input, init);
    }
    try {
      const data = await pullAndFilter(u.toString());
      const env = { code: 200, message: 'ok', data, time: new Date().toISOString() };
      return new Response(JSON.stringify(env), {
        status: 200, headers: { 'Content-Type': 'application/json; charset=utf-8' }
      });
    } catch (e) {
      return origFetch(input, init);
    }
  };

  function inject() {
    const grid = document.querySelector('.filter-grid');
    if (!grid || document.getElementById('fGender')) return;

    const field = document.createElement('div');
    field.className = 'field';
    field.innerHTML = '<label for="fGender">性别</label>' +
      '<select id="fGender">' +
      '<option value="">全部</option><option value="公">公</option><option value="母">母</option>' +
      '</select>';
    grid.appendChild(field);

    const sel = field.querySelector('select');
    sel.value = getGender();
    sel.addEventListener('change', () => {
      localStorage.setItem(KEY, sel.value);
      if (typeof window.load === 'function') window.load(1);
    });

    const origReset = window.resetFilters;
    window.resetFilters = function () {
      localStorage.removeItem(KEY);
      sel.value = '';
      if (typeof origReset === 'function') return origReset.apply(this, arguments);
    };

    if (getGender() && typeof window.load === 'function') window.load(1);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', inject);
  else inject();
})();
```

## 安装与使用

1. 浏览器安装 **Tampermonkey** 扩展。
2. 打开 Tampermonkey → 「添加新脚本」→ 用上面的内容替换模板 → `Ctrl+S` 保存。
3. 保持 `pethospital.exe` 运行，刷新 `http://127.0.0.1:8080/`。
4. 筛选区出现「性别」下拉；选「公」→「查询」，列表与合计条数立即变为公宠物。
5. 关闭/删除脚本后网页恢复原样。

## 输出样例

```text
筛选区：[关键词] [种类▾] [性别▾] [主治医生] [就诊状态▾] [排序方式▾]
选择「性别=母」后：
  共 492 条 · 结果合计 ¥xxx,xxx.xx
  （表格仅显示母宠物，分页总数为 ceil(492/15)=33 页）
```

## 验收标准

1. 页面筛选区出现「性别」下拉（全部 / 公 / 母），样式与其它筛选框一致，不错位。
2. 选「公」查询 → `#countInfo` 显示 `共 516 条`，表格仅公宠物；
   选「母」→ `共 492 条`；选「全部」→ `共 1008 条`。**516 + 492 = 1008**。
3. 性别与 关键词 / 种类 / 医生 / 状态 / 排序 任意组合，结果为**交集**。
4. 分页正确：总页数 = `ceil(过滤后总数 / 15)`，翻页数据连续、不重复、不漏。
5. 「重置条件」会清空性别选择并刷新为全部。
6. 刷新页面后保留上次性别选择（localStorage），首屏即过滤结果。
7. 新增 / 编辑 / 删除 / 查看病历明细 / 顶部统计卡片等**原有功能不受影响**。
8. **未修改 `pethospital.exe`、`data/pet.db` 或任何现有文件**；脚本可随时禁用移除。
9. 脚本**零外部依赖**（无 CDN、无第三方库），离线可用。

## 自测脚本

浏览器 F12 控制台：

```js
// 原始服务端分布（绕过拦截）
await fetch('/api/v1/pets?page=1&pageSize=1').then(r=>r.json()).then(j=>console.log(j.data.total)); // 1008

// 在页面里分别选择性别后观察 #countInfo
// 公 → 516，母 → 492，全部 → 1008
document.querySelector('#countInfo').textContent;
```

PowerShell（服务端真实分布，独立核对）：

```powershell
$items=@(); for($p=1;$p -le 3;$p++){ $r=Invoke-RestMethod "http://127.0.0.1:8080/api/v1/pets?page=$p&pageSize=500"; $items+=$r.data.items }
$exp = Invoke-RestMethod "http://127.0.0.1:8080/api/v1/export?format=json"; $items = if($exp.data.items){$exp.data.items}else{$exp.data}`n"总数=$($items.Count)"; "公=$(($items|?{$_.gender -eq '公'}).Count)"; "母=$(($items|?{$_.gender -eq '母'}).Count)"
```

## 交付检查清单

- [ ] 单文件用户脚本，含正确 `==UserScript==` 头与 `@match http://127.0.0.1:8080/*`
- [ ] 只拦截 GET `/api/v1/pets`，其余请求全部放行
- [ ] 无性别条件时零副作用（与原网页行为一致）
- [ ] 有性别条件时拉全量 → 过滤 → 排序 → 分页 → 合成信封
- [ ] 防递归（内部使用保存的原生 fetch）
- [ ] `total/totalPages/totalCost` 与过滤后集合一致
- [ ] 性别下拉注入、resetFilters 清理、localStorage 持久化
- [ ] 未修改 exe / 数据库 / 任何现有文件

## Non-Goals

- 不修改 `pethospital.exe`、不反编译、不重建 Go 源码
- 不改动服务端接口，不写入/修改任何宠物数据（仅只读 GET）
- 不引入任何第三方库或 CDN
- 不重写整个网页，只做最小侵入式增强

## Verification Commands

```powershell
# 服务端真实分布（应为 1008 / 516 / 492；用 export 一次性取权威数据）
$exp = Invoke-RestMethod "http://127.0.0.1:8080/api/v1/export?format=json"; $items = if($exp.data.items){$exp.data.items}else{$exp.data}
"总数=$($items.Count) 公=$(($items|?{$_.gender -eq '公'}).Count) 母=$(($items|?{$_.gender -eq '母'}).Count)"

# 确认服务端确实忽略 gender（应仍为 1008）
(Invoke-RestMethod 'http://127.0.0.1:8080/api/v1/pets?gender=公&page=1&pageSize=1').data.total
```