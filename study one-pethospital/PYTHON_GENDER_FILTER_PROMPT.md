# Development Prompt: 宠物公母筛选工具（Python 版）

## Task

在不修改现有 Go 程序（`pethospital.exe`）与内嵌网页的前提下，用 **纯 Python 3 标准库**
实现一个命令行筛选工具：在**现有全部筛选能力之上增加「宠物公母（性别）」筛选**，
支持**终端打印输出**筛选结果、**统计总数**（公/母数量、花费汇总等），并可导出 CSV/JSON。

> 目标：补齐现有系统的缺口 —— 现有 API 与网页都**不支持**按性别筛选，本工具负责在
> Python 侧完成该筛选，并可与其余所有筛选条件自由组合。

## 背景事实（必须遵守，已实测）

1. 现有服务由 `pethospital.exe` 提供，默认监听 `http://127.0.0.1:8080`。
   运行 `python` 工具时该 exe **必须处于运行状态**（数据库文件被独占锁定，无法直接读取）。
2. 统一响应信封：

   ```json
   { "code": 200, "message": "ok", "data": { }, "time": "RFC3339" }
   ```

3. **关键限制：`GET /api/v1/pets` 的 `gender` 参数会被服务端忽略**。
   实测 `?gender=公` 返回的 `data.total` 仍为全量 1008，即**不能依赖服务端做性别过滤**。
   → 必须由 Python 拉取数据后在客户端过滤 `gender` 字段。
4. 性别取值来自 `/api/v1/meta`：`gender` 为 `["公","母"]`（仅这两个值）。
5. 列表接口 `GET /api/v1/pets` 返回结构：

   ```
   data.items[]       宠物对象数组
   data.total         命中总数
   data.page          当前页
   data.pageSize      每页条数（服务端上限 500，请求更大值会被钳制为 500）
   data.totalPages    总页数
   data.totalCost     命中集合的总花费
   ```

   → 拉全量需按页循环，`pageSize=500`，`total=1008` 时约 3 页。
6. 宠物对象字段：
   `id, name, species, breed, gender, ageMonths, color, chipNo, ownerName, ownerPhone,`
   `ownerAddr, doctor, disease, status, allergy, note, records[], charges[],`
   `totalCost, visitCount, createdAt, updatedAt`
7. 现有列表查询参数（工具需全部支持并可与性别组合）：
   `q, name, ownerName, ownerPhone, species, doctor, disease, status, min, max, sortBy, order, page, pageSize`
8. 现有高级查询接口（同样返回 `data.items`）：
   `/api/v1/pets/search?q=`、`/by-owner`、`/by-doctor`、`/by-species`、`/by-disease`、
   `/by-status`、`/top-spenders?limit=`、`/cost-range?min=&max=`
9. `/api/v1/export?format=json|csv` 可导出全量数据。

## Tech Stack

- Python 3.10+，**仅标准库**：`urllib.request`、`urllib.parse`、`json`、`argparse`、
  `csv`、`sys`、`os`、`datetime`、`unicodedata`、`collections`
- 禁止第三方依赖（不得使用 `requests`、`flask`、`pandas` 等）
- 平台：Windows（PowerShell / cmd），需正确处理中文与 UTF-8

## Deliverable

单个脚本文件 `pet_filter.py`（放在 `D:\study\windows\` 下），无其他新增文件亦可运行。

## Core Requirements

### 1. 性别筛选（核心新增）

- 支持 `--gender 公`、`--gender 母`、`--gender all`（默认 `all`，不筛选）
- 同时接受别名：`male/female/m/f/男/女`，内部统一映射到 `公`/`母`
- 非法取值给出明确报错并退出（退出码非 0）
- 过滤逻辑：对拉取到的每条 `item`，比较 `item["gender"] == 目标值`
- 映射表建议集中定义，便于后续扩展：

  ```python
  GENDER_ALIASES = {
      "公": "公", "male": "公", "m": "公", "男": "公",
      "母": "母", "female": "母", "f": "母", "女": "母",
      "all": None, "全部": None, "": None,
  }
  ```

### 2. 与现有全部筛选组合

命令行参数需覆盖现有能力，多个条件之间为 **AND** 关系：

| 参数 | 对应 API / 逻辑 |
| --- | --- |
| `--q` | `/api/v1/pets/search?q=` 全文检索 |
| `--name` | `name` 精确/包含 |
| `--owner` | `ownerName` |
| `--phone` | `ownerPhone` |
| `--species` | `species` |
| `--doctor` | `doctor` |
| `--disease` | `disease` |
| `--status` | `status` |
| `--min` / `--max` | 总花费区间 `min` / `max` |
| `--sort-by` / `--order` | `sortBy` / `order`（asc/desc） |
| `--gender` | **本地过滤（API 不支持）** |

实现建议：优先把服务端支持的参数原样透传给 `/api/v1/pets`（减少数据量），
再在本地叠加 `gender` 过滤；`--q` 走 `/search`，其余走 `/pets`。
无论走哪个接口，都要**分页拉全量**（`pageSize=500`）。

> 注意：`--q` 与 `--min/--max/--sort-by` 等若需同时生效，可先用 `/search` 拿到命中集，
> 再在本地对 `totalCost` 做区间与排序（因为 `/search` 不保证支持这些参数）。
> 反之亦可先用 `/pets` 透传全部服务端参数，再本地做 `q` 的子串匹配。二选一，
> 但必须保证最终结果是所有条件的**交集**。

### 3. 打印输出

- 默认输出一张对齐的中文表格，列至少包含：
  `ID / 姓名 / 性别 / 种类 / 品种 / 主人 / 电话 / 主治医生 / 疾病 / 状态 / 总花费 / 就诊次数`
- 中文列宽按显示宽度对齐（中日韩字符按 2 宽度计算，避免表格错位）
- 提供 `--limit N` 控制打印行数（默认 20，`0` 表示全部）
- 顶部打印本次筛选条件摘要
- 建议用 `unicodedata.east_asian_width` 计算宽度：

  ```python
  import unicodedata

  def disp_width(s: str) -> int:
      return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
                 for ch in s)

  def pad(s: str, width: int) -> str:
      s = "" if s is None else str(s)
      return s + " " * max(0, width - disp_width(s))

  def render_table(rows, columns):
      widths = []
      for col in columns:
          w = max([disp_width(col)] + [disp_width(r.get(col, "")) for r in rows])
          widths.append(w)
      header = " | ".join(pad(c, w) for c, w in zip(columns, widths))
      sep = "-+-".join("-" * w for w in widths)
      print(header)
      print(sep)
      for r in rows:
          print(" | ".join(pad(r.get(c, ""), w) for c, w in zip(columns, widths)))
  ```

- 空结果时打印「未找到符合条件的宠物」并正常退出（退出码 0）。

### 4. 统计总数

每次运行都要打印统计区块，至少包含：

- 命中总数（筛选后）
- **按性别分组计数**：公 = X 只，母 = Y 只
- 总花费合计、平均花费、最高/最低花费
- 若未指定 `--gender`，统计区块同样给出公/母分布
- 可选：按种类或状态的 Top N 分布（`--group-by species|status|doctor`）

建议统计实现（对筛选后的 `items`）：

```python
from collections import Counter

def summarize(items):
    total = len(items)
    genders = Counter(i.get("gender", "未知") for i in items)
    costs = [float(i.get("totalCost") or 0) for i in items]
    return {
        "total": total,
        "male": genders.get("公", 0),
        "female": genders.get("母", 0),
        "cost_sum": sum(costs),
        "cost_avg": (sum(costs) / total) if total else 0.0,
        "cost_max": max(costs) if costs else 0.0,
        "cost_min": min(costs) if costs else 0.0,
    }
```

### 5. 导出

- `--export-json FILE`：把筛选结果写成 UTF-8 JSON（`ensure_ascii=False`）
- `--export-csv FILE`：写 CSV，使用 `utf-8-sig` 以便 Excel 正确显示中文
- 导出内容为筛选后的完整结果，不受 `--limit` 影响
- CSV 表头建议与表格列一致，避免嵌套字段（`records`/`charges` 不展开，或仅 JSON 保留）

### 6. 健壮性

- 服务未启动 / 连接失败时，提示「请先运行 pethospital.exe」，退出码非 0，不抛裸异常堆栈
- 所有 HTTP 响应按 UTF-8 解码；Windows 控制台中文乱码时提示 `chcp 65001`
- 空结果时打印「未找到符合条件的宠物」而非崩溃
- `--base-url` 可覆盖默认 `http://127.0.0.1:8080`（便于换端口）
- 捕获 `urllib.error.URLError`、`socket.timeout`、`json.JSONDecodeError` 并给出中文提示

## 参考实现骨架

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宠物公母筛选工具：在服务端能力之上叠加客户端性别过滤。"""
import argparse, csv, json, sys, unicodedata
from collections import Counter
from urllib import request, parse, error

DEFAULT_BASE = "http://127.0.0.1:8080"
PAGE_SIZE = 500

GENDER_ALIASES = {
    "公": "公", "male": "公", "m": "公", "男": "公",
    "母": "母", "female": "母", "f": "母", "女": "母",
    "all": None, "全部": None, "": None,
}


def http_get_json(base, path, params=None):
    url = base.rstrip("/") + path
    if params:
        url += "?" + parse.urlencode({k: v for k, v in params.items()
                                      if v not in (None, "")})
    req = request.Request(url, headers={"Accept": "application/json"})
    with request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8")
    payload = json.loads(body)
    if payload.get("code") != 200:
        raise RuntimeError(payload.get("message", "接口返回异常"))
    return payload.get("data", {})


def fetch_all(base, path, params):
    """分页拉全量，pageSize=500。"""
    items, page = [], 1
    while True:
        p = dict(params or {})
        p.update({"page": page, "pageSize": PAGE_SIZE})
        data = http_get_json(base, path, p)
        batch = data.get("items") or []
        items.extend(batch)
        total_pages = data.get("totalPages") or 1
        if page >= total_pages or not batch:
            break
        page += 1
    return items


def normalize_gender(value):
    key = (value or "").strip().lower()
    if key not in GENDER_ALIASES:
        raise SystemExit(f"非法 --gender 取值：{value}（可选 公/母/all 或 male/female）")
    return GENDER_ALIASES[key]


def apply_local_filters(items, gender, min_cost, max_cost, sort_by, order):
    if gender:
        items = [i for i in items if i.get("gender") == gender]
    if min_cost is not None:
        items = [i for i in items if float(i.get("totalCost") or 0) >= min_cost]
    if max_cost is not None:
        items = [i for i in items if float(i.get("totalCost") or 0) <= max_cost]
    if sort_by:
        items.sort(key=lambda i: i.get(sort_by) or 0, reverse=(order == "desc"))
    return items


def main(argv=None):
    ap = argparse.ArgumentParser(description="宠物医院性别筛选工具")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--gender", default="all")
    ap.add_argument("--q"); ap.add_argument("--name"); ap.add_argument("--owner")
    ap.add_argument("--phone"); ap.add_argument("--species"); ap.add_argument("--doctor")
    ap.add_argument("--disease"); ap.add_argument("--status")
    ap.add_argument("--min", type=float); ap.add_argument("--max", type=float)
    ap.add_argument("--sort-by", default="totalCost")
    ap.add_argument("--order", choices=["asc", "desc"], default="desc")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--group-by", choices=["species", "status", "doctor"])
    ap.add_argument("--export-json"); ap.add_argument("--export-csv")
    args = ap.parse_args(argv)

    gender = normalize_gender(args.gender)
    params = {"name": args.name, "ownerName": args.owner,
              "ownerPhone": args.phone, "species": args.species,
              "doctor": args.doctor, "disease": args.disease, "status": args.status}
    path = "/api/v1/pets/search" if args.q else "/api/v1/pets"
    if args.q:
        params["q"] = args.q
    else:
        params.update({"min": args.min, "max": args.max,
                       "sortBy": args.sort_by, "order": args.order})
    try:
        items = fetch_all(args.base_url, path, params)
    except error.URLError as e:
        print("无法连接服务，请先运行 pethospital.exe 后重试。", file=sys.stderr)
        print(f"详情：{e}", file=sys.stderr)
        return 1
    items = apply_local_filters(items, gender, args.min, args.max,
                                args.sort_by, args.order)
    # ... 打印摘要 / 表格 / 统计 / 导出 ...
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## 输出样例

```text
筛选条件：性别=母 | 种类=猫 | 医生=李医生 | 排序=totalCost desc
────────────────────────────────────────────────────────────
ID          | 姓名   | 性别 | 种类 | 品种     | 主人   | ... | 总花费
PET-000123  | 咪咪   | 母   | 猫   | 英短     | 王芳   | ... | 3200
...
────────────────────────────────────────────────────────────
命中总数：37
性别分布：公 = 0 只，母 = 37 只
花费合计：¥86,540.00   平均：¥2,339.19   最高：¥9,800.00   最低：¥120.00
按种类分布：猫 = 37
```

## CLI 示例

```bash
# 只看母宠物
python pet_filter.py --gender 母

# 犬 + 公 + 花费 1000~5000，按总花费降序，打印全部
python pet_filter.py --species 犬 --gender 公 --min 1000 --max 5000 --sort-by totalCost --order desc --limit 0

# 某医生的母猫
python pet_filter.py --doctor 李医生 --species 猫 --gender female

# 全文检索 + 性别
python pet_filter.py --q 肠胃炎 --gender 公

# 统计公母分布并导出
python pet_filter.py --status 已康复 --gender all --group-by species --export-csv 康复宠物.csv

# 换端口
python pet_filter.py --base-url http://127.0.0.1:9090 --gender 公
```

## Acceptance Criteria

1. `python pet_filter.py --gender 母` 能打印出母宠物列表，且统计总数与列表条数一致。
2. 验证正确性：`--gender 公` 与 `--gender 母` 两次的命中数之和应等于不加性别筛选时的总数
   （当前测试库 1008 条，需实际核对）。
3. 性别可与 `species`/`doctor`/`status`/`min`/`max`/`q` 等任意组合，结果为交集。
4. 表格中文对齐正常，不出现错位；Windows 控制台可正常显示中文。
5. `--export-csv` 产物用 Excel 打开中文不乱码；`--export-json` 为合法 UTF-8 JSON。
6. 服务未启动时给出友好提示而非崩溃。
7. **零第三方依赖**，仅标准库；**不修改任何 Go 代码 / exe / 内嵌网页**。

## 自测脚本（PowerShell）

```powershell
# 1) 分别统计公/母，核对总数
python pet_filter.py --gender 公 --limit 0
python pet_filter.py --gender 母 --limit 0
python pet_filter.py --gender all --limit 0      # 应与上两者之和相等（1008）

# 2) 导出校验
python pet_filter.py --gender 母 --export-json out.json
python -c "import json;d=json.load(open('out.json',encoding='utf-8'));print(len(d))"
python pet_filter.py --gender 母 --export-csv out.csv

# 3) 失败路径（应友好报错，退出码非 0）
python pet_filter.py --base-url http://127.0.0.1:1 --gender 公
echo $LASTEXITCODE
```

## 交付检查清单

- [ ] `pet_filter.py` 可独立运行，仅标准库
- [ ] `--gender` 支持 `公/母/all` 及别名，非法值报错退出
- [ ] 分页拉全量（`pageSize=500`）无遗漏
- [ ] 性别与全部服务端筛选条件 AND 组合
- [ ] 中文表格按显示宽度对齐，`--limit 0` 打印全部
- [ ] 统计区块含公母分布与花费汇总
- [ ] CSV 为 `utf-8-sig`、JSON 为 `ensure_ascii=False`
- [ ] 服务未启动/空结果均有友好提示
- [ ] 未修改 `pethospital.exe`、Go 源码与内嵌网页

## Non-Goals

- 不修改 `pethospital.exe`、不反编译、不重建 Go 源码
- 不直接读写 `data/pet.db`（服务运行时文件被锁定）
- 不做网页界面（本次仅命令行工具）

## Verification Commands

```bash
python pet_filter.py --gender 公 --limit 5
python pet_filter.py --gender 母 --limit 5
python pet_filter.py --limit 0            # 统计公母分布，核对总数
python pet_filter.py --species 犬 --gender 公 --group-by status
python pet_filter.py --gender 公 --export-json out.json
python pet_filter.py --base-url http://127.0.0.1:1 --gender 公   # 应友好报错
```