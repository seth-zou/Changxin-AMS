# Changxin-AMS

还原「AMS 警报管理系统」核心链路的可运行原型，覆盖主档维护、事件与层级升级设定、警报触发/手动发送/补登、ACK/中断、层级升级、无效警报表与基础报表查询。此版本使用 FastAPI + SQLite + 原生 Web Console，便于本地演示与后续替换为企业数据库/消息队列。

## 功能范围

- 登录与会话管理（同账号单点登录、旧会话踢出）
- 系统选单与 33 个主功能页面入口
- 基本主档与 Mapping 设定：使用者、群组、厂别、机台、机台群组、机台类型、机台状态等
- 警报管理设定：子系统、厂别子系统对应、事件通知人员群组、事件通知、事件层级群组对应、警报通知设定、触发条件、服务装置参数
- 警报作业：手动发送、补登、确认回报、强制中断
- 报表：即时警报彙整、警报处理查询、历史纪录、无效警报、装置状态
- 警报交易履历、软删除/恢复、Excel/CSV 导出与导入接口骨架

## 快速启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export AMS_ADMIN_PASSWORD='your-initial-password'   # 首次建库时必须设置
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://localhost:8000`。首次登录账号为 `E0043258`。
数据库默认保存在 `data/ams.db`，可用 `AMS_DB_PATH=/path/to/ams.db` 覆盖。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## API 文档

启动后访问：

- Swagger UI：`/docs`
- OpenAPI JSON：`/openapi.json`
- Health Check：`/health`

## 还原边界

此仓库为架构与业务流程还原，不包含真实邮件/SMS/Voice/飞书外部投递。警报接收人记录与发送状态会在库内生成，后续可把 `ALARM_RECIPIENTS.SEND_STATUS` 的生成点替换为 MQ producer / SMTP / SMS gateway。触发条件 SQL 目前保存并返回给前端，未在 Web 原型中直接执行外部数据库 SQL，避免误连生产资料源。
