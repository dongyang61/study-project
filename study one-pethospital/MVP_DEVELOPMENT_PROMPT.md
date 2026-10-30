# MVP Development Prompt: 宠物医院 · Pet Hospital (Go)

## Task

从零实现一个**单文件可迁移**的本地宠物医院管理系统（Go + 标准库 + 零第三方依赖），
交付一个可双击运行的 `pethospital.exe`：内置网页操作界面 + 完整 REST API +
单文件嵌入式数据库 `data/pet.db` + 可复现的模拟数据生成器。

> 目标成果等价于本目录已发布的 `pethospital.exe`（见 `README-Windows.md` 运行说明），
> 本文档是指导从零重建该项目的 MVP 开发提示。

## Tech Stack

- 语言：Go 1.22+（使用增强型 `ServeMux` 路由）
- 依赖：**仅 Go 标准库**，`go build` 即可，禁止第三方包
- 存储：自研单文件嵌入式数据库，append-only log + CRC32 校验 + 内存索引 + 自动压实
- 前端：单文件 `index.html` 内嵌进可执行文件（`embed`），无外部 css/js/html 文件
- 目标平台：Windows amd64（另支持 Linux / macOS 交叉编译）

## Project Structure

```
.
├── main.go                  启动横幅、服务网址、优雅退出（Ctrl+C 自动压实落盘）
├── go.mod
├── Makefile                 构建与发行命令（make help）
├── build.sh                 构建脚本（无需 make）
└── internal/
    ├── model/model.go       数据模型与校验
    ├── store/store.go       单文件嵌入式数据库引擎
    └── api/
        ├── api.go           REST 路由与处理器
        ├── generate.go      大批量模拟数据生成器
        ├── support.go       ANSI 着色、手工精选数据
        ├── web.go           网页路由（embed 内嵌）
        └── web/index.html   网页界面（单文件）
```

## Core Requirements

### 1. 数据模型 (Pet)

字段：宠物姓名、种类、品种、性别、月龄、毛色、芯片号、主人姓名、电话、住址、
主治医生、疾病、就诊状态、过敏史，以及历史病历 `records[]` 与消费明细 `charges[]`。

派生字段（只读，自动汇总）：

| 字段 | 说明 |
| --- | --- |
| `totalCost` | 总花费金额 = `charges[].amount` 之和 |
| `visitCount` | 就诊次数 = `records` 条数 |

### 2. 单文件数据库引擎 (store)

- 追加写日志（append-only）+ CRC32 校验 + 内存 map 索引
- 自动压实（compaction）回收日志垃圾（超阈值时原子重写：`pet.db.tmp` → `rename`）
- 崩溃安全：`fsync` 落盘、写临时文件后 rename
- 损坏自愈：启动回放日志，CRC 或长度异常时截断到最后一个完整记录
- 写入位置在内存维护（写 `WriteAt` 定位写），批量写入每 500 条才 `fsync` 一次
- 文件格式：Header 32B（magic `"PETDBv1\n"` + version u32 + flags u32）+ 顺序记录区
  `[len u32][crc32 u32][json payload]`，payload 为 `{"op":"put|del","id":"...","data":{}}`
- 同库文件与 macOS/Linux 版完全通用

### 3. REST API（29 个接口）

统一响应信封：`{ "code": 200, "message": "ok", "data": {...}, "time": "RFC3339" }`

**系统与统计**：`GET /`（网页）、`GET /health`、`GET /api/v1/endpoints`（接口清单）、
`GET /api/v1/meta`（枚举字典）、`GET /api/v1/stats`（收入/种类/医生排行）

**档案 CRUD**：`GET|POST /api/v1/pets`、`GET|PUT|PATCH|DELETE /api/v1/pets/{id}`
（`id` 自动生成 `PET-000001`；PUT 全量替换、PATCH 局部更新）

**高级查询**：`GET /api/v1/pets/search?q=`（全文检索，空格分词 AND，含病历全文）、
`/by-owner?ownerName=&phone=`、`/by-doctor?doctor=`、`/by-species?species=`、
`/by-disease?disease=`、`/by-status?status=`、`/top-spenders?limit=`、
`/cost-range?min=&max=`

**历史病历/消费明细**：`GET|POST /api/v1/pets/{id}/records`、
`GET|POST /api/v1/pets/{id}/charges`（追加收费自动累计总花费）、
`GET /api/v1/pets/{id}/summary`

**批量/导出/管理**：`POST /api/v1/pets/batch`、`POST /api/v1/pets/batch-delete`、
`GET /api/v1/export?format=json|csv`、`POST /api/v1/admin/compact`、
`POST /api/v1/admin/seed?force=true&count=N`

### 4. 列表查询参数

`GET /api/v1/pets` 支持：`q` `name` `ownerName` `ownerPhone` `species` `gender` `doctor`
`disease` `status` `min` `max` `sortBy` `order` `page` `pageSize`（`gender` 取值：`公` / `母`）。

示例：`curl 'http://127.0.0.1:8080/api/v1/pets?species=犬&gender=公&min=1000&sortBy=totalCost&order=desc&page=1&pageSize=10'`

### 5. 网页操作界面（web/index.html）

- 档案列表与搜索、按种类/医生/状态筛选、排序、分页
- 新增 / 编辑 / 删除档案（带表单校验与错误提示）
- 点开档案查看历史病历与消费明细，以及费用汇总
- 顶部实时展示档案数、病历数、收费笔数、总收入、客单价
- 单页应用，`textContent` 渲染用户数据避免 XSS；系统原生字体 + 响应式布局
- 默认端口 127.0.0.1:8080，启动后终端打印访问地址（不自动开浏览器）

### 6. 模拟数据生成器（generate.go）

固定随机种子、可复现；覆盖 17 个字段维度、46 种真实兽医疾病、12 位医生、
7 个种类、全国 10 个城市。业务规律约束：

- 疾病与物种匹配（不会出现「仓鼠股骨骨折」等不合理组合）
- 医生按专长分配（骨科→骨科医生、皮肤病→皮肤科医生）
- 费用分层合理（手术/检查/药品/住院/疫苗/护理/其他；重症费用高、复查递减）
- 重症患者有 2-5 次随访记录；状态自动推断（待就诊/就诊中/住院中/已康复/慢性病随访）
- 20% 未植入芯片，5% 有备注，过敏史按真实比例分布

规模参考（2000 条）：约 4294 条病历、17201 笔收费、4.6MB 数据库、写入约 1.5 秒。

## CLI Flags

```
pethospital.exe                    # 默认 127.0.0.1:8080，数据 ./data/pet.db
pethospital.exe -addr 127.0.0.1:9090
pethospital.exe -seed              # 仅空库时写入 8 条手工精选数据
pethospital.exe -seed -count 2000  # 额外生成 2000 条模拟数据
pethospital.exe -db D:\mydata\pet.db
pethospital.exe -no-color          # 关闭彩色终端输出
pethospital.exe -h                 # 查看全部参数
```

启动横幅：ASCII 边框 + 版本号 + 数据库档案数 + 网页入口 + 服务清单 + 可复制访问案例，
随后实时打印访问日志（`GET /health 200 182B 87µs` 风格）。

## Build & Verify

```bash
go build -o dist/pethospital.exe .          # Windows amd64
GOOS=windows GOARCH=amd64 go build -o dist/pethospital.exe .
GOOS=linux   GOARCH=amd64 go build -o dist/pethospital-linux .
GOOS=darwin  GOARCH=arm64 go build -o dist/pethospital
make dist                                     # 构建 + 测试库 + 说明文档
go run . -seed -count 2000                    # 验证模拟数据
```

## MVP Acceptance Criteria

1. `go build` 零第三方依赖成功；双击 exe 即可运行，浏览器访问 `http://127.0.0.1:8080/`
2. 网页端完成全部增删改查 + 病历/明细/汇总 + 统计卡片
3. `/api/v1/endpoints` 返回 29 个接口清单，均可本地 curl 验证
4. 单文件数据库：新增/删除/压实数据正确；断电截断恢复；`Ctrl+C` 安全退出后自动压实
5. 模拟数据业务规律自洽（物种×疾病、医生×专长、费用×严重度）
6. 迁移验证：`exe` + `data/pet.db` 拷贝到另一机器即可继续使用

## Important Notes

- **禁止引入任何第三方 Go 依赖**；嵌入网页用 `embed`，DB 用手写引擎
- 无鉴权、明文 HTTP，仅监听本机，**勿暴露公网**；README 需声明该警告
- README.md 说明特性、快速开始、数据模型、全部接口、数据库文件格式、构建发布
- 输出彩色/平台差异提示遵循 `README.md` 与 `README-Windows.md` 既有规范
- 参考文档：本目录 `README.md`（完整 API 与 DB 格式）、`README-Windows.md`（运行说明）
