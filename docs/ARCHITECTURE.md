# AMS 架构说明（还原版）

## 目标架构

原始 AMS 为 CIM 体系下的警报中枢：Agent 从数据库/web service/机台通信入口接收警报，按厂别、子系统、机台、警报代码（警报四要素）匹配事件通知设定，再通过 Email、SMS、Voice、TeamPlus 等渠道逐级通知人员，记录交易履历并向报表层提供数据。

```
EAP / FDC / MES / SPC / EDC / HSM / WebPage
                  │
                  ▼
          ┌───────────────┐
          │ API Gateway   │  认证、限流、路由、SOAP↔REST、幂等
          └───────┬───────┘
                  │
          ┌───────▼───────┐
          │ Alarm Server  │  接收/过滤/触发/分级/ACK/升级/配置/报表
          └───┬───────┬───┘
              │       │
      ┌───────▼─┐   ┌─▼────────────┐
      │  Redis  │   │ Message Queue│
      └─────────┘   └──────┬───────┘
                           │
      ┌────────────────────▼────────────────────┐
      │ Agent Workers: Email / SMS / Voice / IM │
      └────────────────────┬────────────────────┘
                           │
                 ┌─────────▼─────────┐
                 │  SQL Server / BRM │
                 │ 主档 + 履历 + 报表 │
                 └───────────────────┘
```

## 本仓库实现

| 原系统概念 | 本项目实现 |
|---|---|
| Gateway | FastAPI 统一 API 入口，Cookie 会话 + 401 鉴权 |
| Alarm Server | `app/main.py` 中的警报接收、过滤、事件分级、ACK/升级/终止服务 |
| BRM 动态主档 | `app/metadata.py` 的资源元数据 + 通用 CRUD API + 履历表 |
| Agent / Device | `ALARM_SERVICE_CONFIG` 服务装置目录；页面可启停与查看计数 |
| MSMQ / MQ | 预留发送记录状态；可替换为 MQ Producer |
| 关系数据库 | SQLite（可替换为 SQL Server/PostgreSQL） |
| 前端框架 | 原生 Web Console，按 BRMNormal / BRMMapping / BRMMasterDetail / Report 形态渲染 |

## 警报生命周期

```
Create ──► Process ──► Completed（ACK 达标 / AlarmComplete）
   │          │
   │          ├──► NoNextLevel（无下一层级 / AlarmFail）
   │          └──► Terminated（人工强制中断）
   │
   └──► NoNotify（主档缺失、过滤、忽略重复等，写入 INVALID_ALARMS）
```

交易类型遵循原系统：`Create / Modify / UserAck / LevelUpgrade / AlarmComplete / AlarmFail / Terminate`。

## 过滤顺序

1. 厂别、子系统、机台、警报代码存在且启用。
2. 警报四要素匹配警报通知设定；机台代码 `*` 可作为通配。
3. 机台类型 + 机台状态命中「特定机况不发送」规则时，写无效警报。
4. 在 `IGNORE_PERIOD` 内重复相同警报时，写无效警报。
5. 事件必须存在层级 1；否则写无效警报。
6. 发送至层级 1 绑定的事件通知人员群组；无人员/无发送方式时记录失败并进入 `NoNextLevel`。

## 权限与安全边界

- 演示账号初始密码来自 `AMS_ADMIN_PASSWORD`，不写入代码库。
- 会话 Token 仅保存在 HttpOnly Cookie 中；新登录会清理旧 Token，实现同账号单点登录。
- 触发条件 SQL 当前仅保存配置，不直接执行外部 SQL，避免误触生产数据源。
- 外部通知通道尚未接入；发送状态目前为本地模拟。生产部署应接入消息队列和真实供应商，并对 SQL 触发条件做白名单、超时与只读账号限制。
