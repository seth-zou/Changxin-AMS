# AMS 还原说明

## 交付物

- 可运行系统：`app/`（FastAPI + SQLite + Web Console）
- 自动化测试：`tests/test_ams.py`，4 个测试覆盖健康检查、主档链路、手工/补登警报、ACK、层级升级、强制中断、通配机台、未授权访问
- 架构与业务边界：`docs/ARCHITECTURE.md`
- 附件到实现映射：`docs/RESTORE-MATRIX.md`
- 演示数据脚本：`scripts/demo_seed.py`
- 部署：`Dockerfile`、`docker-compose.yml`

## 验证结果

已执行：

```bash
python3 -m unittest tests.test_ams -v
```

结果：4 项全部通过。

已在浏览器中验证：登录、侧边栏 33 项功能入口、即时警报彙整数据展示、警报确认回报作业页面、事件通知人员群组弹窗、批次隐藏页面。测试过程中发现并修复了 SQLite 跨线程访问、机台 `*` 通配、事件层级唯一性、编辑时自冲突校验等问题。

## 未完成/受限项

1. 附件 `AMS系统需求.xlsx` 是空模板（仅「序号」表头），未提供可落实的需求条目。
2. `RPTSET001` 报表设计器与 `MCMS051` 批次状态规则目前为入口/数据模型级，未实现完整 18 步可视化设计器。
3. 真实 Email、SMS、Voice、TeamPlus 投递与 MSMQ 未接入；本地生成接收人/发送状态记录作为业务模拟。
4. 原系统视觉为 DevExpress/Syncfusion 组件；本还原使用自研 Web UI 复刻信息架构与交互，不复制其商业组件。
