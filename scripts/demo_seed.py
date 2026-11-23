"""Seed a small end-to-end AMS demo dataset against a running instance."""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("AMS_BASE_URL", "http://127.0.0.1:8000")
USER_ID = os.environ.get("AMS_USER_ID", "E0043258")
PASSWORD = os.environ.get("AMS_ADMIN_PASSWORD")
if not PASSWORD:
    raise SystemExit("Set AMS_ADMIN_PASSWORD to the password used when creating the instance.")


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=20) as client:
        response = client.post("/api/auth/login", json={"user_id": USER_ID, "password": PASSWORD})
        response.raise_for_status()

        def create(path: str, **payload):
            response = client.post(path, json=payload)
            if response.status_code not in (200, 201):
                raise SystemExit(f"{path} failed: {response.status_code} {response.text}")
            return response.json()

        factory = create("/api/resources/factories", FACTORY_ID="Factory001", FACTORY_NAME="一廠", FACTORY_DESC="演示廠別")
        subsystem = create("/api/resources/sub-systems", SUB_SYS_ID="MES", SUB_SYS_NAME="製造執行系統")
        create("/api/resources/factory-sub-systems", FACTORY_KEY=factory["FACTORY_KEY"], SUB_SYS_KEY=subsystem["SUB_SYS_KEY"])
        equipment = create("/api/resources/equipment", EQP_ID="PRT01", EQP_NAME="印刷機A")
        users = [
            create("/api/resources/users", USER_ID=user_id, USER_NAME=name, E_MAIL=mail)
            for user_id, name, mail in [
                ("PE001", "王設備", "pe001@example.com"),
                ("PE002", "李設備", "pe002@example.com"),
                ("PE003", "陳主管", "pe003@example.com"),
            ]
        ]
        event = create("/api/resources/events", EVENT_ID="EVT_PRT_DRY", EVENT_NAME="印刷機台缺染料",
                       FACTORY_KEY=factory["FACTORY_KEY"], SUB_SYS_KEY=subsystem["SUB_SYS_KEY"], EVENT_PRIORITY_ID=9)
        create("/api/resources/event-levels", EVENT_KEY=event["EVENT_KEY"], EVENT_LEVEL_ID=1, EVENT_LEVEL_DESC="設備人員", NUMBER_OF_ACK_USERS="2", LEVEL_INTERVAL=10)
        create("/api/resources/event-levels", EVENT_KEY=event["EVENT_KEY"], EVENT_LEVEL_ID=2, EVENT_LEVEL_DESC="主管", NUMBER_OF_ACK_USERS="1", LEVEL_INTERVAL=20)
        equipment_group = create("/api/resources/event-groups", EVENT_GROUP_ID="PE_EQ", EVENT_GROUP_NAME="印刷機設備人員",
                                 FACTORY_KEY=factory["FACTORY_KEY"], SUB_SYS_KEY=subsystem["SUB_SYS_KEY"])
        supervisor_group = create("/api/resources/event-groups", EVENT_GROUP_ID="PE_SUP", EVENT_GROUP_NAME="印刷機主管",
                                  FACTORY_KEY=factory["FACTORY_KEY"], SUB_SYS_KEY=subsystem["SUB_SYS_KEY"])
        for seq, user in enumerate(users[:2], 1):
            create("/api/resources/event-group-members", EVENT_GROUP_KEY=equipment_group["EVENT_GROUP_KEY"], USER_KEY=user["USER_KEY"], MEMBER_SEQ=seq)
        create("/api/resources/event-group-members", EVENT_GROUP_KEY=supervisor_group["EVENT_GROUP_KEY"], USER_KEY=users[2]["USER_KEY"], MEMBER_SEQ=1)
        create("/api/resources/event-level-groups", EVENT_KEY=event["EVENT_KEY"], EVENT_LEVEL_ID=1,
               EVENT_GROUP_KEY=equipment_group["EVENT_GROUP_KEY"], ENABLE_SEND_DEVICES="EMail")
        create("/api/resources/event-level-groups", EVENT_KEY=event["EVENT_KEY"], EVENT_LEVEL_ID=2,
               EVENT_GROUP_KEY=supervisor_group["EVENT_GROUP_KEY"], ENABLE_SEND_DEVICES="EMail;Sms")
        create("/api/resources/alarm-infos", ALARM_INFO_ID="PRT_DRY", ALARM_ID_DESC="印刷機缺染料",
               FACTORY_KEY=factory["FACTORY_KEY"], SUB_SYS_KEY=subsystem["SUB_SYS_KEY"], EVENT_KEY=event["EVENT_KEY"],
               EQP_KEY=equipment["EQP_KEY"], EVENT_PTY_ID=9, IGNORE_PERIOD=900)
        alarm = client.post("/api/alarms/send", json={
            "FACTORY_ID": "Factory001", "SUB_SYS_ID": "MES", "EQP_ID": "PRT01", "ALARM_INFO_ID": "PRT_DRY",
            "SUBJECT": "PRT01 缺染料", "CONTENT": "請設備人員前往補充染料",
        })
        alarm.raise_for_status()
        print("Demo data ready:", alarm.json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
